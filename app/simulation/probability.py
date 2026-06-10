"""
Poisson goal model: derive expected goals from Elo ratings.

World Cup averages ~2.6 total goals/game → ~1.3 per team.
We model each team's expected goals as:
    λ_A = μ * exp(+Δ/2)
    λ_B = μ * exp(-Δ/2)
where Δ = (elo_A - elo_B) / SCALE and μ is the per-team average.

This keeps λ_A * λ_B constant (= μ²) and λ_A/λ_B = exp(Δ).
"""

import numpy as np

MU = 1.3          # average goals per team per 90 min in World Cups
ELO_SCALE = 400.0  # Elo points per log-odds unit (standard)
PENALTY_SCALE = 800.0  # weaker Elo influence in penalty shootouts


def compute_lambdas(elo_a: float, elo_b: float) -> tuple[float, float]:
    delta = (elo_a - elo_b) / ELO_SCALE
    la = MU * np.exp(delta / 2)
    lb = MU * np.exp(-delta / 2)
    return la, lb


def compute_lambdas_vec(elo_a: np.ndarray, elo_b: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Vectorized version — elo_a and elo_b can be arrays of shape (n,)."""
    delta = (elo_a - elo_b) / ELO_SCALE
    la = MU * np.exp(delta / 2)
    lb = MU * np.exp(-delta / 2)
    return la, lb


def penalty_win_prob(elo_a: np.ndarray, elo_b: np.ndarray) -> np.ndarray:
    """P(A wins penalty shootout) with a small Elo influence."""
    return 1.0 / (1.0 + np.exp(-(elo_a - elo_b) / PENALTY_SCALE))


def match_outcome_probs(elo_a: float, elo_b: float, knockout: bool = False, n: int = 200_000) -> dict:
    """
    Single-match outcome probabilities derived from the Poisson goal model.

    For a normal (group-stage) match returns home_win/draw/away_win.
    For a knockout match (no draws allowed - decided by penalties if level
    after 90 min) returns home_win/away_win, where drawn outcomes are
    split via the Elo-weighted penalty shootout model.
    """
    la, lb = compute_lambdas(elo_a, elo_b)
    ga = np.random.poisson(la, n)
    gb = np.random.poisson(lb, n)
    home = ga > gb
    draw = ga == gb
    away = ga < gb
    p_home = float(np.mean(home))
    p_draw = float(np.mean(draw))
    p_away = float(np.mean(away))
    if knockout:
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


def win_prob_from_elo(elo_a: float, elo_b: float) -> dict:
    """
    Approximate win/draw/loss probabilities for a 90-min match.
    Derived analytically from the Poisson model.
    """
    la, lb = compute_lambdas(elo_a, elo_b)
    # Monte Carlo estimate (fast enough for display)
    n = 200_000
    ga = np.random.poisson(la, n)
    gb = np.random.poisson(lb, n)
    p_win = float(np.mean(ga > gb))
    p_draw = float(np.mean(ga == gb))
    p_loss = float(np.mean(ga < gb))
    return {"win": p_win, "draw": p_draw, "loss": p_loss}
