"""
Natural-language "what's at stake" explanations for group qualification.

Given a group, a team, and a target outcome (advance to the knockouts / finish
first / finish second), this builds a decision tree over the *remaining* group
matches and renders it into plain English, e.g.

    Netherlands advance if: they beat Tunisia; or they draw with Tunisia and
    Sweden fail to beat Japan.

How it works (see also app/simulation/engine.py:simulate_group_outcomes):

  1. Run a Monte-Carlo conditioned on the state *before* the match in question.
     For every simulation we know the scoreline of each remaining group match
     and whether the team achieved the outcome.
  2. Build a tree that branches, in schedule order, on each remaining match's
     result (win/draw/loss). Each leaf holds the sims consistent with that path
     and the fraction in which the outcome was achieved.
  3. Prune branches whose every leaf shares the same certain outcome (this drops
     matches that turn out not to matter).
  4. For leaves that are still a mix of yes/no, refine by goal difference (a win
     "by 2+ goals" vs. just a win). Each match may be refined on result once and
     on goal difference once; once both are exhausted a leaf may stay mixed, in
     which case its probability is reported (this happens for the best-third
     race, which genuinely depends on other groups).

The engine's group ranking key is points, then goal difference, then goals-for
(no head-to-head), so goal-difference refinement matches reality except for the
rare cases decided purely by goals-for, which correctly remain "mixed".
"""

from __future__ import annotations

import numpy as np

# How many sims to base an explanation on. The work is one group-stage pass, so
# this is cheap; enough resolution to make near-certain leaves read as certain.
DEFAULT_N = 40_000

# A per-outcome rate must be exactly 0 or 1 (within floating-point noise) to
# be treated as a true clinch/elimination. Using a nonzero tolerance caused
# near-certain outcomes (e.g. 99.7%) to generate misleading "A draw is enough"
# headlines even though a small fraction of simulations end differently.
TOL = 0.0

# Caps on how many routes to spell out, to keep the explanation readable.
MAX_CERTAIN_LINES = 6
MAX_MIXED_LINES = 3

_OUTCOME_KEY = {"advances": "advanced", "first": "first", "second": "second"}
_OUTCOME_VERB = {
    "advances": "advance to the knockouts",
    "first": "win the group",
    "second": "finish runner-up",
}


# ---------------------------------------------------------------------------
# Tree construction
# ---------------------------------------------------------------------------

def _build_tree(matches: list[dict], achieved: np.ndarray, target: str):
    """Return the root node of the decision tree.

    A node is a dict with ``count``, ``rate`` and either ``label`` in
    {YES, NO, MIXED} (a leaf) or ``split`` describing its children.
    """
    n = len(achieved)
    target_idx = next(
        (k for k, m in enumerate(matches) if target in (m["home"], m["away"])),
        None,
    )

    def choose_axis(used: set):
        # All result axes first, in schedule order ...
        for k in range(len(matches)):
            if (k, "result") not in used:
                return (k, "result")
        # ... then refine goal difference, but only for the team's *own* match.
        # Refining the margin of matches the team isn't playing in is rarely
        # what a fan wants and explodes combinatorially.
        if target_idx is not None and (target_idx, "gd") not in used:
            return (target_idx, "gd")
        return None

    def build(mask: np.ndarray, used: set) -> dict:
        count = int(mask.sum())
        if count == 0:
            return {"label": "NO", "count": 0, "rate": 0.0, "split": None}
        rate = float(achieved[mask].mean())
        if rate <= TOL:
            return {"label": "NO", "count": count, "rate": rate, "split": None}
        if rate >= 1 - TOL:
            return {"label": "YES", "count": count, "rate": rate, "split": None}

        axis = choose_axis(used)
        if axis is None:
            return {"label": "MIXED", "count": count, "rate": rate, "split": None}

        k, kind = axis
        branches = []
        if kind == "result":
            res = matches[k]["result"]
            for val in (1, 0, -1):
                sub = mask & (res == val)
                if sub.any():
                    branches.append({"value": int(val), "node": build(sub, used | {axis})})
        else:
            gd = matches[k]["gd"]
            for val in np.unique(gd[mask]):
                sub = mask & (gd == val)
                if sub.any():
                    branches.append({"value": int(val), "node": build(sub, used | {axis})})

        return {"label": None, "count": count, "rate": rate,
                "split": {"match": k, "kind": kind, "branches": branches}}

    return build(np.ones(n, dtype=bool), set()), target_idx


