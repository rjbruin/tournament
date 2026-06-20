import time

from flask import Blueprint, flash, redirect, render_template, request, session, url_for
from flask_login import current_user, login_required, login_user, logout_user
from werkzeug.security import check_password_hash

from app import auth, data_store
from app.email import send_magic_link_email, send_registration_notification, send_verification_email

auth_bp = Blueprint("auth", __name__)

# In-memory brute-force throttle for login (per username/email).
_FAILED_LOGINS: dict[str, list[float]] = {}
_MAX_ATTEMPTS = 5
_LOCKOUT_SECONDS = 60

# IP rate limit for registration and magic-link sends (5 per hour per IP).
_IP_ATTEMPTS: dict[str, list[float]] = {}
_IP_MAX = 5
_IP_WINDOW = 3600


def _is_locked_out(key: str) -> bool:
    attempts = _FAILED_LOGINS.get(key.lower(), [])
    recent = [t for t in attempts if time.time() - t < _LOCKOUT_SECONDS]
    _FAILED_LOGINS[key.lower()] = recent
    return len(recent) >= _MAX_ATTEMPTS


def _record_failed_login(key: str) -> None:
    _FAILED_LOGINS.setdefault(key.lower(), []).append(time.time())


def _clear_failed_logins(key: str) -> None:
    _FAILED_LOGINS.pop(key.lower(), None)


def _ip_allowed(ip: str) -> bool:
    now = time.time()
    attempts = [t for t in _IP_ATTEMPTS.get(ip, []) if now - t < _IP_WINDOW]
    _IP_ATTEMPTS[ip] = attempts
    return len(attempts) < _IP_MAX


def _record_ip_attempt(ip: str) -> None:
    _IP_ATTEMPTS.setdefault(ip, []).append(time.time())


def _resolve_user(identifier: str) -> "auth.User | None":
    """Look up a user by username or email address."""
    user = auth.get_user(identifier)
    if user is None:
        user = auth.get_user_by_email(identifier)
    return user


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

@auth_bp.get("/register")
def register():
    if current_user.is_authenticated:
        return redirect(url_for("web.index"))
    token = request.args.get("invite", "").strip()
    invite = data_store.get_invite(token) if token else None
    gs = data_store.load_global_settings()
    invite_only = gs.get("invite_only", True)
    if invite_only and not invite:
        # Distinguish: token present but invalid/exhausted vs no token at all
        bad_token = bool(token)
        return render_template("register.html", invite=None, invite_only=True, bad_token=bad_token)
    return render_template("register.html", invite=invite, invite_only=invite_only)


@auth_bp.post("/register")
def register_post():
    if current_user.is_authenticated:
        return redirect(url_for("web.index"))

    ip = request.remote_addr or "unknown"
    if not _ip_allowed(ip):
        flash("Too many registration attempts from your network. Please try again in an hour.", "danger")
        return render_template("register.html", invite=None, invite_only=True), 429

    gs = data_store.load_global_settings()
    invite_only = gs.get("invite_only", True)

    # Validate invite token
    token = request.form.get("invite_token", "").strip()
    invite = data_store.get_invite(token) if token else None
    if invite_only and not invite:
        flash("A valid invite link is required to register.", "danger")
        return render_template("register.html", invite=None, invite_only=True), 400

    username = (request.form.get("username") or "").strip()
    email = (request.form.get("email") or "").strip().lower()
    password = request.form.get("password") or ""
    password_confirm = request.form.get("password_confirm") or ""

    error = auth.validate_username(username)
    if not error:
        error = auth.validate_email(email)
    if not error:
        error = auth.validate_password(password)
    if not error and password != password_confirm:
        error = "Passwords do not match."

    if error:
        flash(error, "danger")
        return render_template("register.html", username=username, email=email, invite=invite, invite_only=invite_only), 400

    _record_ip_attempt(ip)
    user = auth.create_user(username, password, email=email,
                            approved=True,  # invite or open registration = auto-approved
                            invite_token=token or None)
    if user is None:
        flash("That username or email address is already registered.", "danger")
        return render_template("register.html", username=username, email=email, invite=invite, invite_only=invite_only), 400

    # Record invite use
    if invite:
        data_store.use_invite(token, username)

    # Send verification email
    verify_token = data_store.create_email_token("verify", username)
    verify_url = url_for("auth.verify_email", token=verify_token, _external=True)
    sent = send_verification_email(email, verify_url)

    # Notify admin
    admin_email = gs.get("admin_email", "").strip()
    if admin_email:
        send_registration_notification(admin_email, username, email,
                                       invite["label"] if invite else None)

    flash(
        ("Account created! Check your email for a verification link. "
         "You can log in straight away, but some features may require a verified email.")
        if sent else
        "Account created! Log in below.",
        "success",
    )
    return redirect(url_for("auth.login_get"))


# ---------------------------------------------------------------------------
# Email verification
# ---------------------------------------------------------------------------

