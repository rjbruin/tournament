"""
Stage 1 acceptance checks beyond behavioral parity: determinism under a
fixed seed (the whole point of app.simulation.rng.SimRng replacing ambient
global RNG state), and a resource guard against the phase abstraction
quietly regressing wall time or memory versus the pre-refactor engine.
"""

import json
import os
import tracemalloc

from app.simulation.compat_wc import to_legacy_results
from app.simulation.run import simulate
from app.simulation.spec import from_wc2026_json

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))


def _annex_raw():
    with open(os.path.join(ROOT, "data", "annex_c.json")) as f:
        return json.load(f)


def test_same_seed_gives_byte_identical_results(engine):
    """simulate(spec, actuals, n, seed=k) called twice must produce an
    identical results dict — the core promise of a pure, explicitly-seeded
    engine (vs. the old engine's dependence on ambient np.random state,
    which is meaningless under concurrent callers)."""
    spec = from_wc2026_json(engine.data, _annex_raw())
    with open(os.path.join(ROOT, "data", "actuals.json")) as f:
        actuals = json.load(f)

    run_a = simulate(spec, actuals=actuals, n=5000, seed=42)
    run_b = simulate(spec, actuals=actuals, n=5000, seed=42)

    results_a = to_legacy_results(run_a)
    results_b = to_legacy_results(run_b)

    # elapsed_seconds legitimately differs between runs; everything else
    # must not.
    del results_a["elapsed_seconds"]
    del results_b["elapsed_seconds"]

    json_a = json.dumps(results_a, sort_keys=True, default=str)
    json_b = json.dumps(results_b, sort_keys=True, default=str)
    assert json_a == json_b


def test_different_seeds_give_different_results(engine):
    """Sanity check on the determinism test above: confirm it isn't
    trivially passing because the simulation is seed-insensitive."""
    spec = from_wc2026_json(engine.data, _annex_raw())
    actuals = {"group_results": {}, "knockout_results": {}, "live_matches": []}

    run_a = simulate(spec, actuals=actuals, n=5000, seed=1)
    run_b = simulate(spec, actuals=actuals, n=5000, seed=2)
    assert not (run_a.reached == run_b.reached).all()


def test_wall_time_within_guard_of_legacy(engine):
    """The new engine.run() must not be dramatically slower than the
    preserved legacy implementation at the same n — guards against the
    phase abstraction introducing quadratic-ish overhead."""
    import time

    actuals = {"group_results": {}, "knockout_results": {}, "live_matches": []}
    n = 100_000

    t0 = time.perf_counter()
    engine._run_legacy(n=n, actuals=actuals)
    legacy_elapsed = time.perf_counter() - t0

    t0 = time.perf_counter()
    engine.run(n=n, actuals=actuals)
    new_elapsed = time.perf_counter() - t0

    # Generous guard band: the analytic (Skellam) match-odds computation
    # replacing 100k/200k-sample MC calls should make the new path FASTER
    # in practice, but allow real slack for CI-noise and one-time overhead
    # (allocator construction, etc.) that a single-run timing can't average
    # away.
    assert new_elapsed < legacy_elapsed * 2.0 + 1.0, (
        f"new engine took {new_elapsed:.2f}s vs legacy {legacy_elapsed:.2f}s at n={n}"
    )


def test_peak_memory_bounded(engine):
    """Peak allocation at a realistic n stays within a documented ceiling —
    a guard specifically because the phase abstraction could tempt
    retaining more per-match (n,) arrays than the original engine does
    (int16 entry indices + summarize-inside-record_match are what keep this
    bounded; see knockout.py's module docstring)."""
    actuals = {"group_results": {}, "knockout_results": {}, "live_matches": []}
    n = 100_000

    tracemalloc.start()
    engine.run(n=n, actuals=actuals)
    _current, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()

    peak_mb = peak / (1024 * 1024)
    # Generous ceiling for n=100k (linear extrapolation from the ~800MB RSS
    # observed for the WHOLE PROCESS at n=250k puts a bare allocation trace
    # at n=100k well under this).
    assert peak_mb < 1500, f"peak traced allocation {peak_mb:.0f} MB at n={n}"
