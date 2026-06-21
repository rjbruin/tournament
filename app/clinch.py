"""
Exact (sampling-free) qualification clinch / elimination for a single group,
plus cross-group reasoning for best-third-place advancement.

The Monte-Carlo engine tells us how *likely* a team is to advance; it cannot
tell us whether advancement is *mathematically guaranteed*, because a scenario
that never appears in N samples still reads as 100%. This module answers the
theoretical question by enumerating every possible combination of remaining
group results and every relevant scoreline, and applying the official
FIFA World Cup 2026 group tiebreakers:

    1. Points
    2. Head-to-head among the teams still level on points:
         a. head-to-head points
         b. head-to-head goal difference
         c. head-to-head goals scored
    3. Overall goal difference
    4. Overall goals scored
    5. (untracked: fair play, then FIFA ranking, then drawing of lots)

Criteria 5 is not modelled, so when two teams are exactly level on every
*tracked* criterion their order is treated as indeterminate — i.e. an adversary
could place either above the other. This keeps the result *sound*: we never
claim a clinch that an untracked tiebreaker could undo.

Why enumeration is exact: the FIFA tiebreakers cascade — a tie on one criterion
hands the decision to the next — so it is not enough to try only the extreme
scorelines; an exact intermediate margin can be what creates (or breaks) a tie
deeper in the chain. We therefore enumerate every scoreline with each side
scoring from 0 up to a per-group ``cap`` that exceeds any played goal total,
plus a dominating ``BIG`` sentinel standing in for "by any larger margin". That
range covers every reachable ordering. The enumeration is restricted to the
final-matchday window (at most two group matches left), which is both where
clinches actually occur and what keeps the cost negligible.

Top-two clinches are handled per-group using full scoreline enumeration.

Best-third-place advancement is a cross-group problem: 8 of the 12 thirds
advance. It is handled by a separate points-only outcome enumeration (W/D/L,
not scorelines), because:

  * GD/GF are unbounded for unfinished groups — any score margin is possible —
    so scoreline enumeration would produce vacuous bounds.
  * Points are bounded (0–9) and fully determinable from outcome signs alone.
  * Equal points between two thirds is treated conservatively as indeterminate
    (an untracked tiebreaker could go either way), consistent with the rest of
    this module.

When both the target group and a comparison group are fully complete (all six
matches played, none in progress), the exact (pts, gd, gf) stats are used for
the cross-group comparison instead of points alone.
"""

from __future__ import annotations

from itertools import groupby, product

# Status values (also used as CSS-friendly identifiers downstream).
OPEN = "open"
CLINCHED_FIRST = "clinched_first"
CLINCHED_TOP2 = "clinched_top2"
CLINCHED_THIRD_ADV = "clinched_third_adv"  # guaranteed to advance as best-third
ELIMINATED = "eliminated"

# The six matches of a 4-team group, as (i, j) local-index pairs with i < j.
ALL_PAIRS = [(0, 1), (0, 2), (0, 3), (1, 2), (1, 3), (2, 3)]

# Far larger than any plausible group goal total, so a "blowout" scoreline
# dominates every played-match contribution to GD / GF.
BIG = 10_000

# W/D/L outcome points for team i and team j: (pts_i, pts_j).
_OUTCOMES = [(3, 0), (1, 1), (0, 3)]


def _scorelines(cap: int, sign: int | None = None) -> list[tuple[int, int]]:
    """All scorelines worth trying for one match: each side scores 0..cap, plus
    a dominating ``BIG`` sentinel that stands in for "by any larger margin".

    Enumerating intermediate margins (not just the extremes) is essential: the
    FIFA tiebreakers cascade, so an exact mid-range scoreline can create a tie
    on one criterion that hands the decision to the next one. ``cap`` is chosen
    per group to exceed every played goal total, so the reachable orderings are
    fully covered. ``sign`` optionally restricts to a fixed result
    (+1 i wins / 0 draw / -1 j wins)."""
    vals = list(range(cap + 1)) + [BIG]
    out = []
    for a in vals:
        for b in vals:
            s = (a > b) - (a < b)
            if sign is None or s == sign:
                out.append((a, b))
    return out


