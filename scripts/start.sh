#!/usr/bin/env bash
# Start the tournament app with the configuration used on the VPS, where it
# runs alongside other services behind a reverse proxy under /tournament.
#
# Intended to be used as the ExecStart command of a systemd service (see
# below), or run directly for a quick manual start.
#
# Usage:
#   scripts/start.sh
#
# Environment variables (all have the defaults below baked in; override by
# exporting before calling, or editing this file):
#   PORT          5050
#   HOST          0.0.0.0
#   URL_PREFIX    /tournament
#   SERVICE_NAME  tournament

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

export PORT="${PORT:-5050}"
export HOST="${HOST:-0.0.0.0}"
export URL_PREFIX="${URL_PREFIX:-/tournament}"
export SERVICE_NAME="${SERVICE_NAME:-tournament}"
export FLASK_DEBUG="${FLASK_DEBUG:-0}"

exec .venv/bin/python run.py
