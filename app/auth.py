"""
Account management.

Accounts are stored in ``data/users.json`` as a dict keyed by (lowercased)
username:

    {
      "alice": {
        "username": "alice",
        "email": "alice@example.com",
        "email_verified": true,
        "password_hash": "...",
        "api_slug": "a1b2c3...",
        "settings": { ... },
        "created_at": 1234567890.0,
        "approved": true,
        "invite_token": "abc..."   # token used to register, if any
      },
      ...
    }

Passwords are hashed with werkzeug's ``generate_password_hash`` (PBKDF2,
salted) — never stored in plaintext.

Admin account: set ``WC2026_ADMIN_EMAIL`` on the server to the email address
of the account that should be the admin. Falls back to ``WC2026_ADMIN_USERNAME``
for backward compatibility (if the account has no email set yet).
"""

import json
import os
import re
import secrets
import time

from flask_login import UserMixin
from werkzeug.security import check_password_hash, generate_password_hash

DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data")
USERS_PATH = os.path.join(DATA_DIR, "users.json")

DEFAULT_USER_SETTINGS = {
    "openrouter_api_key": "",
    "openrouter_key_mode": "own",
    "openrouter_model": "anthropic/claude-sonnet-4.5",
    "display_timezone": "UTC",
    "n_simulations": 250_000,
    "default_team": "Netherlands",
    "favorite_team": "",
    "onboarded": False,
}

USERNAME_RE = re.compile(r"^[a-zA-Z0-9_-]{3,32}$")
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

# Admin is identified by email address (recommended) or by username (legacy).
# Set WC2026_ADMIN_EMAIL (or WC2026_ADMIN_USERNAME) on the server before
# starting the app, e.g.:
#
#     export WC2026_ADMIN_EMAIL=admin@example.com
#
# Restart the app for the change to take effect.
ADMIN_EMAIL_ENV = "WC2026_ADMIN_EMAIL"
ADMIN_USERNAME_ENV = "WC2026_ADMIN_USERNAME"  # legacy fallback


class User(UserMixin):
    def __init__(self, record: dict):
        self._record = record

    @property
    def id(self) -> str:
        return self._record["username"]

    @property
    def username(self) -> str:
        return self._record["username"]

    @property
    def email(self) -> str:
        return self._record.get("email", "")

    @property
    def email_verified(self) -> bool:
        return bool(self._record.get("email_verified", False))

    @property
    def api_slug(self) -> str:
        return self._record["api_slug"]

    @property
    def is_approved(self) -> bool:
        if self.is_admin:
            return True
        return bool(self._record.get("approved", False))

    @property
    def is_admin(self) -> bool:
        admin_email = os.environ.get(ADMIN_EMAIL_ENV, "").strip()
        if admin_email:
            user_email = self._record.get("email", "")
            return bool(user_email) and user_email.lower() == admin_email.lower()
        # Legacy fallback: match by username if ADMIN_EMAIL not set
        admin_username = os.environ.get(ADMIN_USERNAME_ENV, "").strip()
        return bool(admin_username) and self._record["username"].lower() == admin_username.lower()

    @property
    def settings(self) -> dict:
        s = dict(DEFAULT_USER_SETTINGS)
        s.update(self._record.get("settings", {}))
        return s

    def check_password(self, password: str) -> bool:
        return check_password_hash(self._record["password_hash"], password)


def _load_all() -> dict:
    if not os.path.exists(USERS_PATH):
        return {}
    with open(USERS_PATH) as f:
        return json.load(f)


def _save_all(users: dict) -> None:
    target_path = os.path.realpath(USERS_PATH)
    tmp_path = target_path + ".tmp"
    with open(tmp_path, "w") as f:
        json.dump(users, f, indent=2)
    os.replace(tmp_path, target_path)


def get_user(username: str) -> "User | None":
    if not username:
        return None
    users = _load_all()
    record = users.get(username.lower())
    return User(record) if record else None


def get_user_by_email(email: str) -> "User | None":
    if not email:
        return None
    email_lower = email.lower().strip()
    users = _load_all()
    for record in users.values():
        if record.get("email", "").lower() == email_lower:
            return User(record)
    return None


def get_user_by_api_slug(slug: str) -> "User | None":
    if not slug:
        return None
    users = _load_all()
    for record in users.values():
        if secrets.compare_digest(record.get("api_slug", ""), slug):
            return User(record)
    return None


def validate_username(username: str) -> "str | None":
    if not username or not USERNAME_RE.match(username):
        return "Username must be 3-32 characters: letters, numbers, underscore, or hyphen."
    return None


def validate_email(email: str) -> "str | None":
    if not email or not EMAIL_RE.match(email.strip()):
        return "Please enter a valid email address."
    return None


def validate_password(password: str) -> "str | None":
    if not password or len(password) < 8:
        return "Password must be at least 8 characters."
    return None


def create_user(username: str, password: str, email: str = "",
                approved: bool = False, invite_token: str | None = None) -> "User | None":
    """Create a new account. Returns the User, or None if the username or
    email is already taken."""
    users = _load_all()
    key = username.lower()
    if key in users:
        return None
    if email:
        email = email.strip().lower()
        for r in users.values():
            if r.get("email", "").lower() == email:
                return None  # email already registered
    record = {
        "username": username,
        "email": email,
        "email_verified": False,
        "password_hash": generate_password_hash(password),
        "api_slug": secrets.token_hex(20),
        "settings": dict(DEFAULT_USER_SETTINGS),
        "created_at": time.time(),
        "approved": approved,
        "invite_token": invite_token,
    }
    users[key] = record
    _save_all(users)
    return User(record)


def set_email_verified(username: str) -> None:
    users = _load_all()
    record = users.get(username.lower())
    if record:
        record["email_verified"] = True
        _save_all(users)


def approve_user(username: str) -> bool:
    users = _load_all()
    record = users.get(username.lower())
    if not record:
        return False
    record["approved"] = True
    _save_all(users)
    return True


def update_settings(username: str, **kwargs) -> None:
    users = _load_all()
    record = users.get(username.lower())
    if not record:
        return
    settings = dict(DEFAULT_USER_SETTINGS)
    settings.update(record.get("settings", {}))
    settings.update({k: v for k, v in kwargs.items() if v is not None})
    record["settings"] = settings
    _save_all(users)


def regenerate_api_slug(username: str) -> "str | None":
    users = _load_all()
    record = users.get(username.lower())
    if not record:
        return None
    record["api_slug"] = secrets.token_hex(20)
    _save_all(users)
    return record["api_slug"]


def set_password(username: str, password: str) -> bool:
    users = _load_all()
    record = users.get(username.lower())
    if not record:
        return False
    record["password_hash"] = generate_password_hash(password)
    _save_all(users)
    return True


def user_count() -> int:
    return len(_load_all())


def list_users() -> list[dict]:
    """Return a list of user summaries for the admin panel."""
    users = _load_all()
    return sorted(
        ({
            "username": r["username"],
            "email": r.get("email", ""),
            "email_verified": r.get("email_verified", False),
            "created_at": r.get("created_at"),
            "approved": r.get("approved", False),
            "invite_token": r.get("invite_token"),
        } for r in users.values()),
        key=lambda u: u["username"].lower(),
    )
