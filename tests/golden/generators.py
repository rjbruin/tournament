"""
Golden-test generators and a slow, obviously-correct scalar *oracle* for the
FIFA group tiebreaker rules.

The oracle (`reference_rank_group`) is a faithful, per-simulation, pure-Python
translation of the vectorized algorithm in
``app.simulation.engine._rank_group_with_h2h`` — generalized to ``m`` teams so
it can also validate the future generic ``tiebreak.py`` ranker, not just
today's hardcoded ``m=4`` engine.

Because it works one simulation at a time with plain lists and tuples (no
NumPy fancy-indexing, no bulk bucketing), it is trivial to read and verify by
eye against the FIFA tiebreaker text, which is the whole point of an oracle:
it must be *obviously* correct, not merely a second copy of the same
vectorized trick.
"""

from __future__ import annotations

import itertools

import numpy as np

GD_OFFSET = 100


def pack_overall_key(pts: int, gd: int, gf: int) -> int:
    """Same packing as engine.py:60-64 — pts is most significant, then GD
    (shifted positive), then goals-for."""
    return pts * 100_000_000 + (gd + GD_OFFSET) * 100_000 + gf


def match_pairs(m: int) -> list[tuple[int, int]]:
    """All single round-robin pairs (i, j) with i < j, for m entries."""
    return list(itertools.combinations(range(m), 2))


def reference_rank_group(pts, gf, ga, scorelines, m: int):
    """Scalar oracle for one simulation.

    Args:
        pts, gf, ga: length-m sequences of ints — overall group stats.
        scorelines: {(i, j): (goals_i, goals_j)} for every played pair, i < j.
        m: number of teams in the group.

    Returns:
        (order, key) — order: list[int] of length m, team indices best to
        worst. key: list[int] of length m, the packed overall key of the team
        at that position (NOT an h2h-adjusted key — matches engine.py:166-171
        which stores the original overall_key, only the *position* changes).
    """
    gd = [gf[i] - ga[i] for i in range(m)]
    overall_key = [pack_overall_key(pts[i], gd[i], gf[i]) for i in range(m)]

    # Stable descending sort: ties keep original (declaration) order — matches
    # np.argsort(-overall_key, kind="stable").
    order = sorted(range(m), key=lambda i: overall_key[i], reverse=True)

    h2h_p = [[0] * m for _ in range(m)]
    h2h_d = [[0] * m for _ in range(m)]
    h2h_f = [[0] * m for _ in range(m)]
    for (i, j), (gi, gj) in scorelines.items():
        wi, wj, dw = int(gi > gj), int(gj > gi), int(gi == gj)
        h2h_p[i][j] = 3 * wi + dw
        h2h_p[j][i] = 3 * wj + dw
        h2h_f[i][j] = gi
        h2h_f[j][i] = gj
        h2h_d[i][j] = gi - gj
        h2h_d[j][i] = gj - gi

    # Tie groups: consecutive runs of EQUAL POINTS in points-sorted-desc order
    # (not the full overall_key) — matches engine.py:85-91, 97-107.
    pts_sorted = sorted(pts, reverse=True)
    tie_groups = []
    i = 0
    while i < m:
        j = i + 1
        while j < m and pts_sorted[j] == pts_sorted[i]:
            j += 1
        if j - i > 1:
            tie_groups.append(list(range(i, j)))
        i = j

    for pos_group in tie_groups:
        tied_teams = [order[p] for p in pos_group]
        ng = len(tied_teams)
        sum_p = [0] * ng
        sum_d = [0] * ng
        sum_f = [0] * ng
        for k in range(ng):
            tk = tied_teams[k]
            for l in range(ng):
                if k == l:
                    continue
                tl = tied_teams[l]
                sum_p[k] += h2h_p[tk][tl]
                sum_d[k] += h2h_d[tk][tl]
                sum_f[k] += h2h_f[tk][tl]
        grp_gd = [gd[t] for t in tied_teams]
        grp_gf = [gf[t] for t in tied_teams]
        h2h_key = [
            sum_p[k] * 1_000_000_000_000
            + (sum_d[k] + 100) * 1_000_000_000
            + sum_f[k] * 1_000_000
            + (grp_gd[k] + 100) * 1_000
            + grp_gf[k]
            for k in range(ng)
        ]
        within_order = sorted(range(ng), key=lambda k: h2h_key[k], reverse=True)
        new_tied = [tied_teams[k] for k in within_order]
        for idx, p in enumerate(pos_group):
            order[p] = new_tied[idx]

    key = [overall_key[t] for t in order]
    return order, key


def random_group_batch(rng: np.random.Generator, n: int, m: int = 4, goal_max: int = 2):
    """Generate ``n`` synthetic m-team round-robin groups with small goal
    values (0..goal_max) so points/GD ties are common — the interesting case
    for tiebreak testing.

    Returns (pts, gf, ga, scorelines) in the exact shapes
    ``_rank_group_with_h2h`` expects: pts/gf/ga are (n, m) int arrays;
    scorelines is {(i, j): (goals_i (n,), goals_j (n,))} for i < j.
    """
    pairs = match_pairs(m)
    scorelines = {}
    pts = np.zeros((n, m), dtype=int)
    gf = np.zeros((n, m), dtype=int)
    ga = np.zeros((n, m), dtype=int)

    for (i, j) in pairs:
        gi = rng.integers(0, goal_max + 1, size=n)
        gj = rng.integers(0, goal_max + 1, size=n)
        scorelines[(i, j)] = (gi, gj)
        win_i = gi > gj
        win_j = gj > gi
        draw = gi == gj
        pts[:, i] += 3 * win_i + draw
        pts[:, j] += 3 * win_j + draw
        gf[:, i] += gi
        gf[:, j] += gj
        ga[:, i] += gj
        ga[:, j] += gi

    return pts, gf, ga, scorelines


def batch_to_scalar_rows(pts, gf, ga, scorelines, n: int, m: int):
    """Yield (pts_row, gf_row, ga_row, scorelines_row) for each of the n
    simulations in a batch produced by ``random_group_batch``."""
    for s in range(n):
        pts_row = pts[s].tolist()
        gf_row = gf[s].tolist()
        ga_row = ga[s].tolist()
        scorelines_row = {
            (i, j): (int(gi[s]), int(gj[s])) for (i, j), (gi, gj) in scorelines.items()
        }
        yield pts_row, gf_row, ga_row, scorelines_row


def all_thirds_masks():
    """All 4096 possible 12-bit bitmasks, split into the 495 valid (popcount
    == 8) and the remaining invalid ones."""
    valid = []
    invalid = []
    for mask in range(4096):
        if bin(mask).count("1") == 8:
            valid.append(mask)
        else:
            invalid.append(mask)
    return valid, invalid
