"""Tests for the pure logic in app/data_store.py (no on-disk I/O)."""

import pytest

import app as app_module
from app import data_store as ds
from conftest import group_teams, scheduled_group_matches


@pytest.fixture
def installed_engine(engine):
    """Install the real engine as the module-level global, for functions that
    call ``app.get_engine()`` (e.g. describe_progress)."""
    saved = app_module._engine
    app_module._engine = engine
    try:
        yield engine
    finally:
        app_module._engine = saved


# ---------------------------------------------------------------------------
# Small pure helpers
# ---------------------------------------------------------------------------

def test_match_scenario_id_and_detection():
    assert ds.match_scenario_id(7) == "match-7"
    assert ds._is_auto_match_id("match-0") is True
    assert ds._is_auto_match_id("match-42") is True
    assert ds._is_auto_match_id("current") is False
    assert ds._is_auto_match_id("match-abc") is False
    assert ds._is_auto_match_id("pre-draw") is False


def test_matches_played_counts_group_and_knockout():
    actuals = {
        "group_results": {"A": [{}, {}], "B": [{}]},
        "knockout_results": {"73": "X", "74": "Y"},
    }
    assert ds._matches_played(actuals) == 5
    assert ds._matches_played({"group_results": {}, "knockout_results": {}}) == 0


def test_scenario_qualities():
    none_played = ds._scenario_qualities({"group_results": {}, "knockout_results": {}})
    assert none_played["has_group_results"] is False
    assert none_played["group_stage_complete"] is False
    assert none_played["has_knockout_results"] is False
    assert none_played["knockout_complete"] is False

    full_groups = {"group_results": {chr(65 + g): [{}] * 6 for g in range(12)},
                   "knockout_results": {"103": "Champ"}}
    q = ds._scenario_qualities(full_groups)
    assert q["group_stage_complete"] is True   # 72 group matches
    assert q["has_knockout_results"] is True
    assert q["knockout_complete"] is True       # match 103 recorded


# ---------------------------------------------------------------------------
# ordered_match_checkpoints
# ---------------------------------------------------------------------------

def test_ordered_match_checkpoints_structure(engine):
    cps = ds.ordered_match_checkpoints(engine)
    assert len(cps) == 103  # 72 group + 31 knockout
    assert [c["index"] for c in cps] == list(range(1, 104))
    # Sorted by kickoff.
    assert cps == sorted(cps, key=lambda c: c["sort_key"])
    # Group matches come with home/away; knockout with a match number.
    assert all("home" in c and "away" in c for c in cps if c["kind"] == "group")
    assert all("match_no" in c for c in cps if c["kind"] == "knockout")
    assert sum(c["kind"] == "group" for c in cps) == 72
    assert sum(c["kind"] == "knockout" for c in cps) == 31


# ---------------------------------------------------------------------------
# describe_progress
# ---------------------------------------------------------------------------

def test_describe_progress_no_results(installed_engine):
    desc = ds.describe_progress({"group_results": {}, "knockout_results": {}})
    assert desc.startswith("Group stage day 1")


def test_describe_progress_partial_group_day(installed_engine):
    engine = installed_engine
    # Play just the first scheduled group match overall.
    cps = ds.ordered_match_checkpoints(engine)
    first_group = next(c for c in cps if c["kind"] == "group")
    actuals = {"group_results": {first_group["group"]: [
        {"home": first_group["home"], "away": first_group["away"],
         "home_goals": 1, "away_goals": 0}]},
        "knockout_results": {}}
    desc = ds.describe_progress(actuals)
    assert "Group stage day 1" in desc
    assert "games played" in desc


def test_describe_progress_tournament_complete(installed_engine):
    engine = installed_engine
    group_results = {}
    for g in engine.groups:
        entries = []
        for p in scheduled_group_matches(engine, g["name"]):
            entries.append({"home": p["home"], "away": p["away"],
                            "home_goals": 1, "away_goals": 0})
        group_results[g["name"]] = entries
    actuals = {"group_results": group_results, "knockout_results": {"103": "Champ"}}
    assert ds.describe_progress(actuals) == "Tournament complete"
