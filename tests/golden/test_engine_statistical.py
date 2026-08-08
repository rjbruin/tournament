"""
Statistical parity: a fresh engine run against the committed n_eff=1,000,000
reference fixtures (tests/golden/fixtures/wc2026_reference_*.json, produced
by _generate_reference_fixtures.py).

This is deliberately NOT bit-exact — both the fixture and the live run are
independent Monte Carlo estimates of the same true probabilities, so we use
a per-entry Wald bound. The point of running this against TODAY's engine is
to (a) calibrate the tolerance so the test isn't flaky, and (b) establish the
exact harness the future generic engine must also satisfy once
compat_wc.add_legacy_keys() materializes these same dict keys — at that
point this file's assertions do not change, only what's under test does.

Marked `slow`: run explicitly with `pytest -m slow`, not part of the default
`pytest tests/` sweep.
"""

import json
import math
import os

import pytest

from app.simulation.engine import SimulationEngine

FIXTURES_DIR = os.path.join(os.path.dirname(__file__), "fixtures")
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))

N_LIVE = 250_000          # kept modest — this test runs one live simulation
Z = 4.5                    # ~Bonferroni over 48 teams x 6 stages at alpha=0.001
FLOOR = 1e-4                # rounding floor (_aggregate rounds to 4dp)

PROB_KEYS = [
    "group_advance_prob", "round_of_16_prob", "quarterfinal_prob",
    "semifinal_prob", "finalist_prob", "winner_prob",
]
CONSERVATION_TARGETS = {
    "group_advance_prob": 32.0,
    "round_of_16_prob": 16.0,
    "quarterfinal_prob": 8.0,
    "semifinal_prob": 4.0,
    "finalist_prob": 2.0,
    "winner_prob": 1.0,
}


def _wald_bound(p_a, n_a, p_b, n_b):
    p_bar = (p_a + p_b) / 2
    var = p_bar * (1 - p_bar) * (1 / n_a + 1 / n_b)
    return Z * math.sqrt(max(var, 0)) + FLOOR


@pytest.fixture(scope="module")
def live_engine():
    with open(os.path.join(ROOT, "data", "wc2026.json")) as f:
        data = json.load(f)
    return SimulationEngine(data)


def _load_fixture(label):
    path = os.path.join(FIXTURES_DIR, f"wc2026_reference_{label}.json")
    with open(path) as f:
        return json.load(f)


def _actuals_for(label, live_engine):
    """Reads the actuals snapshot EMBEDDED in the fixture file, not the live
    data/actuals.json — that file is mutated by the background results
    poller, so re-reading it here would compare a fresh run against a
    reference generated from a now-stale state (this broke mid-session:
    the poller wrote 13 new knockout results between fixture generation and
    a later test run). "empty" and "partial" are also embedded for a
    single consistent code path, though they're not time-sensitive."""
    fixture = _load_fixture(label)
    if "actuals_snapshot" in fixture:
        return fixture["actuals_snapshot"]
    # Fallback for fixtures generated before actuals_snapshot was added.
    if label == "empty":
        return {"group_results": {}, "knockout_results": {}, "live_matches": []}
    if label == "partial":
        from tests.golden._generate_reference_fixtures import build_partial_actuals
        return build_partial_actuals(live_engine)
    raise ValueError(f"{label}: fixture has no actuals_snapshot and no fallback available")


@pytest.mark.slow
@pytest.mark.parametrize("label", ["empty", "current", "partial"])
def test_statistical_parity_vs_reference(live_engine, label):
    ref = _load_fixture(label)
    actuals = _actuals_for(label, live_engine)
    live = live_engine.run(n=N_LIVE, actuals=actuals)

    n_ref = ref["n_eff"]
    failures = []
    for key in PROB_KEYS:
        for team, p_ref in ref[key].items():
            p_live = live[key].get(team)
            assert p_live is not None, f"{key}: team {team!r} missing from live run"
            bound = _wald_bound(p_ref, n_ref, p_live, N_LIVE)
            if abs(p_live - p_ref) > bound:
                failures.append((key, team, p_live, p_ref, bound))
    assert not failures, (
        f"{len(failures)} teams outside Wald bound (showing up to 10): {failures[:10]}"
    )


@pytest.mark.slow
@pytest.mark.parametrize("label", ["empty", "current", "partial"])
def test_conservation_identities(live_engine, label):
    """Exactly one champion, two finalists, four semifinalists, etc. per
    simulation — these sums should be within rounding noise of the integer
    target, independent of any Wald bound."""
    actuals = _actuals_for(label, live_engine)
    live = live_engine.run(n=N_LIVE, actuals=actuals)
    for key, target in CONSERVATION_TARGETS.items():
        total = sum(live[key].values())
        assert abs(total - target) < 0.05, f"{label}/{key}: sum={total}, expected ~{target}"


@pytest.mark.slow
@pytest.mark.parametrize("label", ["empty", "current", "partial"])
def test_top10_winner_set_matches_reference(live_engine, label):
    """The identity of the top-10 title favourites should be stable across
    independent MC runs — a coarser, more robust check than the per-team
    Wald bound above."""
    ref = _load_fixture(label)
    actuals = _actuals_for(label, live_engine)
    live = live_engine.run(n=N_LIVE, actuals=actuals)

    ref_top10 = {t for t, _ in sorted(ref["winner_prob"].items(), key=lambda x: -x[1])[:10]}
    live_top10 = {t for t, _ in sorted(live["winner_prob"].items(), key=lambda x: -x[1])[:10]}
    overlap = ref_top10 & live_top10
    assert len(overlap) >= 8, (
        f"{label}: only {len(overlap)}/10 overlap between reference and live top-10 "
        f"favourites — ref={ref_top10}, live={live_top10}"
    )
