"""Tests for the Poisson/Elo goal model (app/simulation/probability.py)."""

import numpy as np
import pytest

from app.simulation import probability as P


def test_equal_elo_gives_equal_lambdas():
    la, lb = P.compute_lambdas(1800, 1800)
    assert la == pytest.approx(lb)
    assert la == pytest.approx(P.MU)


def test_stronger_team_has_higher_lambda():
    la, lb = P.compute_lambdas(2000, 1600)
    assert la > P.MU > lb
    # The model keeps the product constant (= MU^2).
    assert la * lb == pytest.approx(P.MU ** 2)


def test_lambdas_vectorized_matches_scalar():
    a = np.array([2000.0, 1600.0])
    b = np.array([1600.0, 2000.0])
    la, lb = P.compute_lambdas_vec(a, b)
    assert la[0] == pytest.approx(P.compute_lambdas(2000, 1600)[0])
    assert lb[1] == pytest.approx(P.compute_lambdas(1600, 2000)[1])


def test_penalty_win_prob_is_a_symmetric_logistic():
    even = P.penalty_win_prob(np.array([1800.0]), np.array([1800.0]))[0]
    assert even == pytest.approx(0.5)
    favored = P.penalty_win_prob(np.array([2200.0]), np.array([1400.0]))[0]
    assert favored > 0.5
    # P(A beats B) + P(B beats A) == 1.
    rev = P.penalty_win_prob(np.array([1400.0]), np.array([2200.0]))[0]
    assert favored + rev == pytest.approx(1.0)


def test_group_match_probs_sum_to_one():
    np.random.seed(7)
    probs = P.match_outcome_probs(1900, 1700, knockout=False, n=200_000)
    assert set(probs) == {"home_win", "draw", "away_win"}
    assert sum(probs.values()) == pytest.approx(1.0, abs=0.01)
    assert probs["home_win"] > probs["away_win"]  # stronger home team


def test_knockout_probs_have_no_draw_and_sum_to_one():
    np.random.seed(7)
    probs = P.match_outcome_probs(1900, 1700, knockout=True, n=200_000)
    assert set(probs) == {"home_win", "away_win"}
    assert sum(probs.values()) == pytest.approx(1.0, abs=0.01)


def test_even_match_is_roughly_symmetric():
    np.random.seed(7)
    probs = P.match_outcome_probs(1800, 1800, knockout=False, n=200_000)
    assert probs["home_win"] == pytest.approx(probs["away_win"], abs=0.02)
