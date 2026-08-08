"""
Seeding phases: assign entries to fixed structural positions (round-robin
group slots, bracket seats) before any match is simulated.

Replaces ``SimulationEngine._temporary_groups`` (engine.py:286-318), which
MUTATES the shared ``self.groups``/``self._group_indices``/
``self._group_team_pos`` for the duration of one ``run()`` call — unsafe
because the live poller, checkpoint warmer, and retrospective computation
(app/__init__.py, app/retrospective.py) all call ``run()`` on the same
engine instance as concurrent web requests, so a pre-draw scenario running
in one thread can corrupt another thread's in-flight simulation.

The replacement needs no mutation: a draw-marginalization caller that wants
to average over several possible group compositions (today's
``app.simulation.draw.simulate_many_draws`` + ``_average_results`` in
app/__init__.py) just builds a fresh ``StaticGroupsSeeding`` with a
different ``groups`` argument for each independent ``simulate()`` call and
averages the results externally — exactly the pattern already used today,
just without the shared-state mutation.
"""

from __future__ import annotations

import numpy as np

from app.simulation.phases.base import Phase, PhaseResult, SimContext, SlotOutput


class StaticGroupsSeeding(Phase):
    """Assigns entries to fixed round-robin group positions — the same
    composition for every simulation in this run. Covers both the real
    tournament groups and a single resolved draw (the caller varies
    ``groups`` across independent runs to marginalize over several draws)."""

    id = "seeding"

    def __init__(self, groups: dict[str, list[str]]):
        self.groups = groups  # {letter: [names]}, order = position within group

    def simulate(self, ctx: SimContext) -> PhaseResult:
        outputs = {}
        for letter, names in self.groups.items():
            for pos, name in enumerate(names):
                idx = ctx.entry_idx[name]
                outputs[("group_slot", letter, pos)] = SlotOutput(
                    entries=np.full(ctx.n, idx, dtype=np.int64)
                )
        return PhaseResult(outputs=outputs, stage_marks=[], matches=[])


class StaticPositionsSeeding(Phase):
    """Assigns entries to fixed bracket seats — the Wimbledon case (a
    published 128-draw), included here as a minimal forward-compatible stub
    since it requires no group-position bookkeeping.

    Not exercised by the WC2026 re-expression (Stage 1); validated for real
    once a bracket-only tournament (Stage 3) uses it."""

    id = "seeding"

    def __init__(self, positions: list[str]):
        self.positions = positions  # index -> entry name, "" for a TBD/bye seat

    def simulate(self, ctx: SimContext) -> PhaseResult:
        outputs = {}
        for seat, name in enumerate(self.positions):
            if not name:
                continue
            idx = ctx.entry_idx[name]
            outputs[("seat", seat)] = SlotOutput(entries=np.full(ctx.n, idx, dtype=np.int64))
        return PhaseResult(outputs=outputs, stage_marks=[], matches=[])
