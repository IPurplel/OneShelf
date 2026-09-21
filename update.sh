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

require_probe
load_configuration

step "Checking this checkout is safe to update automatically"
if [ -e "$ROOT/.git" ]; then
  command -v git >/dev/null 2>&1 || die "git is required to update this checkout"
  if [ -n "$(git -C "$ROOT" status --porcelain --untracked-files=no 2>/dev/null)" ]; then
    die "you have local changes to tracked files.
  An automatic update would have to merge them, and this script will not do that for you.
  Either commit or stash them first:
      git -C \"$ROOT\" stash
  then run ./update.sh again. Your library and .env are untouched either way."
  fi
  [ "$(git -C "$ROOT" symbolic-ref --short -q HEAD)" = main ] || die "automatic updates require branch main (not detached HEAD)"
  for state in MERGE_HEAD CHERRY_PICK_HEAD REVERT_HEAD rebase-merge rebase-apply; do
    [ ! -e "$(git -C "$ROOT" rev-parse --path-format=absolute --git-path "$state")" ] || die "finish the in-progress Git operation before updating"
  done
  if ! git -C "$ROOT" rev-parse --abbrev-ref --symbolic-full-name '@{upstream}' >/dev/null 2>&1; then
    warn "this branch has no upstream, so nothing will be fetched; rebuilding what is here"
  else
    if [ "${ONESHELF_UPDATE_FETCHED:-0}" != 1 ]; then
      step "Fetching updates"
      upstream="$(git -C "$ROOT" rev-parse --abbrev-ref --symbolic-full-name '@{upstream}')"
      [ "$upstream" = origin/main ] || die "automatic updates require upstream origin/main"
      git -C "$ROOT" fetch origin || die "fetch failed; current deployment and data are preserved"
      git -C "$ROOT" merge-base --is-ancestor HEAD origin/main || die "local commits are ahead of or diverged from origin/main; resolve manually"
      git -C "$ROOT" merge --ff-only origin/main || die "fast-forward failed; resolve repository changes manually"
      # The checked-in scripts/config may have changed. Re-enter once to use the updated helpers.
      export ONESHELF_UPDATE_FETCHED=1
      exec "$ROOT/update.sh"
    fi
    ok "updated to $(git -C "$ROOT" log --oneline -1)"
  fi
else
  warn "not a git checkout; rebuilding the image from the files that are here"
fi

validate_custom_directories

step "Rebuilding the image"
compose_cmd build || die "image build failed; current deployment and data are preserved"

check_legacy_storage

step "Restarting OneShelf"
# Migrations and recovery run on startup, the same way they always do — there is no separate path.
compose_cmd up -d || die "container startup failed; inspect Compose logs"

URL="$(oneshelf_url "$ROOT")"
step "Waiting for OneShelf to be ready"
if wait_for_ready "$URL" >/dev/null; then
  ok "ready"
else
  diagnose "$URL"
  die "update failed readiness; preserve your volumes and consult README before any rollback"
fi
verify_health "$URL" || { diagnose "$URL"; die "health check failed"; }
ok "health check passed"
say ""
say "${_b}OneShelf is up to date and running at ${URL}${_r}"
