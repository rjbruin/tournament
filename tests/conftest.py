"""Shared pytest fixtures and helpers for the tournament test suite.

The tests use the real tournament data (``data/wc2026.json``) so groups,
schedule and Elo ratings match production, but they construct their *own*
scenarios (group states) rather than touching the on-disk runtime data.
"""

import json
import os

import numpy as np
import pytest

from app.simulation.engine import SimulationEngine, GROUP_MATCH_PAIRS

ROOT = os.path.dirname(os.path.dirname(__file__))


@pytest.fixture(scope="session")
def engine():
    """A SimulationEngine built straight from the real tournament data, with no
    app/migration/scenario side effects."""
    with open(os.path.join(ROOT, "data", "wc2026.json")) as f:
        data = json.load(f)
    return SimulationEngine(data)


@pytest.fixture(autouse=True)
def _seed_rng():
    """Make every test deterministic. The engine draws from the global NumPy
    RNG, so seed it before each test."""
    np.random.seed(12345)


# ---------------------------------------------------------------------------
# Helpers for building scenarios from the real schedule
# ---------------------------------------------------------------------------

def group_teams(engine, group_name):
    gi = engine.group_pos[group_name]
    return list(engine.groups[gi]["teams"])


def scheduled_group_matches(engine, group_name):
    """The group's 6 matches as ``(home, away)`` pairs in real schedule order."""
    from app.web.view_helpers import utc_sort_key
    gi = engine.group_pos[group_name]
    teams = engine.groups[gi]["teams"]
    sched = engine.data["schedule"]["groups"][group_name]
    pairs = []
    for (i, j), sm in zip(GROUP_MATCH_PAIRS, sched):
        pairs.append({"home": teams[i], "away": teams[j], "sort_key": utc_sort_key(sm)})
    pairs.sort(key=lambda p: p["sort_key"])
    return pairs


def play_through(engine, group_name, n_first, score=(1, 0)):
    """Build an ``actuals`` dict where the first ``n_first`` (schedule-ordered)
    matches of ``group_name`` are played with ``score``; the rest are open."""
    hg, ag = score
    played = scheduled_group_matches(engine, group_name)[:n_first]
    entries = [{"home": p["home"], "away": p["away"], "home_goals": hg, "away_goals": ag}
               for p in played]
    return {"group_results": {group_name: entries}, "knockout_results": {}, "live_matches": []}
