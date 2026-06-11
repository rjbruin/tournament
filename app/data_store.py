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
import uuid

DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data")
ACTUALS_PATH = os.path.join(DATA_DIR, "actuals.json")
SETTINGS_PATH = os.path.join(DATA_DIR, "settings.json")
USERS_DATA_DIR = os.path.join(DATA_DIR, "users")
SCENARIOS_DIR = os.path.join(DATA_DIR, "scenarios")

CURRENT_SCENARIO_ID = "current"

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


# ----------------------------------------------------------------------
# Scenarios — a "scenario" is a particular set of fixture results
# (group_results / knockout_results, the same shape as actuals.json).
#
# The "current" scenario (id == CURRENT_SCENARIO_ID) is special: it's not a
# file in SCENARIOS_DIR, it's backed directly by data/actuals.json and is
# always kept in sync with the real-world tournament (updated via the
# football-data.org sync). Every other scenario is a JSON snapshot under
# data/scenarios/<id>.json that users can create, edit ("what if"), and
# delete freely.
# ----------------------------------------------------------------------


def _scenario_path(scenario_id: str) -> str:
    # Guard against path traversal via a crafted scenario id.
    safe_id = "".join(c for c in scenario_id if c.isalnum() or c in "-_")
    return os.path.join(SCENARIOS_DIR, f"{safe_id}.json")


def _ensure_scenarios_dir() -> None:
    os.makedirs(SCENARIOS_DIR, exist_ok=True)


def list_scenario_ids() -> list[str]:
    _ensure_scenarios_dir()
    ids = []
    for fname in os.listdir(SCENARIOS_DIR):
        if fname.endswith(".json"):
            ids.append(fname[:-len(".json")])
    return ids


def _scenario_qualities(actuals: dict) -> dict:
    """Compute simple boolean qualities of a scenario's actuals, used for
    filtering (e.g. "has the group stage finished?")."""
    group_results = actuals.get("group_results", {})
    knockout_results = actuals.get("knockout_results", {})
    n_group_matches = sum(len(v) for v in group_results.values())
    return {
        # Every group has 6 matches in the 2026 format (12 groups x 4 teams).
        "group_stage_complete": n_group_matches >= 72,
        "has_group_results": n_group_matches > 0,
        "has_knockout_results": len(knockout_results) > 0,
        "knockout_complete": "103" in knockout_results or 103 in knockout_results,
    }


def load_scenario(scenario_id: str | None) -> dict | None:
    """Load a scenario's metadata + actuals. Returns None if not found."""
    scenario_id = scenario_id or CURRENT_SCENARIO_ID
    if scenario_id == CURRENT_SCENARIO_ID:
        actuals = load_actuals()
        return {
            "id": CURRENT_SCENARIO_ID,
            "label": "Current (real results)",
            "actuals": actuals,
            "based_on": None,
            "created_at": None,
            "is_current": True,
            **_scenario_qualities(actuals),
        }
    path = _scenario_path(scenario_id)
    if not os.path.exists(path):
        return None
    with open(path) as f:
        data = json.load(f)
    data.setdefault("actuals", _empty_actuals())
    data["actuals"].setdefault("group_results", {})
    data["actuals"].setdefault("knockout_results", {})
    data["is_current"] = False
    data.update(_scenario_qualities(data["actuals"]))
    return data


def list_scenarios() -> list[dict]:
    """Return metadata (without the bulky `actuals`) for every scenario,
    "current" first."""
    out = []
    current = load_scenario(CURRENT_SCENARIO_ID)
    out.append({k: v for k, v in current.items() if k != "actuals"})
    for sid in sorted(list_scenario_ids()):
        s = load_scenario(sid)
        if s is None:
            continue
        out.append({k: v for k, v in s.items() if k != "actuals"})
    out.sort(key=lambda s: (not s["is_current"], -(s.get("created_at") or 0)))
    return out


def save_scenario(label: str, actuals: dict, based_on: str | None = None,
                   scenario_id: str | None = None) -> dict:
    """Create or update a (non-"current") scenario and persist it."""
    _ensure_scenarios_dir()
    scenario_id = scenario_id or uuid.uuid4().hex[:12]
    if scenario_id == CURRENT_SCENARIO_ID:
        raise ValueError("Cannot save over the 'current' scenario directly.")
    existing = load_scenario(scenario_id)
    data = {
        "id": scenario_id,
        "label": label,
        "actuals": actuals,
        "based_on": based_on if existing is None else existing.get("based_on"),
        "created_at": existing["created_at"] if existing else time.time(),
    }
    with open(_scenario_path(scenario_id), "w") as f:
        json.dump(data, f, indent=2)
    return load_scenario(scenario_id)


def delete_scenario(scenario_id: str) -> bool:
    if scenario_id == CURRENT_SCENARIO_ID:
        return False
    path = _scenario_path(scenario_id)
    if not os.path.exists(path):
        return False
    os.remove(path)
    return True


def archive_current_scenario(label: str | None = None) -> dict:
    """Snapshot the current real-world actuals as a new (frozen) scenario,
    before they're overwritten by a results sync. This lets users keep
    exploring "what the projections looked like before <date>'s results"."""
    actuals = load_actuals()
    label = label or f"Real results as of {time.strftime('%Y-%m-%d %H:%M UTC', time.gmtime())}"
    return save_scenario(label, actuals, based_on=CURRENT_SCENARIO_ID)


def fork_scenario(scenario_id: str, actuals: dict, label: str | None = None) -> dict:
    """Create a new scenario seeded from `actuals`, derived from
    `scenario_id` (used when a user edits results on a scenario they
    shouldn't mutate directly, i.e. "current")."""
    base = load_scenario(scenario_id)
    base_label = (base or {}).get("label", scenario_id)
    label = label or f"What if (based on {base_label})"
    return save_scenario(label, actuals, based_on=scenario_id)
