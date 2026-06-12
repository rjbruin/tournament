"""Lightweight, file-based data migration framework.

The app's persistent state is a tree of JSON files under ``data/`` (see
``app/data_store.py``). Most schema additions are handled gracefully at
read-time via ``dict.setdefault(...)``, but it's still useful to migrate
on-disk files to the current shape:

  - older data directories (e.g. restored from a backup, or upgraded
    in-place on a VPS) get their files rewritten to include new fields,
    so every code path (including ones that don't bother with
    ``setdefault``) sees a consistent shape;
  - it gives us a single, auditable place to put one-off data fixes when
    a release changes the on-disk schema.

How it works
-------------
Each migration lives in ``app/migrations/`` as a module named
``mNNNN_short_description.py`` and exports:

  - ``MIGRATION_ID`` (str): stable identifier, conventionally the filename
    without ``.py`` (e.g. ``"0001_live_matches_and_featured_match"``).
  - ``DESCRIPTION`` (str): one-line human-readable summary.
  - ``run(data_dir: str) -> None``: apply the migration. Must be
    idempotent — it may be run again (e.g. if the state file is lost)
    without causing harm.

Migrations are registered in ``REGISTRY`` below, in the order they should
run. ``run_pending_migrations()`` runs every migration not yet recorded in
``data/.migrations.json``, in order, and records each as it completes.

This is invoked automatically on app startup (see ``app/__init__.py``), and
can also be run manually via ``python -m app.migrations`` or
``scripts/migrate.py``.
"""

import importlib
import json
import os

DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "data")
STATE_PATH = os.path.join(DATA_DIR, ".migrations.json")

# Ordered list of migration module names (without the .py extension), in
# the order they must be applied. Append new migrations to the end.
REGISTRY = [
    "m0001_live_matches_and_featured_match",
]


def _load_state(data_dir: str) -> dict:
    path = os.path.join(data_dir, ".migrations.json")
    if not os.path.exists(path):
        return {"applied": []}
    with open(path) as f:
        return json.load(f)


def _save_state(data_dir: str, state: dict) -> None:
    path = os.path.join(data_dir, ".migrations.json")
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        json.dump(state, f, indent=2)
    os.replace(tmp, path)


def pending_migrations(data_dir: str | None = None) -> list[str]:
    """Return the ids of migrations that have not yet been applied."""
    data_dir = data_dir or DATA_DIR
    state = _load_state(data_dir)
    applied = set(state.get("applied", []))
    return [m for m in REGISTRY if m not in applied]


def run_pending_migrations(data_dir: str | None = None, verbose: bool = True) -> list[str]:
    """Run any not-yet-applied migrations, in registry order.

    Returns the list of migration ids that were run. Safe to call on every
    app startup: when nothing is pending, it's a fast no-op (one small JSON
    file read).
    """
    data_dir = data_dir or DATA_DIR
    state = _load_state(data_dir)
    applied = set(state.get("applied", []))
    ran = []
    for mod_name in REGISTRY:
        if mod_name in applied:
            continue
        module = importlib.import_module(f"app.migrations.{mod_name}")
        if verbose:
            print(f"[migrations] applying {module.MIGRATION_ID}: {module.DESCRIPTION}")
        module.run(data_dir)
        state.setdefault("applied", []).append(module.MIGRATION_ID)
        _save_state(data_dir, state)
        ran.append(module.MIGRATION_ID)
    if verbose and not ran:
        print("[migrations] nothing to do")
    return ran
