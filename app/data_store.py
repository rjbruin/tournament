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
INVITES_PATH = os.path.join(DATA_DIR, "invites.json")
EMAIL_TOKENS_PATH = os.path.join(DATA_DIR, "email_tokens.json")
USERS_DATA_DIR = os.path.join(DATA_DIR, "users")
SCENARIOS_DIR = os.path.join(DATA_DIR, "scenarios")

CURRENT_SCENARIO_ID = "current"
PRE_DRAW_SCENARIO_ID = "pre-draw"

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
    return {"group_results": {}, "knockout_results": {}, "knockout_scores": {}, "live_matches": []}


def load_actuals() -> dict:
    if not os.path.exists(ACTUALS_PATH):
        return _empty_actuals()
    with open(ACTUALS_PATH) as f:
        data = json.load(f)
    data.setdefault("group_results", {})
    data.setdefault("knockout_results", {})
    data.setdefault("knockout_scores", {})
    data.setdefault("live_matches", [])
    return data


def actuals_last_updated() -> float | None:
    if not os.path.exists(ACTUALS_PATH):
        return None
    return os.path.getmtime(ACTUALS_PATH)


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
    "shared_openrouter_api_key": "",
    "admin_email": "",
    "invite_only": True,
    "shared_llm_daily_limit": 100_000,
    "shared_llm_weekly_limit": 1_000_000,
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
# Per-user LLM token usage tracking.
# Entries are appended to data/users/<username>/llm_usage.jsonl, one
# JSON object per line: {"ts": <unix_timestamp>, "tokens": <int>}
# ----------------------------------------------------------------------

# Default LLM limits (used when global settings don't override them).
LLM_DAILY_LIMIT = 100_000
LLM_WEEKLY_LIMIT = 1_000_000


def _llm_usage_path(username: str) -> str:
    return os.path.join(_user_dir(username), "llm_usage.jsonl")


def record_llm_usage(username: str, tokens: int) -> None:
    """Append a token-usage entry for this user."""
    path = _llm_usage_path(username)
    with open(path, "a") as f:
        f.write(json.dumps({"ts": time.time(), "tokens": tokens}) + "\n")


def get_llm_usage(username: str) -> dict:
    """Return {daily_tokens, weekly_tokens} consumed so far by this user."""
    path = _llm_usage_path(username)
    if not os.path.exists(path):
        return {"daily_tokens": 0, "weekly_tokens": 0}
    now = time.time()
    day_ago = now - 86400
    week_ago = now - 604800
    daily = 0
    weekly = 0
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                continue
            ts = entry.get("ts", 0)
            t = entry.get("tokens", 0)
            if ts >= week_ago:
                weekly += t
            if ts >= day_ago:
                daily += t
    return {"daily_tokens": daily, "weekly_tokens": weekly}


def check_llm_quota(username: str, global_settings: dict | None = None) -> str | None:
    """Return an error message if the user has hit their shared-key quota, else None.
    Limits are taken from global_settings if provided, otherwise use defaults."""
    gs = global_settings or {}
    daily_limit = int(gs.get("shared_llm_daily_limit") or LLM_DAILY_LIMIT)
    weekly_limit = int(gs.get("shared_llm_weekly_limit") or LLM_WEEKLY_LIMIT)
    usage = get_llm_usage(username)
    if usage["daily_tokens"] >= daily_limit:
        return (f"Daily Ask AI limit reached ({daily_limit:,} tokens). "
                "Your quota resets every 24 hours.")
    if usage["weekly_tokens"] >= weekly_limit:
        return (f"Weekly Ask AI limit reached ({weekly_limit:,} tokens). "
                "Your quota resets every 7 days.")
    return None


# ----------------------------------------------------------------------
# Invite links.
# Stored in data/invites.json: {token: {label, max_uses, accounts, created_at}}
# ----------------------------------------------------------------------

def _load_invites() -> dict:
    if not os.path.exists(INVITES_PATH):
        return {}
    with open(INVITES_PATH) as f:
        return json.load(f)


def _save_invites(invites: dict) -> None:
    target = os.path.realpath(INVITES_PATH)
    tmp = target + ".tmp"
    with open(tmp, "w") as f:
        json.dump(invites, f, indent=2)
    os.replace(tmp, target)


def create_invite(label: str, max_uses: int) -> dict:
    """Create and persist a new invite link. Returns the invite dict."""
    import secrets as _secrets
    invites = _load_invites()
    token = _secrets.token_urlsafe(24)
    invite = {"label": label, "max_uses": max_uses, "accounts": [], "created_at": time.time()}
    invites[token] = invite
    _save_invites(invites)
    return {"token": token, **invite}


