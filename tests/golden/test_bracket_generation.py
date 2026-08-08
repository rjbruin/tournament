"""
Tests for app.simulation.phases.knockout.generate_single_elimination — the
structural generator a Grand-Slam-style draw uses instead of WC's
hand-written 31 match defs.
"""

import numpy as np
import pytest

from app.simulation.phases.base import SimContext
from app.simulation.phases.knockout import KnockoutPhase, generate_single_elimination
from app.simulation.phases.seeding import StaticPositionsSeeding
from app.simulation.rng import SimRng
from app.simulation.sports.base import MatchRules
from app.simulation.sports.football import Football


def test_rejects_non_power_of_2():
    with pytest.raises(ValueError):
        generate_single_elimination(12)
    with pytest.raises(ValueError):
        generate_single_elimination(1)


def test_8_seat_bracket_structure():
    rounds = generate_single_elimination(8)
    assert [r.round_id for r in rounds] == ["r4", "r2", "final"]
    assert len(rounds[0].matches) == 4
    assert len(rounds[1].matches) == 2
    assert len(rounds[2].matches) == 1

    # Round 1: seats paired (0,1), (2,3), (4,5), (6,7).
    for i, m in enumerate(rounds[0].matches):
        assert m["home"] == ["E", 2 * i]
        assert m["away"] == ["E", 2 * i + 1]
        assert m["number"] is None
        assert m["index"] == i

    # Round 2 references round 1's winners in pairs.
    assert rounds[1].matches[0]["home"] == ("r4", 0)
    assert rounds[1].matches[0]["away"] == ("r4", 1)
    assert rounds[1].matches[1]["home"] == ("r4", 2)
    assert rounds[1].matches[1]["away"] == ("r4", 3)

    # Final references round 2's two winners.
    assert rounds[2].matches[0]["home"] == ("r2", 0)
    assert rounds[2].matches[0]["away"] == ("r2", 1)


def test_custom_round_ids():
    rounds = generate_single_elimination(4, round_ids=["semis", "final"])
    assert [r.round_id for r in rounds] == ["semis", "final"]


def test_128_seat_matches_wimbledon_round_count():
    rounds = generate_single_elimination(128)
    assert len(rounds) == 7  # 128->64->32->16->8->4->2->1
    total_matches = sum(len(r.matches) for r in rounds)
    assert total_matches == 127


def _run_8_player_bracket(n, seed=1, actuals=None):
    names = [f"P{i}" for i in range(8)]
    idx = {name: i for i, name in enumerate(names)}
    elos = np.array([2000, 1900, 1850, 1950, 1700, 2100, 1600, 2050], dtype=float)

    seeding = StaticPositionsSeeding(names)  # seat i = names[i]
    rounds = generate_single_elimination(8)
    phase = KnockoutPhase(rounds=rounds, rules=MatchRules(decider="shootout"), winner_stage="champion")

    ctx = SimContext(n=n, rng=SimRng(seed=seed), sport=Football(),
                      entry_names=names, entry_idx=idx, entry_elos=elos,
                      actuals=actuals or {"knockout_results": {}})
    ctx.outputs.update(seeding.simulate(ctx).outputs)
    result = phase.simulate(ctx)
    return ctx, result


def test_generated_bracket_conserves_stage_counts():
    n = 20_000
    ctx, result = _run_8_player_bracket(n)

    from app.simulation.stages import StageLadder
    ladder = StageLadder(["r4", "r2", "final", "champion"])
    reached = ladder.build_reached(n, len(ctx.entry_names), result.stage_marks)
    reach_prob = ladder.reach_prob(reached, ctx.entry_names)

    assert sum(reach_prob["r4"].values()) == pytest.approx(8.0, abs=0.01)
    assert sum(reach_prob["r2"].values()) == pytest.approx(4.0, abs=0.01)
    assert sum(reach_prob["final"].values()) == pytest.approx(2.0, abs=0.01)
    assert sum(reach_prob["champion"].values()) == pytest.approx(1.0, abs=0.01)


def test_fully_determined_generated_bracket_is_exact():
    """All 7 matches fixed -> deterministic champion, zero RNG needed."""
    actuals = {"knockout_results": {
        "r4:0": "P0", "r4:1": "P3", "r4:2": "P5", "r4:3": "P7",
        "r2:0": "P0", "r2:1": "P5",
        "final:0": "P5",
    }}
    n = 500
    ctx, result = _run_8_player_bracket(n, actuals=actuals)
    champion_idx = result.extra["match_winner"][("final", 0)]
    assert np.all(champion_idx == ctx.entry_idx["P5"])


def test_seed_1_and_2_meet_only_in_final_deterministic_path():
    """With seeds 1 and 8 (opposite halves) both winning every match up to
    the final, they must meet exactly at the final and nowhere earlier."""
    actuals = {"knockout_results": {
        "r4:0": "P0", "r4:1": "P3", "r4:2": "P5", "r4:3": "P7",
        "r2:0": "P0", "r2:1": "P7",
    }}
    n = 500
    ctx, result = _run_8_player_bracket(n, actuals=actuals)
    final_match = [mr for mr in result.matches if mr.round_id == "final"][0]
    assert {final_match.side_a["team"], final_match.side_b["team"]} == {"P0", "P7"}
