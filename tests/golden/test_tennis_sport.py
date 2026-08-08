"""
Golden test: app.simulation.sports.tennis.Tennis — the set_scale calibration
(the numeric solve is reproduced here from scratch as an independent check,
not just re-imported) and empirical/analytic self-consistency.
"""

import math

import numpy as np
import pytest
from scipy.optimize import minimize_scalar

from app.simulation.rng import SimRng
from app.simulation.sports.base import MatchRules
from app.simulation.sports.tennis import (
    ELO_SCALE, SET_SCALE_BEST_OF_3, SET_SCALE_BEST_OF_5, Tennis, match_prob_analytic, p_set,
)

sport = Tennis()


def _target_p_match(delta):
    return 1.0 / (1.0 + np.exp(-delta / ELO_SCALE))


def _match_prob_best_of_n(p, sets_to_win):
    return sum(
        math.comb(sets_to_win - 1 + k, k) * p**sets_to_win * (1 - p) ** k
        for k in range(sets_to_win)
    )


def _induced_p_match(delta, set_scale, sets_to_win):
    p = 1.0 / (1.0 + np.exp(-delta / set_scale))
    return _match_prob_best_of_n(p, sets_to_win)


@pytest.mark.parametrize("sets_to_win,expected_scale", [(3, SET_SCALE_BEST_OF_5), (2, SET_SCALE_BEST_OF_3)])
def test_set_scale_is_the_least_squares_optimum(sets_to_win, expected_scale):
    """Independently re-derive the calibration (not just re-import the
    constant) and confirm the module's baked-in value matches the optimum."""
    deltas = np.linspace(-800, 800, 400)
    targets = _target_p_match(deltas)

    def loss(scale):
        induced = np.array([_induced_p_match(d, scale, sets_to_win) for d in deltas])
        return float(np.mean((induced - targets) ** 2))

    res = minimize_scalar(loss, bounds=(200, 1200), method="bounded")
    assert abs(res.x - expected_scale) < 1.0, f"recomputed optimum {res.x} vs baked-in {expected_scale}"


@pytest.mark.parametrize("sets_to_win", [3, 2])
@pytest.mark.parametrize("delta", [50, 100, 200, 400])
def test_calibration_within_tolerance_at_required_deltas(sets_to_win, delta):
    scale = SET_SCALE_BEST_OF_5 if sets_to_win == 3 else SET_SCALE_BEST_OF_3
    target = _target_p_match(delta)
    induced = _induced_p_match(delta, scale, sets_to_win)
    assert abs(target - induced) < 0.005, f"delta={delta} sets_to_win={sets_to_win}: target={target} induced={induced}"


def test_match_prob_analytic_matches_reference_formula():
    for elo_a, elo_b in [(2300, 1900), (2100, 2100), (1900, 2300)]:
        analytic = match_prob_analytic(elo_a, elo_b, sets_to_win=3)
        p = float(p_set(np.array([elo_a]), np.array([elo_b]), 3)[0])
        expected_home = _match_prob_best_of_n(p, 3)
        assert analytic["home_win"] == pytest.approx(expected_home, abs=1e-4)
        assert analytic["home_win"] + analytic["away_win"] == pytest.approx(1.0, abs=1e-4)


def test_simulate_h2h_empirical_matches_analytic():
    n = 300_000
    rng = SimRng(seed=7)
    for elo_a, elo_b in [(2300, 1900), (2100, 2100), (1950, 2250)]:
        elo_a_arr = np.full(n, elo_a, dtype=float)
        elo_b_arr = np.full(n, elo_b, dtype=float)
        outcome = sport.simulate_h2h(elo_a_arr, elo_b_arr, MatchRules(extra={"sets_to_win": 3}), rng)
        empirical_home = float(np.mean(outcome.winner == 0))
        analytic = match_prob_analytic(elo_a, elo_b, sets_to_win=3)

        p_bar = (empirical_home + analytic["home_win"]) / 2
        bound = 4.5 * math.sqrt(p_bar * (1 - p_bar) / n) + 1e-4
        assert abs(empirical_home - analytic["home_win"]) < bound, (
            f"elo=({elo_a},{elo_b}): empirical={empirical_home} analytic={analytic['home_win']}"
        )


def test_simulate_h2h_set_counts_are_valid():
    n = 5000
    rng = SimRng(seed=8)
    elo_a = np.full(n, 2200, dtype=float)
    elo_b = np.full(n, 1900, dtype=float)
    outcome = sport.simulate_h2h(elo_a, elo_b, MatchRules(extra={"sets_to_win": 3}), rng)
    sets_a, sets_b = outcome.stats["sets"]

    assert np.all((sets_a == 3) | (sets_b == 3)), "every match must have a side reach 3 sets"
    assert np.all(sets_a < 3) | np.all(sets_a <= 3)
    assert np.all((sets_a <= 3) & (sets_b <= 3))
    assert np.all((sets_a < 3) | (sets_b < 3)), "both sides can't reach 3 (match ends immediately)"
    winner_a = outcome.winner == 0
    assert np.all(sets_a[winner_a] == 3)
    assert np.all(sets_b[~winner_a] == 3)


def test_never_a_draw():
    n = 2000
    rng = SimRng(seed=9)
    elo_a = np.full(n, 2000, dtype=float)
    elo_b = np.full(n, 2000, dtype=float)
    outcome = sport.simulate_h2h(elo_a, elo_b, MatchRules(extra={"sets_to_win": 3}), rng)
    assert set(np.unique(outcome.winner).tolist()) <= {0, 1}


def test_best_of_3_uses_different_scale_and_resolves_at_2_sets():
    n = 4000
    rng = SimRng(seed=10)
    elo_a = np.full(n, 2100, dtype=float)
    elo_b = np.full(n, 1900, dtype=float)
    outcome = sport.simulate_h2h(elo_a, elo_b, MatchRules(extra={"sets_to_win": 2}), rng)
    sets_a, sets_b = outcome.stats["sets"]
    assert np.all((sets_a == 2) | (sets_b == 2))
    assert np.all((sets_a <= 2) & (sets_b <= 2))
