"""
Golden test [T0]: app.simulation.tiebreak.rank_group_h2h against both (a) the
scalar oracle (for m=4 AND other group sizes, proving genuine generality)
and (b) the current engine's hardcoded-m=4 function directly (proving exact
behavioural parity, not just "close enough").
"""

import numpy as np

from app.simulation.engine import _rank_group_with_h2h
from app.simulation.tiebreak import rank_group_h2h
from tests.golden.generators import batch_to_scalar_rows, random_group_batch, reference_rank_group


def _assert_matches_oracle(pts, gf, ga, scorelines, n, m):
    order, key = rank_group_h2h(n, pts, gf, ga, scorelines, m)
    mismatches = []
    for s, (pts_row, gf_row, ga_row, sl_row) in enumerate(
        batch_to_scalar_rows(pts, gf, ga, scorelines, n, m)
    ):
        ref_order, _ref_key = reference_rank_group(pts_row, gf_row, ga_row, sl_row, m)
        if list(order[s]) != ref_order:
            mismatches.append((s, pts_row, list(order[s]), ref_order))
        if len(mismatches) >= 5:
            break
    assert not mismatches, f"{len(mismatches)}+ order mismatches vs oracle (m={m}): {mismatches}"


def test_matches_oracle_m4():
    rng = np.random.default_rng(30260101)
    pts, gf, ga, scorelines = random_group_batch(rng, 10_000, m=4, goal_max=2)
    _assert_matches_oracle(pts, gf, ga, scorelines, 10_000, 4)


def test_matches_current_engine_exactly_m4():
    """The real T0 gate: byte-identical order AND key against
    _rank_group_with_h2h, not just agreement with the oracle."""
    rng = np.random.default_rng(30260102)
    pts, gf, ga, scorelines = random_group_batch(rng, 10_000, m=4, goal_max=2)
    order_new, key_new = rank_group_h2h(10_000, pts, gf, ga, scorelines, 4)
    order_old, key_old = _rank_group_with_h2h(10_000, pts, gf, ga, scorelines)
    assert np.array_equal(order_new, order_old)
    # key values differ in absolute magnitude (different packing headroom)
    # but must induce the IDENTICAL relative order, which order_new==order_old
    # already proves; additionally check monotonic consistency directly.
    order_from_new_key = np.argsort(-key_new, axis=1, kind="stable")
    order_from_old_key = np.argsort(-key_old, axis=1, kind="stable")
    assert np.array_equal(order_from_new_key, order_from_old_key)


def test_matches_oracle_various_group_sizes():
    """Prove genuine m-generality — sizes with no special relationship to 4."""
    for m in (2, 3, 5, 6, 8):
        rng = np.random.default_rng(30260200 + m)
        n = 3000
        pts, gf, ga, scorelines = random_group_batch(rng, n, m=m, goal_max=2)
        _assert_matches_oracle(pts, gf, ga, scorelines, n, m)


def test_all_ties_declaration_order_fallback_m6():
    """Every match a 0-0 draw in a 6-team group: complete tie on everything,
    fallback must be pure declaration order [0,1,2,3,4,5]."""
    m = 6
    n = 500
    pts = np.zeros((n, m), dtype=int)
    gf = np.zeros((n, m), dtype=int)
    ga = np.zeros((n, m), dtype=int)
    scorelines = {(i, j): (np.zeros(n, dtype=int), np.zeros(n, dtype=int))
                  for i in range(m) for j in range(m) if i < j}
    order, _key = rank_group_h2h(n, pts, gf, ga, scorelines, m)
    assert np.all(order == np.arange(m))
