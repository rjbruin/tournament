import smtplib
import time
from email.message import EmailMessage

from flask import Blueprint, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required, login_user, logout_user
from werkzeug.security import check_password_hash

from app import auth

auth_bp = Blueprint("auth", __name__)

# In-memory brute-force throttle for login (per username).
_FAILED_LOGINS: dict[str, list[float]] = {}
_MAX_ATTEMPTS = 5
_LOCKOUT_SECONDS = 60

# In-memory IP rate limit for registration (5 per hour per IP).
_REGISTER_ATTEMPTS: dict[str, list[float]] = {}
_REGISTER_MAX = 5
_REGISTER_WINDOW = 3600


def _is_locked_out(username: str) -> bool:
    attempts = _FAILED_LOGINS.get(username.lower(), [])
    recent = [t for t in attempts if time.time() - t < _LOCKOUT_SECONDS]
    _FAILED_LOGINS[username.lower()] = recent
    return len(recent) >= _MAX_ATTEMPTS


def _record_failed_login(username: str) -> None:
    _FAILED_LOGINS.setdefault(username.lower(), []).append(time.time())


def _clear_failed_logins(username: str) -> None:
    _FAILED_LOGINS.pop(username.lower(), None)


def _register_ip_allowed(ip: str) -> bool:
    now = time.time()
    attempts = [t for t in _REGISTER_ATTEMPTS.get(ip, []) if now - t < _REGISTER_WINDOW]
    _REGISTER_ATTEMPTS[ip] = attempts
    return len(attempts) < _REGISTER_MAX


def _record_register_attempt(ip: str) -> None:
    _REGISTER_ATTEMPTS.setdefault(ip, []).append(time.time())


def _send_admin_registration_email(username: str, admin_email: str, approve_url: str) -> None:
    """Best-effort: send an email to the admin notifying them of a new
    registration. Uses the local SMTP server (sendmail/Postfix on localhost:25).
    Silently swallows any error so a missing mail server never breaks signup."""
    try:
        msg = EmailMessage()
        msg["Subject"] = f"[WC 2026] New registration: {username}"
        msg["From"] = "wc2026@localhost"
        msg["To"] = admin_email
        msg.set_content(
            f"A new account has been created and is waiting for your approval.\n\n"
            f"  Username: {username}\n\n"
            f"To approve this account, visit the Settings page and click Approve "
            f"next to the username, or follow this link:\n\n"
            f"  {approve_url}\n\n"
            f"Until approved, the user cannot log in."
        )
        with smtplib.SMTP("localhost", 25, timeout=5) as s:
            s.send_message(msg)
    except Exception:
        pass


@auth_bp.get("/register")
def register():
    if current_user.is_authenticated:
        return redirect(url_for("web.index"))
    return render_template("register.html")


@auth_bp.post("/register")
def register_post():
    if current_user.is_authenticated:
        return redirect(url_for("web.index"))

    ip = request.remote_addr or "unknown"
    if not _register_ip_allowed(ip):
        flash("Too many registration attempts from your network. Please try again in an hour.", "danger")
        return render_template("register.html"), 429

    username = (request.form.get("username") or "").strip()
    password = request.form.get("password") or ""
    password_confirm = request.form.get("password_confirm") or ""

    error = auth.validate_username(username)
    if not error:
        error = auth.validate_password(password)
    if not error and password != password_confirm:
        error = "Passwords do not match."

    if error:
        flash(error, "danger")
        return render_template("register.html", username=username), 400

    _record_register_attempt(ip)
    user = auth.create_user(username, password, approved=False)
    if user is None:
        flash("That username is already taken.", "danger")
        return render_template("register.html", username=username), 400

    # Notify admin by email if an admin email is configured.
    from app import data_store
    global_settings = data_store.load_global_settings()
    admin_email = global_settings.get("admin_email", "").strip()
    if admin_email:
        approve_url = url_for("web.admin_approve_user", username=username, _external=True)
        _send_admin_registration_email(username, admin_email, approve_url)

    flash(
        "Account created! Your registration is pending admin approval — "
        "you'll be able to log in once it's approved.",
        "success",
    )
    return redirect(url_for("auth.login"))


@auth_bp.get("/login")
def login():
    if current_user.is_authenticated:
        return redirect(url_for("web.index"))
    return render_template("login.html", next=request.args.get("next", ""))


@auth_bp.post("/login")
def login_post():
    if current_user.is_authenticated:
        return redirect(url_for("web.index"))

    username = (request.form.get("username") or "").strip()
    password = request.form.get("password") or ""
    next_url = request.form.get("next") or ""

    if _is_locked_out(username):
        flash("Too many failed login attempts. Please wait a minute and try again.", "danger")
        return render_template("login.html", username=username, next=next_url), 429

    user = auth.get_user(username)
    valid = user.check_password(password) if user else check_password_hash(
        "pbkdf2:sha256:600000$dummysaltvalue$" + "0" * 64, password
    )

    if not user or not valid:
        _record_failed_login(username)
        flash("Invalid username or password.", "danger")
        return render_template("login.html", username=username, next=next_url), 401

    if not user.is_approved:
        flash("Your account is pending admin approval. Please check back later.", "warning")
        return render_template("login.html", username=username, next=next_url), 403

    _clear_failed_logins(username)
    login_user(user, remember=True)
    flash(f"Welcome back, {user.username}!", "success")

    if next_url and next_url.startswith("/") and not next_url.startswith("//"):
        return redirect(next_url)
    return redirect(url_for("web.index"))


@auth_bp.post("/logout")
@login_required
def logout():
    logout_user()
    flash("Logged out.", "info")
    return redirect(url_for("auth.login"))
