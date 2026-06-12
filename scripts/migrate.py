#!/usr/bin/env python3
"""Run any pending data migrations (see app/migrations/).

This happens automatically on app startup (create_app() calls
run_pending_migrations()), but it can also be run standalone — e.g. as a
pre-flight step in a deploy script, or to migrate a data directory before
starting the app.

Usage:
    python3 scripts/migrate.py [data_dir]
"""

import os
import sys

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO_ROOT)

from app.migrations import run_pending_migrations, pending_migrations  # noqa: E402


def main():
    data_dir = sys.argv[1] if len(sys.argv) > 1 else None
    pending = pending_migrations(data_dir)
    if not pending:
        print("Up to date, nothing to migrate.")
        return
    print(f"Pending migrations: {', '.join(pending)}")
    run_pending_migrations(data_dir)
    print("Done.")


if __name__ == "__main__":
    main()
