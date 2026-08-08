"""
Tennis: per-set win probability from Elo, best-of-N sets (5 for men's
Grand Slam singles, 3 for most other formats), no draws — every match has
a winner by construction.

``set_scale`` (the Elo-to-log-odds divisor at the SET level) is NOT the
same number as the match-level ELO_SCALE, and must not be guessed: playing
best-of-N sets AMPLIFIES a per-set edge into a larger match-level edge (a
0.60 set-win probability compounds to a 0.68 match-win probability at
best-of-5), so a set_scale equal to the target match-level scale would
overstate the true match-level favourite. The values below were solved
numerically — least-squares fit of the induced best-of-N match probability
against the target Elo logistic over Δ ∈ [-800, 800] — and validated to
match the target within 0.005 at Δ ∈ {50, 100, 200, 400} (see
tests/golden/test_tennis_sport.py). Re-run the calibration in that test's
module docstring if ELO_SCALE ever changes.
"""

from __future__ import annotations

import numpy as np

from app.simulation.sports.base import MatchOutcome, MatchRules, register

ELO_SCALE = 400.0  # match-level target — same convention as football

# Solved numerically (see module docstring) for ELO_SCALE=400.
SET_SCALE_BEST_OF_5 = 766.24
SET_SCALE_BEST_OF_3 = 609.70


def _set_scale(sets_to_win: int) -> float:
    if sets_to_win == 3:
        return SET_SCALE_BEST_OF_5
    if sets_to_win == 2:
        return SET_SCALE_BEST_OF_3
    raise ValueError(
        f"tennis: no calibrated set_scale for sets_to_win={sets_to_win} "
        f"(only best-of-5 [3] and best-of-3 [2] are calibrated)"
    )


def p_set(elo_a, elo_b, sets_to_win: int):
    scale = _set_scale(sets_to_win)
    delta = (elo_a - elo_b) / scale
    return 1.0 / (1.0 + np.exp(-delta))


def match_prob_analytic(elo_a: float, elo_b: float, sets_to_win: int) -> dict:
    """Analytic (closed-form, no RNG) match-win probabilities — the negative
    binomial "win `sets_to_win` before opponent does" formula."""
    p = float(p_set(np.array([elo_a]), np.array([elo_b]), sets_to_win)[0])
    max_losses = sets_to_win - 1
    home_win = sum(
        _comb(sets_to_win - 1 + k, k) * p**sets_to_win * (1 - p) ** k
        for k in range(max_losses + 1)
    )
    return {"home_win": round(home_win, 4), "away_win": round(1 - home_win, 4)}


def _comb(n, k):
    from math import comb
    return comb(n, k)


class Tennis:
    def stat_names(self) -> list[str]:
        return ["sets"]

    def simulate_h2h(self, elo_a, elo_b, rules: MatchRules, rng, state=None) -> MatchOutcome:
        sets_to_win = rules.get("sets_to_win", 3)
        max_sets = 2 * sets_to_win - 1
        n = elo_a.shape[0]
        prob = p_set(elo_a, elo_b, sets_to_win)

        draws = rng.random((n, max_sets))
        won_a = draws < prob[:, None]  # (n, max_sets) bool
        cum_a = np.cumsum(won_a, axis=1)
        cum_b = np.cumsum(~won_a, axis=1)
        # First column index where either side reaches sets_to_win.
        decided = (cum_a >= sets_to_win) | (cum_b >= sets_to_win)
        k = decided.argmax(axis=1)  # first True index per row (all rows decide within max_sets)
        rows = np.arange(n)
        sets_a = cum_a[rows, k]
        sets_b = cum_b[rows, k]

        winner = np.where(sets_a > sets_b, 0, 1).astype(np.int8)
        return MatchOutcome(winner=winner, stats={"sets": (sets_a, sets_b)}, drew=None)

    def points_for(self, outcome: MatchOutcome, rules: MatchRules):
        # Tennis knockout has no round-robin points concept in this
        # template (Wimbledon is bracket-only), but a future round-robin
        # tennis format (e.g. a league) could reuse "sets won" as points.
        sets_a, sets_b = outcome.stats["sets"]
        return sets_a.astype(int), sets_b.astype(int)

    def outcome_probs(self, elo_a: float, elo_b: float, rules: MatchRules) -> dict:
        sets_to_win = rules.get("sets_to_win", 3)
        return match_prob_analytic(elo_a, elo_b, sets_to_win)


register("tennis", Tennis())
