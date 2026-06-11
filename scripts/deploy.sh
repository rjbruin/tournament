#!/usr/bin/env bash
# Deploy a tagged release of the tournament app to a server.
#
# By default, downloads a release tarball from GitHub (e.g. v0.1.0) and
# unpacks it into a versioned directory. If GitHub isn't reachable from the
# server (e.g. private repo with no auth, or no internet access), pass a
# local tarball file instead with --tarball <path> (e.g. one downloaded via
# `gh release download` or `git archive` on a machine that does have access).
#
# Then sets up/reuses a Python virtualenv, installs dependencies, symlinks
# persistent data, and restarts the service.
#
# Usage:
#   scripts/deploy.sh <version> [install-dir] [--tarball <path>]
#
# Example:
#   scripts/deploy.sh v0.1.0
#   scripts/deploy.sh v0.1.0 /opt/tournament
#   scripts/deploy.sh v0.1.0 /opt/tournament --tarball /tmp/tournament-v0.1.0.tar.gz
#
# Environment variables:
#   REPO              GitHub "owner/repo" slug (default: shown below)
#   SERVICE_NAME      systemd service to restart after deploy (optional)
#   SERVICE_USER      user the service runs as; the data directory is
#                      chowned to this user so it can write
#                      settings/users/snapshots (default: www-data)
#   PORT              port the app should run on (default: 5001)

set -euo pipefail

VERSION="${1:-}"
if [[ -z "$VERSION" ]]; then
  echo "Usage: $0 <version> [install-dir] [--tarball <path>]" >&2
  exit 1
fi
# Allow both "0.1.0" and "v0.1.0".
[[ "$VERSION" != v* ]] && VERSION="v${VERSION}"

INSTALL_DIR="/opt/tournament"
TARBALL_PATH=""

# Parse remaining args: an optional positional install-dir, and an optional
# --tarball <path> flag (in either order).
shift || true
while [[ $# -gt 0 ]]; do
  case "$1" in
    --tarball)
      TARBALL_PATH="${2:-}"
      shift 2
      ;;
    *)
      INSTALL_DIR="$1"
      shift
      ;;
  esac
done

REPO="${REPO:-rjbruin/tournament}"
PORT="${PORT:-5001}"
SERVICE_NAME="${SERVICE_NAME:-}"
SERVICE_USER="${SERVICE_USER:-www-data}"

RELEASES_DIR="${INSTALL_DIR}/releases"
RELEASE_DIR="${RELEASES_DIR}/${VERSION}"
SHARED_DIR="${INSTALL_DIR}/shared"
CURRENT_LINK="${INSTALL_DIR}/current"

echo "==> Deploying ${REPO} ${VERSION} to ${INSTALL_DIR}"

mkdir -p "$RELEASES_DIR" "$SHARED_DIR/data"

if [[ -d "$RELEASE_DIR" ]]; then
  echo "==> ${RELEASE_DIR} already exists, removing it for a clean deploy"
  rm -rf "$RELEASE_DIR"
fi
mkdir -p "$RELEASE_DIR"

if [[ -n "$TARBALL_PATH" ]]; then
  if [[ ! -f "$TARBALL_PATH" ]]; then
    echo "Error: tarball not found at ${TARBALL_PATH}" >&2
    exit 1
  fi
  echo "==> Using local tarball ${TARBALL_PATH}"
  TARBALL_FILE="$TARBALL_PATH"
else
  TARBALL_URL="https://github.com/${REPO}/archive/refs/tags/${VERSION}.tar.gz"
  TARBALL_FILE="/tmp/tournament-${VERSION}.tar.gz"
  echo "==> Downloading ${TARBALL_URL}"
  curl -fsSL "$TARBALL_URL" -o "$TARBALL_FILE"
fi

echo "==> Extracting"
tar -xzf "$TARBALL_FILE" -C "$RELEASE_DIR" --strip-components=1
[[ -z "$TARBALL_PATH" ]] && rm -f "$TARBALL_FILE"

echo "==> Setting up virtualenv"
python3 -m venv "${RELEASE_DIR}/.venv"
"${RELEASE_DIR}/.venv/bin/pip" install --upgrade pip
"${RELEASE_DIR}/.venv/bin/pip" install -r "${RELEASE_DIR}/requirements.txt"

# Persist mutable data (snapshots, settings, actuals) across releases by
# storing it in a shared directory and symlinking it into each release.
echo "==> Linking persistent data directory"
for f in settings.json actuals.json users.json; do
  src="${SHARED_DIR}/data/${f}"
  dst="${RELEASE_DIR}/data/${f}"
  if [[ -f "$dst" && ! -f "$src" ]]; then
    # Seed shared storage from the bundled defaults on first deploy.
    cp "$dst" "$src"
  fi
  rm -f "$dst"
  ln -s "$src" "$dst"
done

# Per-account snapshot directories (data/users/<username>/snapshots.json).
src_dir="${SHARED_DIR}/data/users"
dst_dir="${RELEASE_DIR}/data/users"
mkdir -p "$src_dir"
rm -rf "$dst_dir"
ln -s "$src_dir" "$dst_dir"

# Saved "what if" scenarios (data/scenarios/<id>.json).
src_dir="${SHARED_DIR}/data/scenarios"
dst_dir="${RELEASE_DIR}/data/scenarios"
mkdir -p "$src_dir"
rm -rf "$dst_dir"
ln -s "$src_dir" "$dst_dir"

# The service user (e.g. www-data) needs to write to the shared data
# directory and to the release's data/ directory itself (which holds the
# symlinks — atomic writes create a temp file alongside the symlink before
# renaming over it).
echo "==> Setting data ownership to ${SERVICE_USER}"
sudo chown -R "${SERVICE_USER}:${SERVICE_USER}" "${SHARED_DIR}/data" "${RELEASE_DIR}/data"

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
