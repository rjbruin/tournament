"""
Sport protocol: how a match between two entries is simulated (vectorized,
across all n Monte Carlo runs at once) and scored for round-robin points.

A "sport" owns everything specific to the GAME being played — goal/set
models, tiebreak deciders. A "phase" (app.simulation.phases) owns tournament
STRUCTURE (who plays whom, who advances) and is sport-agnostic. Splitting
these is what lets the same round_robin/knockout phase code serve football
(engine.py's current hardcoded Poisson model) and tennis (Stage 3) alike.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol

import numpy as np


@dataclass
class MatchOutcome:
    """Result of simulating one batch of head-to-head matches (n at once).

    Attributes:
        winner: ``(n,)`` int8 — 0 if side A won, 1 if side B won, -1 where
            undecided (a draw that no decider resolved — only possible when
            ``rules.decider == "draw"``; round_robin phases handle this,
            knockout phases must use a decider that never leaves -1).
        stats: ``{"stat_name": (a_array, b_array)}``, each ``(n,)`` — the
            per-entry statistics a round_robin phase accumulates and
            tiebreaks on (e.g. ``{"goals": (ga, gb)}`` for football,
            ``{"sets": (sa, sb)}`` for tennis). Every sport must produce
            enough stats for its own ``points_for``/tiebreak criteria.
        drew: ``(n,)`` bool, or None for sports with no draw concept
            (e.g. tennis) — whether the match was level before any decider.
    """

    winner: np.ndarray
    stats: dict[str, tuple[np.ndarray, np.ndarray]]
    drew: np.ndarray | None = None


@dataclass
class MatchRules:
    """Sport- and phase-specific match configuration (e.g. football's
    knockout decider, tennis's sets-to-win). Each Sport interprets its own
    keys via ``get``; unknown keys are ignored, so a round_robin phase's
    rules and a knockout phase's rules for the same sport can carry
    different extras without needing separate types."""

    decider: str = "draw"  # "draw" | "shootout" | ...
    extra: dict = field(default_factory=dict)

    def get(self, key, default=None):
        return self.extra.get(key, default)


class Sport(Protocol):
    """Everything a phase needs to simulate matches and score a table for
    one sport. Implementations must be pure functions of
    (elo, rules, rng[, state]) — no global state, no ambient RNG (see
    app.simulation.rng.SimRng); this is what makes ``simulate(seed=k)``
    reproducible even under concurrent engine runs."""

    def stat_names(self) -> list[str]:
        """Names this sport can produce in MatchOutcome.stats — used to
        validate a tiebreak cascade at spec-load time instead of failing
        deep into a 250k-simulation run on a YAML typo."""
        ...

    def simulate_h2h(
        self,
        elo_a: np.ndarray,
        elo_b: np.ndarray,
        rules: MatchRules,
        rng,
        state: dict | None = None,
    ) -> MatchOutcome:
        """Simulate n matches at once. ``state``, when given, describes a
        partial/in-progress match to condition on — reserved for Stage 4
        (partial-match simulation); Stage 1-3 implementations ignore it and
        always simulate from a clean start."""
        ...

    def points_for(self, outcome: MatchOutcome, rules: MatchRules) -> tuple[np.ndarray, np.ndarray]:
        """Round-robin points awarded to (side A, side B) for this outcome,
        each an ``(n,)`` int array."""
        ...

    def outcome_probs(self, elo_a: float, elo_b: float, rules: MatchRules) -> dict:
        """Analytic (not sampled) single-match outcome probabilities for
        display odds, e.g. ``{"home_win", "draw", "away_win"}``."""
        ...


_REGISTRY: dict[str, Sport] = {}


def register(name: str, sport: Sport) -> None:
    _REGISTRY[name] = sport


def get(name: str) -> Sport:
    try:
        return _REGISTRY[name]
    except KeyError:
        raise ValueError(f"unknown sport {name!r}; registered: {sorted(_REGISTRY)}")
