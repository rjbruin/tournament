"""
Top-level orchestration: ``simulate(spec, actuals, n, seed, groups) ->
TournamentRun``. A PURE function of its arguments — no shared mutable
state, no ambient RNG (see app.simulation.rng.SimRng) — so concurrent calls
never interfere. This is what retires
``SimulationEngine._temporary_groups``'s shared-state mutation
(engine.py:286-318): the live poller, checkpoint warmer, retrospective
computation, and web requests can each call ``simulate()`` from a different
thread on the same process without one run's custom ``groups`` override
corrupting another's in-flight simulation, because each call builds its own
fresh ``SimContext`` and seeding phase rather than mutating shared state.
"""

from __future__ import annotations

import time
from dataclasses import dataclass

import numpy as np

from app.simulation.phases.base import SimContext
from app.simulation.rng import SimRng
from app.simulation.stages import StageLadder


@dataclass
class TournamentRun:
    n: int
    spec: object
    ctx: SimContext
    phase_results: dict          # phase.id -> PhaseResult
    reached: np.ndarray           # (n, n_entries) int16 stage ladder
    ladder: StageLadder
    elapsed_seconds: float


def simulate(
    spec,
    actuals: dict,
    n: int,
    seed: int | None = None,
    groups: dict[str, list[str]] | None = None,
) -> TournamentRun:
    t0 = time.perf_counter()

    rng = SimRng(seed=seed)
    ctx = SimContext(
        n=n, rng=rng, sport=spec.sport,
        entry_names=spec.entry_names, entry_idx=spec.entry_idx, entry_elos=spec.entry_elos,
        actuals=actuals,
    )

    seeding = spec.seeding_factory(groups)
    ctx.outputs.update(seeding.simulate(ctx).outputs)

    stage_marks: list[tuple[np.ndarray, str]] = []
    phase_results: dict = {}
    for phase in spec.phases:
        result = phase.simulate(ctx)
        ctx.outputs.update(result.outputs)
        stage_marks.extend(result.stage_marks)
        phase_results[phase.id] = result

    ladder = StageLadder(spec.stage_ids)
    reached = ladder.build_reached(n, len(spec.entry_names), stage_marks)

    elapsed = time.perf_counter() - t0
    return TournamentRun(
        n=n, spec=spec, ctx=ctx, phase_results=phase_results,
        reached=reached, ladder=ladder, elapsed_seconds=elapsed,
    )
