"""One-time purge of all on-disk scenario files.

Earlier versions accumulated a mix of scenario files: auto-generated
"after match N" snapshots, ad-hoc user "what if" scenarios, and the
single-slot hypothetical/manual scenarios. The scenario model is now a
clean, auto-maintained canonical set — "before the first match" (match-0)
plus one snapshot after each played match (match-N) — rebuilt by
``data_store.update_scenarios()`` (called on startup and whenever results
change).

To start from a clean slate, this migration deletes every file under
``data/scenarios/`` exactly once. The canonical set is then regenerated
automatically; any stale user/hypothetical/manual scenarios are discarded.

Idempotent: running it again simply finds nothing to delete. It only runs
once in practice because it's recorded in ``data/.migrations.json``.
"""

import os

MIGRATION_ID = "m0002_purge_scenarios"
DESCRIPTION = "One-time purge of all scenario files; canonical set is rebuilt automatically"


def run(data_dir: str) -> None:
    scenarios_dir = os.path.join(data_dir, "scenarios")
    if not os.path.isdir(scenarios_dir):
        return
    for fname in os.listdir(scenarios_dir):
        if fname.endswith(".json"):
            os.remove(os.path.join(scenarios_dir, fname))
