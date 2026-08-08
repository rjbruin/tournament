"""
Football (association football): Poisson goal model from Elo, draws allowed
in round-robin play, a penalty-shootout decider in knockout play.

Ports the model from the pre-refactor ``app.simulation.probability`` and the
knockout match simulation from
``SimulationEngine._simulate_knockout_match`` (engine.py:715-732).

The one behavioural change from the original: ``outcome_probs`` (used only
for DISPLAY odds — e.g. the group-fixture "62% / 24% / 14%" badges) is now
analytic via the Skellam distribution (the exact distribution of the
difference of two independent Poisson variables) instead of drawing
100,000-200,000 Poisson samples per call (engine.py:562, 809 and the old
``match_outcome_probs``). This removes sampling noise from every display
number and is materially faster — validated against the old MC estimate in
tests/golden/test_football_sport.py.
"""

from __future__ import annotations

import numpy as np
from scipy.stats import skellam

from app.simulation.sports.base import MatchOutcome, MatchRules, register

MU = 1.3                # average goals per team per 90 min in World Cups
ELO_SCALE = 400.0       # Elo points per log-odds unit
PENALTY_SCALE = 800.0   # weaker Elo influence in penalty shootouts


def compute_lambdas(elo_a, elo_b):
    """Poisson goal-rate pair from an Elo gap. Vectorized (elo_a/elo_b may
    be arrays) and scalar-safe (matches the old compute_lambdas/
    compute_lambdas_vec split, now a single function)."""
    delta = (elo_a - elo_b) / ELO_SCALE
    la = MU * np.exp(delta / 2)
    lb = MU * np.exp(-delta / 2)
    return la, lb


def penalty_win_prob(elo_a, elo_b):
    """P(side A wins a penalty shootout), a weak Elo-logistic influence."""
    return 1.0 / (1.0 + np.exp(-(elo_a - elo_b) / PENALTY_SCALE))


class Football:
    def stat_names(self) -> list[str]:
        return ["goals"]

    def simulate_h2h(self, elo_a, elo_b, rules: MatchRules, rng, state=None) -> MatchOutcome:
        la, lb = compute_lambdas(elo_a, elo_b)
        goals_a = rng.poisson(la)
        goals_b = rng.poisson(lb)
        drew = goals_a == goals_b

        winner = np.where(goals_a > goals_b, 0, np.where(goals_a < goals_b, 1, -1)).astype(np.int8)

        decider = rules.decider
        if decider == "shootout":
            if np.any(drew):
                p_a_pen = penalty_win_prob(elo_a[drew], elo_b[drew])
                pen_wins_a = rng.random(int(np.sum(drew))) < p_a_pen
                winner[drew] = np.where(pen_wins_a, 0, 1).astype(np.int8)
        elif decider != "draw":
            raise ValueError(f"football: unknown decider {decider!r}")
        # decider == "draw": leave winner == -1 wherever drew is True; the
        # round_robin phase awards draw points and never needs a winner.

        return MatchOutcome(winner=winner, stats={"goals": (goals_a, goals_b)}, drew=drew)

    def points_for(self, outcome: MatchOutcome, rules: MatchRules) -> tuple[np.ndarray, np.ndarray]:
        win_pts = rules.get("win_points", 3)
        draw_pts = rules.get("draw_points", 1)
        loss_pts = rules.get("loss_points", 0)
        ga, gb = outcome.stats["goals"]
        win_a = ga > gb
        win_b = gb > ga
        draw = ga == gb
        pts_a = win_pts * win_a + draw_pts * draw + loss_pts * (~win_a & ~draw)
        pts_b = win_pts * win_b + draw_pts * draw + loss_pts * (~win_b & ~draw)
        return pts_a.astype(int), pts_b.astype(int)

    def outcome_probs(self, elo_a: float, elo_b: float, rules: MatchRules) -> dict:
        la, lb = compute_lambdas(elo_a, elo_b)
        p_draw = float(skellam.pmf(0, la, lb))
        p_away = float(skellam.cdf(-1, la, lb))
        p_home = 1.0 - float(skellam.cdf(0, la, lb))
        if rules.decider == "shootout":
            p_pen = float(penalty_win_prob(np.array([elo_a]), np.array([elo_b]))[0])
            return {
                "home_win": round(p_home + p_draw * p_pen, 4),
                "away_win": round(p_away + p_draw * (1 - p_pen), 4),
            }
        return {
            "home_win": round(p_home, 4),
            "draw": round(p_draw, 4),
            "away_win": round(p_away, 4),
        }


register("football", Football())
