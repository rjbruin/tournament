"""
Fetch official 2026 FIFA World Cup results from football-data.org and merge
finished group-stage matches into data/actuals.json.

football-data.org (https://www.football-data.org/) is a free, well-documented
JSON API that covers the World Cup under competition code "WC". It requires a
free API key sent as the `X-Auth-Token` header. We use:

    GET https://api.football-data.org/v4/competitions/WC/matches

Each match has a `status` (e.g. "FINISHED"), `homeTeam`/`awayTeam` (with
`name`), and `score.fullTime.home`/`score.fullTime.away`.

Team names returned by football-data.org don't always match the names used
in data/wc2026.json, so we normalize them via TEAM_NAME_MAP below.
"""

import requests

from app import data_store

FOOTBALL_DATA_URL = "https://api.football-data.org/v4/competitions/WC/matches"

# Map football-data.org team names -> wc2026.json team names.
TEAM_NAME_MAP = {
    "Korea Republic": "South Korea",
    "South Korea": "South Korea",
    "Côte d'Ivoire": "Ivory Coast",
    "Ivory Coast": "Ivory Coast",
    "United States": "USA",
    "USA": "USA",
    "Czechia": "Czech Republic",
    "Czech Republic": "Czech Republic",
    "Bosnia & Herzegovina": "Bosnia and Herzegovina",
    "Bosnia and Herzegovina": "Bosnia and Herzegovina",
    "DR Congo": "DR Congo",
    "Congo DR": "DR Congo",
    "Cape Verde Islands": "Cape Verde",
    "Cabo Verde": "Cape Verde",
    "Cape Verde": "Cape Verde",
    "Curaçao": "Curacao",
    "Curacao": "Curacao",
    "Republic of Ireland": "Ireland",
    "New Zealand": "New Zealand",
}


def _normalize_team_name(name: str) -> str:
    return TEAM_NAME_MAP.get(name, name)


def fetch_and_apply_official_results(engine) -> dict:
    """Fetch finished group-stage matches and merge them into actuals.json.

    Returns a dict with `updated` (list of newly-recorded group results) and
    `skipped` (matches we couldn't map to a known team), or `{"error": ...}`
    if the request couldn't be made.
    """
    settings = data_store.load_global_settings()
    api_key = settings.get("football_data_api_key", "")
    if not api_key:
        return {"error": "No football-data.org API key configured. Add one on the Settings page."}

    try:
        resp = requests.get(
            FOOTBALL_DATA_URL,
            headers={"X-Auth-Token": api_key},
            timeout=30,
        )
        resp.raise_for_status()
    except requests.RequestException as e:
        return {"error": f"Request to football-data.org failed: {e}"}

    try:
        data = resp.json()
    except ValueError:
        return {"error": "Invalid response from football-data.org."}

    matches = data.get("matches", [])

    actuals = data_store.load_actuals()
    group_results = actuals.setdefault("group_results", {})
    live_matches = actuals.setdefault("live_matches", [])

    # Build a lookup of team -> group, from the engine/tournament data.
    team_group = {}
    for g in engine.groups:
        for t in g["teams"]:
            team_group[t] = g["name"]

    updated = []
    skipped = []

    for m in matches:
        if m.get("status") != "FINISHED":
            continue
        score = m.get("score", {}).get("fullTime", {})
        home_goals, away_goals = score.get("home"), score.get("away")
        if home_goals is None or away_goals is None:
            continue

        home = _normalize_team_name(m.get("homeTeam", {}).get("name", ""))
        away = _normalize_team_name(m.get("awayTeam", {}).get("name", ""))

        if home not in team_group or away not in team_group:
            skipped.append({"home": home, "away": away})
            continue

        gname_home, gname_away = team_group[home], team_group[away]
        if gname_home != gname_away:
            # Not a group-stage fixture (or teams from different groups) — skip.
            skipped.append({"home": home, "away": away})
            continue

        gname = gname_home
        existing = group_results.setdefault(gname, [])
        # Replace any existing entry for the same fixture.
        existing[:] = [
            r for r in existing
            if {r.get("home"), r.get("away")} != {home, away}
        ]
        entry = {
            "home": home,
            "away": away,
            "home_goals": int(home_goals),
            "away_goals": int(away_goals),
        }
        existing.append(entry)
        updated.append({"group": gname, **entry})

        # A FINISHED match is no longer "live", even if it was previously
        # marked in_progress.
        before = len(live_matches)
        live_matches[:] = [
            lm for lm in live_matches
            if {lm.get("home"), lm.get("away")} != {home, away}
        ]
        if len(live_matches) != before:
            updated[-1]["finished_live"] = True

    if updated:
        data_store.save_actuals(actuals)
        data_store.ensure_match_scenarios()

    return {"updated": updated, "skipped": skipped}
