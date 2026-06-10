"""
Account management.

Accounts are stored in ``data/users.json`` as a dict keyed by (lowercased)
username:

    {
      "alice": {
        "username": "alice",
        "password_hash": "...",
        "api_slug": "a1b2c3...",
        "settings": {
          "openrouter_api_key": "",
          "openrouter_model": "anthropic/claude-sonnet-4.5",
          "display_timezone": "UTC",
          "n_simulations": 100000
        },
        "created_at": 1234567890.0
      },
      ...
    }

Passwords are hashed with werkzeug's ``generate_password_hash`` (PBKDF2,
salted) — never stored in plaintext.

Each account also gets a unique ``api_slug``: a long random token that can be
used to authenticate API requests without a session cookie (e.g.
``Authorization: Bearer <api_slug>`` or ``?api_key=<api_slug>``). It can be
regenerated from the Account settings page if it leaks.

Each account has its own simulation results, snapshot history, and settings
(OpenRouter key/model, display timezone, default number of simulations) —
see ``app/data_store.py`` for the per-user data files.
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
    "openrouter_model": "anthropic/claude-sonnet-4.5",
    "display_timezone": "UTC",
    "n_simulations": 100_000,
}

USERNAME_RE = re.compile(r"^[a-zA-Z0-9_-]{3,32}$")


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
    def api_slug(self) -> str:
        return self._record["api_slug"]

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
    # Resolve symlinks first: USERS_PATH may be a symlink into a directory
    # that's persisted across deploys (see scripts/deploy.sh). os.replace()
    # does NOT follow a symlink for its destination — it would delete the
    # symlink and write the new file in its place inside the (ephemeral)
    # release directory, silently breaking persistence across updates.
    target_path = os.path.realpath(USERS_PATH)
    tmp_path = target_path + ".tmp"
    with open(tmp_path, "w") as f:
        json.dump(users, f, indent=2)
    os.replace(tmp_path, target_path)


def get_user(username: str) -> User | None:
    if not username:
        return None
    users = _load_all()
    record = users.get(username.lower())
    return User(record) if record else None


def get_user_by_api_slug(slug: str) -> User | None:
    if not slug:
        return None
    users = _load_all()
    for record in users.values():
        if secrets.compare_digest(record.get("api_slug", ""), slug):
            return User(record)
    return None


def validate_username(username: str) -> str | None:
    """Returns an error message, or None if the username is valid."""
    if not username or not USERNAME_RE.match(username):
        return "Username must be 3-32 characters: letters, numbers, underscore, or hyphen."
    return None


def validate_password(password: str) -> str | None:
    """Returns an error message, or None if the password is acceptable."""
    if not password or len(password) < 8:
        return "Password must be at least 8 characters."
    return None


def create_user(username: str, password: str) -> User | None:
    """Create a new account. Returns the User, or None if the username is
    already taken."""
    users = _load_all()
    key = username.lower()
    if key in users:
        return None
    record = {
        "username": username,
        "password_hash": generate_password_hash(password),
        "api_slug": secrets.token_hex(20),
        "settings": dict(DEFAULT_USER_SETTINGS),
        "created_at": time.time(),
    }
    users[key] = record
    _save_all(users)
    return User(record)


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


def regenerate_api_slug(username: str) -> str | None:
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
