#!/usr/bin/env bash
# Does the running OneShelf serve the interface built from a given commit?
#
#   scripts/agent/deployed-revision.sh [commit] [url]
#
# The app does not report its commit, so this builds the frontend of <commit> (default: origin/main) in a
# throwaway worktree and compares Vite's content-hashed entry assets with the ones the live index.html
# names. Equal hashes mean the deployed interface was built from that frontend source.
# Exit 0 = MATCH, 1 = MISMATCH (live assets differ from this build), 2 = could not check.
# Deployment is user-managed (AGENTS.md): run this only after the user confirms their manual update. A MATCH
# is evidence for the frontend assets only, not the running image's Git revision; a MISMATCH is a reason to
# compare build conditions and the user's host evidence, not by itself proof that the server is stale.

set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
COMMIT="${1:-origin/main}"
URL="${2:-${ONESHELF_URL:-http://192.168.8.32:8420/}}"
CACHE="${XDG_CACHE_HOME:-$HOME/.cache}/oneshelf-agent"

git -C "$ROOT" fetch -q origin 2>/dev/null || echo "warning: fetch failed, using local refs" >&2
SHA="$(git -C "$ROOT" rev-parse --verify "$COMMIT^{commit}")" || { echo "unknown commit: $COMMIT" >&2; exit 2; }

live="$(curl -fsS -m 15 "$URL" | grep -oE '/assets/index-[A-Za-z0-9_-]+\.(js|css)' | sort -u)" \
  || { echo "UNCHECKED: cannot fetch $URL" >&2; exit 2; }
[ -n "$live" ] || { echo "UNCHECKED: no entry assets found in $URL" >&2; exit 2; }

mkdir -p "$CACHE"
expected_file="$CACHE/assets-$SHA.txt"
if [ ! -s "$expected_file" ]; then
  tree="$(mktemp -d)"
  trap 'git -C "$ROOT" worktree remove --force "$tree" >/dev/null 2>&1 || rm -rf "$tree"' EXIT
  git -C "$ROOT" worktree add -q --detach "$tree" "$SHA"
  (cd "$tree/frontend" && npm ci --no-audit --no-fund --silent >/dev/null && npm run -s build >/dev/null 2>&1) \
    || { echo "UNCHECKED: frontend build of $SHA failed" >&2; exit 2; }
  grep -oE '/assets/index-[A-Za-z0-9_-]+\.(js|css)' "$tree/frontend/dist/index.html" | sort -u > "$expected_file"
fi

echo "commit:   $SHA"
echo "expected: $(tr '\n' ' ' < "$expected_file")"
echo "live:     $(echo "$live" | tr '\n' ' ')"
if [ "$live" = "$(cat "$expected_file")" ]; then
  echo "MATCH: $URL serves frontend assets identical to a build of $SHA (frontend evidence only)"
else
  echo "MISMATCH: $URL serves different frontend assets than a build of $SHA."
  echo "  Before the user confirms their manual update this is expected (READY — AWAITING USER-MANAGED DEPLOYMENT)."
  echo "  After it, compare build conditions and the user's host evidence; it does not by itself prove a stale server."
  exit 1
fi
