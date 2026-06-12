"""Add the v0.6.0 "live match" fields to on-disk actuals/scenario files.

v0.6.0 introduces:
  - ``actuals["live_matches"]``: a list of ``{"home", "away"}`` pairs for
    group matches that are in progress (live scoreline, not yet final).
  - ``scenario["featured_match"]``: optional ``{"group", "home", "away"}``
    recorded on the hypothetical scenario, identifying which match was
    edited so the homepage can feature it.

Both fields are already filled in with defaults at read-time (see
``data_store.load_actuals`` / ``data_store.load_scenario``), so this
migration is not required for correctness — but it brings existing on-disk
files up to the current shape so they're self-describing and consistent
for any future code that reads them directly.
"""

import json
import os

MIGRATION_ID = "m0001_live_matches_and_featured_match"
DESCRIPTION = 'Add "live_matches" to actuals and "featured_match" to scenarios'


def _add_defaults_to_actuals(actuals: dict) -> bool:
    changed = False
    if "group_results" not in actuals:
        actuals["group_results"] = {}
        changed = True
    if "knockout_results" not in actuals:
        actuals["knockout_results"] = {}
        changed = True
    if "live_matches" not in actuals:
        actuals["live_matches"] = []
        changed = True
    return changed


def run(data_dir: str) -> None:
    # data/actuals.json
    actuals_path = os.path.join(data_dir, "actuals.json")
    if os.path.exists(actuals_path):
        with open(actuals_path) as f:
            actuals = json.load(f)
        if _add_defaults_to_actuals(actuals):
            with open(actuals_path, "w") as f:
                json.dump(actuals, f, indent=2)

    # data/scenarios/*.json
    scenarios_dir = os.path.join(data_dir, "scenarios")
    if os.path.isdir(scenarios_dir):
        for fname in os.listdir(scenarios_dir):
            if not fname.endswith(".json"):
                continue
            path = os.path.join(scenarios_dir, fname)
            with open(path) as f:
                scenario = json.load(f)
            changed = False
            if "actuals" not in scenario or not isinstance(scenario["actuals"], dict):
                scenario["actuals"] = {}
                changed = True
            if _add_defaults_to_actuals(scenario["actuals"]):
                changed = True
            if "featured_match" not in scenario:
                scenario["featured_match"] = None
                changed = True
            if changed:
                with open(path, "w") as f:
                    json.dump(scenario, f, indent=2)