def get_invite(token: str) -> dict | None:
    """Return the invite dict for this token, or None if invalid/exhausted."""
    if not token:
        return None
    invites = _load_invites()
    invite = invites.get(token)
    if not invite:
        return None
    if len(invite["accounts"]) >= invite["max_uses"]:
        return None  # exhausted
    return {"token": token, **invite}


def use_invite(token: str, username: str) -> bool:
    """Record a registration use of this invite. Returns True on success."""
    invites = _load_invites()
    invite = invites.get(token)
    if not invite:
        return False
    invite["accounts"].append(username)
    _save_invites(invites)
    return True


def list_invites() -> list[dict]:
    """Return all invites sorted by creation time (newest first)."""
    invites = _load_invites()
    result = []
    for token, inv in invites.items():
        result.append({
            "token": token,
            "label": inv["label"],
            "max_uses": inv["max_uses"],
            "accounts": inv["accounts"],
            "uses_remaining": inv["max_uses"] - len(inv["accounts"]),
            "created_at": inv["created_at"],
        })
    return sorted(result, key=lambda i: i["created_at"], reverse=True)


def delete_invite(token: str) -> bool:
    invites = _load_invites()
    if token not in invites:
        return False
    del invites[token]
    _save_invites(invites)
    return True


# ----------------------------------------------------------------------
# One-time email tokens for verification and magic-link sign-in.
# Stored in data/email_tokens.json:
#   {token: {type: "verify"|"magic", username, expires_at}}
# ----------------------------------------------------------------------

_TOKEN_TTL = {"verify": 86400, "magic": 3600}  # seconds


def _load_email_tokens() -> dict:
    if not os.path.exists(EMAIL_TOKENS_PATH):
        return {}
    with open(EMAIL_TOKENS_PATH) as f:
        return json.load(f)


def _save_email_tokens(tokens: dict) -> None:
    target = os.path.realpath(EMAIL_TOKENS_PATH)
    tmp = target + ".tmp"
    with open(tmp, "w") as f:
        json.dump(tokens, f, indent=2)
    os.replace(tmp, target)


def create_email_token(token_type: str, username: str) -> str:
    """Create a one-time token of type 'verify' or 'magic'. Returns the token."""
    import secrets as _secrets
    tokens = _load_email_tokens()
    # Prune expired tokens
    now = time.time()
    tokens = {k: v for k, v in tokens.items() if v.get("expires_at", 0) > now}
    token = _secrets.token_urlsafe(32)
    tokens[token] = {
        "type": token_type,
        "username": username,
        "expires_at": now + _TOKEN_TTL.get(token_type, 3600),
    }
    _save_email_tokens(tokens)
    return token


def consume_email_token(token: str, expected_type: str) -> str | None:
    """Validate and consume a one-time token. Returns username on success, None otherwise."""
    if not token:
        return None
    tokens = _load_email_tokens()
    entry = tokens.get(token)
    if not entry:
        return None
    if entry.get("type") != expected_type:
        return None
    if entry.get("expires_at", 0) < time.time():
        return None
    username = entry["username"]
    del tokens[token]
    _save_email_tokens(tokens)
    return username


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


def _is_global_scenario_id(scenario_id: str) -> bool:
    """True for scenario ids that are shared across all accounts: the
    auto-generated "state of the tournament" snapshots, the "before the
    first match" baseline, and the manually-entered-results baseline.
    Everything else (uuid "what if" forks, the per-user "hypothetical"
    slot) is private to the account that created it."""
    return (scenario_id == BEFORE_FIRST_MATCH_SCENARIO_ID
            or scenario_id == MANUAL_SCENARIO_ID
            or _is_auto_match_id(scenario_id))


def _user_scenarios_dir(username: str) -> str:
    path = os.path.join(_user_dir(username), "scenarios")
    os.makedirs(path, exist_ok=True)
    return path


def _scenario_path(scenario_id: str, username: str | None = None) -> str:
    # Guard against path traversal via a crafted scenario id.
    safe_id = "".join(c for c in scenario_id if c.isalnum() or c in "-_")
    if username and not _is_global_scenario_id(safe_id):
        return os.path.join(_user_scenarios_dir(username), f"{safe_id}.json")
    return os.path.join(SCENARIOS_DIR, f"{safe_id}.json")


def _ensure_scenarios_dir() -> None:
    os.makedirs(SCENARIOS_DIR, exist_ok=True)


