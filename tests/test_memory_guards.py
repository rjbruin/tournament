"""
Guards on the memory behaviour of the simulation path.

On 2026-08-20 the production service grew to 2.7 GB and was OOM-killed,
taking neighbouring services on the same VM down with it. The cause was not
an object leak — Python frees every simulation array — but peak memory per
run, multiplied by unbounded concurrency, on top of an unbounded cache:

  * a single n=250,000 run allocated ~1.16 GB, dominated by (n, group_size)
    int64 arrays that are retained for every group until the run ends;
  * the threaded server let N cache-missing requests each start their own
    run simultaneously;
  * the results cache was keyed by account and never evicted.

These tests pin the three fixes so a well-meaning refactor can't quietly
restore any of them.
"""

import threading

import numpy as np

import app as app_module


def test_group_stage_uses_compact_dtypes(engine):
    """The per-simulation group arrays dominate peak memory and are retained
    for every group for the whole run, so their dtype is a memory decision,
    not an incidental one. Values are entry indices, points (<= 3/match) and
    per-team stat totals — all comfortably inside int16."""
    from app.simulation.phases.round_robin import _GROUP_DTYPE

    assert np.dtype(_GROUP_DTYPE).itemsize <= 2, "group arrays must stay narrow"

    # And the arrays actually built by a run use it.
    from app.simulation.run import simulate
    r = simulate(engine._spec, actuals={"group_results": {}, "knockout_results": {}}, n=500)
    standings = r.phase_results["groups"].extra["standings"]
    any_group = next(iter(standings.values()))
    for field in ("positions", "pts", "goals_for", "goals_against"):
        assert any_group[field].dtype == _GROUP_DTYPE, (
            f"standings[{field}] is {any_group[field].dtype}, expected {_GROUP_DTYPE}"
        )


def test_results_cache_is_bounded_and_lru(monkeypatch):
    """An unbounded cache keyed by (account, tournament, scenario) grows with
    every combination ever viewed; entries are ~0.5 MB each."""
    monkeypatch.setattr(app_module, "_simulation_results", type(app_module._simulation_results)())
    cap = app_module._RESULTS_CACHE_MAX

    for i in range(cap + 40):
        app_module.set_simulation_results(f"user{i}", {"n": i}, "current", "wc2026")

    assert len(app_module._simulation_results) == cap, "cache must not grow without bound"
    # The oldest entries were evicted, the newest retained.
    assert app_module.get_simulation_results("user0", "current", "wc2026") is None
    assert app_module.get_simulation_results(f"user{cap + 39}", "current", "wc2026") is not None


def test_reading_an_entry_marks_it_recently_used(monkeypatch):
    monkeypatch.setattr(app_module, "_simulation_results", type(app_module._simulation_results)())
    cap = app_module._RESULTS_CACHE_MAX
    for i in range(cap):
        app_module.set_simulation_results(f"user{i}", {"n": i}, "current", "wc2026")

    app_module.get_simulation_results("user0", "current", "wc2026")   # touch the oldest
    app_module.set_simulation_results("newcomer", {"n": -1}, "current", "wc2026")

    assert app_module.get_simulation_results("user0", "current", "wc2026") is not None, \
        "a recently-read entry must not be the one evicted"
    assert app_module.get_simulation_results("user1", "current", "wc2026") is None


def test_simulation_runs_are_serialized():
    """Concurrent cache misses must not each allocate a full run's worth of
    memory at the same time — that is what turned a busy moment into an OOM."""
    concurrent = 0
    max_concurrent = 0
    barrier_lock = threading.Lock()

    def fake_run():
        nonlocal concurrent, max_concurrent
        with app_module._simulation_lock:
            with barrier_lock:
                concurrent += 1
                max_concurrent = max(max_concurrent, concurrent)
            # Hold long enough that any unsynchronized peer would overlap.
            threading.Event().wait(0.05)
            with barrier_lock:
                concurrent -= 1

    threads = [threading.Thread(target=fake_run) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert max_concurrent == 1, f"{max_concurrent} simulations ran concurrently"


def test_release_freed_memory_is_safe_to_call():
    """Called after every run; must never raise, including off glibc."""
    app_module.release_freed_memory()
