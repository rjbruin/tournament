#!/usr/bin/env bash
# Cut a new release: bumps VERSION, tags the commit, pushes the tag, and
# creates a GitHub release (if `gh` is available and authenticated).
#
# Usage:
#   scripts/release.sh <version> [release notes file]
#
# Example:
#   scripts/release.sh 0.2.0
#   scripts/release.sh 0.2.0 CHANGELOG.md

set -euo pipefail

VERSION="${1:-}"
if [[ -z "$VERSION" ]]; then
  echo "Usage: $0 <version> [notes-file]" >&2
  exit 1
fi

# Strip an optional leading "v" so VERSION file and tag stay consistent.
VERSION="${VERSION#v}"
TAG="v${VERSION}"

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

if [[ -n "$(git status --porcelain)" ]]; then
  echo "Error: working tree is not clean. Commit or stash changes first." >&2
  exit 1
fi

echo "$VERSION" > VERSION
git add VERSION
git commit -m "Release ${TAG}"

git tag -a "$TAG" -m "Release ${TAG}"

echo "Pushing branch and tag..."
git push origin HEAD
git push origin "$TAG"

if command -v gh >/dev/null 2>&1; then
  NOTES_ARGS=()
  if [[ -n "${2:-}" && -f "${2:-}" ]]; then
    NOTES_ARGS=(--notes-file "$2")
  else
    NOTES_ARGS=(--generate-notes)
  fi
  echo "Creating GitHub release ${TAG}..."
  gh release create "$TAG" "${NOTES_ARGS[@]}" --title "$TAG"
else
  echo "gh CLI not found; skipping GitHub release creation."
  echo "Tag ${TAG} has been pushed. Create the release manually on GitHub."
fi

echo "Done: ${TAG}"
