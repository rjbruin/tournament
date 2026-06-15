"""Integration tests: the real SimulationEngine on constructed scenarios.

These assert invariants that must hold regardless of the random draws, and one
fully-determined "already qualified" case.
"""

import numpy as np

from app.qualification import explain_qualification
from conftest import group_teams, scheduled_group_matches, play_through


GROUP = "A"


def test_simulate_group_outcomes_invariants(engine):
    actuals = play_through(engine, GROUP, 4)  # final matchday
    sim = engine.simulate_group_outcomes(5000, actuals, GROUP)

    # Two matches remain on the final matchday.
    assert len(sim["matches"]) == 2
    for m in sim["matches"]:
        assert len(m["result"]) == 5000
        assert set(np.unique(m["result"])).issubset({-1, 0, 1})

    teams = group_teams(engine, GROUP)
    assert set(sim["outcomes"]) == set(teams)
    for name in teams:
        o = sim["outcomes"][name]
        # 1st and 2nd are mutually exclusive ...
        assert not (o["first"] & o["second"]).any()
        # ... and finishing top-2 always means advancing.
        assert (o["advanced"] | ~(o["first"] | o["second"])).all()


def test_final_matchday_statuses_are_valid(engine):
    actuals = play_through(engine, GROUP, 4)
    for team in group_teams(engine, GROUP):
        r = explain_qualification(engine, actuals, GROUP, team, "advances", n=8000)
        assert r is not None
        assert r["status"] in {"certain", "impossible", "conditional"}
        assert isinstance(r["summary"], str) and r["summary"]
        assert team in r["summary"]


def test_guaranteed_qualification_is_certain(engine):
    """Engineer a final-matchday state where one team cannot be caught.

    With T on 6 points, two rivals on 3 and one on 0, and the last games being
    T-vs-(0-pt) and (3-pt)-vs-(3-pt), only one rival can reach 6 — so T is
    guaranteed a top-2 finish whatever happens."""
    final = scheduled_group_matches(engine, GROUP)[-2:]
    T, C = final[0]["home"], final[0]["away"]   # T plays the 0-point team C
    A, B = final[1]["home"], final[1]["away"]   # the two 3-point rivals

    # The four earlier matches are exactly {T-A, T-B, A-C, B-C}. Make T win both
    # of its games and the rivals each beat C, so C finishes on 0.
    winners = {T}  # T beats everyone it plays before the final round
    entries = []
    for p in scheduled_group_matches(engine, GROUP)[:4]:
        h, a = p["home"], p["away"]
        winner = T if T in (h, a) else (a if h == C else h)
        entries.append({"home": h, "away": a,
                        "home_goals": 1 if winner == h else 0,
                        "away_goals": 1 if winner == a else 0})
    actuals = {"group_results": {GROUP: entries}, "knockout_results": {}, "live_matches": []}

    r = explain_qualification(engine, actuals, GROUP, T, "advances", n=8000)
    assert r["status"] == "certain"
    assert "guaranteed" in r["summary"]

    # The 0-point team, needing to win and depend on others, is not yet certain.
    r_c = explain_qualification(engine, actuals, GROUP, C, "advances", n=8000)
    assert r_c["status"] in {"impossible", "conditional"}


def test_probabilities_are_well_formed(engine):
    actuals = play_through(engine, GROUP, 4)
    for team in group_teams(engine, GROUP):
        r = explain_qualification(engine, actuals, GROUP, team, "advances", n=8000)
        for line in r["lines"]:
            if "% chance" in line:
                pct = int(line.split("~")[1].split("%")[0])
                assert 0 <= pct <= 100
