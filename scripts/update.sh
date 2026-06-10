#!/usr/bin/env bash
# Update an existing tournament install on the VPS to the latest (or a
# specific) release, and restart the service.
#
# This is a thin wrapper around deploy.sh for the common "update in place"
# case: it figures out the latest release tag from GitHub (or uses the one
# you pass), then deploys it into the same install directory used before.
#
# Usage:
#   scripts/update.sh [version] [install-dir]
#
# Example (run on the VPS, from anywhere):
#   /opt/tournament/current/scripts/update.sh
#   /opt/tournament/current/scripts/update.sh v0.3.0
#   /opt/tournament/current/scripts/update.sh v0.3.0 /opt/tournament
#
# Environment variables:
#   REPO          GitHub "owner/repo" slug (default: rjbruin/tournament)
#   SERVICE_NAME  systemd service to restart after deploy (default: tournament)

set -euo pipefail

REPO="${REPO:-rjbruin/tournament}"
SERVICE_NAME="${SERVICE_NAME:-tournament}"

VERSION="${1:-}"
INSTALL_DIR="${2:-/opt/tournament}"

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

if [[ -z "$VERSION" ]]; then
  echo "==> No version given, looking up latest release of ${REPO}"
  if command -v gh >/dev/null 2>&1; then
    VERSION="$(gh release view -R "$REPO" --json tagName -q .tagName)"
  else
    VERSION="$(curl -fsSL "https://api.github.com/repos/${REPO}/releases/latest" | grep -o '"tag_name": *"[^"]*"' | head -1 | cut -d'"' -f4)"
  fi
  if [[ -z "$VERSION" ]]; then
    echo "Error: could not determine latest release version." >&2
    exit 1
  fi
  echo "==> Latest release is ${VERSION}"
fi

echo "==> Updating ${INSTALL_DIR} to ${VERSION}"
SERVICE_NAME="$SERVICE_NAME" "${REPO_ROOT}/scripts/deploy.sh" "$VERSION" "$INSTALL_DIR"

echo "==> Update complete: ${VERSION}"
