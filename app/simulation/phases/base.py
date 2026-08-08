"""
Phase protocol: a tournament STAGE's progression logic (who plays whom, who
advances), sport-agnostic — as opposed to app.simulation.sports.Sport, which
owns how one match is scored. round_robin.py and knockout.py implement this
for group tables and elimination brackets respectively; both work for any
sport that implements the Sport protocol.

Scoping note (Stage 1): actuals are consumed in TODAY's shape — group
results keyed by group name with home/away entry NAMES, knockout results
keyed by an external match number — rather than the fully general flat
structural addressing sketched in the refactor plan (MatchAddr tuples,
positional addressing for name-pair collisions). That generalization is
needed once a tournament has no groups or no match numbers (Wimbledon,
Stage 3); building it now, with only one real format to validate it
against, risks getting the abstraction wrong. `enumerate_matches` /
`resolve_actuals` are left as documented extension points for that stage
rather than implemented against a single example.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np


@dataclass
class SlotOutput:
    """One named, cross-referenceable output of a phase: an ``(n,)`` array
    of entry indices, plus an optional ``rank_key`` for cross-group
    comparison (e.g. Annex C-style wildcard allocation — see
    app.simulation.allocators)."""

    entries: np.ndarray
    rank_key: np.ndarray | None = None


@dataclass
class MatchRecord:
    """A single match's DISPLAY-oriented summary — already reduced from
    per-simulation ``(n,)`` arrays to distributions, mirroring what
    ``SimulationEngine._slot_summary`` / ``_summarize_bracket_matches``
    produce today, so a compat shim can reconstruct the legacy
    ``fixtures``/``bracket_matches`` dicts without re-deriving anything."""

    match_id: Any             # phase-defined address, e.g. ("ko", 73)
    phase: str
    round_id: str | None
    number: int | None        # external match number, if the format has one
    side_a: dict               # {"determined": bool, "team": str|None, "elo": float|None, "candidates": [...]}
    side_b: dict
    outcome: dict | None       # analytic match odds, e.g. {"home_win":..,"draw":..,"away_win":..}
    actual: dict | None        # recorded real-world result, if any
    extra: dict = field(default_factory=dict)   # schedule/venue/group letter/etc, passthrough


@dataclass
class PhaseResult:
    outputs: dict[Any, SlotOutput]
    stage_marks: list[tuple[np.ndarray, str]]   # [(entry_index_array, stage_id), ...]
    matches: list[MatchRecord]
    extra: dict = field(default_factory=dict)    # phase-specific extras, e.g. round_robin's standings table


@dataclass
class SimContext:
    """Shared state threaded through every phase of one simulation run.

    ``outputs`` accumulates every phase's ``SlotOutput``s as phases run in
    spec order, so a later phase (e.g. knockout) can reference an earlier
    phase's output (e.g. ``("group_pos", "A", 1)``) by key.
    """

    n: int
    rng: Any                      # app.simulation.rng.SimRng
    sport: Any                    # app.simulation.sports.base.Sport
    entry_names: list[str]
    entry_idx: dict[str, int]
    entry_elos: np.ndarray        # (n_entries,) float
    actuals: dict
    outputs: dict = field(default_factory=dict)


class Phase:
    """Base class for a tournament phase. Subclasses implement ``simulate``;
    ``id`` should be a stable identifier used as the phase key in
    ``TournamentRun``/``Results.phases``."""

    id: str = ""

    def simulate(self, ctx: SimContext) -> PhaseResult:
        raise NotImplementedError
