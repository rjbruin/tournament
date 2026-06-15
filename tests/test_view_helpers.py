"""Tests for the display helpers (app/web/view_helpers.py)."""

from datetime import datetime

import pytest

from app.web.view_helpers import (
    compute_group_table,
    normalize_group_match,
    normalize_bracket_match,
    utc_sort_key,
)


# ---------------------------------------------------------------------------
# utc_sort_key
# ---------------------------------------------------------------------------

def test_utc_sort_key_converts_local_to_utc():
    m = {"date": "2026-06-15", "local_time": "21:00", "local_timezone": "America/New_York"}
    dt = utc_sort_key(m)
    # 21:00 EDT (UTC-4 in June) -> 01:00 UTC next day.
    assert (dt.year, dt.month, dt.day, dt.hour) == (2026, 6, 16, 1)


def test_utc_sort_key_orders_across_timezones():
    earlier = {"date": "2026-06-15", "local_time": "12:00", "local_timezone": "America/Los_Angeles"}
    later = {"date": "2026-06-15", "local_time": "12:00", "local_timezone": "America/New_York"}
    # Same wall-clock, but LA noon is 3h after NY noon in absolute time.
    assert utc_sort_key(later) < utc_sort_key(earlier)


def test_utc_sort_key_fallback_on_missing_or_bad_data():
    assert utc_sort_key({}) == datetime.min
    assert utc_sort_key({"date": "2026-06-15"}) == datetime.min
    assert utc_sort_key({"date": "nonsense", "local_time": "??"}) == datetime.min


# ---------------------------------------------------------------------------
# normalize_group_match
# ---------------------------------------------------------------------------

def test_normalize_played_match_carries_score():
    out = normalize_group_match({"home": "A", "away": "B", "played": True,
                                 "home_goals": 2, "away_goals": 1})
    assert out["home_team"] == "A" and out["away_team"] == "B"
    assert out["played"] and out["home_goals"] == 2 and out["away_goals"] == 1
    assert "home_prob" not in out


def test_normalize_upcoming_match_carries_odds():
    out = normalize_group_match({"home": "A", "away": "B", "played": False,
                                 "odds": {"home_win": 0.5, "draw": 0.3, "away_win": 0.2}})
    assert out["home_prob"] == 0.5 and out["draw_prob"] == 0.3 and out["away_prob"] == 0.2
    assert "home_goals" not in out


def test_normalize_bracket_determined_vs_candidates():
    determined = normalize_bracket_match({
        "match": 73, "home": {"determined": True, "team": "A"},
        "away": {"determined": False, "candidates": [{"team": "B", "probability": 0.6},
                                                     {"team": "C", "probability": 0.4}]},
    })
    assert determined["home_team"] == "A"
    assert determined["away_candidates"] == {"B": 0.6, "C": 0.4}


def test_normalize_bracket_marks_played_when_actual_winner():
    out = normalize_bracket_match({
        "match": 73, "home": {"determined": True, "team": "A"},
        "away": {"determined": True, "team": "B"}, "actual_winner": "A",
    })
    assert out["played"] is True and out["actual_winner"] == "A"


# ---------------------------------------------------------------------------
# compute_group_table
# ---------------------------------------------------------------------------

def _teams_by_name(names):
    return {n: {"name": n, "elo": 1800} for n in names}


def test_group_table_points_and_goal_stats():
    group = {"name": "A", "teams": ["A", "B", "C", "D"]}
    fixtures = [
        {"home": "A", "away": "B", "played": True, "home_goals": 3, "away_goals": 0},
        {"home": "C", "away": "D", "played": True, "home_goals": 1, "away_goals": 1},
        {"home": "A", "away": "C", "played": False},
    ]
    rows = compute_group_table(group, fixtures, _teams_by_name(group["teams"]), None)
    by = {r["name"]: r for r in rows}
    assert (by["A"]["pts"], by["A"]["gf"], by["A"]["ga"], by["A"]["gd"]) == (3, 3, 0, 3)
    assert (by["B"]["pts"], by["B"]["gd"]) == (0, -3)
    assert (by["C"]["pts"], by["D"]["pts"]) == (1, 1)  # draw


def test_group_table_sorted_by_points_then_gd_then_gf():
    group = {"name": "A", "teams": ["A", "B", "C", "D"]}
    fixtures = [
        {"home": "A", "away": "D", "played": True, "home_goals": 1, "away_goals": 0},  # A 3pts gd+1
        {"home": "B", "away": "C", "played": True, "home_goals": 3, "away_goals": 0},  # B 3pts gd+3
    ]
    rows = compute_group_table(group, fixtures, _teams_by_name(group["teams"]), None)
    # Both A and B on 3 pts, but B has the better goal difference.
    assert rows[0]["name"] == "B"
    assert rows[1]["name"] == "A"


def test_group_table_falls_back_to_advance_prob_when_unplayed():
    group = {"name": "A", "teams": ["A", "B", "C", "D"]}
    fixtures = [{"home": "A", "away": "B", "played": False},
                {"home": "C", "away": "D", "played": False}]
    results = {"group_advance_prob": {"A": 0.1, "B": 0.9, "C": 0.5, "D": 0.5}}
    rows = compute_group_table(group, fixtures, _teams_by_name(group["teams"]), results)
    assert rows[0]["name"] == "B"  # highest advance prob floats to the top
