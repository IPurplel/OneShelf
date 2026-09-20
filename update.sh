#!/usr/bin/env bash
# OneShelf: update in place.
#
#   ./update.sh
#
# Your library, your settings and your .env are left alone. If anything about this checkout makes an
# automatic update unsafe, this stops and explains rather than guessing.

set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=deploy/lib.sh
. "$ROOT/deploy/lib.sh"
require_repo_root "$ROOT"

RUNTIME="$(detect_runtime)"
COMPOSE="$(detect_compose "$RUNTIME")"
[ -f "$ROOT/.env" ] || die "no .env here — run ./install.sh first"

step "Checking this checkout is safe to update automatically"
if [ -d "$ROOT/.git" ] && command -v git >/dev/null 2>&1; then
  if [ -n "$(git -C "$ROOT" status --porcelain --untracked-files=no 2>/dev/null)" ]; then
    die "you have local changes to tracked files.
  An automatic update would have to merge them, and this script will not do that for you.
  Either commit or stash them first:
      git -C \"$ROOT\" stash
  then run ./update.sh again. Your library and .env are untouched either way."
  fi
  if ! git -C "$ROOT" rev-parse --abbrev-ref --symbolic-full-name '@{upstream}' >/dev/null 2>&1; then
    warn "this branch has no upstream, so nothing will be fetched; rebuilding what is here"
  else
    step "Fetching updates"
    git -C "$ROOT" pull --ff-only || die "the update is not a fast-forward.
  Your branch and the upstream have diverged, which needs a decision this script must not make for you.
  Nothing has been changed. Your library and .env are untouched."
    ok "updated to $(git -C "$ROOT" log --oneline -1)"
  fi
else
  warn "not a git checkout; rebuilding the image from the files that are here"
fi

step "Rebuilding the image"
compose_cmd build

step "Restarting OneShelf"
# Migrations and recovery run on startup, the same way they always do — there is no separate path.
compose_cmd up -d

URL="$(oneshelf_url "$ROOT")"
step "Waiting for OneShelf to be ready"
READY=""; READY_STATUS=0
READY="$(wait_for_ready "$URL")" || READY_STATUS=$?
if [ "$READY_STATUS" -eq 0 ]; then
  ok "ready — $(printf '%s' "$READY" | tr -d '\n' | cut -c1-120)"
elif [ "$READY_STATUS" -eq 3 ]; then
  warn "skipping the readiness check; open $URL yourself to confirm"
else
  diagnose "$URL"
  say ""
  say "Your data has not been touched. To go back to the previous version:"
  say "    git -C \"$ROOT\" log --oneline -5      # find the commit you were on"
  say "    git -C \"$ROOT\" checkout <commit>"
  say "    ./install.sh"
  exit 1
fi

probe "$URL/api/health" >/dev/null || { diagnose "$URL"; exit 1; }
ok "health check passed"
say ""
say "${_b}OneShelf is up to date and running at ${URL}${_r}"
