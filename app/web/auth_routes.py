import time

from flask import Blueprint, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required, login_user, logout_user
from werkzeug.security import check_password_hash

from app import auth

auth_bp = Blueprint("auth", __name__)

# Very small in-memory brute-force throttle: after a few failed attempts for
# a given username, require a short cool-down before the next attempt is
# even checked. Resets on successful login or process restart.
_FAILED_LOGINS: dict[str, list[float]] = {}
_MAX_ATTEMPTS = 5
_LOCKOUT_SECONDS = 60


def _is_locked_out(username: str) -> bool:
    attempts = _FAILED_LOGINS.get(username.lower(), [])
    recent = [t for t in attempts if time.time() - t < _LOCKOUT_SECONDS]
    _FAILED_LOGINS[username.lower()] = recent
    return len(recent) >= _MAX_ATTEMPTS


def _record_failed_login(username: str) -> None:
    _FAILED_LOGINS.setdefault(username.lower(), []).append(time.time())


def _clear_failed_logins(username: str) -> None:
    _FAILED_LOGINS.pop(username.lower(), None)


@auth_bp.get("/register")
def register():
    if current_user.is_authenticated:
        return redirect(url_for("web.index"))
    return render_template("register.html")


@auth_bp.post("/register")
def register_post():
    if current_user.is_authenticated:
        return redirect(url_for("web.index"))

    username = (request.form.get("username") or "").strip()
    password = request.form.get("password") or ""
    password_confirm = request.form.get("password_confirm") or ""

    error = auth.validate_username(username)
    if not error:
        error = auth.validate_password(password)
    if not error and password != password_confirm:
        error = "Passwords do not match."

    if not error:
        user = auth.create_user(username, password)
        if user is None:
            error = "That username is already taken."

    if error:
        flash(error, "danger")
        return render_template("register.html", username=username), 400

    login_user(user)
    flash("Account created. Welcome!", "success")
    return redirect(url_for("web.index"))


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
    # Always run check_password (even for a missing user, against a dummy
    # hash) so the response time doesn't reveal whether the username exists.
    valid = user.check_password(password) if user else check_password_hash(
        "pbkdf2:sha256:600000$dummysaltvalue$" + "0" * 64, password
    )

    if not user or not valid:
        _record_failed_login(username)
        flash("Invalid username or password.", "danger")
        return render_template("login.html", username=username, next=next_url), 401

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
