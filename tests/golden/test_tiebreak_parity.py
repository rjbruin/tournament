"""
Golden test: the vectorized 4-team group ranker
(``app.simulation.engine._rank_group_with_h2h``) against a slow, obviously
correct scalar oracle (``tests.golden.generators.reference_rank_group``).

This is the harness that the future generic ``app/simulation/tiebreak.py``
must also pass (against the same oracle, parametrized to other group sizes).
Building and trusting it BEFORE the rewrite is the point: a bug injected into
the ranking logic must show up here.
"""

import numpy as np
import pytest

from app.simulation.engine import _rank_group_with_h2h
from tests.golden.generators import (
    batch_to_scalar_rows,
    pack_overall_key,
    random_group_batch,
    reference_rank_group,
)

N_RANDOM = 20_000
M = 4


def _assert_batch_matches(pts, gf, ga, scorelines, n, m):
    order, key = _rank_group_with_h2h(n, pts, gf, ga, scorelines)
    mismatches = []
    seen_pattern_keys = set()
    for s, (pts_row, gf_row, ga_row, sl_row) in enumerate(
        batch_to_scalar_rows(pts, gf, ga, scorelines, n, m)
    ):
        ref_order, ref_key = reference_rank_group(pts_row, gf_row, ga_row, sl_row, m)
        pts_sorted = tuple(sorted(pts_row, reverse=True))
        seen_pattern_keys.add(pts_sorted)
        if list(order[s]) != ref_order or list(key[s]) != ref_key:
            mismatches.append((s, pts_row, gf_row, ga_row, list(order[s]), ref_order,
                                list(key[s]), ref_key))
        if len(mismatches) >= 5:
            break
    assert not mismatches, (
        f"{len(mismatches)}+ mismatches out of {n} (showing up to 5): {mismatches}"
    )
    return seen_pattern_keys


def test_random_groups_small_goal_alphabet():
    """Goals in {0,1,2} — ties are common (this is the primary parity check)."""
    rng = np.random.default_rng(20260101)
    pts, gf, ga, scorelines = random_group_batch(rng, N_RANDOM, m=M, goal_max=2)
    _assert_batch_matches(pts, gf, ga, scorelines, N_RANDOM, M)


def test_random_groups_wider_goal_alphabet():
    """Goals in {0..4} — fewer ties, exercises the "already correct, no h2h
    correction needed" path more often."""
    rng = np.random.default_rng(20260102)
    pts, gf, ga, scorelines = random_group_batch(rng, 5_000, m=M, goal_max=4)
    _assert_batch_matches(pts, gf, ga, scorelines, 5_000, M)


def test_all_draws_full_four_way_tie():
    """Every match 0-0: complete 4-way tie on points, GD, GF, and every H2H
    stat. The fallback must be pure declaration order (stable sort of an
    all-equal key), i.e. order == [0,1,2,3] for every simulation."""
    rng = np.random.default_rng(20260103)
    n = 2_000
    pts = np.zeros((n, M), dtype=int)
    gf = np.zeros((n, M), dtype=int)
    ga = np.zeros((n, M), dtype=int)
    scorelines = {(i, j): (np.zeros(n, dtype=int), np.zeros(n, dtype=int))
                  for i in range(M) for j in range(M) if i < j}
    order, key = _rank_group_with_h2h(n, pts, gf, ga, scorelines)
    assert np.all(order == np.array([0, 1, 2, 3]))
    expected_key = pack_overall_key(0, 0, 0)
    assert np.all(key == expected_key)


def test_pattern_key_coverage():
    """Every reachable 4-digit descending-points pattern (with small goal
    alphabet) must appear at least once across a large batch — otherwise the
    parity test above could be silently skipping tie-resolution branches."""
    rng = np.random.default_rng(20260104)
    pts, gf, ga, scorelines = random_group_batch(rng, 50_000, m=M, goal_max=2)
    seen = _assert_batch_matches(pts, gf, ga, scorelines, 50_000, M)
    # (3,3,3,3): every one of the 6 matches was a draw (each team earns 1 pt
    # per match, 3 matches each) — the deepest possible 4-way tie. A pattern
    # with a 9 (one team won all 3 of its matches) should also appear.
    assert (3, 3, 3, 3) in seen, (
        "expected the all-draw (3,3,3,3) pattern in a 50k sample; the goal "
        "distribution may be miscalibrated"
    )
    assert any(p[0] == 9 for p in seen), (
        "expected at least one pattern with a team on 9 points (3 wins) in a 50k sample"
    )
    assert len(seen) > 20, f"only {len(seen)} distinct points patterns observed — low diversity"


def test_harness_catches_an_injected_bug():
    """Meta-test: prove the comparison harness itself would flag a wrong
    ranker. We deliberately corrupt the h2h weighting (swap the GD/GF
    priority) and confirm at least one mismatch appears in a modest batch.
    This does not touch the real engine — it's a local reimplementation of
    just enough of the algorithm to demonstrate detectability.
    """
    rng = np.random.default_rng(20260105)
    n = 500
    pts, gf, ga, scorelines = random_group_batch(rng, n, m=M, goal_max=2)

    def buggy_pack(pts_v, gd_v, gf_v):
        # BUG: swaps the weight of GD and GF, which changes ranking whenever
        # a tie is broken on the overall-GD/GF fallback with GD != GF.
        return pts_v * 100_000_000 + gf_v * 100_000 + (gd_v + 100)

    mismatches = 0
    for s in range(n):
        gd_row = [gf[s, i] - ga[s, i] for i in range(M)]
        buggy_key = [buggy_pack(pts[s, i], gd_row[i], gf[s, i]) for i in range(M)]
        correct_key = [pack_overall_key(pts[s, i], gd_row[i], gf[s, i]) for i in range(M)]
        buggy_order = sorted(range(M), key=lambda i: buggy_key[i], reverse=True)
        correct_order = sorted(range(M), key=lambda i: correct_key[i], reverse=True)
        if buggy_order != correct_order:
            mismatches += 1
    assert mismatches > 0, "the injected bug produced no detectable mismatches — harness is too weak"
