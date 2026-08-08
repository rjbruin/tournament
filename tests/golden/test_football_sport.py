"""
Golden test: app.simulation.sports.football.Football against the current
engine's Poisson/penalty model (app.simulation.probability, and
SimulationEngine._simulate_knockout_match for the shootout decider).

outcome_probs is now analytic (Skellam) rather than Monte Carlo, so it is
compared against a large-n MC estimate from the OLD code within a tight
statistical tolerance, not bit-for-bit. simulate_h2h is compared against
itself (empirical vs analytic self-consistency) and against the actual
production knockout-match simulator's empirical win rate.
"""

import math

import numpy as np
import pytest

from app.simulation.probability import match_outcome_probs, compute_lambdas as old_compute_lambdas
from app.simulation.rng import SimRng
from app.simulation.sports.base import MatchRules
from app.simulation.sports.football import Football, compute_lambdas, penalty_win_prob

ELO_PAIRS = [(1600, 1600), (1700, 1600), (1600, 1700), (1900, 1500), (1500, 1900), (1650, 1648)]

sport = Football()


def _wald_bound(p_a, n_a, p_b, n_b, z=4.0):
    p_bar = (p_a + p_b) / 2
    var = p_bar * (1 - p_bar) * (1 / n_a + 1 / n_b)
    return z * math.sqrt(max(var, 0)) + 1e-4


def test_compute_lambdas_matches_old_exactly():
    for elo_a, elo_b in ELO_PAIRS:
        la_new, lb_new = compute_lambdas(elo_a, elo_b)
        la_old, lb_old = old_compute_lambdas(elo_a, elo_b)
        assert la_new == pytest.approx(la_old)
        assert lb_new == pytest.approx(lb_old)


def test_group_outcome_probs_analytic_matches_old_mc():
    n_mc = 2_000_000
    for elo_a, elo_b in ELO_PAIRS:
        analytic = sport.outcome_probs(elo_a, elo_b, MatchRules(decider="draw"))
        old_mc = match_outcome_probs(elo_a, elo_b, knockout=False, n=n_mc)
        for key in ("home_win", "draw", "away_win"):
            bound = _wald_bound(analytic[key], 10_000_000, old_mc[key], n_mc)  # analytic treated as ~exact
            assert abs(analytic[key] - old_mc[key]) < bound, (
                f"elo=({elo_a},{elo_b}) {key}: analytic={analytic[key]} mc={old_mc[key]} bound={bound}"
            )
        # Each of the 3 values is independently rounded to 4dp, so the sum
        # can be off from 1.0 by up to ~3*0.00005 — not exactly 1.0.
        total = sum(analytic.values())
        assert total == pytest.approx(1.0, abs=2e-4)


def test_knockout_outcome_probs_analytic_matches_old_mc():
    n_mc = 2_000_000
    for elo_a, elo_b in ELO_PAIRS:
        analytic = sport.outcome_probs(elo_a, elo_b, MatchRules(decider="shootout"))
        old_mc = match_outcome_probs(elo_a, elo_b, knockout=True, n=n_mc)
        for key in ("home_win", "away_win"):
            bound = _wald_bound(analytic[key], 10_000_000, old_mc[key], n_mc)
            assert abs(analytic[key] - old_mc[key]) < bound
        total = sum(analytic.values())
        assert total == pytest.approx(1.0, abs=1e-6)


def test_simulate_h2h_group_empirical_matches_analytic():
    n = 300_000
    rng = SimRng(seed=1)
    for elo_a, elo_b in ELO_PAIRS[:3]:
        elo_a_arr = np.full(n, elo_a, dtype=float)
        elo_b_arr = np.full(n, elo_b, dtype=float)
        outcome = sport.simulate_h2h(elo_a_arr, elo_b_arr, MatchRules(decider="draw"), rng)
        p_home = float(np.mean(outcome.winner == 0))
        p_away = float(np.mean(outcome.winner == 1))
        p_draw = float(np.mean(outcome.drew))
        analytic = sport.outcome_probs(elo_a, elo_b, MatchRules(decider="draw"))
        for key, empirical in (("home_win", p_home), ("draw", p_draw), ("away_win", p_away)):
            bound = _wald_bound(analytic[key], 10_000_000, empirical, n)
            assert abs(analytic[key] - empirical) < bound, (
                f"elo=({elo_a},{elo_b}) {key}: analytic={analytic[key]} empirical={empirical}"
            )


def test_simulate_h2h_shootout_matches_production_knockout_match(engine):
    """Compares against the ACTUAL production simulator
    (SimulationEngine._simulate_knockout_match), not just our own formula.
    That function indexes self.team_elos by TEAM INDEX, not by raw Elo
    value, so we use a few real team-index pairs (whatever Elo gaps they
    happen to have) rather than the synthetic ELO_PAIRS above."""
    n = 300_000
    np.random.seed(777)  # old path uses global RNG
    rng = SimRng(seed=777)

    index_pairs = [(0, 1), (0, 10), (5, 40)]
    for ia, ib in index_pairs:
        team_a_idx = np.full(n, ia, dtype=int)
        team_b_idx = np.full(n, ib, dtype=int)
        elo_a, elo_b = float(engine.team_elos[ia]), float(engine.team_elos[ib])

        old_winner = engine._simulate_knockout_match(team_a_idx, team_b_idx)  # 0=a,1=b
        old_p_home = float(np.mean(old_winner == 0))

        elo_a_arr = np.full(n, elo_a, dtype=float)
        elo_b_arr = np.full(n, elo_b, dtype=float)
        outcome = sport.simulate_h2h(elo_a_arr, elo_b_arr, MatchRules(decider="shootout"), rng)
        assert not np.any(outcome.winner == -1), "shootout decider must resolve every draw"
        new_p_home = float(np.mean(outcome.winner == 0))

        bound = _wald_bound(old_p_home, n, new_p_home, n, z=5.0)
        assert abs(old_p_home - new_p_home) < bound, (
            f"elo=({elo_a},{elo_b}): old={old_p_home} new={new_p_home} bound={bound}"
        )


def test_points_for_standard_3_1_0():
    n = 4
    ga = np.array([2, 0, 1, 3])
    gb = np.array([0, 2, 1, 1])
    from app.simulation.sports.base import MatchOutcome
    outcome = MatchOutcome(
        winner=np.array([0, 1, -1, 0], dtype=np.int8),
        stats={"goals": (ga, gb)},
        drew=np.array([False, False, True, False]),
    )
    pts_a, pts_b = sport.points_for(outcome, MatchRules(decider="draw"))
    assert pts_a.tolist() == [3, 0, 1, 3]
    assert pts_b.tolist() == [0, 3, 1, 0]


def test_penalty_win_prob_matches_old_formula():
    old = 1.0 / (1.0 + np.exp(-(1700 - 1600) / 800.0))
    new = penalty_win_prob(np.array([1700.0]), np.array([1600.0]))[0]
    assert new == pytest.approx(old)
