#!/usr/bin/env bash
# Does the running OneShelf serve the interface built from a given commit?
#
#   scripts/agent/deployed-revision.sh [commit] [url]
#
# The app does not report its commit, so this builds the frontend of <commit> (default: origin/main) in a
# throwaway worktree and compares Vite's content-hashed entry assets with the ones the live index.html
# names. Equal hashes mean the deployed interface was built from that frontend source.
# Exit 0 = MATCH, 1 = MISMATCH (deployment not updated, or built from another commit), 2 = could not check.
# A backend-only commit leaves the frontend hashes unchanged, so a MATCH there only proves the frontend;
# confirm backend changes through the behaviour they change (see docs/agent-browser-verification.md).

set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
COMMIT="${1:-origin/main}"
URL="${2:-${ONESHELF_URL:-http://192.168.8.32:8420/}}"
CACHE="${XDG_CACHE_HOME:-$HOME/.cache}/oneshelf-agent"

git -C "$ROOT" fetch -q origin 2>/dev/null || echo "warning: fetch failed, using local refs" >&2
SHA="$(git -C "$ROOT" rev-parse --verify "$COMMIT^{commit}")" || { echo "unknown commit: $COMMIT" >&2; exit 2; }

live="$(curl -fsS -m 15 "$URL" | grep -oE '/assets/index-[A-Za-z0-9_-]+\.(js|css)' | sort -u)" \
  || { echo "BLOCKED: cannot fetch $URL" >&2; exit 2; }
[ -n "$live" ] || { echo "BLOCKED: no entry assets found in $URL" >&2; exit 2; }

mkdir -p "$CACHE"
expected_file="$CACHE/assets-$SHA.txt"
if [ ! -s "$expected_file" ]; then
  tree="$(mktemp -d)"
  trap 'git -C "$ROOT" worktree remove --force "$tree" >/dev/null 2>&1 || rm -rf "$tree"' EXIT
  git -C "$ROOT" worktree add -q --detach "$tree" "$SHA"
  (cd "$tree/frontend" && npm ci --no-audit --no-fund --silent >/dev/null && npm run -s build >/dev/null 2>&1) \
    || { echo "BLOCKED: frontend build of $SHA failed" >&2; exit 2; }
  grep -oE '/assets/index-[A-Za-z0-9_-]+\.(js|css)' "$tree/frontend/dist/index.html" | sort -u > "$expected_file"
fi

echo "commit:   $SHA"
echo "expected: $(tr '\n' ' ' < "$expected_file")"
echo "live:     $(echo "$live" | tr '\n' ' ')"
if [ "$live" = "$(cat "$expected_file")" ]; then
  echo "MATCH: $URL serves the interface built from $SHA"
else
  echo "MISMATCH: $URL is not serving the interface of $SHA — BLOCKED — DEPLOYMENT NOT UPDATED"
  exit 1
fi
