"""
TournamentSpec: a sport + ordered list of phases (excluding seeding, which a
run constructs fresh per call — see app.simulation.run) + entry data,
sufficient to simulate() a full tournament.

Stage 1 builds a spec directly in Python from data/wc2026.json +
data/annex_c.json (``from_wc2026_json``); a YAML-driven loader for
templates/instances lands in Stage 2.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

import numpy as np

from app.simulation.allocators import LutBitmaskAllocator
from app.simulation.phases.base import Phase
from app.simulation.phases.knockout import KnockoutPhase, KnockoutRound, generate_single_elimination
from app.simulation.phases.round_robin import RoundRobinPhase
from app.simulation.phases.seeding import StaticGroupsSeeding, StaticPositionsSeeding
from app.simulation.sports.base import MatchRules
from app.simulation.sports.football import Football


@dataclass
class TournamentSpec:
    sport: object
    entry_names: list[str]
    entry_idx: dict[str, int]
    entry_elos: np.ndarray
    stage_ids: list[str]                    # ordered, least significant first
    phases: list                             # ordered Phase instances, seeding excluded
    # (groups_override: dict|None) -> a fresh seeding Phase instance for one
    # run. Format-specific: WC ignores nothing and needs groups_override for
    # custom draws; Wimbledon has no "groups" concept and ignores the arg.
    seeding_factory: Callable[[dict | None], Phase]
    raw_data: dict = field(default_factory=dict)   # passthrough for compat_wc (schedule, bracket defs, ...)
    # WC-specific extras, read by compat_wc.py; None for group-less formats.
    default_groups: dict[str, list[str]] | None = None
    group_letters: list[str] | None = None
    wildcard_position: int | None = None


def from_wc2026_json(tournament_data: dict, annex_c: dict) -> TournamentSpec:
    teams = tournament_data["teams"]
    entry_names = [t["name"] for t in teams]
    entry_idx = {name: i for i, name in enumerate(entry_names)}
    entry_elos = np.array([t["elo"] for t in teams], dtype=float)

    groups = tournament_data["groups"]
    group_letters = [g["name"] for g in groups]
    default_groups = {g["name"]: list(g["teams"]) for g in groups}

    bracket = tournament_data["bracket"]

    def defs_to_matches(defs):
        return [{"number": m["match"], "home": m["home"], "away": m["away"]} for m in defs]

    rounds = [
        KnockoutRound("r32", "r32", defs_to_matches(bracket["r32"])),
        KnockoutRound("r16", "r16", defs_to_matches(bracket["r16"])),
        KnockoutRound("qf", "qf", defs_to_matches(bracket["qf"])),
        KnockoutRound("sf", "sf", defs_to_matches(bracket["sf"])),
        KnockoutRound("final", "final", defs_to_matches([bracket["final"]])),
    ]
    allocator = LutBitmaskAllocator.from_annex_c(annex_c, n_groups=len(group_letters))

    from app.simulation.engine import GROUP_MATCH_PAIRS

    round_robin = RoundRobinPhase(
        group_letters=group_letters, group_size=4, match_order=GROUP_MATCH_PAIRS,
        rules=MatchRules(decider="draw", extra={"win_points": 3, "draw_points": 1, "loss_points": 0}),
        tiebreak_stat="goals", wildcard_position=2,
    )
    knockout = KnockoutPhase(
        rounds=rounds, rules=MatchRules(decider="shootout"), winner_stage="champion",
        wildcard_allocator=allocator, wildcard_source=(group_letters, 2),
    )

    def seeding_factory(groups_override):
        return StaticGroupsSeeding(groups_override or default_groups)

    return TournamentSpec(
        sport=Football(),
        entry_names=entry_names, entry_idx=entry_idx, entry_elos=entry_elos,
        stage_ids=["r32", "r16", "qf", "sf", "final", "champion"],
        phases=[round_robin, knockout],
        seeding_factory=seeding_factory,
        default_groups=default_groups,
        group_letters=group_letters,
        wildcard_position=2,
        raw_data={
            "tournament_data": tournament_data,
            "groups": groups,
            "bracket": bracket,
            "annex_match_order": annex_c["match_order"],
        },
    )