def _rank_tiers(scores: dict[tuple[int, int], tuple[int, int]]) -> list[set]:
    """Rank the four teams given all six scorelines, returning a list of tiers
    (best to worst). Each tier is a set of teams that are exactly level on every
    tracked criterion — their relative order is indeterminate (untracked
    tiebreakers). Mirrors ``engine._rank_group_with_h2h``."""
    pts = [0, 0, 0, 0]
    gf = [0, 0, 0, 0]
    ga = [0, 0, 0, 0]
    for (i, j), (gi, gj) in scores.items():
        gf[i] += gi
        ga[i] += gj
        gf[j] += gj
        ga[j] += gi
        if gi > gj:
            pts[i] += 3
        elif gj > gi:
            pts[j] += 3
        else:
            pts[i] += 1
            pts[j] += 1
    gd = [gf[t] - ga[t] for t in range(4)]

    def h2h_key(team: int, cluster: list[int]) -> tuple:
        """Full tiebreak key for ``team`` within a points-level ``cluster``:
        (h2h pts, h2h gd, h2h gf, overall gd, overall gf), higher = better."""
        hp = hgd = hgf = 0
        for other in cluster:
            if other == team:
                continue
            pair = (team, other) if (team, other) in scores else (other, team)
            gi, gj = scores[pair]
            tf, ta = (gi, gj) if pair[0] == team else (gj, gi)
            hgf += tf
            hgd += tf - ta
            if tf > ta:
                hp += 3
            elif tf == ta:
                hp += 1
        return (hp, hgd, hgf, gd[team], gf[team])

    by_pts = sorted(range(4), key=lambda t: pts[t], reverse=True)
    tiers: list[set] = []
    for _, cluster_iter in groupby(by_pts, key=lambda t: pts[t]):
        cluster = list(cluster_iter)
        if len(cluster) == 1:
            tiers.append({cluster[0]})
            continue
        ranked = sorted(cluster, key=lambda t: h2h_key(t, cluster), reverse=True)
        for _, sub_iter in groupby(ranked, key=lambda t: h2h_key(t, cluster)):
            tiers.append(set(sub_iter))
    return tiers


def group_clinch(played: dict[tuple[int, int], tuple[int, int]],
                 forced: dict[tuple[int, int], int] | None = None) -> dict[int, str]:
    """Theoretical status for each of the four teams (by local index 0-3).

    ``played`` maps a subset of :data:`ALL_PAIRS` to ``(goals_i, goals_j)``.
    ``forced`` optionally pins the *result* (sign: +1/0/-1) of some still-to-play
    pairs while leaving their scoreline free — used to ask "if this match ends as
    a win/draw/loss, is the team then guaranteed top two?".

    Returns ``{team_index: status}``. Only evaluated with at most two group
    matches left (the window where a clinch can occur); earlier states return
    :data:`OPEN`."""
    forced = forced or {}
    remaining = [p for p in ALL_PAIRS if p not in played]
    # Clinches and eliminations only become decidable late (a 4-team group can
    # at most be settled with two matches left). Restricting the exact scoreline
    # enumeration to that window keeps it fast enough to run for every group on
    # every page. Returning OPEN earlier is sound — it never asserts a clinch —
    # at worst slightly conservative for a rare very-early clinch (shown as
    # ">99.9%" instead of ✓).
    if len(remaining) > 2:
        return {t: OPEN for t in range(4)}

    # Cap goals at a value that dominates every played total, so the enumerated
    # scorelines cover all reachable orderings (intermediate margins included).
    cap = 6
    for gi, gj in played.values():
        cap = max(cap, gi + gj)
    cap += 2

    sl_space = [_scorelines(cap, forced.get(p)) for p in remaining]
    worst = [1, 1, 1, 1]   # max finishing position reachable (1 = best)
    best = [4, 4, 4, 4]    # min finishing position reachable
    for assignment in product(*sl_space):
        scores = dict(played)
        for pair, sl in zip(remaining, assignment):
            scores[pair] = sl
        before = 0
        for tier in _rank_tiers(scores):
            size = len(tier)
            for t in tier:
                if before + size > worst[t]:
                    worst[t] = before + size
                if before + 1 < best[t]:
                    best[t] = before + 1
            before += size

    status = {}
    for t in range(4):
        if worst[t] == 1:
            status[t] = CLINCHED_FIRST
        elif worst[t] <= 2:
            status[t] = CLINCHED_TOP2
        elif best[t] == 4:
            status[t] = ELIMINATED
        else:
            status[t] = OPEN
    return status


