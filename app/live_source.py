"""
Live in-play polling from football-data.org.

While a group-stage match is being played, this module fetches the World Cup
matches feed and writes the current scoreline (plus any goal/card events the
API exposes) into ``data/actuals.json`` so the rest of the app — standings,
brackets, the frontpage "Live match" card — reflects the live state.

Relationship to :mod:`app.results_source`:
  - ``results_source.fetch_and_apply_official_results`` is the admin-triggered
    "sync finished results" action (records FINISHED group matches only).
  - ``live_source.poll_live_matches`` is the automatic background poller: it
    handles IN_PLAY/PAUSED matches (live scores + minute + events) *and*
    records a match as final the moment the API reports it FINISHED, removing
    it from ``live_matches``.

Data model (in ``actuals.json``):
  - ``group_results[GROUP]`` entries gain an optional ``events`` list:
        {"type": "goal"|"yellow"|"red", "minute": int, "player": str, "team": str}
    Events persist after the match finishes (they live on the result entry).
  - ``live_matches`` entries gain optional transient ``minute`` and ``status``
    fields while the match is in progress; the entry is removed on FINISHED.

Subscription note: the current football-data.org tier returns match status and
scores but NOT detailed events (``goals``/``bookings`` are absent). The event
parser below is written defensively so that if/when the subscription is
upgraded to a tier that includes them, scorers and cards populate automatically
with no further code changes.
"""

import requests

from app import data_store
from app.results_source import _normalize_team_name, FOOTBALL_DATA_URL

# Match statuses football-data.org uses for a game that is currently being
# played (the ball is in play, or it's the half-time break).
LIVE_STATUSES = {"IN_PLAY", "PAUSED"}


def _parse_events(match: dict, home: str, away: str) -> list[dict]:
    """Extract goal and card events from a football-data.org match object.

    Returns a chronologically-sorted list of
    ``{"type", "minute", "player", "team"}`` dicts. ``type`` is one of
    ``"goal"``, ``"yellow"``, ``"red"``. Team names are normalized to the
    names used in ``wc2026.json``.

    Defensive by design: tiers that don't include ``goals``/``bookings`` simply
    yield an empty list.
    """
    events: list[dict] = []

    for g in match.get("goals", []) or []:
        team = _normalize_team_name((g.get("team") or {}).get("name", "")) or None
        scorer = (g.get("scorer") or {}).get("name") or "Unknown"
        minute = g.get("minute")
        injury = g.get("injuryTime")
        events.append({
            "type": "goal",
            "minute": minute,
            "injury_time": injury,
            "player": scorer,
            "team": team,
            "goal_type": g.get("type"),  # e.g. REGULAR, OWN, PENALTY
        })

    for b in match.get("bookings", []) or []:
        team = _normalize_team_name((b.get("team") or {}).get("name", "")) or None
        player = (b.get("player") or {}).get("name") or "Unknown"
        card = (b.get("card") or "").upper()
        if "RED" in card and "YELLOW_RED" not in card:
            ctype = "red"
        elif "YELLOW_RED" in card:
            ctype = "red"  # second yellow -> sending off
        else:
            ctype = "yellow"
        events.append({
            "type": ctype,
            "minute": b.get("minute"),
            "injury_time": b.get("injuryTime"),
            "player": player,
            "team": team,
        })

    # Sort by (minute, injury_time), pushing unknowns to the end.
    def _key(e):
        m = e.get("minute")
        it = e.get("injury_time") or 0
        return (m if m is not None else 9999, it)

    events.sort(key=_key)
    return events


def _fetch_matches(api_key: str) -> tuple[list | None, str | None]:
    """Fetch the WC matches feed. Returns (matches, error)."""
    try:
        resp = requests.get(
            FOOTBALL_DATA_URL,
            headers={"X-Auth-Token": api_key, "X-Api-Version": "v4.1"},
            timeout=30,
        )
        resp.raise_for_status()
    except requests.RequestException as e:
        return None, f"Request to football-data.org failed: {e}"
    try:
        data = resp.json()
    except ValueError:
        return None, "Invalid response from football-data.org."
    return data.get("matches", []), None


def _kickoff_utc(sm: dict):
    """UTC datetime for a scheduled match (date + local_time + tz), or None."""
    from datetime import datetime
    from zoneinfo import ZoneInfo
    try:
        dt = datetime.fromisoformat(f"{sm['date']}T{sm['local_time']}")
        dt = dt.replace(tzinfo=ZoneInfo(sm.get("local_timezone") or "UTC"))
        return dt.astimezone(ZoneInfo("UTC"))
    except Exception:
        return None