def _signature(node: dict):
    """A canonical shape of a subtree, used to detect irrelevant branch points.
    Mixed leaves include their (rounded) rate so genuinely different
    probabilities aren't merged."""
    split = node.get("split")
    if not split:
        if node["label"] == "MIXED":
            return ("L", "MIXED", round(node["rate"], 2))
        return ("L", node["label"])
    return ("S", split["match"], split["kind"],
            tuple(sorted((b["value"], _signature(b["node"])) for b in split["branches"])))


def _prune(node: dict) -> dict:
    """Simplify the tree (your step 5a): collapse a branch point when it makes
    no difference to the outcome — either because every child is a leaf with the
    same certain label, or because the children are all structurally equivalent
    (so the match being branched on is irrelevant)."""
    split = node.get("split")
    if not split:
        return node
    for b in split["branches"]:
        b["node"] = _prune(b["node"])

    labels = {b["node"]["label"] for b in split["branches"]}
    if labels == {"YES"}:
        return {"label": "YES", "count": node["count"], "rate": node["rate"], "split": None}
    if labels == {"NO"}:
        return {"label": "NO", "count": node["count"], "rate": node["rate"], "split": None}

    # Irrelevant branch point: all continuations are the same. Keep one, but
    # preserve this node's overall count/rate.
    sigs = {_signature(b["node"]) for b in split["branches"]}
    if len(sigs) == 1:
        kept = split["branches"][0]["node"]
        kept = dict(kept)
        kept["count"] = node["count"]
        kept["rate"] = node["rate"]
        return kept

    return node


# ---------------------------------------------------------------------------
# Path collection
# ---------------------------------------------------------------------------

def _collect(node: dict, prefix: list, out: list) -> None:
    """Walk the tree, emitting one entry per YES/MIXED outcome. Sibling leaves
    of a single split that share a label are merged into one clause."""
    split = node.get("split")
    if not split:
        if node["label"] in ("YES", "MIXED"):
            out.append({"clauses": prefix[:], "label": node["label"], "rate": node["rate"]})
        return

    leaves_only = all(not b["node"].get("split") for b in split["branches"])
    if leaves_only:
        bs = sorted(split["branches"], key=lambda b: b["value"])
        groups: list[dict] = []
        for b in bs:
            lab = b["node"]["label"]
            if groups and groups[-1]["label"] == lab and lab != "MIXED":
                groups[-1]["values"].append(b["value"])
                groups[-1]["nodes"].append(b["node"])
            else:
                groups.append({"label": lab, "values": [b["value"]], "nodes": [b["node"]]})
        for grp in groups:
            if grp["label"] == "NO":
                continue
            tot = sum(nd["count"] for nd in grp["nodes"]) or 1
            rate = sum(nd["rate"] * nd["count"] for nd in grp["nodes"]) / tot
            clause = {"match": split["match"], "kind": split["kind"], "values": grp["values"]}
            out.append({"clauses": prefix + [clause], "label": grp["label"], "rate": rate})
        return

    for b in split["branches"]:
        clause = {"match": split["match"], "kind": split["kind"], "values": [b["value"]]}
        _collect(b["node"], prefix + [clause], out)


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------