# ---------------------------------------------------------------------------
# Results-level helper with per-group caching
# ---------------------------------------------------------------------------

# {group_name: (signature, {team_name: status})}. The signature is the group's
# played scorelines only, so a result in one group never invalidates another.
_CACHE: dict[str, tuple] = {}


def _group_signature(fixtures: list) -> tuple:
    sig = []
    for m in fixtures:
        if m.get("played"):
            sig.append((m["home"], m["away"], m["home_goals"], m["away_goals"]))
    return tuple(sorted(sig))


def clinch_for_group(group: dict, fixtures: list) -> dict[str, str]:
    """Theoretical status for every team in ``group`` (by name), cached on the
    group's played results. ``fixtures`` is the group's list of normalized-ish
    match dicts with ``home``/``away``/``played``/``home_goals``/``away_goals``."""
    name = group["name"]
    sig = _group_signature(fixtures)
    cached = _CACHE.get(name)
    if cached is not None and cached[0] == sig:
        return cached[1]

    teams = group["teams"]
    _pos, played = _played_from_fixtures(group, fixtures)
    by_index = group_clinch(played)
    result = {teams[i]: by_index[i] for i in range(4)}
    _CACHE[name] = (sig, result)
    return result


def _played_from_fixtures(group: dict, fixtures: list):
    """Return (pos, played) where pos maps team name -> local index and played
    maps oriented pairs -> scorelines, for the played matches in ``fixtures``."""
    teams = group["teams"]
    pos = {t: i for i, t in enumerate(teams)}
    played: dict[tuple[int, int], tuple[int, int]] = {}
    for m in fixtures:
        if not m.get("played"):
            continue
        hi, ai = pos[m["home"]], pos[m["away"]]
        if hi < ai:
            played[(hi, ai)] = (m["home_goals"], m["away_goals"])
        else:
            played[(ai, hi)] = (m["away_goals"], m["home_goals"])
    return pos, played


def clinch_after_match(group: dict, fixtures: list, team: str, opponent: str,
                       outcome: str) -> dict[str, str]:
    """Theoretical status of every team in ``group`` assuming the (still-to-play)
    ``team`` vs ``opponent`` match ends as ``outcome`` ('win'/'draw'/'loss' from
    ``team``'s perspective), with that match's scoreline and all other remaining
    matches left free. Used for per-outcome "what's at stake" reasoning."""
    pos, played = _played_from_fixtures(group, fixtures)
    ti, oi = pos[team], pos[opponent]
    sign = {"win": 1, "draw": 0, "loss": -1}[outcome]
    # Orient the forced result to the canonical (low, high) pair ordering.
    if ti < oi:
        pair, fsign = (ti, oi), sign
    else:
        pair, fsign = (oi, ti), -sign
    by_index = group_clinch(played, forced={pair: fsign})
    return {group["teams"][i]: by_index[i] for i in range(4)}


# ---------------------------------------------------------------------------
# Third-place best-thirds reasoning (cross-group, points-only for live groups,
# full pts/gd/gf when both groups are complete).
# ---------------------------------------------------------------------------

def _compute_pts_stats(played: dict) -> tuple[list, list, list]:
    """Compute (pts, gf, ga) for each of the four teams from a played dict."""
    pts = [0, 0, 0, 0]
    gf  = [0, 0, 0, 0]
    ga  = [0, 0, 0, 0]
    for (i, j), (gi, gj) in played.items():
        gf[i] += gi;  ga[i] += gj
        gf[j] += gj;  ga[j] += gi
        if gi > gj:    pts[i] += 3
        elif gj > gi:  pts[j] += 3
        else:          pts[i] += 1; pts[j] += 1
    return pts, gf, ga


def _played_excl_live(group: dict, fixtures: list) -> dict:
    """Like ``_played_from_fixtures`` but skips in-progress matches."""
    teams = group["teams"]
    pos = {t: i for i, t in enumerate(teams)}
    played: dict[tuple[int, int], tuple[int, int]] = {}
    for m in fixtures:
        if not m.get("played") or m.get("in_progress"):
            continue
        hi, ai = pos[m["home"]], pos[m["away"]]
        if hi < ai:
            played[(hi, ai)] = (m["home_goals"], m["away_goals"])
        else:
            played[(ai, hi)] = (m["away_goals"], m["home_goals"])
    return played


