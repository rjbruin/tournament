"""
Simple JSON-file-backed persistence for:
  - actual results entered as the tournament progresses (data/actuals.json,
    shared across all accounts — these are real-world facts, not per-user)
  - per-account simulation snapshots, so a new run can be compared against
    an older one (data/users/<username>/snapshots.json)
  - global app configuration not tied to an account (data/settings.json),
    e.g. the API key used to fetch official results

Per-account settings (OpenRouter key/model, display timezone, default number
of simulations, API slug) live in ``data/users.json`` — see ``app/auth.py``.
"""

import json
import os
import time

DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data")
ACTUALS_PATH = os.path.join(DATA_DIR, "actuals.json")
SETTINGS_PATH = os.path.join(DATA_DIR, "settings.json")
USERS_DATA_DIR = os.path.join(DATA_DIR, "users")

MAX_SNAPSHOTS = 20

# Keys from the engine's results dict that are cheap to keep around for
# historical comparison (skip the bulky per-match `fixtures`/`bracket_matches`).
_SUMMARY_KEYS = [
    "group_advance_prob",
    "round_of_16_prob",
    "quarterfinal_prob",
    "semifinal_prob",
    "finalist_prob",
    "winner_prob",
    "n_simulations",
    "elapsed_seconds",
]


def _empty_actuals():
    return {"group_results": {}, "knockout_results": {}}


def load_actuals() -> dict:
    if not os.path.exists(ACTUALS_PATH):
        return _empty_actuals()
    with open(ACTUALS_PATH) as f:
        data = json.load(f)
    data.setdefault("group_results", {})
    data.setdefault("knockout_results", {})
    return data


def save_actuals(data: dict) -> None:
    with open(ACTUALS_PATH, "w") as f:
        json.dump(data, f, indent=2)


def _summarize(results: dict, label: str | None = None) -> dict:
    summary = {k: results[k] for k in _SUMMARY_KEYS if k in results}
    summary["timestamp"] = time.time()
    summary["label"] = label or time.strftime("%Y-%m-%d %H:%M:%S")
    return summary


def _user_dir(username: str) -> str:
    path = os.path.join(USERS_DATA_DIR, username.lower())
    os.makedirs(path, exist_ok=True)
    return path


def _snapshots_path(username: str) -> str:
    return os.path.join(_user_dir(username), "snapshots.json")


def load_snapshots(username: str) -> list:
    path = _snapshots_path(username)
    if not os.path.exists(path):
        return []
    with open(path) as f:
        return json.load(f)


def save_snapshot(username: str, results: dict, label: str | None = None) -> dict:
    """Append a summarized snapshot of `results` and persist to disk."""
    snapshots = load_snapshots(username)
    snap = _summarize(results, label)
    snapshots.append(snap)
    if len(snapshots) > MAX_SNAPSHOTS:
        snapshots = snapshots[-MAX_SNAPSHOTS:]
    with open(_snapshots_path(username), "w") as f:
        json.dump(snapshots, f, indent=2)
    return snap


def delete_snapshot(username: str, index: int) -> bool:
    """Remove the snapshot at `index`. Returns True if removed."""
    snapshots = load_snapshots(username)
    try:
        snapshots.pop(index)
    except IndexError:
        return False
    with open(_snapshots_path(username), "w") as f:
        json.dump(snapshots, f, indent=2)
    return True


def get_snapshot(username: str, index: int) -> dict | None:
    snapshots = load_snapshots(username)
    if not snapshots:
        return None
    try:
        return snapshots[index]
    except IndexError:
        return None


def get_previous_snapshot(username: str) -> dict | None:
    """Most recently saved snapshot (i.e. the run prior to the current one)."""
    snapshots = load_snapshots(username)
    if not snapshots:
        return None
    return snapshots[-1]


# ----------------------------------------------------------------------
# Global (non-per-account) app settings, e.g. third-party API keys used
# for fetching official results.
# ----------------------------------------------------------------------

DEFAULT_GLOBAL_SETTINGS = {
    "football_data_api_key": "",
}


def load_global_settings() -> dict:
    settings = dict(DEFAULT_GLOBAL_SETTINGS)
    if os.path.exists(SETTINGS_PATH):
        with open(SETTINGS_PATH) as f:
            settings.update(json.load(f))
    return settings


def save_global_settings(settings: dict) -> None:
    current = load_global_settings()
    current.update(settings)
    with open(SETTINGS_PATH, "w") as f:
        json.dump(current, f, indent=2)