def _result_phrase(values: list[int], home: str, away: str, target: str) -> str:
    vset = set(values)
    if target in (home, away):
        opp = away if target == home else home
        win = (1 if target == home else -1) in vset
        lose = (-1 if target == home else 1) in vset
        draw = 0 in vset
        if win and draw and not lose:
            return f"{target} avoid defeat against {opp}"
        if draw and lose and not win:
            return f"{target} fail to beat {opp}"
        if win and not draw and not lose:
            return f"{target} beat {opp}"
        if draw and not win and not lose:
            return f"{target} draw with {opp}"
        if lose and not win and not draw:
            return f"{target} lose to {opp}"
        return f"{target} avoid a draw with {opp}"  # win or lose (rare)

    # A match the target team isn't playing in.
    home_win = 1 in vset
    away_win = -1 in vset
    draw = 0 in vset
    if home_win and not away_win and not draw:
        return f"{home} beat {away}"
    if away_win and not home_win and not draw:
        return f"{away} beat {home}"
    if draw and not home_win and not away_win:
        return f"{home} and {away} draw"
    if home_win and draw and not away_win:
        return f"{home} avoid defeat against {away}"
    if away_win and draw and not home_win:
        return f"{away} avoid defeat against {home}"
    return f"{home} vs {away} is not drawn"


def _match_phrase(m: dict, target: str, rvalues, gvalues) -> str:
    """Phrase a single match's requirement, combining its result branch
    (``rvalues``) and optional goal-difference refinement (``gvalues``)."""
    home, away = m["home"], m["away"]
    if not gvalues:
        return _result_phrase(rvalues, home, away, target)

    # Goal-difference refinement. Only applied to the target's own match, where
    # the result branch is a win; qualification is monotone in margin, so a set
    # of values means "by at least the smallest", a single value "by exactly".
    opp = away if target == home else home
    margins = [v if target == home else -v for v in gvalues]
    if any(mg <= 0 for mg in margins):
        # Not a clean win margin (e.g. the result wasn't a win) — fall back.
        return _result_phrase(rvalues or [1 if target == home else -1], home, away, target)
    thr = min(margins)
    if thr <= 1 and len(margins) > 1:
        return f"{target} beat {opp}"
    if len(margins) == 1:
        return f"{target} beat {opp} by exactly {thr} goal" + ("s" if thr != 1 else "")
    return f"{target} beat {opp} by {thr}+ goals"


