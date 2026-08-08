"""
Golden test: app.simulation.keys.rank_rows / pack_key against the current
engine's hand-packed int64 ordering (engine.py:60-65, 143-157).
"""

import numpy as np

from app.simulation.keys import pack_key, rank_rows


def test_rank_rows_matches_single_criterion_argsort():
    rng = np.random.default_rng(1)
    n, m = 5000, 4
    overall_key = rng.integers(-1000, 1000, size=(n, m))
    ref = np.argsort(-overall_key, axis=1, kind="stable")
    mine = rank_rows([(overall_key, True)])
    assert np.array_equal(ref, mine)


def test_rank_rows_multi_criterion_priority():
    # Row: pts ties on [7,7,3], gd breaks the tie for the top two.
    pts = np.array([[7, 7, 3]])
    gd = np.array([[1, 5, 9]])   # entry 1 has better GD than entry 0 despite lower index
    order = rank_rows([(pts, True), (gd, True)])
    assert order.tolist() == [[1, 0, 2]]


def test_rank_rows_ascending_criterion():
    # Lower is better (e.g. a "penalty count" criterion).
    val = np.array([[3, 1, 2]])
    order = rank_rows([(val, False)])
    assert order.tolist() == [[1, 2, 0]]


def test_rank_rows_stable_tiebreak_is_declaration_order():
    val = np.array([[5, 5, 5, 5]])
    order = rank_rows([(val, True)])
    assert order.tolist() == [[0, 1, 2, 3]]


def test_pack_key_ordering_matches_lexicographic_criteria():
    """pack_key's job is a single scalar usable for cross-group argsort — its
    digit weights need not match engine.py's fixed decimal slots (which use
    generous fixed headroom, not tight field-range multipliers), but sorting
    by the packed value MUST agree with lexicographic (pts, then gd, then
    gf) comparison, which we cross-check against rank_rows on the same
    criteria."""
    rng = np.random.default_rng(2)
    n = 2000
    pts = rng.integers(0, 10, size=n).reshape(n, 1)
    gd = rng.integers(-20, 20, size=n).reshape(n, 1)
    gf = rng.integers(0, 20, size=n).reshape(n, 1)

    packed = pack_key([(pts.ravel(), 0, 9), (gd.ravel(), 20, 40), (gf.ravel(), 0, 19)])
    order_by_pack = np.argsort(-packed, kind="stable")

    # Reference lexicographic order via plain Python sort (most significant
    # first — matches pack_key's field ordering).
    rows = list(zip(pts.ravel().tolist(), gd.ravel().tolist(), gf.ravel().tolist(), range(n)))
    rows.sort(key=lambda r: (-r[0], -r[1], -r[2], r[3]))
    order_ref = [r[3] for r in rows]

    assert order_by_pack.tolist() == order_ref


def test_pack_key_rejects_undersized_bound():
    import pytest
    vals = np.array([50, 200])  # exceeds declared max
    with pytest.raises(AssertionError):
        pack_key([(vals, 0, 99)])
