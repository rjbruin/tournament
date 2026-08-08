"""
Golden test [T1]: app.simulation.allocators.LutBitmaskAllocator against the
current engine's dense Annex C table and _resolve_third_place_assignments.
"""

import json
import os

import numpy as np

from app.simulation.allocators import LutBitmaskAllocator, top_k_by_key

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))


def _annex_raw():
    with open(os.path.join(ROOT, "data", "annex_c.json")) as f:
        return json.load(f)


def test_dense_table_matches_engine_lut(engine):
    allocator = LutBitmaskAllocator.from_annex_c(_annex_raw(), n_groups=12)
    assert np.array_equal(allocator._dense, engine._annex_lut)


def test_assign_matches_engine_third_place_assignment(engine):
    """Build synthetic (group_order, group_key), run both the old
    ``_resolve_third_place_assignments`` and the new allocator's ``assign``,
    and confirm identical team-index results end-to-end."""
    rng = np.random.default_rng(40260101)
    n = 5000
    n_groups = 12

    # Third-place team index per group (arbitrary — group_order[:,:,2] is
    # just "the team currently in position 2" and never re-derived here).
    third_team = rng.integers(0, 48, size=(n, n_groups))
    # A random but valid-looking overall key per group's 3rd place.
    pts = rng.integers(0, 10, size=(n, n_groups))
    gd = rng.integers(-10, 10, size=(n, n_groups))
    gf = rng.integers(0, 15, size=(n, n_groups))
    third_key = pts.astype(np.int64) * 100_000_000 + (gd + 100).astype(np.int64) * 100_000 + gf

    # --- old path ---
    group_order = np.zeros((n, n_groups, 4), dtype=int)
    group_order[:, :, 2] = third_team
    group_key = np.zeros((n, n_groups, 4), dtype=np.int64)
    group_key[:, :, 2] = third_key
    old_result = engine._resolve_third_place_assignments(n, group_order, group_key)

    # --- new path ---
    allocator = LutBitmaskAllocator.from_annex_c(_annex_raw(), n_groups=12)
    group_assignment = allocator.assign(third_key)
    new_result = {
        slot_id: np.take_along_axis(third_team, group_idx.reshape(-1, 1), axis=1)[:, 0]
        for slot_id, group_idx in group_assignment.items()
    }

    assert set(old_result.keys()) == set(new_result.keys())
    for slot_id in old_result:
        assert np.array_equal(old_result[slot_id], new_result[slot_id]), (
            f"slot {slot_id}: mismatch between old and new allocator team assignment"
        )


def test_possible_sources_nonempty_and_bounded():
    allocator = LutBitmaskAllocator.from_annex_c(_annex_raw(), n_groups=12)
    for slot_id in allocator.match_order:
        sources = allocator.possible_sources(slot_id)
        assert sources, f"slot {slot_id} has no possible sources"
        assert sources <= set(range(12))


def test_top_k_by_key_basic():
    key = np.array([[5, 9, 1, 7]])
    top2 = top_k_by_key(key, 2)
    assert top2.tolist() == [[1, 3]]  # group 1 (val 9), group 3 (val 7)


def test_top_k_by_key_stable_ties():
    key = np.array([[5, 5, 5, 5]])
    top2 = top_k_by_key(key, 2)
    assert top2.tolist() == [[0, 1]]