def _path_phrase(clauses: list[dict], matches: list[dict], target: str) -> str:
    # Merge a result clause and a goal-difference clause for the same match.
    by_match: dict[int, dict] = {}
    order: list[int] = []
    for c in clauses:
        k = c["match"]
        if k not in by_match:
            by_match[k] = {}
            order.append(k)
        by_match[k][c["kind"]] = c

    parts = []
    for k in order:
        info = by_match[k]
        rvalues = info.get("result", {}).get("values")
        gvalues = info.get("gd", {}).get("values")
        parts.append(_match_phrase(matches[k], target, rvalues, gvalues))

    if len(parts) == 1:
        return parts[0]
    return ", ".join(parts[:-1]) + " and " + parts[-1]


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def explain_qualification(engine, actuals: dict, group_name: str, team_name: str,
                          outcome: str = "advances", n: int = DEFAULT_N) -> dict | None:
    """Return a structured explanation, or ``None`` if it can't be computed.

    The result dict has::

        {"team", "outcome", "verb",
         "status": "certain" | "impossible" | "conditional",
         "summary": str, "lines": [str, ...]}
    """
    if outcome not in _OUTCOME_KEY:
        return None
    if group_name not in engine.group_pos:
        return None

    sim = engine.simulate_group_outcomes(n, actuals, group_name)
    if team_name not in sim["outcomes"]:
        return None

    achieved = sim["outcomes"][team_name][_OUTCOME_KEY[outcome]]
    # Present the remaining matches in chronological (kickoff) order, so the
    # decision tree reads next-match-first rather than in internal pairing order.
    matches = _chronological(engine, group_name, sim["matches"])
    verb = _OUTCOME_VERB[outcome]
    base_rate = float(achieved.mean())

    # Nothing left to play in this group: the outcome is already settled (up to
    # the third-place race, which we report as a probability if undecided).
    if not matches:
        if base_rate >= 1 - TOL:
            return {"team": team_name, "outcome": outcome, "verb": verb,
                    "status": "certain",
                    "summary": f"{team_name} have already secured to {verb}.",
                    "lines": []}
        if base_rate <= TOL:
            return {"team": team_name, "outcome": outcome, "verb": verb,
                    "status": "impossible",
                    "summary": f"{team_name} can no longer {verb}.",
                    "lines": []}
        return {"team": team_name, "outcome": outcome, "verb": verb,
                "status": "conditional",
                "summary": f"{team_name} have a ~{round(base_rate * 100)}% chance to {verb}, "
                           "depending on results in other groups.",
                "lines": []}

    tree, _ = _build_tree(matches, achieved, team_name)
    tree = _prune(tree)

    if tree["label"] == "YES":
        return {"team": team_name, "outcome": outcome, "verb": verb,
                "status": "certain",
                "summary": f"{team_name} are guaranteed to {verb}.",
                "lines": []}
    if tree["label"] == "NO":
        return {"team": team_name, "outcome": outcome, "verb": verb,
                "status": "impossible",
                "summary": f"{team_name} can no longer {verb}.",
                "lines": []}

    paths: list[dict] = []
    _collect(tree, [], paths)

    certain = [p for p in paths if p["label"] == "YES"]
    mixed = [p for p in paths if p["label"] == "MIXED"]
    # Prefer the simplest (fewest-clause) certain routes, then the most likely.
    certain.sort(key=lambda p: (len(p["clauses"]), -p["rate"]))
    mixed.sort(key=lambda p: -p["rate"])

    certain_lines = [_path_phrase(p["clauses"], matches, team_name) for p in certain]
    # De-duplicate while preserving order (different leaves can phrase alike).
    seen = set()
    certain_lines = [x for x in certain_lines if not (x in seen or seen.add(x))]

    lines = list(certain_lines[:MAX_CERTAIN_LINES])
    if len(certain_lines) > MAX_CERTAIN_LINES:
        lines.append("…or several other combinations.")
    mixed_seen = set(certain_lines)
    mixed_shown = 0
    for p in mixed:
        if mixed_shown >= MAX_MIXED_LINES:
            break
        phrase = _path_phrase(p["clauses"], matches, team_name)
        if phrase in mixed_seen:
            continue
        mixed_seen.add(phrase)
        lines.append(f"{phrase} — then a ~{round(p['rate'] * 100)}% chance")
        mixed_shown += 1

    if certain and not mixed and len(certain_lines) <= MAX_CERTAIN_LINES:
        summary = f"{team_name} {verb} if " + _join_or(certain_lines) + "."
    elif certain:
        head = certain_lines[:MAX_CERTAIN_LINES]
        summary = (f"{team_name} {verb} if " + _join_or(head)
                   + (". Some other results leave it to chance."
                      if (mixed or len(certain_lines) > MAX_CERTAIN_LINES) else "."))
    else:
        summary = (f"{team_name} have a ~{round(base_rate * 100)}% chance to {verb}; "
                   "it depends on the exact scorelines and other groups.")

    return {"team": team_name, "outcome": outcome, "verb": verb,
            "status": "conditional", "summary": summary, "lines": lines}


def _chronological(engine, group_name: str, matches: list[dict]) -> list[dict]:
    """Reorder a group's remaining-match dicts by scheduled kickoff (earliest
    first). Matches without a resolvable kickoff sort last but keep their order."""
    from datetime import datetime
    from zoneinfo import ZoneInfo
    from app.simulation.engine import GROUP_MATCH_PAIRS

    groups = getattr(engine, "groups", None)
    data = getattr(engine, "data", {})
    g = next((g for g in groups if g["name"] == group_name), None) if groups else None
    sched = data.get("schedule", {}).get("groups", {}).get(group_name, [])
    if g is None or not sched:
        return matches

    far = datetime.max.replace(tzinfo=ZoneInfo("UTC"))
    key_by_pair = {}
    for (i, j), sm in zip(GROUP_MATCH_PAIRS, sched):
        pair = frozenset((g["teams"][i], g["teams"][j]))
        try:
            dt = datetime.fromisoformat(f"{sm['date']}T{sm['local_time']}")
            dt = dt.replace(tzinfo=ZoneInfo(sm.get("local_timezone") or "UTC")).astimezone(ZoneInfo("UTC"))
        except Exception:
            dt = far
        key_by_pair[pair] = dt

    return sorted(
        matches,
        key=lambda m: key_by_pair.get(frozenset((m["home"], m["away"])), far),
    )


