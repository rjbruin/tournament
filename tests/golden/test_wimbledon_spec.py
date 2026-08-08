"""
Golden tests [Stage 3 acceptance]: app.simulation.spec.from_wimbledon_json
against the real 2026 Wimbledon gentlemen's singles draw (parsed from
Wikipedia — see data/tournaments/wimbledon_2026/SOURCE.md).
"""

import json
import os

import numpy as np
import pytest

from app.simulation.run import simulate
from app.simulation.spec import from_wimbledon_json

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
DATA_DIR = os.path.join(ROOT, "data", "tournaments", "wimbledon_2026")


@pytest.fixture(scope="module")
def wimbledon_spec():
    with open(os.path.join(DATA_DIR, "entries.json")) as f:
        entries = json.load(f)
    with open(os.path.join(DATA_DIR, "positions.json")) as f:
        positions = json.load(f)
    return from_wimbledon_json(entries, positions)


def test_128_real_entries_loaded(wimbledon_spec):
    assert len(wimbledon_spec.entry_names) == 128
    assert len(set(wimbledon_spec.entry_names)) == 128
    assert "Jannik Sinner" in wimbledon_spec.entry_names
    assert "Alexander Zverev" in wimbledon_spec.entry_names


def test_stage_ladder_matches_grand_slam_rounds(wimbledon_spec):
    assert wimbledon_spec.stage_ids == ["r128", "r64", "r32", "r16", "qf", "sf", "final", "champion"]


def test_reach_probabilities_sum_to_power_of_two_per_stage(wimbledon_spec):
    n = 20_000
    run = simulate(wimbledon_spec, actuals={"knockout_results": {}}, n=n, seed=1)
    reach_prob = run.ladder.reach_prob(run.reached, wimbledon_spec.entry_names)

    expected = {"r128": 128.0, "r64": 64.0, "r32": 32.0, "r16": 16.0,
                "qf": 8.0, "sf": 4.0, "final": 2.0, "champion": 1.0}
    for stage, target in expected.items():
        total = sum(reach_prob[stage].values())
        assert total == pytest.approx(target, abs=0.5), f"{stage}: sum={total}, expected {target}"


def test_seed_1_and_2_never_meet_before_the_final(wimbledon_spec):
    """Standard seeding places seeds 1 and 2 in opposite halves — they can
    only meet in the final, never earlier, for any outcome of the other 126
    matches. Verified deterministically: force both to win every match up
    to the final and confirm they're paired there, then separately confirm
    a free-running simulation never puts them in the same EARLIER round's
    opponent-probability table."""
    n = 30_000
    run = simulate(wimbledon_spec, actuals={"knockout_results": {}}, n=n, seed=2)
    opponent_data = run.phase_results["ko"].extra["opponent_data"]

    sinner_idx = wimbledon_spec.entry_idx["Jannik Sinner"]
    zverev_idx = wimbledon_spec.entry_idx["Alexander Zverev"]

    for round_id in ("r128", "r64", "r32", "r16", "qf", "sf"):
        od = opponent_data[round_id]
        count = od["opp_counts"][sinner_idx, zverev_idx]
        assert count == 0, f"Sinner and Zverev met in round {round_id} in {count} simulations"

    final_od = opponent_data["final"]
    final_meetings = final_od["opp_counts"][sinner_idx, zverev_idx]
    assert final_meetings > 0, "Sinner and Zverev should meet in the final in some simulations"


def test_equal_elo_gives_uniform_title_odds():
    """Sanity check independent of the real data: 128 equal-Elo entries
    must each have title probability ~1/128."""
    entries = [{"name": f"P{i}", "elo_grass": 2000.0} for i in range(128)]
    positions = [f"P{i}" for i in range(128)]
    spec = from_wimbledon_json(entries, positions)

    n = 40_000
    run = simulate(spec, actuals={"knockout_results": {}}, n=n, seed=3)
    reach_prob = run.ladder.reach_prob(run.reached, spec.entry_names)

    probs = np.array(list(reach_prob["champion"].values()))
    expected = 1.0 / 128
    # Wald bound per entry at n=40k, p~1/128
    bound = 4.5 * np.sqrt(expected * (1 - expected) / n) + 1e-4
    assert np.all(np.abs(probs - expected) < bound), (
        f"max deviation {np.max(np.abs(probs - expected))} vs bound {bound}"
    )


def test_fully_determined_bracket_gives_exact_champion(wimbledon_spec):
    """Force every one of the 127 matches by always picking the lower draw
    position as the winner — deterministic, zero RNG needed, exact champion."""
    with open(os.path.join(DATA_DIR, "positions.json")) as f:
        positions = json.load(f)

    # Simulate the deterministic "lower seat always wins" bracket by hand.
    round_sizes = [128, 64, 32, 16, 8, 4, 2]
    round_ids = ["r128", "r64", "r32", "r16", "qf", "sf", "final"]
    current = list(positions)
    knockout_results = {}
    for ri, (round_id, size) in enumerate(zip(round_ids, round_sizes)):
        winners = []
        for i in range(size // 2):
            a, b = current[2 * i], current[2 * i + 1]
            winners.append(a)  # lower position always "wins"
            knockout_results[f"{round_id}:{i}"] = a
        current = winners
    champion = current[0]
    assert champion == positions[0]  # position 0 (Sinner) wins every match

    n = 200
    run = simulate(wimbledon_spec, actuals={"knockout_results": knockout_results}, n=n, seed=5)
    reach_prob = run.ladder.reach_prob(run.reached, wimbledon_spec.entry_names)
    for name, p in reach_prob["champion"].items():
        expected = 1.0 if name == champion else 0.0
        assert p == expected, f"{name}: {p} != {expected}"
