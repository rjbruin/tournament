#!/usr/bin/env bash
# Deploy a tagged release of the tournament app to a server.
#
# Downloads a release tarball from GitHub (e.g. v0.1.0), unpacks it into a
# versioned directory, sets up/reuses a Python virtualenv, installs
# dependencies, symlinks persistent data, and restarts the service.
#
# Usage:
#   scripts/deploy.sh <version> [install-dir]
#
# Example:
#   scripts/deploy.sh v0.1.0
#   scripts/deploy.sh v0.1.0 /opt/tournament
#
# Environment variables:
#   REPO              GitHub "owner/repo" slug (default: shown below)
#   SERVICE_NAME      systemd service to restart after deploy (optional)
#   PORT              port the app should run on (default: 5001)

set -euo pipefail

VERSION="${1:-}"
if [[ -z "$VERSION" ]]; then
  echo "Usage: $0 <version> [install-dir]" >&2
  exit 1
fi
# Allow both "0.1.0" and "v0.1.0".
[[ "$VERSION" != v* ]] && VERSION="v${VERSION}"

REPO="${REPO:-robert-jan/tournament}"
INSTALL_DIR="${2:-/opt/tournament}"
PORT="${PORT:-5001}"
SERVICE_NAME="${SERVICE_NAME:-}"

RELEASES_DIR="${INSTALL_DIR}/releases"
RELEASE_DIR="${RELEASES_DIR}/${VERSION}"
SHARED_DIR="${INSTALL_DIR}/shared"
CURRENT_LINK="${INSTALL_DIR}/current"

TARBALL_URL="https://github.com/${REPO}/archive/refs/tags/${VERSION}.tar.gz"

echo "==> Deploying ${REPO} ${VERSION} to ${INSTALL_DIR}"

mkdir -p "$RELEASES_DIR" "$SHARED_DIR/data"

if [[ -d "$RELEASE_DIR" ]]; then
  echo "==> ${RELEASE_DIR} already exists, removing it for a clean deploy"
  rm -rf "$RELEASE_DIR"
fi
mkdir -p "$RELEASE_DIR"

echo "==> Downloading ${TARBALL_URL}"
curl -fsSL "$TARBALL_URL" -o "/tmp/tournament-${VERSION}.tar.gz"

echo "==> Extracting"
tar -xzf "/tmp/tournament-${VERSION}.tar.gz" -C "$RELEASE_DIR" --strip-components=1
rm -f "/tmp/tournament-${VERSION}.tar.gz"

echo "==> Setting up virtualenv"
python3 -m venv "${RELEASE_DIR}/.venv"
"${RELEASE_DIR}/.venv/bin/pip" install --upgrade pip
"${RELEASE_DIR}/.venv/bin/pip" install -r "${RELEASE_DIR}/requirements.txt"

# Persist mutable data (snapshots, settings, actuals) across releases by
# storing it in a shared directory and symlinking it into each release.
echo "==> Linking persistent data directory"
for f in snapshots.json settings.json actuals.json; do
  src="${SHARED_DIR}/data/${f}"
  dst="${RELEASE_DIR}/data/${f}"
  if [[ -f "$dst" && ! -f "$src" ]]; then
    # Seed shared storage from the bundled defaults on first deploy.
    cp "$dst" "$src"
  fi
  rm -f "$dst"
  ln -s "$src" "$dst"
done

echo "==> Linking ${CURRENT_LINK} -> ${RELEASE_DIR}"
ln -sfn "$RELEASE_DIR" "$CURRENT_LINK"

if [[ -n "$SERVICE_NAME" ]]; then
  echo "==> Restarting systemd service ${SERVICE_NAME}"
  sudo systemctl restart "$SERVICE_NAME"
  sudo systemctl status "$SERVICE_NAME" --no-pager -l | head -n 10
else
  cat <<EOF

==> Deployed ${VERSION} to ${RELEASE_DIR} (current -> ${CURRENT_LINK})

No SERVICE_NAME set, so the app was not (re)started automatically.
To run it manually:

  cd ${CURRENT_LINK}
  .venv/bin/python run.py   # listens on port ${PORT} by default

To run it under systemd, create /etc/systemd/system/tournament.service with:

  [Unit]
  Description=WC Tournament Simulator
  After=network.target

  [Service]
  WorkingDirectory=${CURRENT_LINK}
  ExecStart=${CURRENT_LINK}/.venv/bin/python run.py
  Restart=on-failure
  User=www-data

  [Install]
  WantedBy=multi-user.target

then re-run with SERVICE_NAME=tournament.
EOF
fi

# Prune old releases, keeping the 5 most recent.
echo "==> Pruning old releases (keeping 5 most recent)"
ls -1dt "${RELEASES_DIR}"/*/ 2>/dev/null | tail -n +6 | xargs -r rm -rf

echo "==> Done"
