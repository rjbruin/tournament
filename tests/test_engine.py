"""Invariant tests for the Monte-Carlo engine (app/simulation/engine.py).

These assert properties that must hold regardless of the random draws, using
modest simulation counts for speed and generous tolerances so they're not
flaky.
"""

import numpy as np
import pytest

from conftest import group_teams


def test_round_reach_totals(engine):
    np.random.seed(101)
    r = engine.run(n=4000)
    # Exactly one champion, two finalists, etc. — the per-team probabilities
    # must sum to the number of teams reaching that stage.
    assert sum(r["winner_prob"].values()) == pytest.approx(1, abs=0.02)
    assert sum(r["finalist_prob"].values()) == pytest.approx(2, abs=0.05)
    assert sum(r["semifinal_prob"].values()) == pytest.approx(4, abs=0.05)
    assert sum(r["quarterfinal_prob"].values()) == pytest.approx(8, abs=0.05)
    assert sum(r["round_of_16_prob"].values()) == pytest.approx(16, abs=0.1)
    assert sum(r["group_advance_prob"].values()) == pytest.approx(32, abs=0.1)


def test_probabilities_are_in_range(engine):
    np.random.seed(102)
    r = engine.run(n=2000)
    for key in ("winner_prob", "group_advance_prob", "finalist_prob"):
        for p in r[key].values():
            assert 0.0 <= p <= 1.0


def test_group_finish_positions_sum_to_one_per_group(engine):
    np.random.seed(103)
    r = engine.run(n=4000)
    for gname, teams in r["group_finish"].items():
        # Exactly one team finishes 1st in a group, one 2nd, etc.
        for pos in ("first_prob", "second_prob", "third_prob", "fourth_prob"):
            assert sum(t[pos] for t in teams.values()) == pytest.approx(1, abs=0.02)


def test_advance_prob_at_least_top_two_prob(engine):
    np.random.seed(104)
    r = engine.run(n=4000)
    for teams in r["group_finish"].values():
        for t in teams.values():
            # Advancing includes finishing top-2 (plus best-third), so it can
            # never be less than first+second.
            assert t["advance_prob"] >= t["first_prob"] + t["second_prob"] - 0.02


def test_run_is_deterministic_under_seed(engine):
    np.random.seed(99)
    a = engine.run(n=1500)["winner_prob"]
    np.random.seed(99)
    b = engine.run(n=1500)["winner_prob"]
    assert a == b


def test_fixed_group_result_is_reflected_in_fixtures(engine):
    g = engine.groups[0]
    teams = g["teams"]
    actuals = {"group_results": {g["name"]: [
        {"home": teams[0], "away": teams[1], "home_goals": 4, "away_goals": 0}]},
        "knockout_results": {}}
    np.random.seed(5)
    r = engine.run(n=1000, actuals=actuals)
    fixtures = r["fixtures"][g["name"]]
    played = next(m for m in fixtures
                  if {m["home"], m["away"]} == {teams[0], teams[1]})
    assert played["played"] is True
    assert played["home_goals"] == 4 and played["away_goals"] == 0


def test_fixed_knockout_winner_recorded(engine):
    # Force a champion for match 103; the engine should tag the bracket match.
    some_team = engine.team_names[0]
    actuals = {"group_results": {}, "knockout_results": {"103": some_team}}
    np.random.seed(6)
    r = engine.run(n=600, actuals=actuals)
    assert r["bracket_matches"][103]["actual_winner"] == some_team


def test_strong_group_favorite_advances_more_often(engine):
    # Within a group, the highest-Elo team should have the highest advance prob.
    np.random.seed(7)
    r = engine.run(n=5000)
    g = engine.groups[0]
    by_elo = max(g["teams"], key=lambda t: engine.team_elos[engine.team_idx[t]])
    advance = r["group_advance_prob"]
    assert advance[by_elo] == max(advance[t] for t in g["teams"])