def group_third_place_range(group: dict, fixtures: list) -> dict:
    """Min/max points the third-place finisher in ``group`` can have.

    For complete groups (all 6 non-live matches played), also returns the
    exact ``third_key`` = (pts, gd, gf) of the best possible third-place team,
    used for GD/GF refinement in cross-group comparisons.

    Keys always present: ``min_pts``, ``max_pts``, ``complete``.
    Extra when ``complete`` is True: ``third_key`` (tuple).
    """
    _, played = _played_from_fixtures(group, fixtures)
    played_final = _played_excl_live(group, fixtures)
    complete = len(played_final) == 6

    if complete:
        pts, gf_list, ga_list = _compute_pts_stats(played_final)
        gd = [gf_list[t] - ga_list[t] for t in range(4)]
        order = sorted(range(4), key=lambda t: (pts[t], gd[t], gf_list[t]), reverse=True)
        t3 = order[2]
        actual_pts = pts[t3]
        # Use the better-ranked of the two tied teams (if any) as the
        # adversarial worst-case for other groups' comparisons.
        third_key = (pts[t3], gd[t3], gf_list[t3])
        return {"min_pts": actual_pts, "max_pts": actual_pts,
                "complete": True, "third_key": third_key}

    # Enumerate W/D/L outcomes (including in-progress as still undecided).
    remaining = [p for p in ALL_PAIRS if p not in played]
    base_pts, _, _ = _compute_pts_stats(played)
    min_pts, max_pts = 9, 0
    for assignment in product(*[_OUTCOMES for _ in remaining]):
        pts = list(base_pts)
        for (i, j), (pi, pj) in zip(remaining, assignment):
            pts[i] += pi; pts[j] += pj
        third = sorted(pts, reverse=True)[2]
        if third < min_pts: min_pts = third
        if third > max_pts: max_pts = third
    return {"min_pts": min_pts, "max_pts": max_pts, "complete": False}


def _team_pts_range_as_third(group: dict, fixtures: list, team_name: str,
                              ) -> tuple[int | None, int | None]:
    """Points range for ``team_name`` when it finishes exactly third in ``group``.

    Enumerates all W/D/L outcomes and applies adversarial tiebreaking: a team
    can finish third in an outcome when its best possible rank ≤ 3 AND its
    worst possible rank ≥ 3 (i.e. an adversary could arrange the ties either
    way). Equal points count against the team (conservative).

    Returns ``(None, None)`` if the team can never finish third (e.g. it is
    guaranteed top-two, or guaranteed last).
    """
    teams = group["teams"]
    pos = {t: i for i, t in enumerate(teams)}
    ti = pos[team_name]
    _, played = _played_from_fixtures(group, fixtures)
    remaining = [p for p in ALL_PAIRS if p not in played]
    base_pts, _, _ = _compute_pts_stats(played)

    min_pts: int | None = None
    max_pts: int | None = None

    for assignment in product(*[_OUTCOMES for _ in remaining]):
        pts = list(base_pts)
        for (i, j), (pi, pj) in zip(remaining, assignment):
            pts[i] += pi; pts[j] += pj
        T = pts[ti]
        strictly_above = sum(1 for t in range(4) if t != ti and pts[t] > T)
        tied = sum(1 for t in range(4) if t != ti and pts[t] == T)
        best_rank  = strictly_above + 1
        worst_rank = strictly_above + tied + 1
        # Adversarially, the team is in 3rd when best_rank ≤ 3 ≤ worst_rank.
        if best_rank <= 3 and worst_rank >= 3:
            if min_pts is None or T < min_pts: min_pts = T
            if max_pts is None or T > max_pts: max_pts = T

    return min_pts, max_pts


_THIRD_ADV_CACHE: dict = {}  # {combined_sig: frozenset[str]}