def list_scenario_ids(username: str | None = None) -> list[str]:
    _ensure_scenarios_dir()
    ids = []
    for fname in os.listdir(SCENARIOS_DIR):
        if fname.endswith(".json"):
            ids.append(fname[:-len(".json")])
    if username:
        d = _user_scenarios_dir(username)
        for fname in os.listdir(d):
            if fname.endswith(".json"):
                ids.append(fname[:-len(".json")])
    return ids


def _scenario_qualities(actuals: dict, draw: dict | None = None) -> dict:
    """Compute simple boolean qualities of a scenario's actuals, used for
    filtering (e.g. "has the group stage finished?")."""
    from app.simulation.draw import is_draw_complete

    group_results = actuals.get("group_results", {})
    knockout_results = actuals.get("knockout_results", {})
    n_group_matches = sum(len(v) for v in group_results.values())
    return {
        # Every group has 6 matches in the 2026 format (12 groups x 4 teams).
        "group_stage_complete": n_group_matches >= 72,
        "has_group_results": n_group_matches > 0,
        "has_knockout_results": len(knockout_results) > 0,
        "knockout_complete": "103" in knockout_results or 103 in knockout_results,
        "draw_complete": is_draw_complete(draw) if draw is not None else True,
    }


# ----------------------------------------------------------------------
# Auto-labeling: describe how far the tournament has progressed for a
# given set of actuals, e.g. "Group stage day 10 - 1/3 games played" or
# "Round of 32 - all games played".
# ----------------------------------------------------------------------

_ROUND_INFO = [
    ("Round of 32", range(73, 89)),
    ("Round of 16", range(89, 97)),
    ("Quarterfinals", range(97, 101)),
    ("Semifinals", range(101, 103)),
    ("Final", range(103, 104)),
]


def describe_progress(actuals: dict) -> str:
    """Human-readable description of tournament progress, e.g.
    "Group stage day 10 - 1/3 games played" or "Round of 32 - all games
    played", based on which group/knockout matches have results."""
    import app as app_module

    engine = app_module.get_engine()
    if engine is None:
        return ""

    schedule = engine.data.get("schedule", {})

    # --- Group stage ---
    group_results = actuals.get("group_results", {})
    played_pairs = {}
    for gname, entries in group_results.items():
        played_pairs[gname] = {
            frozenset((e.get("home"), e.get("away"))) for e in entries
        }

    by_day = {}  # date -> [total, played]
    for g in engine.groups:
        gname = g["name"]
        sched_matches = schedule.get("groups", {}).get(gname, [])
        played_set = played_pairs.get(gname, set())
        for (i, j), sm in zip(GROUP_MATCH_PAIRS, sched_matches):
            date = sm.get("date")
            entry = by_day.setdefault(date, [0, 0])
            entry[0] += 1
            pair = frozenset((g["teams"][i], g["teams"][j]))
            if pair in played_set:
                entry[1] += 1

    days = sorted(d for d in by_day if d)
    total_group_played = sum(p for _, p in by_day.values())
    total_group_matches = sum(t for t, _ in by_day.values())

    if total_group_played < total_group_matches:
        # Find the latest matchday with at least one played match (or day 1
        # if none have been played yet).
        day_index = 1
        for i, d in enumerate(days, start=1):
            if by_day[d][1] > 0:
                day_index = i
        total, played = by_day[days[day_index - 1]]
        desc = "all games played" if played == total else f"{played}/{total} games played"
        return f"Group stage day {day_index} - {desc}"

    # --- Knockout stage ---
    knockout_results = actuals.get("knockout_results", {})
    played_ko = {int(k) for k in knockout_results.keys()}

    if 103 in played_ko:
        return "Tournament complete"

    round_name = "Round of 32"
    for name, rng in _ROUND_INFO:
        total = len(rng)
        played = sum(1 for m in rng if m in played_ko)
        if played > 0:
            round_name, r_total, r_played = name, total, played
        if played < total:
            r_total, r_played = total, played
            round_name = name
            break
    else:
        r_total, r_played = len(_ROUND_INFO[-1][1]), 0

    desc = "all games played" if r_played == r_total else f"{r_played}/{r_total} games played"
    return f"{round_name} - {desc}"


from app.simulation.engine import GROUP_MATCH_PAIRS  # noqa: E402


