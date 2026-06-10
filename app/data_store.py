"""
Simple JSON-file-backed persistence for:
  - actual results entered as the tournament progresses (data/actuals.json)
  - simulation snapshots, so a new run can be compared against an older one
    (data/snapshots.json)
"""

import json
import os
import time

DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data")
ACTUALS_PATH = os.path.join(DATA_DIR, "actuals.json")
SNAPSHOTS_PATH = os.path.join(DATA_DIR, "snapshots.json")
SETTINGS_PATH = os.path.join(DATA_DIR, "settings.json")

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


def load_snapshots() -> list:
    if not os.path.exists(SNAPSHOTS_PATH):
        return []
    with open(SNAPSHOTS_PATH) as f:
        return json.load(f)


def save_snapshot(results: dict, label: str | None = None) -> dict:
    """Append a summarized snapshot of `results` and persist to disk."""
    snapshots = load_snapshots()
    snap = _summarize(results, label)
    snapshots.append(snap)
    if len(snapshots) > MAX_SNAPSHOTS:
        snapshots = snapshots[-MAX_SNAPSHOTS:]
    with open(SNAPSHOTS_PATH, "w") as f:
        json.dump(snapshots, f, indent=2)
    return snap


def delete_snapshot(index: int) -> bool:
    """Remove the snapshot at `index`. Returns True if removed."""
    snapshots = load_snapshots()
    try:
        snapshots.pop(index)
    except IndexError:
        return False
    with open(SNAPSHOTS_PATH, "w") as f:
        json.dump(snapshots, f, indent=2)
    return True


def get_snapshot(index: int) -> dict | None:
    snapshots = load_snapshots()
    if not snapshots:
        return None
    try:
        return snapshots[index]
    except IndexError:
        return None


DEFAULT_SETTINGS = {
    "openrouter_api_key": "",
    "openrouter_model": "anthropic/claude-sonnet-4.5",
    "display_timezone": "UTC",
}


def load_settings() -> dict:
    settings = dict(DEFAULT_SETTINGS)
    if os.path.exists(SETTINGS_PATH):
        with open(SETTINGS_PATH) as f:
            settings.update(json.load(f))
    return settings


def save_settings(settings: dict) -> None:
    current = load_settings()
    current.update(settings)
    with open(SETTINGS_PATH, "w") as f:
        json.dump(current, f, indent=2)


def get_previous_snapshot() -> dict | None:
    """Most recently saved snapshot (i.e. the run prior to the current one)."""
    snapshots = load_snapshots()
    if not snapshots:
        return None
    return snapshots[-1]