def clinch_third_advancement(groups: list, fixtures_by_group: dict) -> frozenset:
    """Teams theoretically guaranteed to advance as one of the 8 best thirds.

    A team T in group G is included when, in every possible joint scenario:
      * T finishes third in G with its minimum possible points (worst case).
      * Every other group produces its maximum possible third-place points.
      * At most 7 other thirds can beat T's worst-case points (so T ≤ 8th).

    Ties are resolved adversarially against T: a comparison third that can
    EQUAL T (on points while either group is live, or on the full (pts, gd, gf)
    key when both are complete) is counted as able to beat T, because the
    remaining tiebreakers (GD/GF while live; fair-play / drawing of lots when
    complete) could fall either way. Hence non-strict ``>=`` throughout — using
    strict ``>`` would under-count threats and over-claim clinches.

    When both G and a comparison group Y are fully complete (no remaining or
    in-progress matches), the full lexicographic (pts, gd, gf) key is used
    instead of points alone — GD/GF are meaningless while either group still
    has undecided matches.
    """
    group_ranges = {
        g["name"]: group_third_place_range(g, fixtures_by_group.get(g["name"], []))
        for g in groups
    }

    clinched: set[str] = set()
    for g in groups:
        gname = g["name"]
        fixtures = fixtures_by_group.get(gname, [])
        g_range = group_ranges[gname]

        # Pre-compute T's actual (pts, gd, gf) for complete-group comparisons.
        T_full_key: dict[str, tuple] = {}
        if g_range["complete"]:
            played_final = _played_excl_live(g, fixtures)
            pts_g, gf_g, ga_g = _compute_pts_stats(played_final)
            for t_name in g["teams"]:
                ti = {t: i for i, t in enumerate(g["teams"])}[t_name]
                T_full_key[t_name] = (pts_g[ti], gf_g[ti] - ga_g[ti], gf_g[ti])

        for team_name in g["teams"]:
            t3_min, _t3_max = _team_pts_range_as_third(g, fixtures, team_name)
            if t3_min is None:
                continue  # Team cannot finish third

            can_beat = 0
            for og in groups:
                if og["name"] == gname:
                    continue
                y_range = group_ranges[og["name"]]

                if g_range["complete"] and y_range["complete"]:
                    # Both groups finished: full lexicographic comparison.
                    # A tie on (pts, gd, gf) is resolved by fair-play points /
                    # drawing of lots — indeterminate — so a non-strict ``>=``
                    # adversarially counts an equal third as able to beat T.
                    T_key = T_full_key[team_name]
                    if y_range["third_key"] >= T_key:
                        can_beat += 1
                else:
                    # At least one group still live: points-only. GD/GF are not
                    # final, so a points tie can be broken either way — count an
                    # equal-points third as a possible threat (non-strict ``>=``).
                    # Using strict ``>`` here would UNDER-count threats and let a
                    # team clinch when an equal-points group could still pip it.
                    if y_range["max_pts"] >= t3_min:
                        can_beat += 1

            # 12 groups, 8 advance → need ≤ 7 groups able to beat T.
            if can_beat <= 7:
                clinched.add(team_name)

    return frozenset(clinched)


def clinch_by_team(results: dict, groups: list) -> dict[str, str]:
    """Flat ``{team_name: status}`` across all groups for the given results.
    Teams in groups without fixtures (e.g. pre-draw) are simply omitted.

    Two passes are performed:
      1. Per-group top-two clinch (scoreline enumeration, existing logic).
      2. Cross-group best-third advancement (outcome enumeration over all groups).

    The second pass is cached on a combined signature of all groups' played
    results, so repeated calls within the same tournament state are free.
    """
    out: dict[str, str] = {}
    if not results:
        return out
    fixtures_by_group = results.get("fixtures", {})
    for g in groups:
        fixtures = fixtures_by_group.get(g["name"])
        if not fixtures:
            continue
        out.update(clinch_for_group(g, fixtures))

    # Cross-group third-place pass — cached on tournament state signature.
    combined_sig = tuple(
        (g["name"], _group_signature(fixtures_by_group.get(g["name"], [])))
        for g in groups
    )
    if combined_sig not in _THIRD_ADV_CACHE:
        _THIRD_ADV_CACHE[combined_sig] = clinch_third_advancement(groups, fixtures_by_group)
        # Keep only the current entry; old states are irrelevant.
        for k in [k for k in _THIRD_ADV_CACHE if k != combined_sig]:
            _THIRD_ADV_CACHE.pop(k)

    third_adv = _THIRD_ADV_CACHE[combined_sig]
    for team in third_adv:
        if out.get(team) not in (CLINCHED_FIRST, CLINCHED_TOP2):
            out[team] = CLINCHED_THIRD_ADV

    return out


def advances_for_sure(status: str | None) -> bool:
    """Whether a status means the team is theoretically through to the knockouts."""
    return status in (CLINCHED_FIRST, CLINCHED_TOP2, CLINCHED_THIRD_ADV)