# Poll cadences (seconds).
LIVE_INTERVAL = 10      # poll every 10 seconds while a match is in play
IDLE_MAX = 900          # longest nap when nothing is happening
KICKOFF_WINDOW_H = 3    # treat a match as "should be live" up to 3h post-kickoff


def compute_poll_delay(engine, any_live: bool) -> int:
    """How long to sleep before the next poll.

    ``LIVE_INTERVAL`` while a match is in play or one is within its kickoff
    window; otherwise sleep until ~1 minute before the next scheduled kickoff,
    clamped to ``[LIVE_INTERVAL, IDLE_MAX]``."""
    if any_live:
        return LIVE_INTERVAL

    from datetime import datetime, timezone, timedelta
    from app.simulation.engine import GROUP_MATCH_PAIRS

    now = datetime.now(timezone.utc)
    actuals = data_store.load_actuals()
    live = {frozenset((lm.get("home"), lm.get("away"))) for lm in actuals.get("live_matches", [])}
    finished = set()
    for entries in actuals.get("group_results", {}).values():
        for e in entries:
            pair = frozenset((e.get("home"), e.get("away")))
            if pair not in live:
                finished.add(pair)

    schedule = engine.data.get("schedule", {})
    next_future = None
    for g in engine.groups:
        sched = schedule.get("groups", {}).get(g["name"], [])
        for (i, j), sm in zip(GROUP_MATCH_PAIRS, sched):
            ko = _kickoff_utc(sm)
            if ko is None:
                continue
            pair = frozenset((g["teams"][i], g["teams"][j]))
            if pair in finished:
                continue
            if ko - timedelta(minutes=3) <= now <= ko + timedelta(hours=KICKOFF_WINDOW_H):
                return LIVE_INTERVAL  # a match should be live or about to start
            if ko > now and (next_future is None or ko < next_future):
                next_future = ko

    if next_future is None:
        return IDLE_MAX
    delay = (next_future - now).total_seconds() - LIVE_INTERVAL
    return int(max(LIVE_INTERVAL, min(delay, IDLE_MAX)))


