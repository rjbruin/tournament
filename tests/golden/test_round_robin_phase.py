"""
Golden test: app.simulation.phases.round_robin.RoundRobinPhase against the
current engine's internal group-stage simulation
(SimulationEngine._resolve_fixed_group_results + _simulate_group_stage),
using the REAL WC2026 team/group/Elo data so global entry indices line up
directly between old and new.
"""

import numpy as np

from app.simulation.engine import GROUP_MATCH_PAIRS
from app.simulation.phases.base import SimContext
from app.simulation.phases.round_robin import RoundRobinPhase
from app.simulation.phases.seeding import StaticGroupsSeeding
from app.simulation.rng import SimRng
from app.simulation.sports.base import MatchRules
from app.simulation.sports.football import Football
from tests.conftest import scheduled_group_matches


def _make_ctx(engine, n, actuals, seed=1):
    seeding = StaticGroupsSeeding({g["name"]: list(g["teams"]) for g in engine.groups})
    ctx = SimContext(
        n=n, rng=SimRng(seed=seed), sport=Football(),
        entry_names=engine.team_names, entry_idx=engine.team_idx,
        entry_elos=engine.team_elos, actuals=actuals,
    )
    ctx.outputs.update(seeding.simulate(ctx).outputs)
    return ctx


def _make_phase(engine):
    return RoundRobinPhase(
        group_letters=engine.group_letters, group_size=4,
        match_order=GROUP_MATCH_PAIRS,
        rules=MatchRules(decider="draw", extra={"win_points": 3, "draw_points": 1, "loss_points": 0}),
        tiebreak_stat="goals", wildcard_position=2,
    )


def _random_full_actuals(rng, engine):
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


def test_fully_determined_matches_old_engine_exactly(engine):
    """All 72 group matches fixed => zero RNG on either side => exact
    per-position entry-index equality, group by group."""
    rng = np.random.default_rng(50260101)
    phase = _make_phase(engine)

    for trial in range(15):
        actuals = _random_full_actuals(rng, engine)
        n = 50

        fixed_pairs = engine._resolve_fixed_group_results(actuals["group_results"])
        old_order, old_key = engine._simulate_group_stage(n, fixed_pairs)

        ctx = _make_ctx(engine, n, actuals)
        result = phase.simulate(ctx)

        for gi, letter in enumerate(engine.group_letters):
            for pos in range(4):
                new_entries = result.outputs[("group_pos", letter, pos)].entries
                old_entries = old_order[:, gi, pos]
                assert np.array_equal(new_entries, old_entries), (
                    f"trial {trial} group {letter} pos {pos}: "
                    f"new={new_entries[:5]} old={old_entries[:5]}"
                )
                if pos == 2:  # wildcard_position
                    new_key = result.outputs[("group_pos", letter, pos)].rank_key
                    # Packed differently (different headroom) but must induce
                    # the identical cross-group ORDER — checked separately in
                    # test_wildcard_rank_key_orders_identically_to_old below.
                    assert new_key is not None


def test_wildcard_rank_key_orders_identically_to_old(engine):
    """The new rank_key uses different packing headroom than the old
    group_key, so values differ — but sorting all 12 groups' 3rd-place
    rank_key must give the IDENTICAL group ordering as the old group_key,
    since that ordering is what Annex C allocation depends on."""
    rng = np.random.default_rng(50260102)
    phase = _make_phase(engine)
    n = 200

    actuals = _random_full_actuals(rng, engine)
    fixed_pairs = engine._resolve_fixed_group_results(actuals["group_results"])
    _old_order, old_key = engine._simulate_group_stage(n, fixed_pairs)
    old_third_key = old_key[:, :, 2]  # (n, 12)
    old_group_order = np.argsort(-old_third_key, axis=1, kind="stable")

    ctx = _make_ctx(engine, n, actuals)
    result = phase.simulate(ctx)
    new_third_key = np.stack(
        [result.outputs[("group_pos", letter, 2)].rank_key for letter in engine.group_letters],
        axis=1,
    )
    new_group_order = np.argsort(-new_third_key, axis=1, kind="stable")

    assert np.array_equal(old_group_order, new_group_order)


def test_free_running_group_stage_statistical_parity(engine):
    """No actuals fixed: compare aggregate group_advance-equivalent stats
    (top-2 finish rate) between old and new over a large n — statistical,
    not exact, since both sides burn RNG."""
    n = 200_000
    empty_actuals = {"group_results": {}, "knockout_results": {}, "live_matches": []}

    np.random.seed(999)
    old_order, _old_key = engine._simulate_group_stage(n, {})

    ctx = _make_ctx(engine, n, empty_actuals, seed=999)
    phase = _make_phase(engine)
    result = phase.simulate(ctx)

    for gi, letter in enumerate(engine.group_letters):
        # Compare, per team in this group, P(finish in top 2) old vs new.
        for team in engine.groups[gi]["teams"]:
            tidx = engine.team_idx[team]
            old_advance = float(np.mean(np.any(old_order[:, gi, :2] == tidx, axis=1)))
            new_top2_entries = np.stack([
                result.outputs[("group_pos", letter, 0)].entries,
                result.outputs[("group_pos", letter, 1)].entries,
            ], axis=1)
            new_advance = float(np.mean(np.any(new_top2_entries == tidx, axis=1)))
            assert abs(old_advance - new_advance) < 0.02, (
                f"{letter}/{team}: old_advance={old_advance} new_advance={new_advance}"
            )
