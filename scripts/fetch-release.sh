#!/usr/bin/env bash
# Download a release tarball locally (where you're authenticated to GitHub)
# so it can be copied to a server for use with `deploy.sh ... --tarball`.
#
# Usage:
#   scripts/fetch-release.sh <version> [output-dir]
#
# Example:
#   scripts/fetch-release.sh v0.1.0
#   scp tournament-v0.1.0.tar.gz myserver:/tmp/
#   ssh myserver REPO=rjbruin/tournament /opt/tournament/scripts/deploy.sh v0.1.0 /opt/tournament --tarball /tmp/tournament-v0.1.0.tar.gz

set -euo pipefail

VERSION="${1:-}"
if [[ -z "$VERSION" ]]; then
  echo "Usage: $0 <version> [output-dir]" >&2
  exit 1
fi
[[ "$VERSION" != v* ]] && VERSION="v${VERSION}"

REPO="${REPO:-rjbruin/tournament}"
OUT_DIR="${2:-.}"
OUT_FILE="${OUT_DIR}/tournament-${VERSION}.tar.gz"

mkdir -p "$OUT_DIR"

if command -v gh >/dev/null 2>&1; then
  echo "==> Fetching ${REPO}@${VERSION} via gh"
  gh release download "$VERSION" -R "$REPO" --archive=tar.gz -O "$OUT_FILE" --clobber
else
  echo "==> Fetching ${REPO}@${VERSION} via curl"
  curl -fsSL "https://github.com/${REPO}/archive/refs/tags/${VERSION}.tar.gz" -o "$OUT_FILE"
fi

echo "==> Saved ${OUT_FILE}"
echo "Copy it to the server and run:"
echo "  deploy.sh ${VERSION} /opt/tournament --tarball /path/to/$(basename "$OUT_FILE")"