def _stake_headline(clinch: set, elim: set) -> tuple[str, str]:
    """A one-line, this-match-framed summary from the set of outcomes
    ({'win','draw','loss'}) that clinch advancement / cause elimination.
    Returns ``(headline, status)`` where status is one of
    ``certain | impossible | swing | open``."""
    cw, cd = "win" in clinch, "draw" in clinch
    ew, el = "win" in elim, "loss" in elim
    ed = "draw" in elim

    if {"win", "draw", "loss"} <= clinch:
        return "Already through to the knockouts.", "certain"
    if {"win", "draw", "loss"} <= elim:
        return "Can no longer advance.", "impossible"
    if cw and cd:
        return "A draw is enough to go through.", "swing"
    if cw:
        if el:
            return "Win to go through; defeat sends them out.", "swing"
        return "Win to go through.", "swing"
    if ed and el:
        return "Must win to stay alive.", "swing"
    if el:
        return "Defeat sends them out.", "swing"
    return "", "open"


def match_stakes(engine, actuals: dict, group_name: str, home: str, away: str,
                 n: int = DEFAULT_N) -> dict | None:
    """What's at stake for the two teams in the group match ``home`` vs ``away``.

    For each team, marginalizing over every other remaining group match,
    computes the chance to reach the knockouts conditional on this match being a
    win / draw / loss, and an acute one-line headline. Returns::

        {"any_decisive": bool,
         "teams": [
            {"team", "status", "headline",
             "odds": {"win": p|None, "draw": p|None, "loss": p|None}}, ...]}

    in the given (home, away) order. ``None`` if the match isn't a remaining
    match of the group or the group is unknown.
    """
    if group_name not in engine.group_pos:
        return None
    sim = engine.simulate_group_outcomes(n, actuals, group_name)
    matches = sim["matches"]
    f = next((k for k, m in enumerate(matches)
              if {m["home"], m["away"]} == {home, away}), None)
    if f is None:
        return None
    res = matches[f]["result"]
    sim_home = matches[f]["home"]

    any_decisive = False
    teams = []
    for team in (home, away):
        if team not in sim["outcomes"]:
            continue
        achieved = sim["outcomes"][team]["advanced"]
        # Result sign from THIS team's perspective (+1 win, 0 draw, -1 loss).
        signs = {"win": 1, "draw": 0, "loss": -1} if team == sim_home \
            else {"win": -1, "draw": 0, "loss": 1}
        odds = {}
        clinch, elim = set(), set()
        for label, v in signs.items():
            mask = res == v
            if not mask.any():
                odds[label] = None
                continue
            rate = float(achieved[mask].mean())
            odds[label] = rate
            if rate >= 1 - TOL:
                clinch.add(label)
            elif rate <= TOL:
                elim.add(label)
        headline, status = _stake_headline(clinch, elim)
        if clinch or elim:
            any_decisive = True
        teams.append({"team": team, "status": status, "headline": headline, "odds": odds})

    return {"any_decisive": any_decisive, "teams": teams}


_CACHE: dict = {}
_CACHE_MAX = 256


def explain_qualification_cached(engine, actuals: dict, group_name: str, team_name: str,
                                 outcome: str = "advances", n: int = DEFAULT_N) -> dict | None:
    """Memoized :func:`explain_qualification`. Keyed by the (immutable) state
    being reasoned about, so repeated homepage loads don't re-simulate."""
    import hashlib
    import json
    digest = hashlib.md5(
        json.dumps(actuals, sort_keys=True, default=str).encode()
    ).hexdigest()
    key = (digest, group_name, team_name, outcome, n)
    if key in _CACHE:
        return _CACHE[key]
    result = explain_qualification(engine, actuals, group_name, team_name, outcome, n)
    if len(_CACHE) >= _CACHE_MAX:
        _CACHE.clear()
    _CACHE[key] = result
    return result


def _join_or(items: list[str]) -> str:
    if not items:
        return ""
    if len(items) == 1:
        return items[0]
    return "; ".join(items[:-1]) + "; or " + items[-1]
