"""
One-off generator for the statistical reference fixtures used by
test_engine_statistical.py. NOT a pytest test — run manually to (re)create
the committed fixtures:

    python3 tests/golden/_generate_reference_fixtures.py

Rationale for n_eff = 1,000,000 rather than the 2,000,000 mentioned in the
refactor plan: a single n=250,000 run peaks around ~800MB RSS in this
environment, which is already close to the machine's free memory. Four
sequential 250k draws (discarded between calls, never held concurrently)
comfortably fit and give the same effective sample size as one large run
would, at the cost of a slightly coarser 4-decimal rounding per draw before
averaging — negligible next to the Wald tolerance used downstream.

Produces three states, chosen to exercise different RNG paths:
  - empty:   no actuals at all — maximum uncertainty, full group+KO RNG.
  - current: the real data/actuals.json on disk AT GENERATION TIME, embedded
             into the fixture as `actuals_snapshot` (not re-read live by the
             comparison test — data/actuals.json is mutated by the
             background results poller and will have moved on by the time
             the fixture is used).
  - partial: a synthetic state with the first 2 matchdays (4 of 6 matches)
             of every group played and nothing else — exercises group-stage
             RNG for partially-determined groups (the "clinch window").

Uses SimulationEngine._run_legacy — the frozen pre-refactor implementation
— NOT .run(), which now delegates to the new engine under test. Generating
against .run() would make the fixture compare the new engine against
itself.
"""

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from app.simulation.engine import SimulationEngine  # noqa: E402
from tests.conftest import scheduled_group_matches  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
FIXTURES_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures")

N_PER_DRAW = 250_000
N_DRAWS = 4  # n_eff = 1,000,000

PROB_KEYS = [
    "group_advance_prob", "round_of_16_prob", "quarterfinal_prob",
    "semifinal_prob", "finalist_prob", "winner_prob",
]


def _average_prob_dicts(dicts):
    keys = dicts[0].keys()
    return {k: round(sum(d[k] for d in dicts) / len(dicts), 6) for k in keys}


def _average_group_finish(finishes):
    out = {}
    for gname in finishes[0]:
        out[gname] = {}
        for team in finishes[0][gname]:
            out[gname][team] = {}
            for stat in finishes[0][gname][team]:
                vals = [f[gname][team][stat] for f in finishes]
                out[gname][team][stat] = round(sum(vals) / len(vals), 6)
    return out


def run_state(engine, actuals, label):
    prob_draws = {k: [] for k in PROB_KEYS}
    finish_draws = []
    for d in range(N_DRAWS):
        print(f"  [{label}] draw {d + 1}/{N_DRAWS} (n={N_PER_DRAW}) ...", flush=True)
        results = engine._run_legacy(n=N_PER_DRAW, actuals=actuals)
        for k in PROB_KEYS:
            prob_draws[k].append(results[k])
        finish_draws.append(results["group_finish"])

    out = {"n_eff": N_PER_DRAW * N_DRAWS, "n_draws": N_DRAWS, "n_per_draw": N_PER_DRAW}
    for k in PROB_KEYS:
        out[k] = _average_prob_dicts(prob_draws[k])
    out["group_finish"] = _average_group_finish(finish_draws)
    return out


def build_partial_actuals(engine):
    group_results = {}
    for g in engine.groups:
        gname = g["name"]
        matches = scheduled_group_matches(engine, gname)[:4]  # first 2 matchdays
        entries = []
        for idx, pair in enumerate(matches):
            # Deterministic small-goal pseudo-scores, varied per match so it
            # isn't a uniform "everyone draws" state.
            hg, ag = (idx % 3), ((idx + 1) % 3)
            entries.append({"home": pair["home"], "away": pair["away"],
                             "home_goals": hg, "away_goals": ag})
        group_results[gname] = entries
    return {"group_results": group_results, "knockout_results": {}, "live_matches": []}


def main():
    os.makedirs(FIXTURES_DIR, exist_ok=True)
    with open(os.path.join(ROOT, "data", "wc2026.json")) as f:
        data = json.load(f)
    engine = SimulationEngine(data)

    with open(os.path.join(ROOT, "data", "actuals.json")) as f:
        current_actuals = json.load(f)

    states = {
        "empty": {"group_results": {}, "knockout_results": {}, "live_matches": []},
        "current": current_actuals,
        "partial": build_partial_actuals(engine),
    }

    for label, actuals in states.items():
        print(f"Generating reference fixture: {label}")
        out = run_state(engine, actuals, label)
        # Embed the actuals snapshot used to produce this fixture, so the
        # comparison test replays against a FROZEN state rather than
        # re-reading data/actuals.json — which is a live file, mutated by
        # the background results poller, and will have moved on by the
        # time this fixture is compared against (discovered the hard way:
        # the "current" fixture went stale mid-session once the poller
        # wrote new knockout results to disk).
        out["actuals_snapshot"] = actuals
        path = os.path.join(FIXTURES_DIR, f"wc2026_reference_{label}.json")
        with open(path, "w") as f:
            json.dump(out, f, indent=2, sort_keys=True)
        print(f"  wrote {path}")


if __name__ == "__main__":
    main()
