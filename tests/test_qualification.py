"""Tests for the natural-language group-qualification explanations.

Two layers:

* Unit tests drive ``explain_qualification`` through a ``FakeEngine`` whose
  per-simulation data is hand-built, so the decision tree, pruning, goal-
  difference refinement and rendering can be asserted *exactly* and
  deterministically across a range of group states.
* Integration tests run the real ``SimulationEngine`` on constructed scenarios
  and assert the structural invariants that must hold whatever the random draws.
"""

import numpy as np
import pytest

from app.qualification import explain_qualification


# ---------------------------------------------------------------------------
# Fake engine: full control over the per-simulation outcome distribution
# ---------------------------------------------------------------------------

class FakeEngine:
    def __init__(self, group, matches, outcomes):
        self.group_pos = {group: 0}
        self._matches = matches
        self._outcomes = outcomes
        self._n = len(next(iter(outcomes.values()))["advanced"]) if outcomes else 0

    def simulate_group_outcomes(self, n, actuals, group_name):
        return {"matches": self._matches, "outcomes": self._outcomes, "n": self._n}


def build_world(target, match_defs, sims, outcome_key="advanced"):
    """Construct a FakeEngine from an explicit list of simulations.

    ``match_defs``: ordered ``[(home, away), ...]`` (tree branches in this order).
    ``sims``: ``[(scores, achieved), ...]`` where ``scores`` maps each
    ``(home, away)`` to a ``(home_goals, away_goals)`` tuple and ``achieved`` is
    whether the target team got the outcome in that simulation.
    """
    nmatch = len(match_defs)
    results = [[] for _ in range(nmatch)]
    gds = [[] for _ in range(nmatch)]
    achieved = []
    for scores, got in sims:
        for k, (h, a) in enumerate(match_defs):
            gi, gj = scores[(h, a)]
            results[k].append(int(np.sign(gi - gj)))
            gds[k].append(int(gi - gj))
        achieved.append(bool(got))

    matches = [
        {"home": h, "away": a,
         "result": np.array(results[k]), "gd": np.array(gds[k])}
        for k, (h, a) in enumerate(match_defs)
    ]
    n = len(sims)
    outcomes = {target: {"first": np.zeros(n, bool),
                         "second": np.zeros(n, bool),
                         "advanced": np.zeros(n, bool)}}
    outcomes[target][outcome_key] = np.array(achieved, dtype=bool)
    return FakeEngine("G", matches, outcomes)


def explain(world, team="T", outcome="advances"):
    return explain_qualification(world, {}, "G", team, outcome, n=world._n)


# ---------------------------------------------------------------------------
# Already-decided states (no matches remaining)
# ---------------------------------------------------------------------------

def test_no_remaining_matches_certain():
    world = build_world("T", [], [({}, True)] * 4)
    r = explain(world)
    assert r["status"] == "certain"
    assert "already secured" in r["summary"]


def test_no_remaining_matches_impossible():
    world = build_world("T", [], [({}, False)] * 4)
    r = explain(world)
    assert r["status"] == "impossible"
    assert "can no longer" in r["summary"]


def test_no_remaining_matches_probabilistic():
    world = build_world("T", [], [({}, True), ({}, False)])
    r = explain(world)
    assert r["status"] == "conditional"
    assert "% chance" in r["summary"]


# ---------------------------------------------------------------------------
# Single decisive match
# ---------------------------------------------------------------------------

def test_certain_regardless_of_result():
    # Already through: every result still advances.
    sims = [
        ({("T", "X"): (2, 0)}, True),
        ({("T", "X"): (1, 1)}, True),
        ({("T", "X"): (0, 1)}, True),
    ]
    r = explain(build_world("T", [("T", "X")], sims))
    assert r["status"] == "certain"
    assert "guaranteed" in r["summary"]


def test_impossible():
    sims = [
        ({("T", "X"): (2, 0)}, False),
        ({("T", "X"): (1, 1)}, False),
        ({("T", "X"): (0, 1)}, False),
    ]
    r = explain(build_world("T", [("T", "X")], sims))
    assert r["status"] == "impossible"
    assert "can no longer" in r["summary"]


def test_win_clinches():
    sims = [
        ({("T", "X"): (1, 0)}, True),
        ({("T", "X"): (1, 1)}, False),
        ({("T", "X"): (0, 1)}, False),
    ]
    r = explain(build_world("T", [("T", "X")], sims))
    assert r["status"] == "conditional"
    assert r["lines"] == ["T beat X"]
    assert r["summary"] == "T advance to the knockouts if T beat X."


def test_avoid_defeat():
    sims = [
        ({("T", "X"): (1, 0)}, True),   # win
        ({("T", "X"): (1, 1)}, True),   # draw
        ({("T", "X"): (0, 1)}, False),  # loss
    ]
    r = explain(build_world("T", [("T", "X")], sims))
    assert r["lines"] == ["T avoid defeat against X"]


def test_goal_difference_threshold():
    sims = [
        ({("T", "X"): (1, 0)}, False),  # win by 1 — not enough
        ({("T", "X"): (2, 0)}, True),   # win by 2
        ({("T", "X"): (3, 0)}, True),   # win by 3
        ({("T", "X"): (1, 1)}, False),  # draw
        ({("T", "X"): (0, 1)}, False),  # loss
    ]
    r = explain(build_world("T", [("T", "X")], sims))
    assert r["lines"] == ["T beat X by 2+ goals"]


