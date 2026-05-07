#!/bin/sh
# Rewrite the asset cache-buster in docs/index.html from the current
# git short SHA + today's date. Run this BEFORE commits that change
# docs/assets/* so users on stale CDN/browser caches get the new
# bundle on their next visit.
#
# Manual run:
#   ./scripts/stamp-cache-buster.sh
#
# Or via npm:
#   npm run stamp
#
# The script is idempotent — re-running on a tree at the same SHA
# is a no-op. Replaces v19.51 manual three-place-edit dance.
set -e

REPO_ROOT="$(git rev-parse --show-toplevel)"
INDEX="$REPO_ROOT/docs/index.html"

if [ ! -f "$INDEX" ]; then
  echo "[stamp] $INDEX not found." >&2
  exit 1
fi

DATE="$(date +%Y%m%d)"
SHA="$(git rev-parse --short=7 HEAD)"
NEW_TAG="${DATE}-${SHA}"

# Match the existing scheme: `?v=<anything>` on tokens.css, app.css, app.js.
# Compatible with any prior format ("v=20260507-v19-51d").
sed_inplace() {
  if sed --version >/dev/null 2>&1; then
    sed -i "$@"
  else
    sed -i '' "$@"
  fi
}
sed_inplace -E "s|(assets/(tokens\.css\|app\.css\|app\.js))\?v=[^\"]*|\1?v=${NEW_TAG}|g" "$INDEX"

if git -C "$REPO_ROOT" diff --quiet -- docs/index.html; then
  echo "[stamp] cache-buster already up to date (${NEW_TAG})"
else
  echo "[stamp] docs/index.html cache-buster → ${NEW_TAG}"
  echo "[stamp] git add docs/index.html && commit when ready."
fi
