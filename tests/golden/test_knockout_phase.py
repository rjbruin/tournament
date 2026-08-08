"""
Golden test: app.simulation.phases.knockout.KnockoutPhase, chained with
seeding + round_robin, against the current engine's full run() pipeline,
using the REAL WC2026 bracket/Annex C data.
"""

import json
import os

import numpy as np

from app.simulation.allocators import LutBitmaskAllocator
from app.simulation.engine import GROUP_MATCH_PAIRS
from app.simulation.phases.base import SimContext
from app.simulation.phases.knockout import KnockoutPhase, KnockoutRound
from app.simulation.phases.round_robin import RoundRobinPhase
from app.simulation.phases.seeding import StaticGroupsSeeding
from app.simulation.rng import SimRng
from app.simulation.sports.base import MatchRules
from app.simulation.sports.football import Football
from tests.conftest import scheduled_group_matches

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))


def _annex_raw():
    with open(os.path.join(ROOT, "data", "annex_c.json")) as f:
        return json.load(f)


def _build_knockout_phase(engine):
    def defs_to_matches(defs):
        return [{"number": m["match"], "home": m["home"], "away": m["away"]} for m in defs]

    rounds = [
        KnockoutRound("r32", "r32", defs_to_matches(engine.r32_defs)),
        KnockoutRound("r16", "r16", defs_to_matches(engine.r16_defs)),
        KnockoutRound("qf", "qf", defs_to_matches(engine.qf_defs)),
        KnockoutRound("sf", "sf", defs_to_matches(engine.sf_defs)),
        KnockoutRound("final", "final", defs_to_matches([engine.final_def])),
    ]
    allocator = LutBitmaskAllocator.from_annex_c(_annex_raw(), n_groups=12)
    return KnockoutPhase(
        rounds=rounds,
        rules=MatchRules(decider="shootout"),
        winner_stage="champion",
        wildcard_allocator=allocator,
        wildcard_source=(engine.group_letters, 2),
    )


def _build_round_robin_phase(engine):
    return RoundRobinPhase(
        group_letters=engine.group_letters, group_size=4,
        match_order=GROUP_MATCH_PAIRS,
        rules=MatchRules(decider="draw", extra={"win_points": 3, "draw_points": 1, "loss_points": 0}),
        tiebreak_stat="goals", wildcard_position=2,
    )


def _run_pipeline(engine, n, actuals, seed=1):
    seeding = StaticGroupsSeeding({g["name"]: list(g["teams"]) for g in engine.groups})
    ctx = SimContext(
        n=n, rng=SimRng(seed=seed), sport=Football(),
        entry_names=engine.team_names, entry_idx=engine.team_idx,
        entry_elos=engine.team_elos, actuals=actuals,
    )
    ctx.outputs.update(seeding.simulate(ctx).outputs)

    rr = _build_round_robin_phase(engine)
    rr_result = rr.simulate(ctx)
    ctx.outputs.update(rr_result.outputs)

    ko = _build_knockout_phase(engine)
    ko_result = ko.simulate(ctx)
    ctx.outputs.update(ko_result.outputs)

    return rr_result, ko_result


def _random_full_group_actuals(rng, engine):
    group_results = {}
    for g in engine.groups:
        gname = g["name"]
        entries = []
        for pair in scheduled_group_matches(engine, gname):
            hg, ag = int(rng.integers(0, 3)), int(rng.integers(0, 3))
            entries.append({"home": pair["home"], "away": pair["away"],
                             "home_goals": hg, "away_goals": ag})
        group_results[gname] = entries
    return {"group_results": group_results, "knockout_results": {}, "live_matches": []}


def test_group_stage_fixed_r32_participants_match_old_engine(engine):
    """All 72 group results fixed (no knockout results yet): the R32
    participants resolved via the phase pipeline must exactly match the old
    engine's bracket_matches R32 slots."""
    rng = np.random.default_rng(60260101)
    for trial in range(10):
        actuals = _random_full_group_actuals(rng, engine)
        n = 20

        old_results = engine._run_legacy(n=n, actuals=actuals)
        rr_result, ko_result = _run_pipeline(engine, n, actuals)

        for m in engine.r32_defs:
            mno = m["match"]
            old_bm = old_results["bracket_matches"][mno]
            new_winner_dict = ko_result.extra["match_winner"]
            # We don't have direct per-match home/away arrays outside the
            # phase, but match_winner isn't populated until AFTER the match
            # is resolved. Instead, verify via the phase's MatchRecord list.
        # Cross-check via MatchRecord list, which does carry side_a/side_b.
        recorded = {mr.number: mr for mr in ko_result.matches if mr.phase == "ko"}
        for m in engine.r32_defs:
            mno = m["match"]
            old_bm = old_results["bracket_matches"][mno]
            new_mr = recorded[mno]
            assert new_mr.side_a["determined"] and new_mr.side_b["determined"], (
                f"trial {trial} match {mno} not determined with all group results fixed"
            )
            assert old_bm["home"]["determined"] and old_bm["away"]["determined"]
            assert new_mr.side_a["team"] == old_bm["home"]["team"], (
                f"trial {trial} match {mno} home: new={new_mr.side_a['team']} "
                f"old={old_bm['home']['team']}"
            )
            assert new_mr.side_b["team"] == old_bm["away"]["team"]


