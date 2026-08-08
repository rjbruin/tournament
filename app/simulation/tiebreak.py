"""
Generic h2h-bucketed round-robin ranker — an m-entry generalization of
``app.simulation.engine._rank_group_with_h2h`` (engine.py:31-173), which
hardcodes a 4-team group (fixed-shape ``(n,4,4)`` h2h tensors, a base-10
4-digit points pattern assuming ≤9 points/entry, and an int64 key packing
whose overflow bounds are only proven correct for m=4 in a hand-written
comment).

Two changes from the original, both load-bearing for generality, neither
changing behaviour for m=4 (proven in tests/golden/test_tiebreak_generic.py
against the scalar oracle and against the original function directly):

  - Ranking uses ``keys.rank_rows`` (row-wise ``np.lexsort``) instead of a
    hand-packed int64 key + argsort, so there is no overflow proof to redo
    for larger m or a different points scale.
  - The tie-bucketing "points pattern" uses a base derived from the actual
    max points value (``pts.max() + 1``) instead of a fixed base-10 digit,
    so it stays correct however many points a round-robin format can award.

FIFA tiebreak semantics preserved deliberately (see the module docstring in
tests/golden/generators.py for the parity discussion):
  - Tie groups are runs of EQUAL POINTS in points-sorted-descending order —
    not equal on the full (pts, gd, gf) key.
  - Within a tie group, the h2h criteria (h2h pts, h2h gd, h2h gf, overall
    gd, overall gf) are applied as a SINGLE flat pass, not FIFA's literal
    recursive re-application to a remaining sub-tie. Kept for parity with
    the current engine.
  - The final fallback for anything still tied is declaration order (lower
    original index wins), not a random draw.
"""

from __future__ import annotations

import numpy as np

from app.simulation.keys import pack_key, rank_rows


def rank_group_h2h(
    n: int,
    pts: np.ndarray,
    gf: np.ndarray,
    ga: np.ndarray,
    scorelines: dict[tuple[int, int], tuple[np.ndarray, np.ndarray]],
    m: int,
) -> tuple[np.ndarray, np.ndarray]:
    """Rank m entries per simulation according to the FIFA-style tiebreaker
    cascade described above.

    Args:
        n: number of simulations.
        pts, gf, ga: ``(n, m)`` int arrays — overall round-robin stats.
        scorelines: ``{(i, j): (goals_i, goals_j)}`` for every played pair
            ``i < j``, each an ``(n,)`` array.
        m: number of entries in the group.

    Returns:
        order: ``(n, m)`` local entry indices (0..m-1), best to worst.
        key: ``(n, m)`` packed overall key (pts, gd, gf) of the entry at
            each final position — NOT h2h-adjusted (matches
            engine.py:166-171), intended for cross-group comparison (e.g.
            the best-thirds wildcard allocator).
    """
    gd = gf - ga

    order = rank_rows([(pts, True), (gd, True), (gf, True)])

    # Generous, explicitly bounds-checked headroom for the cross-group
    # comparison scalar — mirrors the fixed-decimal-slot spirit of
    # engine.py:60-64 but raises instead of silently corrupting if a sport
    # ever produces values outside these (very generous) ranges.
    overall_key = pack_key([
        (pts, 0, 999),
        (gd, 1000, 1999),
        (gf, 0, 999),
    ])

    h2h_p = np.zeros((n, m, m), dtype=np.int64)
    h2h_d = np.zeros((n, m, m), dtype=np.int64)
    h2h_f = np.zeros((n, m, m), dtype=np.int64)
    for (i, j), (gi_s, gj_s) in scorelines.items():
        gi_s = gi_s.astype(np.int64)
        gj_s = gj_s.astype(np.int64)
        wi = gi_s > gj_s
        wj = gj_s > gi_s
        dw = gi_s == gj_s
        h2h_p[:, i, j] = 3 * wi + dw
        h2h_p[:, j, i] = 3 * wj + dw
        h2h_f[:, i, j] = gi_s
        h2h_f[:, j, i] = gj_s
        h2h_d[:, i, j] = gi_s - gj_s
        h2h_d[:, j, i] = gj_s - gi_s

    pts_sorted = np.sort(pts, axis=1)[:, ::-1].astype(np.int64)   # (n, m) descending
    base = int(pts.max()) + 1 if pts.size else 1
    pattern_key = np.zeros(n, dtype=np.int64)
    for d in range(m):
        pattern_key = pattern_key * base + pts_sorted[:, d]

    for pk in np.unique(pattern_key):
        sim_idx = np.where(pattern_key == pk)[0]
        mm = sim_idx.size

        sample = pts_sorted[sim_idx[0]]
        tie_groups: list[list[int]] = []
        i = 0
        while i < m:
            j = i + 1
            while j < m and sample[j] == sample[i]:
                j += 1
            if j - i > 1:
                tie_groups.append(list(range(i, j)))
            i = j

        if not tie_groups:
            continue

        cur_order = order[sim_idx].copy()
        cur_gd = np.take_along_axis(gd[sim_idx], cur_order, axis=1)
        cur_gf = np.take_along_axis(gf[sim_idx], cur_order, axis=1)

        h2h_p_sub = h2h_p[sim_idx]
        h2h_d_sub = h2h_d[sim_idx]
        h2h_f_sub = h2h_f[sim_idx]
        arange_mm = np.arange(mm)

        for pos_group in tie_groups:
            ng = len(pos_group)
            tied_teams = cur_order[:, pos_group]

            sum_p = np.zeros((mm, ng), dtype=np.int64)
            sum_d = np.zeros((mm, ng), dtype=np.int64)
            sum_f = np.zeros((mm, ng), dtype=np.int64)
            for k in range(ng):
                t_k = tied_teams[:, k]
                for l in range(ng):
                    if k == l:
                        continue
                    t_l = tied_teams[:, l]
                    sum_p[:, k] += h2h_p_sub[arange_mm, t_k, t_l]
                    sum_d[:, k] += h2h_d_sub[arange_mm, t_k, t_l]
                    sum_f[:, k] += h2h_f_sub[arange_mm, t_k, t_l]

            grp_gd = cur_gd[:, pos_group]
            grp_gf = cur_gf[:, pos_group]

            within_order = rank_rows([
                (sum_p, True), (sum_d, True), (sum_f, True),
                (grp_gd, True), (grp_gf, True),
            ])
            cur_order[:, pos_group] = np.take_along_axis(tied_teams, within_order, axis=1)
            cur_gd[:, pos_group] = np.take_along_axis(grp_gd, within_order, axis=1)
            cur_gf[:, pos_group] = np.take_along_axis(grp_gf, within_order, axis=1)

        order[sim_idx] = cur_order

    out_key = np.take_along_axis(overall_key, order, axis=1)
    return order, out_key
