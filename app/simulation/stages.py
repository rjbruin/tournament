"""
Stage ladder: turns per-phase stage_marks (which entries reached which named
stage, emitted by round_robin/knockout phases — see
app.simulation.phases.knockout's module docstring for the marking scheme)
into a numeric progression ladder and per-stage reach probabilities.

Generalizes the hardcoded reach-code ladder (codes 1,2,3,4,5,7 — 6 unused,
since there's no third-place playoff) in
SimulationEngine._simulate_knockout (engine.py:656-662) into an ordered,
named, template-declared list of stages. The specific integer codes used
here are an implementation detail — what matters is the ORDER, since
reach_prob is computed via a ">=" threshold on the code.
"""

from __future__ import annotations

import numpy as np


class StageLadder:
    def __init__(self, stage_ids: list[str]):
        """Args:
            stage_ids: ordered list, LEAST significant first (e.g.
                ``["r32", "r16", "qf", "sf", "final", "champion"]``).
        """
        self.stage_ids = list(stage_ids)
        self.code = {sid: i + 1 for i, sid in enumerate(self.stage_ids)}  # 1-based, monotone

    def build_reached(
        self, n: int, n_entries: int, stage_marks: list[tuple[np.ndarray, str]]
    ) -> np.ndarray:
        """``stage_marks``: ``[(entry_index_array, stage_id), ...]`` as
        emitted by phases' ``PhaseResult.stage_marks``. Each array must have
        shape ``(n,)`` — the entry occupying that "row" for every
        simulation (round_robin/knockout always mark full-width arrays, not
        boolean masks, since every match has a participant in every
        simulation)."""
        reached = np.zeros((n, n_entries), dtype=np.int16)
        sim_range = np.arange(n)
        for entries, stage_id in stage_marks:
            code = self.code[stage_id]
            reached[sim_range, entries] = np.maximum(reached[sim_range, entries], code)
        return reached

    def reach_prob(self, reached: np.ndarray, entry_names: list[str]) -> dict[str, dict[str, float]]:
        out = {}
        for sid in self.stage_ids:
            code = self.code[sid]
            probs = (reached >= code).mean(axis=0)
            out[sid] = {name: round(float(p), 4) for name, p in zip(entry_names, probs)}
        return out