def test_fully_determined_bracket_matches_old_engine_exactly(engine):
    """All 72 group + all 31 knockout results fixed: the champion (and every
    intermediate winner) resolved via the phase pipeline must exactly match
    the old engine, deterministically (zero RNG on either side)."""
    rng = np.random.default_rng(60260102)

    for trial in range(10):
        group_actuals = _random_full_group_actuals(rng, engine)

        # Probe R32 participants (deterministic once groups are fixed).
        probe = engine._run_legacy(n=2, actuals=group_actuals)
        r32_participants = {}
        for m in engine.r32_defs:
            mno = m["match"]
            bm = probe["bracket_matches"][mno]
            assert bm["home"]["determined"] and bm["away"]["determined"]
            r32_participants[mno] = (bm["home"]["team"], bm["away"]["team"])

        winners = {}
        for mno, (h, a) in r32_participants.items():
            winners[mno] = h  # deterministic choice: home always "wins"
        for m in engine.r16_defs + engine.qf_defs + engine.sf_defs + [engine.final_def]:
            winners[m["match"]] = winners[m["home"]]

        actuals = {
            "group_results": group_actuals["group_results"],
            "knockout_results": {str(mno): name for mno, name in winners.items()},
            "live_matches": [],
        }
        n = 50
        old_results = engine._run_legacy(n=n, actuals=actuals)
        rr_result, ko_result = _run_pipeline(engine, n, actuals)

        champion = winners[engine.final_def["match"]]
        new_match_winner = ko_result.extra["match_winner"]
        new_champion_idx = new_match_winner[engine.final_def["match"]]
        assert np.all(new_champion_idx == engine.team_idx[champion]), (
            f"trial {trial}: expected champion {champion} in every simulation"
        )
        for team, p in old_results["winner_prob"].items():
            expected = 1.0 if team == champion else 0.0
            assert p == expected  # sanity on the old side itself

        # Every knockout match's winner must match exactly.
        for m in engine.all_knockout_defs:
            mno = m["match"]
            assert np.all(new_match_winner[mno] == engine.team_idx[winners[mno]]), (
                f"trial {trial} match {mno}: expected {winners[mno]}"
            )


def test_stage_marks_reproduce_reach_semantics(engine):
    """With a fully determined bracket, verify the stage_marks emitted by
    round_robin + knockout exactly reproduce, per team, the set of stages
    reached — cross-checked against the old engine's *_prob outputs (all
    exactly 0.0/1.0 in this deterministic setting)."""
    rng = np.random.default_rng(60260103)
    group_actuals = _random_full_group_actuals(rng, engine)

    probe = engine._run_legacy(n=2, actuals=group_actuals)
    r32_participants = {
        m["match"]: (probe["bracket_matches"][m["match"]]["home"]["team"],
                     probe["bracket_matches"][m["match"]]["away"]["team"])
        for m in engine.r32_defs
    }
    winners = {mno: h for mno, (h, a) in r32_participants.items()}
    for m in engine.r16_defs + engine.qf_defs + engine.sf_defs + [engine.final_def]:
        winners[m["match"]] = winners[m["home"]]

    actuals = {
        "group_results": group_actuals["group_results"],
        "knockout_results": {str(mno): name for mno, name in winners.items()},
        "live_matches": [],
    }
    n = 20
    old_results = engine._run_legacy(n=n, actuals=actuals)
    rr_result, ko_result = _run_pipeline(engine, n, actuals)

    # Build {team_name: set(stages reached)} from stage_marks (deterministic
    # => every simulation row agrees, so [0] is representative).
    reached_stages: dict[str, set] = {name: set() for name in engine.team_names}
    for entries, stage in rr_result.stage_marks + ko_result.stage_marks:
        for idx in np.unique(entries):
            reached_stages[engine.team_names[int(idx)]].add(stage)

    stage_to_legacy = {
        "r32": "group_advance_prob", "r16": "round_of_16_prob", "qf": "quarterfinal_prob",
        "sf": "semifinal_prob", "final": "finalist_prob", "champion": "winner_prob",
    }
    for stage, legacy_key in stage_to_legacy.items():
        for team, p in old_results[legacy_key].items():
            expected_reached = (p == 1.0)
            actual_reached = stage in reached_stages[team]
            assert actual_reached == expected_reached, (
                f"{team} stage={stage}: old prob={p} (reached={expected_reached}) "
                f"but stage_marks says reached={actual_reached}"
            )