def ordered_match_checkpoints(engine) -> list[dict]:
    """All 103 matches (72 group + 31 knockout), ordered chronologically by
    their scheduled date/time, each tagged with a 1-based ``index``."""
    schedule = engine.data.get("schedule", {})
    checkpoints = []
    for g in engine.groups:
        gname = g["name"]
        sched_matches = schedule.get("groups", {}).get(gname, [])
        for (i, j), sm in zip(GROUP_MATCH_PAIRS, sched_matches):
            checkpoints.append({
                "kind": "group",
                "group": gname,
                "home": g["teams"][i],
                "away": g["teams"][j],
                "sort_key": (sm.get("date") or "", sm.get("local_time") or ""),
            })
    for mno_str, sm in schedule.get("knockout", {}).items():
        checkpoints.append({
            "kind": "knockout",
            "match_no": int(mno_str),
            "sort_key": (sm.get("date") or "", sm.get("local_time") or ""),
        })
    checkpoints.sort(key=lambda c: c["sort_key"])
    for idx, cp in enumerate(checkpoints, start=1):
        cp["index"] = idx
    return checkpoints


# The "before the first match" baseline scenario: the real draw is known
# but no matches have been played yet. It's the index-0 member of the
# auto-generated "match-N" family (which otherwise snapshots the state right
# after each played match N).
BEFORE_FIRST_MATCH_SCENARIO_ID = "match-0"


def match_scenario_id(index: int) -> str:
    return f"match-{index}"


def _is_auto_match_id(scenario_id: str) -> bool:
    """True for the ids of the auto-generated canonical "state of the
    tournament" scenarios (match-0 = before the first match, match-N =
    after played match N)."""
    if not scenario_id.startswith("match-"):
        return False
    return scenario_id[len("match-"):].isdigit()


def update_scenarios() -> dict:
    """Ensure exactly the canonical set of auto-generated scenarios exists,
    one per unique state of the tournament:

      - ``match-0``  — "Before the first match" (real draw, no results yet);
      - ``match-N``  — the state right after each played match N, built up
                       incrementally in chronological order.

    Any stale ``match-*`` scenario whose match no longer has a recorded
    result is pruned, so the set always mirrors the real results exactly.
    Non-auto scenarios (user "what if"s, the live/hypothetical slot, the
    manual baseline) are left untouched. Returns ``{created, removed}``.
    """
    import copy
    import app as app_module
    from app.simulation.engine import ROUND_NAMES

    engine = app_module.get_engine()
    if engine is None:
        return {"created": [], "removed": []}

    actuals = load_actuals()
    group_results = actuals.get("group_results", {})
    knockout_results = actuals.get("knockout_results", {})

    played_pairs = {}
    for gname, entries in group_results.items():
        for e in entries:
            played_pairs[(gname, frozenset((e.get("home"), e.get("away"))))] = e

    created = []
    desired = {BEFORE_FIRST_MATCH_SCENARIO_ID}

    # match-0: before the first match (real draw, no results yet).
    if not os.path.exists(_scenario_path(BEFORE_FIRST_MATCH_SCENARIO_ID)):
        save_scenario("Before the first match",
                      {"group_results": {}, "knockout_results": {}, "live_matches": []},
                      based_on=CURRENT_SCENARIO_ID,
                      scenario_id=BEFORE_FIRST_MATCH_SCENARIO_ID, is_auto_match=True)
        created.append(BEFORE_FIRST_MATCH_SCENARIO_ID)

    running_group: dict = {}
    running_ko: dict = {}
    for cp in ordered_match_checkpoints(engine):
        if cp["kind"] == "group":
            entry = played_pairs.get((cp["group"], frozenset((cp["home"], cp["away"]))))
            if entry is None:
                continue
            running_group.setdefault(cp["group"], []).append(entry)
            label = f"After {cp['home']} vs {cp['away']} (Group {cp['group']})"
        else:
            mno = cp["match_no"]
            winner = knockout_results.get(str(mno), knockout_results.get(mno))
            if winner is None:
                continue
            running_ko[mno] = winner
            label = f"After match {mno} ({ROUND_NAMES.get(mno, '')})"

        sid = match_scenario_id(cp["index"])
        desired.add(sid)
        if os.path.exists(_scenario_path(sid)):
            continue
        snapshot = {
            "group_results": copy.deepcopy(running_group),
            "knockout_results": dict(running_ko),
            "live_matches": [],
        }
        save_scenario(label, snapshot, based_on=CURRENT_SCENARIO_ID, scenario_id=sid, is_auto_match=True)
        created.append(sid)

    # Prune stale auto-match scenarios (a result was removed/changed).
    removed = []
    for sid in list_scenario_ids():
        if _is_auto_match_id(sid) and sid not in desired:
            delete_scenario(sid)
            removed.append(sid)

    return {"created": created, "removed": removed}


