"""
Seeded, per-run random number generation.

The current engine draws every random number from the GLOBAL ``np.random``
state (e.g. ``np.random.poisson`` at engine.py:393, 720), which has two real
consequences: ``np.random.seed()`` reproducibility (relied on by
``tests/conftest.py``'s autouse ``_seed_rng`` fixture) is meaningless the
moment two runs interleave, and they do — the live poller, checkpoint
warmer, and retrospective computation are all background threads that call
``SimulationEngine.run()`` on the same process as concurrent web requests
(see app/__init__.py's poller threads and app/retrospective.py).

``SimRng`` makes randomness an explicit, passed-in dependency instead of
ambient global state, so ``simulate(..., seed=k)`` is a pure function: same
spec + same actuals + same seed + same n => byte-identical output, regardless
of what else is running concurrently.
"""

from __future__ import annotations

import numpy as np


class SimRng:
    """Thin wrapper around ``np.random.Generator`` exposing exactly the
    operations the simulation primitives need. Never touch ``np.random``
    directly from simulation code — take a ``SimRng`` instead."""

    def __init__(self, seed: int | None = None):
        self._gen = np.random.default_rng(seed)

    def poisson(self, lam: np.ndarray, size=None) -> np.ndarray:
        return self._gen.poisson(lam, size=size)

    def random(self, size=None) -> np.ndarray:
        return self._gen.random(size=size)

    def integers(self, low, high=None, size=None) -> np.ndarray:
        return self._gen.integers(low, high, size=size)

    def permutation(self, x):
        return self._gen.permutation(x)

    def choice(self, a, size=None, replace: bool = True, p=None):
        return self._gen.choice(a, size=size, replace=replace, p=p)

    def spawn(self, n: int) -> list["SimRng"]:
        """Independent child generators (for e.g. per-draw pre-draw
        marginalization, where each draw needs its own uncorrelated stream)."""
        children = self._gen.spawn(n)
        out = []
        for child in children:
            wrapper = SimRng.__new__(SimRng)
            wrapper._gen = child
            out.append(wrapper)
        return out
