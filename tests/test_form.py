"""Tests for the form indicator (app/form.py)."""

import numpy as np

from app.form import compute_form


def _two_teams_by_elo(engine):
    """Return (strong, weak) team names with a large Elo gap."""
    order = sorted(engine.team_names, key=lambda n: engine.team_elos[engine.team_idx[n]])
    return order[-1], order[0]


def test_no_results_gives_empty_form(engine):
    assert compute_form({"group_results": {}}, engine) == {}
    assert compute_form({}, engine) == {}


def test_overperformer_positive_underperformer_negative(engine):
    strong, weak = _two_teams_by_elo(engine)
    # The strong team (home) loses to the weak team: strong underperforms,
    # weak overperforms.
    actuals = {"group_results": {"A": [
        {"home": strong, "away": weak, "home_goals": 0, "away_goals": 1},
    ]}}
    form = compute_form(actuals, engine)
    assert form[strong] < 0
    assert form[weak] > 0


def test_meeting_expectation_is_near_zero(engine):
    strong, weak = _two_teams_by_elo(engine)
    # Strong team wins as expected: divergence ~ small.
    actuals = {"group_results": {"A": [
        {"home": strong, "away": weak, "home_goals": 2, "away_goals": 0},
    ]}}
    form = compute_form(actuals, engine)
    assert abs(form[strong]) < abs(compute_form(
        {"group_results": {"A": [{"home": strong, "away": weak,
                                  "home_goals": 0, "away_goals": 1}]}}, engine)[strong])


def test_shrinkage_grows_with_more_evidence(engine):
    strong, weak = _two_teams_by_elo(engine)
    others = [n for n in engine.team_names if n not in (strong, weak)][:3]

    one = {"group_results": {"A": [
        {"home": strong, "away": others[0], "home_goals": 0, "away_goals": 1},
    ]}}
    three = {"group_results": {"A": [
        {"home": strong, "away": others[0], "home_goals": 0, "away_goals": 1},
        {"home": strong, "away": others[1], "home_goals": 0, "away_goals": 1},
        {"home": strong, "away": others[2], "home_goals": 0, "away_goals": 1},
    ]}}
    # Same per-match divergence, but more matches -> less shrinkage -> larger
    # magnitude.
    assert abs(compute_form(three, engine)[strong]) > abs(compute_form(one, engine)[strong])


def test_unknown_teams_are_ignored(engine):
    actuals = {"group_results": {"A": [
        {"home": "Atlantis", "away": "Wakanda", "home_goals": 1, "away_goals": 0},
    ]}}
    assert compute_form(actuals, engine) == {}
