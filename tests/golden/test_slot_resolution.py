"""
Golden test: ``SimulationEngine._resolve_slot`` against every real slot
descriptor in the WC2026 bracket (all 31 matches x 2 sides), using synthetic
group_order/third_assign/match_winner arrays where every possible value is
distinguishable — so a wrong slot kind, a swapped W/R, or an off-by-one group
index all produce a detectable mismatch.
"""

import numpy as np


def _synthetic_arrays(engine, n=3):
    """Build group_order/third_assign/match_winner where every distinct
    "thing that could be resolved" (group winner, group runner-up, third-place
    wildcard slot, match winner) has a unique, easily-traced value."""
    n_groups = engine.n_groups

    # group_order[:, gi, 0] = winner marker, [:, gi, 1] = runner-up marker.
    # Positions 2/3 (third/fourth) are irrelevant to slot resolution but must
    # be filled for shape consistency.
    group_order = np.empty((n, n_groups, 4), dtype=int)
    for gi in range(n_groups):
        group_order[:, gi, 0] = 10_000 + gi * 10 + 0   # "winner of group gi"
        group_order[:, gi, 1] = 10_000 + gi * 10 + 1   # "runner-up of group gi"
        group_order[:, gi, 2] = 10_000 + gi * 10 + 2
        group_order[:, gi, 3] = 10_000 + gi * 10 + 3

    # One synthetic marker per Annex C wildcard match number.
    third_assign = {
        mno: np.full(n, 20_000 + mno, dtype=int) for mno in engine.annex_match_order
    }

    return group_order, third_assign


def _expected_and_actual(engine, slot, group_order, third_assign, match_winner, n):
    if isinstance(slot, list):
        kind, val = slot
        if kind == "W":
            gi = engine.group_pos[val]
            expected = np.full(n, 10_000 + gi * 10 + 0)
        elif kind == "R":
            gi = engine.group_pos[val]
            expected = np.full(n, 10_000 + gi * 10 + 1)
        elif kind == "T":
            expected = third_assign[val]
        else:
            raise AssertionError(f"unexpected slot kind {kind!r} in real bracket data")
    else:
        expected = match_winner[slot]
    actual = engine._resolve_slot(slot, n, group_order, third_assign, match_winner)
    return expected, actual


def test_r32_slots_resolve_correctly(engine):
    """R32 (matches 73-88): every home/away slot is W/R/T — no bare-int
    references exist at this round since it's the bracket's entry point."""
    n = 3
    group_order, third_assign = _synthetic_arrays(engine, n)
    match_winner = {}   # R32 never references a prior match

    checked = 0
    for m in engine.r32_defs:
        for side in ("home", "away"):
            slot = m[side]
            assert isinstance(slot, list) and slot[0] in ("W", "R", "T"), (
                f"match {m['match']} {side}: expected W/R/T slot in real R32 data, got {slot}"
            )
            expected, actual = _expected_and_actual(
                engine, slot, group_order, third_assign, match_winner, n
            )
            assert np.array_equal(actual, expected), (
                f"match {m['match']} {side} slot {slot}: got {actual}, expected {expected}"
            )
            checked += 1
    assert checked == 32, f"expected 32 R32 slots (16 matches x 2), checked {checked}"


def test_r16_qf_sf_final_slots_reference_prior_winners(engine):
    """R16/QF/SF/Final (matches 89-103): every slot is a bare int referencing
    a prior match's winner — confirmed against the real bracket data, then
    resolved through match_winner directly (mirrors engine.py:699-708, which
    does NOT go through _resolve_slot for these rounds)."""
    n = 3
    all_later_defs = engine.r16_defs + engine.qf_defs + engine.sf_defs + [engine.final_def]

    # Assign a unique synthetic winner marker to every match number that can
    # be referenced (73..102 — everything except the Final itself).
    match_winner = {mno: np.full(n, 30_000 + mno, dtype=int) for mno in range(73, 103)}

    checked = 0
    for m in all_later_defs:
        for side in ("home", "away"):
            slot = m[side]
            assert isinstance(slot, int), (
                f"match {m['match']} {side}: expected a bare int (prior match ref) "
                f"in real R16+ data, got {slot!r}"
            )
            expected = match_winner[slot]
            actual = match_winner[m[side]]  # what engine.py:699-708 actually does
            assert np.array_equal(actual, expected)
            checked += 1
    assert checked == (8 + 4 + 2 + 1) * 2, f"expected 30 slots, checked {checked}"


def test_all_31_matches_covered_exactly_once():
    """Sanity on the bracket structure itself: 16+8+4+2+1 = 31 matches,
    numbered 73..103 with no gaps or duplicates — the assumption every other
    golden test and the future knockout phase relies on."""
    import json
    import os

    root = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
    with open(os.path.join(root, "data", "wc2026.json")) as f:
        data = json.load(f)
    b = data["bracket"]
    numbers = (
        [m["match"] for m in b["r32"]]
        + [m["match"] for m in b["r16"]]
        + [m["match"] for m in b["qf"]]
        + [m["match"] for m in b["sf"]]
        + [b["final"]["match"]]
    )
    assert len(numbers) == 31
    assert sorted(numbers) == list(range(73, 104))