def ensure_match_scenarios() -> list[str]:
    """Backwards-compatible wrapper around :func:`update_scenarios`; returns
    just the ids of newly-created scenarios."""
    return update_scenarios()["created"]


def load_scenario(scenario_id: str | None, username: str | None = None) -> dict | None:
    """Load a scenario's metadata + actuals. Returns None if not found.

    ``username`` is required to resolve "what if" scenarios (uuid-named
    forks and the per-account "hypothetical" slot), which are private to
    the account that created them. Global scenarios (current, pre-draw,
    the auto-generated match-by-match snapshots, the manual baseline) are
    resolved regardless of ``username``."""
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
            "is_pre_draw": False,
            "is_hypothetical": False,
            "is_manual": False,
            "draw": None,
            **_scenario_qualities(actuals, draw=None),
            "progress_label": describe_progress(actuals),
        }
    if scenario_id == PRE_DRAW_SCENARIO_ID:
        actuals = _empty_actuals()
        return {
            "id": PRE_DRAW_SCENARIO_ID,
            "label": "Pre-draw (average over possible draws)",
            "actuals": actuals,
            "based_on": None,
            "created_at": None,
            "is_current": False,
            "is_pre_draw": True,
            "is_hypothetical": False,
            "is_manual": False,
            "draw": None,
            **_scenario_qualities(actuals, draw=None),
            "draw_complete": False,
            "progress_label": "Pre-draw",
        }
    path = _scenario_path(scenario_id, username)
    if not os.path.exists(path):
        # Fall back to the global scenarios dir (e.g. manually created demo scenarios)
        if username:
            path = _scenario_path(scenario_id, None)
        if not os.path.exists(path):
            return None
    with open(path) as f:
        data = json.load(f)
    data.setdefault("actuals", _empty_actuals())
    data["actuals"].setdefault("group_results", {})
    data["actuals"].setdefault("knockout_results", {})
    data["actuals"].setdefault("live_matches", [])
    data.setdefault("draw", None)
    data.setdefault("is_pre_draw", False)
    data.setdefault("is_hypothetical", False)
    data.setdefault("is_manual", False)
    data.setdefault("is_auto_match", False)
    data.setdefault("featured_match", None)
    data["is_current"] = False
    data.update(_scenario_qualities(data["actuals"], draw=data.get("draw")))
    data["progress_label"] = describe_progress(data["actuals"])
    return data


def _matches_played(actuals: dict) -> int:
    """Number of completed matches (group + knockout) in a set of actuals."""
    gr = actuals.get("group_results", {})
    kr = actuals.get("knockout_results", {})
    return sum(len(v) for v in gr.values()) + len(kr)


def list_scenarios(username: str | None = None) -> list[dict]:
    """Return metadata (without the bulky ``actuals``) for every scenario
    visible to ``username``, ordered from most matches played to least.
    "Current" (the live real results) is always pinned first; "pre-draw"
    sorts last. Global scenarios are visible to everyone; "what if" forks
    (uuid ids, the "hypothetical" slot) are only included for their owner."""
    scenarios = [load_scenario(CURRENT_SCENARIO_ID), load_scenario(PRE_DRAW_SCENARIO_ID)]
    for sid in list_scenario_ids(username):
        if _is_global_scenario_id(sid):
            s = load_scenario(sid)
        elif username:
            s = load_scenario(sid, username)
        else:
            continue
        if s is not None:
            scenarios.append(s)

    for s in scenarios:
        s["matches_played"] = _matches_played(s["actuals"])

    scenarios.sort(key=lambda s: (
        not s["is_current"],          # current first
        s.get("is_pre_draw", False),  # pre-draw last
        -s["matches_played"],         # most matches played to least
    ))
    return [{k: v for k, v in s.items() if k != "actuals"} for s in scenarios]