def poll_live_matches(engine) -> dict:
    """Poll the live feed and merge in-play state into actuals.

    Handles both group-stage and knockout matches. Group results are written
    to ``group_results``; knockout scores go to ``knockout_scores`` and
    ``knockout_results`` (on FINISHED). Both add entries to ``live_matches``
    while the match is in play.

    Returns a summary dict::

        {
          "any_live": bool,
          "changed": bool,
          "live": [ {home, away, home_goals, away_goals, minute, status} ],
          "finished": [ {home, away, home_goals, away_goals} ],
          "error": str,                # only present on failure
        }
    """
    settings = data_store.load_global_settings()
    api_key = settings.get("football_data_api_key", "")
    if not api_key:
        return {"any_live": False, "changed": False, "live": [], "finished": [],
                "error": "No football-data.org API key configured."}

    matches, err = _fetch_matches(api_key)
    if err:
        return {"any_live": False, "changed": False, "live": [], "finished": [], "error": err}

    actuals = data_store.load_actuals()
    group_results = actuals.setdefault("group_results", {})
    live_matches = actuals.setdefault("live_matches", [])

    # team -> group, so we only act on group-stage fixtures.
    team_group = {}
    for grp in engine.groups:
        for t in grp["teams"]:
            team_group[t] = grp["name"]

    # Index existing live entries by the unordered team pair.
    def _pair(a, b):
        return frozenset((a, b))

    live_by_pair = {_pair(lm.get("home"), lm.get("away")): lm for lm in live_matches}

    live_out: list[dict] = []
    finished_out: list[dict] = []
    changed = False

    for m in matches:
        status = m.get("status")
        if status not in LIVE_STATUSES and status != "FINISHED":
            continue

        home = _normalize_team_name((m.get("homeTeam") or {}).get("name", ""))
        away = _normalize_team_name((m.get("awayTeam") or {}).get("name", ""))
        if home not in team_group or away not in team_group:
            continue
        if team_group[home] != team_group[away]:
            continue  # not a group-stage fixture
        gname = team_group[home]

        score = (m.get("score") or {}).get("fullTime") or {}
        hg, ag = score.get("home"), score.get("away")
        # Live matches before kickoff can report null scores; treat as 0-0.
        if hg is None:
            hg = 0
        if ag is None:
            ag = 0
        hg, ag = int(hg), int(ag)

        events = _parse_events(m, home, away)

        # Upsert the group_results entry (always stored home-team-first using
        # the API's orientation; the engine re-orients to the schedule).
        existing = group_results.setdefault(gname, [])
        prior = next((r for r in existing if _pair(r.get("home"), r.get("away")) == _pair(home, away)), None)
        new_entry = {
            "home": home,
            "away": away,
            "home_goals": hg,
            "away_goals": ag,
        }
        if events:
            new_entry["events"] = events
        elif prior and prior.get("events"):
            # Keep previously-captured events if this poll returned none.
            new_entry["events"] = prior["events"]

        if prior != new_entry:
            existing[:] = [r for r in existing if _pair(r.get("home"), r.get("away")) != _pair(home, away)]
            existing.append(new_entry)
            changed = True

        pair = _pair(home, away)
        if status in LIVE_STATUSES:
            minute = m.get("minute")
            entry = {"home": home, "away": away, "status": status}
            if minute is not None:
                entry["minute"] = minute
            prev_live = live_by_pair.get(pair)
            if prev_live != entry:
                changed = True
            live_by_pair[pair] = entry
            live_out.append({"group": gname, "home": home, "away": away,
                             "home_goals": hg, "away_goals": ag,
                             "minute": minute, "status": status})
        else:  # FINISHED
            if pair in live_by_pair:
                del live_by_pair[pair]
                changed = True
            finished_out.append({"group": gname, "home": home, "away": away,
                                 "home_goals": hg, "away_goals": ag})

    # Rebuild live_matches from the (possibly mutated) index.
    actuals["live_matches"] = list(live_by_pair.values())

    # --- Knockout matches ---
    # Build a lookup: frozenset(home, away) -> match_no from the engine.
    from app import get_or_run_results as _get_results
    _results = _get_results("_system", "current")
    bm = (_results or {}).get("bracket_matches", {})
    ko_pair_to_no = {}
    for mno, bme in bm.items():
        h = (bme.get("home") or {})
        a = (bme.get("away") or {})
        ht = h.get("team") if h.get("determined") else None
        at = a.get("team") if a.get("determined") else None
        if ht and at:
            ko_pair_to_no[_pair(ht, at)] = int(mno)

    ko_scores = actuals.setdefault("knockout_scores", {})
    ko_results = actuals.setdefault("knockout_results", {})

    for m in matches:
        status = m.get("status")
        if status not in LIVE_STATUSES and status != "FINISHED":
            continue
        home = _normalize_team_name((m.get("homeTeam") or {}).get("name", ""))
        away = _normalize_team_name((m.get("awayTeam") or {}).get("name", ""))
        pair = _pair(home, away)
        match_no = ko_pair_to_no.get(pair)
        if match_no is None:
            continue  # not a known knockout fixture

        score_ft = (m.get("score") or {}).get("fullTime") or {}
        score_reg = (m.get("score") or {}).get("regularTime") or {}
        hg = score_ft.get("home") or 0
        ag = score_ft.get("away") or 0
        hg, ag = int(hg), int(ag)

        mno_str = str(match_no)
        existing_score = ko_scores.get(mno_str, {})

        if status in LIVE_STATUSES:
            minute = m.get("minute")
            entry = {"home": home, "away": away, "status": status}
            if minute is not None:
                entry["minute"] = minute
            prev_live = live_by_pair.get(pair)
            if prev_live != entry:
                changed = True
            live_by_pair[pair] = entry
            live_out.append({"home": home, "away": away,
                             "home_goals": hg, "away_goals": ag,
                             "minute": minute, "status": status})
            new_score = {"home": home, "away": away,
                         "home_goals": hg, "away_goals": ag}
            if new_score != {k: v for k, v in existing_score.items()
                             if k in new_score}:
                ko_scores[mno_str] = {**existing_score, **new_score}
                changed = True
        else:  # FINISHED
            if pair in live_by_pair:
                del live_by_pair[pair]
                changed = True
            # Determine penalties if the match went to a shootout.
            shootout = (m.get("score") or {}).get("penalties") or {}
            hp = shootout.get("home")
            ap = shootout.get("away")
            reg_hg = score_reg.get("home")
            reg_ag = score_reg.get("away")
            new_score = {"home": home, "away": away,
                         "home_goals": int(reg_hg) if reg_hg is not None else hg,
                         "away_goals": int(reg_ag) if reg_ag is not None else ag}
            if hp is not None and ap is not None:
                new_score["home_penalties"] = int(hp)
                new_score["away_penalties"] = int(ap)
            winner = home if hg > ag else away
            if ko_scores.get(mno_str) != new_score or ko_results.get(mno_str) != winner:
                ko_scores[mno_str] = new_score
                ko_results[mno_str] = winner
                changed = True
            finished_out.append({"home": home, "away": away,
                                 "home_goals": hg, "away_goals": ag})

    # Rebuild live_matches from the merged index (group + knockout live entries).
    actuals["live_matches"] = list(live_by_pair.values())

    if changed:
        data_store.save_actuals(actuals)
        data_store.ensure_match_scenarios()

    return {
        "any_live": bool(live_out),
        "changed": changed,
        "live": live_out,
        "finished": finished_out,
    }
