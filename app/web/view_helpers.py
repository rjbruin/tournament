"""
Helpers that normalize engine output into the shapes expected by the
unified fixture display macros (app/templates/_fixture_macros.html).
"""

import functools
import json
import os
from datetime import datetime
from zoneinfo import ZoneInfo

_DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "data")
_LETTERS = "ABCDEFGHIJKL"

TENNIS_ROUND_LABELS = {
    "r128": "First round", "r64": "Second round", "r32": "Third round",
    "r16": "Fourth round", "qf": "Quarterfinals", "sf": "Semifinals", "final": "Final",
}


@functools.cache
def _build_seed_labels() -> dict:
    """Precompute, for each knockout match number (73-103), a pair of
    human-readable seed labels for the home/away slots, e.g. "1A", "2B",
    "3A/C/D/F", "W77".

    Lazy (module-import used to eagerly read two JSON files as a side
    effect of `import app.web.view_helpers`, which four other modules do
    transitively — routes, api, llm/interface, conftest). Cached so the
    files are still only read once per process."""
    with open(os.path.join(_DATA_DIR, "wc2026.json")) as f:
        bracket = json.load(f)["bracket"]
    with open(os.path.join(_DATA_DIR, "annex_c.json")) as f:
        annex = json.load(f)

    annex_poss: dict[int, set] = {m: set() for m in annex["match_order"]}
    for groups in annex["lut"].values():
        if not groups:
            continue
        for i, g in enumerate(groups):
            annex_poss[annex["match_order"][i]].add(_LETTERS[g])

    def slot_label(slot):
        if isinstance(slot, list):
            kind, val = slot
            if kind == "W":
                return f"1{val}"
            if kind == "R":
                return f"2{val}"
            if kind == "T":
                return "3" + "/".join(sorted(annex_poss.get(val, [])))
            return "?"
        return f"W{slot}"

    defs = bracket["r32"] + bracket["r16"] + bracket["qf"] + bracket["sf"] + [bracket["final"]]
    return {m["match"]: (slot_label(m["home"]), slot_label(m["away"])) for m in defs}


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
        "match": match.get("match"),
        "date": match.get("date"),
        "local_time": match.get("local_time"),
        "local_timezone": match.get("local_timezone"),
        "venue": match.get("venue"),
        "place": match.get("place"),
        "in_progress": match.get("in_progress", False),
    }
    if match.get("minute") is not None:
        out["minute"] = match["minute"]
    if match.get("status"):
        out["status"] = match["status"]
    if match.get("events"):
        out["events"] = match["events"]
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


def normalize_bracket_match(m: dict, ko_scores: dict = None) -> dict:
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
    out["seed_home"], out["seed_away"] = _build_seed_labels().get(m["match"], (None, None))
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
        # Attach score and penalty info if available.
        if ko_scores:
            s = ko_scores.get(str(m["match"]))
            if s:
                out["home_goals"] = s.get("home_goals")
                out["away_goals"] = s.get("away_goals")
                hp = s.get("home_penalties")
                ap = s.get("away_penalties")
                # Only expose penalties when both sides have a real value.
                if isinstance(hp, int) and isinstance(ap, int):
                    out["home_penalties"] = hp
                    out["away_penalties"] = ap
    return out


def normalize_tennis_match(m: dict, entry_by_name: dict, match_info: dict | None = None) -> dict:
    """Tennis analogue of normalize_bracket_match: takes a generic
    MatchRecord dict (app.simulation.phases.base, as returned by
    BracketEngine's to_results()) and produces the shape
    tennis_knockout_fixture() expects.

    entry_by_name: {player name -> entries.json row} for seed/country lookup.
    match_info: {"round_id:index" -> matches.json row} for the real
        score/date of a played match — see load_tennis_match_info().
    """
    out = {
        "round_id": m.get("round_id"),
        "index": m.get("extra", {}).get("index"),
        "actual_winner": (m.get("actual") or {}).get("winner"),
    }
    home, away = m["side_a"], m["side_b"]
    if home.get("determined"):
        out["home_team"] = home["team"]
        entry = entry_by_name.get(home["team"], {})
        out["home_seed"] = entry.get("seed")
        out["home_country"] = entry.get("country")
    else:
        out["home_candidates"] = _candidates_dict(home)
    if away.get("determined"):
        out["away_team"] = away["team"]
        entry = entry_by_name.get(away["team"], {})
        out["away_seed"] = entry.get("seed")
        out["away_country"] = entry.get("country")
    else:
        out["away_candidates"] = _candidates_dict(away)

    outcome = m.get("outcome")
    if outcome:
        out["home_prob"] = outcome.get("home_win")
        out["away_prob"] = outcome.get("away_win")

    if match_info:
        info = match_info.get(f"{out['round_id']}:{out['index']}")
        if info:
            out["score"] = info.get("score")
            out["date"] = info.get("date")
            out["date_confirmed"] = info.get("date_confirmed")
            out["date_range"] = info.get("date_range")
    return out


def load_tennis_match_info(matches_path: str | None) -> dict:
    """{"round_id:index" -> matches.json row}, or {} if no matches.json is
    configured for this tournament (e.g. a draw that hasn't been played)."""
    if not matches_path or not os.path.exists(matches_path):
        return {}
    with open(matches_path) as f:
        data = json.load(f)
    return {f"{m['round']}:{m['index']}": m for m in data.get("matches", [])}


def build_tennis_player_status(matches: list) -> dict:
    """{player name -> {"result": "champion"|"eliminated", "round_label": str,
    "opponent": str|None}} derived from a completed matches.json — every
    non-champion loses exactly once in a single-elimination bracket, so the
    match they lost IS their tournament result. Players from unplayed
    matches (no recorded winner) are simply absent."""
    status = {}
    for m in matches:
        winner = m.get("winner")
        if not winner:
            continue
        loser = m["player2"] if winner == m["player1"] else m["player1"]
        status[loser] = {
            "result": "eliminated",
            "round_label": TENNIS_ROUND_LABELS.get(m["round"], m["round"]),
            "opponent": winner,
        }
        if m["round"] == "final":
            status[winner] = {"result": "champion", "round_label": "Champion", "opponent": None}
    return status


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
        if h not in stats or a not in stats:
            continue
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

    # Theoretical (sampling-free) clinch / elimination status for this group,
    # computed from the played results actually in ``fixtures`` (so it reflects
    # whatever point-in-time state the caller built the table for).
    from app import clinch as _clinch
    status_by_team = _clinch.clinch_for_group(group, fixtures)

    # Annotate each row with its current standings rank and a qualification
    # state, used to colour the table and drive the badges. The "secured"
    # states are *theoretical* (mathematically guaranteed); the statistical
    # ">99.9%" case is handled by the advance badge, not here.
    for i, r in enumerate(rows):
        r["rank"] = i + 1
        status = status_by_team.get(r["name"], "open")
        r["clinch_status"] = status
        r["clinched"] = status in ("clinched_first", "clinched_top2", "clinched_second")
        r["eliminated"] = status == "eliminated"
        if status == "clinched_first":
            r["qual"] = "secured_first"
        elif status in ("clinched_top2", "clinched_second"):
            r["qual"] = "secured_second"
        elif status == "eliminated":
            r["qual"] = "eliminated"
        elif r["rank"] == 1:
            r["qual"] = "place_first"
        elif r["rank"] == 2:
            r["qual"] = "place_second"
        elif r["rank"] == 3:
            r["qual"] = "place_third"
        else:
            r["qual"] = None
    return rows