# ---------------------------------------------------------------------------
# Two remaining matches (dependency on another fixture)
# ---------------------------------------------------------------------------

def test_irrelevant_second_match_is_pruned():
    # T's own win is enough regardless of the Y-Z match: that branch point
    # should be pruned away entirely (step 5a).
    sims = []
    for t_score, t_win in [((1, 0), True), ((1, 1), False), ((0, 1), False)]:
        for yz in [(1, 0), (1, 1), (0, 1)]:
            sims.append(({("T", "X"): t_score, ("Y", "Z"): yz}, t_win))
    r = explain(build_world("T", [("Y", "Z"), ("T", "X")], sims))
    assert r["lines"] == ["T beat X"]


def test_or_condition_across_matches():
    # Advance if T win, OR T draw and Z beats Y.
    sims = []
    for t_score, t_res in [((1, 0), "W"), ((1, 1), "D"), ((0, 1), "L")]:
        for yz, yz_res in [((1, 0), "Ywin"), ((1, 1), "draw"), ((0, 1), "Zwin")]:
            got = (t_res == "W") or (t_res == "D" and yz_res == "Zwin")
            sims.append(({("T", "X"): t_score, ("Y", "Z"): yz}, got))
    r = explain(build_world("T", [("T", "X"), ("Y", "Z")], sims))
    assert r["status"] == "conditional"
    assert r["lines"] == ["T beat X", "T draw with X and Z beat Y"]
    assert r["summary"] == (
        "T advance to the knockouts if T beat X; or T draw with X and Z beat Y."
    )


def test_mixed_leaf_collapses_when_other_match_is_uninformative():
    # The residual uncertainty depends only on the Y-Z *margin* (which we don't
    # branch on), and the Y-Z result is constant across those sims, so it's
    # pruned: the mixed leaf is reported on T's result alone.
    sims = [
        ({("T", "X"): (2, 0), ("Y", "Z"): (1, 0)}, True),   # T win -> through
        ({("T", "X"): (1, 1), ("Y", "Z"): (1, 0)}, False),  # T draw, Y by 1 -> out
        ({("T", "X"): (1, 1), ("Y", "Z"): (3, 0)}, True),   # T draw, Y by 3 -> in
        ({("T", "X"): (0, 1), ("Y", "Z"): (1, 0)}, False),  # T lose -> out
    ]
    r = explain(build_world("T", [("T", "X"), ("Y", "Z")], sims))
    assert r["status"] == "conditional"
    assert r["lines"] == ["T beat X", "T draw with X — then a ~50% chance"]
    assert "leave it to chance" in r["summary"]


def test_mixed_leaf_reports_probability_with_other_match():
    # Here the Y-Z *result* genuinely matters (Z winning is hopeless) and is
    # retained, while the residual 50% within "Y beat Z" comes from its margin.
    sims = [
        ({("T", "X"): (2, 0), ("Y", "Z"): (1, 0)}, True),   # T win -> through
        ({("T", "X"): (1, 1), ("Y", "Z"): (1, 0)}, True),   # T draw, Y beat Z (by 1)
        ({("T", "X"): (1, 1), ("Y", "Z"): (2, 0)}, False),  # T draw, Y beat Z (by 2)
        ({("T", "X"): (1, 1), ("Y", "Z"): (0, 1)}, False),  # T draw, Z beat Y -> out
        ({("T", "X"): (0, 1), ("Y", "Z"): (1, 0)}, False),  # T lose -> out
    ]
    r = explain(build_world("T", [("T", "X"), ("Y", "Z")], sims))
    assert r["status"] == "conditional"
    assert "T beat X" in r["lines"]
    assert "T draw with X and Y beat Z — then a ~50% chance" in r["lines"]
    assert "leave it to chance" in r["summary"]


# ---------------------------------------------------------------------------
# Outcome wording and input validation
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("outcome,phrase", [
    ("first", "win the group"),
    ("second", "finish runner-up"),
    ("advances", "advance to the knockouts"),
])
def test_outcome_verbs(outcome, phrase):
    key = {"first": "first", "second": "second", "advances": "advanced"}[outcome]
    sims = [
        ({("T", "X"): (1, 0)}, True),
        ({("T", "X"): (1, 1)}, False),
        ({("T", "X"): (0, 1)}, False),
    ]
    r = explain(build_world("T", [("T", "X")], sims, outcome_key=key),
                outcome=outcome)
    assert phrase in r["summary"]


def test_unknown_group_returns_none():
    world = build_world("T", [("T", "X")], [({("T", "X"): (1, 0)}, True)])
    assert explain_qualification(world, {}, "ZZ", "T", "advances", n=1) is None


def test_unknown_team_returns_none():
    world = build_world("T", [("T", "X")], [({("T", "X"): (1, 0)}, True)])
    assert explain_qualification(world, {}, "G", "Nobody", "advances", n=1) is None


def test_invalid_outcome_returns_none():
    world = build_world("T", [("T", "X")], [({("T", "X"): (1, 0)}, True)])
    assert explain_qualification(world, {}, "G", "T", "champion", n=1) is None