def save_scenario(label: str, actuals: dict, based_on: str | None = None,
                   scenario_id: str | None = None, draw: dict | None = None,
                   is_hypothetical: bool | None = None, is_manual: bool | None = None,
                   is_auto_match: bool | None = None,
                   featured_match: dict | None = None,
                   username: str | None = None) -> dict:
    """Create or update a (non-"current") scenario and persist it.

    ``draw`` (optional): a ``{letter: [pot1..pot4 team names]}`` dict
    representing a (possibly partial) draw for this scenario. ``None``
    means "no custom draw" (the scenario uses the real/actual groups).

    ``username`` (optional): owner of a private "what if" scenario (uuid
    id or the "hypothetical" slot). Ignored for global scenario ids."""
    _ensure_scenarios_dir()
    scenario_id = scenario_id or uuid.uuid4().hex[:12]
    if scenario_id in (CURRENT_SCENARIO_ID, PRE_DRAW_SCENARIO_ID):
        raise ValueError(f"Cannot save over the '{scenario_id}' scenario directly.")
    existing = load_scenario(scenario_id, username)
    data = {
        "id": scenario_id,
        "label": label,
        "actuals": actuals,
        "based_on": based_on if existing is None else existing.get("based_on"),
        "created_at": existing["created_at"] if existing else time.time(),
        "draw": draw if draw is not None else (existing.get("draw") if existing else None),
        "is_hypothetical": is_hypothetical if is_hypothetical is not None else (existing.get("is_hypothetical", False) if existing else False),
        "is_manual": is_manual if is_manual is not None else (existing.get("is_manual", False) if existing else False),
        "is_auto_match": is_auto_match if is_auto_match is not None else (existing.get("is_auto_match", False) if existing else False),
        "featured_match": featured_match if featured_match is not None else (existing.get("featured_match") if existing else None),
    }
    with open(_scenario_path(scenario_id, username), "w") as f:
        json.dump(data, f, indent=2)
    return load_scenario(scenario_id, username)


# Fixed ids for the single-slot "what if" (hypothetical) and "manually
# entered current results" scenarios.
HYPOTHETICAL_SCENARIO_ID = "hypothetical"
MANUAL_SCENARIO_ID = "manual"


def find_hypothetical_scenario(username: str) -> dict | None:
    return load_scenario(HYPOTHETICAL_SCENARIO_ID, username) if os.path.exists(_scenario_path(HYPOTHETICAL_SCENARIO_ID, username)) else None


def delete_hypothetical_scenario(username: str) -> bool:
    return delete_scenario(HYPOTHETICAL_SCENARIO_ID, username)


def save_manual_snapshot() -> dict:
    """Copy the current real-world actuals into the single "manual"
    scenario, used to remember what was manually entered so it can later be
    compared against freshly-synced official results."""
    import copy
    actuals = copy.deepcopy(load_actuals())
    return save_scenario("Manually entered results", actuals, based_on=CURRENT_SCENARIO_ID,
                          scenario_id=MANUAL_SCENARIO_ID, is_manual=True)


def delete_scenario(scenario_id: str, username: str | None = None) -> bool:
    if scenario_id == CURRENT_SCENARIO_ID:
        return False
    path = _scenario_path(scenario_id, username)
    if not os.path.exists(path):
        return False
    os.remove(path)
    return True


def archive_current_scenario(label: str | None = None) -> dict:
    """Snapshot the current real-world actuals as a new (frozen) scenario,
    before they're overwritten by a results sync. This lets users keep
    exploring "what the projections looked like before <date>'s results"."""
    actuals = load_actuals()
    label = label or describe_progress(actuals) or f"Real results as of {time.strftime('%Y-%m-%d %H:%M UTC', time.gmtime())}"
    return save_scenario(label, actuals, based_on=CURRENT_SCENARIO_ID)


def fork_scenario(scenario_id: str, actuals: dict, label: str | None = None,
                   username: str | None = None) -> dict:
    """Create a new scenario seeded from `actuals`, derived from
    `scenario_id` (used when a user edits results on a scenario they
    shouldn't mutate directly, i.e. "current"). The fork is private to
    `username` (a "what if" scenario)."""
    base = load_scenario(scenario_id, username)
    base_label = (base or {}).get("label", scenario_id)
    label = label or f"What if (based on {base_label})"
    return save_scenario(label, actuals, based_on=scenario_id, username=username)


# ---------------------------------------------------------------------------
# Page-view usage tracking.
# Entries appended to data/pageviews.jsonl, one JSON object per line:
#   {"ts": <unix>, "ip": "<ip>", "page": "<path>", "user": "<username|null>"}
# ---------------------------------------------------------------------------

_PAGEVIEWS_PATH = os.path.join(DATA_DIR, "pageviews.jsonl")


def record_pageview(ip: str, page: str, username: str | None) -> None:
    with open(_PAGEVIEWS_PATH, "a") as f:
        f.write(json.dumps({"ts": time.time(), "ip": ip, "page": page, "user": username}) + "\n")
