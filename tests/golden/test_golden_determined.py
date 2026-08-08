"""
Golden test: fully-determined scenarios are deterministic. With every group
match (and, in the second family, every knockout match) fixed, the engine
consumes zero RNG for the ranking/allocation/slot-resolution pipeline, so the
results are EXACT — 0.0 or 1.0, not "close to". This is the highest-value,
zero-tolerance check: it exercises the h2h ranker, Annex C, all 31 slot
resolutions, and the whole results-dict serialization end-to-end.

This is the reference behaviour the future generic engine (spec + phases +
compat_wc) must reproduce exactly (see plan §1a, "T3").
"""

import numpy as np
import pytest

from app.simulation.engine import GROUP_MATCH_PAIRS
from tests.conftest import group_teams, scheduled_group_matches

N_SCENARIOS = 30


def _random_full_group_actuals(rng, engine):
    """Every one of the 72 group matches gets a random small-goal scoreline
    (favoring ties, like the tiebreak generator) so the tiebreak/Annex C
    machinery is genuinely exercised, not just "team A always wins"."""
    group_results = {}
    for g in engine.groups:
        gname = g["name"]
        entries = []
        for pair in scheduled_group_matches(engine, gname):
            hg, ag = int(rng.integers(0, 3)), int(rng.integers(0, 3))
            entries.append({"home": pair["home"], "away": pair["away"],
                             "home_goals": hg, "away_goals": ag})
        group_results[gname] = entries
    return {"group_results": group_results, "knockout_results": {}, "live_matches": []}


def _resolve_full_bracket(engine, r32_participants, choose_winner):
    """r32_participants: {match_no: (home_name, away_name)}. Walks the whole
    bracket definition (which is purely structural — no RNG) and returns
    {match_no: winner_name} for all 31 matches, using `choose_winner(h, a)`
    to pick a winner at every step."""
    winners = {}
    for mno, (h, a) in r32_participants.items():
        winners[mno] = choose_winner(h, a)
    for m in engine.r16_defs + engine.qf_defs + engine.sf_defs + [engine.final_def]:
        h = winners[m["home"]]
        a = winners[m["away"]]
        winners[m["match"]] = choose_winner(h, a)
    return winners


def _r32_participants(engine, group_actuals, choose_winner):
    """Run the engine once at a trivial n with ONLY the group actuals fixed
    to read off the (now fully determined) R32 participants."""
    probe = engine.run(n=2, actuals=group_actuals)
    participants = {}
    for m in engine.r32_defs:
        mno = m["match"]
        bm = probe["bracket_matches"][mno]
        assert bm["home"]["determined"] and bm["away"]["determined"], (
            f"R32 match {mno} not fully determined with all group results fixed — "
            f"home={bm['home']}, away={bm['away']}"
        )
        participants[mno] = (bm["home"]["team"], bm["away"]["team"])
    return participants


@pytest.fixture(scope="module")
def scenarios(engine):
    """N_SCENARIOS independent (group_actuals, full_knockout_winners) pairs,
    generated once and shared across the tests below."""
    rng = np.random.default_rng(20260201)
    out = []
    for i in range(N_SCENARIOS):
        group_actuals = _random_full_group_actuals(rng, engine)
        r32 = _r32_participants(engine, group_actuals, choose_winner=lambda h, a: h)
        winners = _resolve_full_bracket(engine, r32, choose_winner=lambda h, a: h)
        out.append((group_actuals, winners))
    return out


def test_group_stage_only_is_exact(engine, scenarios):
    """All 72 group results fixed, no knockout results: group_finish and
    group_advance_prob must be exactly 0.0/1.0 for every team, and every
    R32 slot must be a single determined team (no candidate list)."""
    for group_actuals, _winners in scenarios:
        results = engine.run(n=500, actuals=group_actuals)

        for gname, teams in results["group_finish"].items():
            for team, stats in teams.items():
                for key in ("first_prob", "second_prob", "third_prob",
                            "fourth_prob", "advance_prob", "eliminate_prob"):
                    v = stats[key]
                    assert v in (0.0, 1.0), (
                        f"{gname}/{team}/{key} = {v}, expected exactly 0.0 or 1.0 "
                        f"with all group results fixed"
                    )

        for team, p in results["group_advance_prob"].items():
            assert p in (0.0, 1.0), f"group_advance_prob[{team}] = {p}"

        for m in engine.r32_defs:
            bm = results["bracket_matches"][m["match"]]
            assert bm["home"]["determined"] and bm["away"]["determined"]
            assert bm["home"]["candidates"] == []
            assert bm["away"]["candidates"] == []


def test_group_stage_fixtures_reflect_actuals_exactly(engine, scenarios):
    """The `fixtures` section must echo back the exact scoreline for every
    played match (goals normalized to schedule orientation)."""
    group_actuals, _winners = scenarios[0]
    results = engine.run(n=10, actuals=group_actuals)
    for gname, entries in group_actuals["group_results"].items():
        by_pair = {frozenset((e["home"], e["away"])): e for e in entries}
        for fx in results["fixtures"][gname]:
            key = frozenset((fx["home"], fx["away"]))
            entry = by_pair[key]
            assert fx["played"] is True
            if fx["home"] == entry["home"]:
                assert fx["home_goals"] == entry["home_goals"]
                assert fx["away_goals"] == entry["away_goals"]
            else:
                assert fx["home_goals"] == entry["away_goals"]
                assert fx["away_goals"] == entry["home_goals"]


def test_full_bracket_fixed_gives_exact_champion(engine, scenarios):
    """All 72 group + all 31 knockout results fixed: winner_prob must be
    exactly 1.0 for the chosen champion and 0.0 for every other team, and
    every bracket match's actual_winner and determined teams must match the
    chosen progression exactly."""
    for group_actuals, winners in scenarios:
        actuals = {
            "group_results": group_actuals["group_results"],
            "knockout_results": {str(mno): name for mno, name in winners.items()},
            "live_matches": [],
        }
        results = engine.run(n=200, actuals=actuals)

        champion = winners[engine.final_def["match"]]
        for team, p in results["winner_prob"].items():
            expected = 1.0 if team == champion else 0.0
            assert p == expected, f"winner_prob[{team}] = {p}, expected {expected}"

        # Finalists are the winners of the two SF matches.
        finalists = {winners[m["match"]] for m in engine.sf_defs}
        for team, p in results["finalist_prob"].items():
            expected = 1.0 if team in finalists else 0.0
            assert p == expected, f"finalist_prob[{team}] = {p}, expected {expected}"

        for m in engine.all_knockout_defs:
            mno = m["match"]
            bm = results["bracket_matches"][mno]
            assert bm["home"]["determined"] and bm["away"]["determined"], (
                f"match {mno} not fully determined with full bracket fixed"
            )
            assert bm["actual_winner"] == winners[mno]
            assert winners[mno] in (bm["home"]["team"], bm["away"]["team"])