@auth_bp.get("/verify-email/<token>")
def verify_email(token):
    username = data_store.consume_email_token(token, "verify")
    if not username:
        flash("This verification link is invalid or has expired. Log in and we'll send a new one.", "danger")
        return redirect(url_for("auth.login_get"))
    auth.set_email_verified(username)
    flash("Email verified! Your account is fully active.", "success")
    if current_user.is_authenticated and current_user.username == username:
        return redirect(url_for("web.index"))
    return redirect(url_for("auth.login_get"))


# ---------------------------------------------------------------------------
# Login (password)
# ---------------------------------------------------------------------------

@auth_bp.get("/login")
def login_get():
    if current_user.is_authenticated:
        return redirect(url_for("web.index"))
    return render_template("login.html", next=request.args.get("next", ""))


@auth_bp.post("/login")
def login_post():
    if current_user.is_authenticated:
        return redirect(url_for("web.index"))

    identifier = (request.form.get("identifier") or "").strip()
    password = request.form.get("password") or ""
    next_url = request.form.get("next") or ""

    if _is_locked_out(identifier):
        flash("Too many failed login attempts. Please wait a minute and try again.", "danger")
        return render_template("login.html", identifier=identifier, next=next_url), 429

    user = _resolve_user(identifier)
    valid = user.check_password(password) if user else check_password_hash(
        "pbkdf2:sha256:600000$dummysaltvalue$" + "0" * 64, password
    )

    if not user or not valid:
        _record_failed_login(identifier)
        flash("Invalid username/email or password.", "danger")
        return render_template("login.html", identifier=identifier, next=next_url), 401

    if not user.is_approved:
        flash("Your account is pending admin approval. Please check back later.", "warning")
        return render_template("login.html", identifier=identifier, next=next_url), 403

    _clear_failed_logins(identifier)
    login_user(user, remember=True)

    # Nudge to verify email if not yet done
    if user.email and not user.email_verified:
        flash(f"Welcome back, {user.username}! Your email isn't verified yet — check your inbox.", "warning")
    else:
        flash(f"Welcome back, {user.username}!", "success")

    if next_url and next_url.startswith("/") and not next_url.startswith("//"):
        return redirect(next_url)
    return redirect(url_for("web.index"))


# ---------------------------------------------------------------------------
# Magic link (passwordless sign-in / password reset)
# ---------------------------------------------------------------------------

@auth_bp.get("/magic-link")
def magic_link_get():
    if current_user.is_authenticated:
        return redirect(url_for("web.index"))
    return render_template("magic_link.html")


@auth_bp.post("/magic-link")
def magic_link_post():
    if current_user.is_authenticated:
        return redirect(url_for("web.index"))

    ip = request.remote_addr or "unknown"
    if not _ip_allowed(ip):
        flash("Too many requests from your network. Please try again in an hour.", "danger")
        return render_template("magic_link.html"), 429

    email = (request.form.get("email") or "").strip().lower()
    if not email:
        flash("Please enter your email address.", "danger")
        return render_template("magic_link.html"), 400

    _record_ip_attempt(ip)

    # Always respond the same way — don't reveal whether email exists.
    user = auth.get_user_by_email(email)
    if user and user.email_verified:
        token = data_store.create_email_token("magic", user.username)
        login_url = url_for("auth.magic_link_consume", token=token, _external=True)
        send_magic_link_email(email, login_url)

    flash("If that email is registered and verified, a sign-in link has been sent. Check your inbox.", "info")
    return render_template("magic_link.html", sent=True)


@auth_bp.get("/magic-link/<token>")
def magic_link_consume(token):
    username = data_store.consume_email_token(token, "magic")
    if not username:
        flash("This sign-in link is invalid or has expired. Request a new one.", "danger")
        return redirect(url_for("auth.magic_link_get"))

    user = auth.get_user(username)
    if not user or not user.is_approved:
        flash("Account not found or not yet approved.", "danger")
        return redirect(url_for("auth.login_get"))

    login_user(user, remember=True)
    flash(f"Signed in as {user.username}. You can set a new password below if you like.", "success")
    # Store a flag so the settings page can show the "set new password" form prominently
    session["magic_link_login"] = True
    return redirect(url_for("web.settings"))


# ---------------------------------------------------------------------------
# Resend verification email
# ---------------------------------------------------------------------------

@auth_bp.post("/resend-verification")
@login_required
def resend_verification():
    user = current_user
    if user.email_verified:
        flash("Your email is already verified.", "info")
        return redirect(url_for("web.index"))
    if not user.email:
        flash("No email address on your account. Add one in Settings first.", "warning")
        return redirect(url_for("web.settings"))
    token = data_store.create_email_token("verify", user.username)
    verify_url = url_for("auth.verify_email", token=token, _external=True)
    sent = send_verification_email(user.email, verify_url)
    flash("Verification email sent! Check your inbox." if sent else
          "Could not send email — the server may not have an SMTP relay configured.", "info")
    return redirect(url_for("web.index"))


# ---------------------------------------------------------------------------
# Logout
# ---------------------------------------------------------------------------

@auth_bp.post("/logout")
@login_required
def logout():
    logout_user()
    flash("Logged out.", "info")
    return redirect(url_for("auth.login_get"))
