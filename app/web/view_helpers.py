"""
Helpers that normalize engine output into the shapes expected by the
unified fixture display macros (app/templates/_fixture_macros.html).
"""

from datetime import datetime
from zoneinfo import ZoneInfo


def utc_sort_key(match: dict):
    """Return a UTC datetime (or empty-string fallback) for chronological
    sorting of fixtures whose kickoff is stored as local date/time/tz."""
    date, t, tz = match.get("date"), match.get("local_time"), match.get("local_timezone")
    if not date or not t:
        return datetime.min
    try:
        dt = datetime.fromisoformat(f"{date}T{t}").replace(tzinfo=ZoneInfo(tz or "UTC"))
        return dt.astimezone(ZoneInfo("UTC"))
    except Exception:
        return datetime.min


def normalize_group_match(match: dict) -> dict:
    out = {
        "home_team": match["home"],
        "away_team": match["away"],
        "played": match.get("played", False),
        "date": match.get("date"),
        "local_time": match.get("local_time"),
        "local_timezone": match.get("local_timezone"),
        "venue": match.get("venue"),
        "place": match.get("place"),
    }
    if match.get("played"):
        out["home_goals"] = match["home_goals"]
        out["away_goals"] = match["away_goals"]
    elif match.get("odds"):
        out["home_prob"] = match["odds"]["home_win"]
        out["draw_prob"] = match["odds"]["draw"]
        out["away_prob"] = match["odds"]["away_win"]
    return out


def _candidates_dict(side: dict) -> dict:
    return {c["team"]: c["probability"] for c in side.get("candidates", [])}


def normalize_bracket_match(m: dict) -> dict:
    out = {
        "match": m["match"],
        "round": m.get("round", ""),
        "date": m.get("date"),
        "local_time": m.get("local_time"),
        "local_timezone": m.get("local_timezone"),
        "venue": m.get("venue"),
        "place": m.get("place"),
        "actual_winner": m.get("actual_winner"),
    }
    home, away = m["home"], m["away"]
    if home.get("determined"):
        out["home_team"] = home["team"]
    else:
        out["home_candidates"] = _candidates_dict(home)
    if away.get("determined"):
        out["away_team"] = away["team"]
    else:
        out["away_candidates"] = _candidates_dict(away)

    outcome = m.get("outcome")
    if outcome:
        out["home_prob"] = outcome.get("home_win")
        out["away_prob"] = outcome.get("away_win")

    if m.get("actual_winner"):
        out["played"] = True
    return out


def compute_group_table(group: dict, fixtures: list, teams_by_name: dict, results: dict | None) -> list:
    """Combined standings + advance odds for a group's table.

    Returns a list of dicts (one per team) sorted by points/GD/GF (played
    matches), falling back to advance probability when nothing has been
    played yet.
    """
    stats = {
        tname: {"name": tname, "gp": 0, "gf": 0, "ga": 0, "pts": 0}
        for tname in group["teams"]
    }
    for m in fixtures:
        if not m.get("played"):
            continue
        h, a = m["home"], m["away"]
        hg, ag = m["home_goals"], m["away_goals"]
        stats[h]["gp"] += 1
        stats[a]["gp"] += 1
        stats[h]["gf"] += hg
        stats[h]["ga"] += ag
        stats[a]["gf"] += ag
        stats[a]["ga"] += hg
        if hg > ag:
            stats[h]["pts"] += 3
        elif hg < ag:
            stats[a]["pts"] += 3
        else:
            stats[h]["pts"] += 1
            stats[a]["pts"] += 1

    advance = (results or {}).get("group_advance_prob", {})
    rows = []
    for tname in group["teams"]:
        s = stats[tname]
        s["gd"] = s["gf"] - s["ga"]
        s["elo"] = teams_by_name[tname]["elo"]
        s["advance_prob"] = advance.get(tname, 0)
        rows.append(s)

    rows.sort(key=lambda r: (r["pts"], r["gd"], r["gf"], r["advance_prob"]), reverse=True)
    return rows
