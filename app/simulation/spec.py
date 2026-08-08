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
from app.simulation.sports.tennis import Tennis


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


def from_wimbledon_json(entries_data: list[dict], positions: list[str], elo_field: str = "elo_grass",
                         sets_to_win: int = 3) -> TournamentSpec:
    """Build a spec for a single-elimination, groupless bracket tournament
    (e.g. Wimbledon gentlemen's singles) from a flat entries list and an
    ordered draw-position list.

    Args:
        entries_data: ``[{"name", ..., <elo_field>: float}, ...]`` — order
            doesn't matter, only ``positions`` determines draw seats.
        positions: ``positions[i]`` is the entry name occupying draw seat i;
            length must be a power of 2.
        elo_field: which key in each entry dict holds the rating to use
            (e.g. a surface-specific rating like "elo_grass").
        sets_to_win: 3 for best-of-5 (men's Slams), 2 for best-of-3.
    """
    entry_names = [e["name"] for e in entries_data]
    entry_idx = {name: i for i, name in enumerate(entry_names)}
    entry_elos = np.array([e[elo_field] for e in entries_data], dtype=float)

    n_seats = len(positions)
    if n_seats & (n_seats - 1) != 0:
        raise ValueError(f"positions has {n_seats} entries; must be a power of 2")

    n_rounds = n_seats.bit_length() - 1
    # WC-style "entrants" naming (r128 round = 128 entrants), consistent
    # with from_wc2026_json's stage_ids so compat_wc-style reach_prob
    # threshold semantics read the same way across formats.
    named_tail = ["qf", "sf", "final"]
    n_named = min(len(named_tail), n_rounds)
    n_numeric = n_rounds - n_named
    round_ids = [f"r{n_seats // (2 ** i)}" for i in range(n_numeric)] + named_tail[len(named_tail) - n_named:]

    rounds = generate_single_elimination(n_seats, round_ids=round_ids)
    knockout = KnockoutPhase(
        # Tennis.simulate_h2h/outcome_probs don't consult `decider` at all —
        # every match resolves to a winner by construction (no draws exist
        # in tennis). "sets" documents why, rather than reusing football's
        # "draw"/"shootout" vocabulary where neither applies.
        rounds=rounds,
        rules=MatchRules(decider="sets", extra={"sets_to_win": sets_to_win}),
        winner_stage="champion",
    )

    def seeding_factory(groups_override):
        # No "groups" concept for a bracket-only format; groups_override is
        # accepted (for a uniform run.simulate(..., groups=) signature) and
        # ignored.
        return StaticPositionsSeeding(positions)

    return TournamentSpec(
        sport=Tennis(),
        entry_names=entry_names, entry_idx=entry_idx, entry_elos=entry_elos,
        stage_ids=round_ids + ["champion"],
        phases=[knockout],
        seeding_factory=seeding_factory,
        raw_data={"entries": entries_data, "positions": positions},
    )

