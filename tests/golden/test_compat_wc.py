"""
Golden test [T3]: app.simulation.compat_wc.to_legacy_results against
SimulationEngine._run_legacy — the pre-refactor implementation, kept solely
as this frozen reference oracle now that SimulationEngine.run() itself
delegates to the new engine (see engine.py's run()/._run_legacy split). This
is the ultimate Stage 1 acceptance test: for fully determined scenarios (all
group + all knockout results fixed), every key except match-odds sub-dicts
must be EXACTLY equal (zero RNG on either path for anything but display
odds); match odds are compared within a tight statistical tolerance since
old is 100k-sample MC and new is analytic.
"""

import json
import os

import numpy as np

from app.simulation.compat_wc import to_legacy_results
from app.simulation.run import simulate
from app.simulation.spec import from_wc2026_json
from tests.conftest import scheduled_group_matches

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))


def _annex_raw():
    with open(os.path.join(ROOT, "data", "annex_c.json")) as f:
        return json.load(f)


def _spec(engine):
    return from_wc2026_json(engine.data, _annex_raw())


def _random_full_group_actuals(rng, engine):
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


def _fully_determined_actuals(rng, engine):
    group_actuals = _random_full_group_actuals(rng, engine)
    probe = engine._run_legacy(n=2, actuals=group_actuals)
    winners = {}
    for m in engine.r32_defs:
        mno = m["match"]
        bm = probe["bracket_matches"][mno]
        winners[mno] = bm["home"]["team"]
    for m in engine.r16_defs + engine.qf_defs + engine.sf_defs + [engine.final_def]:
        winners[m["match"]] = winners[m["home"]]
    return {
        "group_results": group_actuals["group_results"],
        "knockout_results": {str(mno): name for mno, name in winners.items()},
        "live_matches": [],
    }


def _assert_prob_dicts_equal(new_d, old_d, label):
    assert set(new_d.keys()) == set(old_d.keys()), f"{label}: key mismatch"
    for k in old_d:
        assert new_d[k] == old_d[k], f"{label}[{k}]: new={new_d[k]} old={old_d[k]}"


def test_full_legacy_dict_exact_parity_fully_determined(engine):
    spec = _spec(engine)
    rng = np.random.default_rng(70260101)

    for trial in range(8):
        actuals = _fully_determined_actuals(rng, engine)
        n = 60

        old = engine._run_legacy(n=n, actuals=actuals)
        run = simulate(spec, actuals=actuals, n=n, seed=trial)
        new = to_legacy_results(run)

        for key in ("group_advance_prob", "round_of_16_prob", "quarterfinal_prob",
                    "semifinal_prob", "finalist_prob", "winner_prob"):
            _assert_prob_dicts_equal(new[key], old[key], f"trial{trial}.{key}")

        assert set(new["group_finish"].keys()) == set(old["group_finish"].keys())
        for letter in old["group_finish"]:
            for team in old["group_finish"][letter]:
                assert new["group_finish"][letter][team] == old["group_finish"][letter][team], (
                    f"trial {trial} group_finish[{letter}][{team}]: "
                    f"new={new['group_finish'][letter][team]} old={old['group_finish'][letter][team]}"
                )

        for letter in old["fixtures"]:
            old_fx = {frozenset((f["home"], f["away"])): f for f in old["fixtures"][letter]}
            new_fx = {frozenset((f["home"], f["away"])): f for f in new["fixtures"][letter]}
            assert set(old_fx.keys()) == set(new_fx.keys())
            for key, ofx in old_fx.items():
                nfx = new_fx[key]
                assert nfx["played"] == ofx["played"]
                if ofx["played"]:
                    assert nfx["home"] == ofx["home"] and nfx["away"] == ofx["away"]
                    assert nfx["home_goals"] == ofx["home_goals"]
                    assert nfx["away_goals"] == ofx["away_goals"]

        for mno, obm in old["bracket_matches"].items():
            nbm = new["bracket_matches"][mno]
            assert nbm["round"] == obm["round"], f"trial {trial} match {mno} round label"
            assert nbm["home"]["determined"] == obm["home"]["determined"]
            assert nbm["away"]["determined"] == obm["away"]["determined"]
            assert nbm["home"]["team"] == obm["home"]["team"]
            assert nbm["away"]["team"] == obm["away"]["team"]
            assert nbm["actual_winner"] == obm["actual_winner"], (
                f"trial {trial} match {mno}: new_winner={nbm['actual_winner']} "
                f"old_winner={obm['actual_winner']}"
            )

        assert set(new["opponent_probs"].keys()) == set(old["opponent_probs"].keys())
        for team in old["opponent_probs"]:
            assert set(new["opponent_probs"][team].keys()) == set(old["opponent_probs"][team].keys()), (
                f"trial {trial} team {team}: round-label mismatch "
                f"new={list(new['opponent_probs'][team].keys())} "
                f"old={list(old['opponent_probs'][team].keys())}"
            )
            for round_label in old["opponent_probs"][team]:
                old_opps = {o["team"]: o["probability"] for o in old["opponent_probs"][team][round_label]}
                new_opps = {o["team"]: o["probability"] for o in new["opponent_probs"][team][round_label]}
                assert old_opps == new_opps, (
                    f"trial {trial} {team}/{round_label}: new={new_opps} old={old_opps}"
                )

        for letter in old["fixtures"]:
            for of, nf in zip(
                sorted(old["fixtures"][letter], key=lambda f: (f["home"], f["away"])),
                sorted(new["fixtures"][letter], key=lambda f: (f["home"], f["away"])),
            ):
                assert of.get("date") == nf.get("date")
                assert of.get("venue") == nf.get("venue")
        for mno, obm in old["bracket_matches"].items():
            nbm = new["bracket_matches"][mno]
            assert obm.get("date") == nbm.get("date")
            assert obm.get("venue") == nbm.get("venue")


def test_match_odds_analytic_close_to_old_mc(engine):
    """The one place old (MC) and new (analytic) genuinely differ in VALUE,
    not just precision: pre-match odds on determined-but-unplayed matches.
    Use a partially-determined scenario (some groups fixed, not all) so
    unplayed fixtures with real odds actually exist."""
    spec = _spec(engine)
    rng = np.random.default_rng(70260102)

    group_results = {}
    letters = list(engine.group_letters)[:3]  # only fix 3 of 12 groups
    for letter in letters:
        entries = []
        for pair in scheduled_group_matches(engine, letter):
            hg, ag = int(rng.integers(0, 3)), int(rng.integers(0, 3))
            entries.append({"home": pair["home"], "away": pair["away"],
                             "home_goals": hg, "away_goals": ag})
        group_results[letter] = entries
    actuals = {"group_results": group_results, "knockout_results": {}, "live_matches": []}

    old = engine._run_legacy(n=1000, actuals=actuals)
    run = simulate(spec, actuals=actuals, n=1000, seed=1)
    new = to_legacy_results(run)

    checked = 0
    for letter in engine.group_letters:
        if letter in letters:
            continue  # played, no odds
        for of, nf in zip(old["fixtures"][letter], new["fixtures"][letter]):
            assert of["played"] is False and nf["played"] is False
            for key in ("home_win", "draw", "away_win"):
                assert abs(of["odds"][key] - nf["odds"][key]) < 0.02, (
                    f"{letter} {of['home']}v{of['away']} {key}: old={of['odds'][key]} new={nf['odds'][key]}"
                )
            checked += 1
    assert checked > 0
