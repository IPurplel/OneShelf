#!/usr/bin/env bash
# OneShelf: stop and remove the running deployment.
#
#   ./uninstall.sh                 stops and removes the containers. YOUR LIBRARY IS KEPT.
#   ./uninstall.sh --delete-data   also deletes OneShelf's data directories. Asks first.
#
# Nothing outside OneShelf's own directories is ever touched.

set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=deploy/lib.sh
. "$ROOT/deploy/lib.sh"
require_repo_root "$ROOT"

DELETE_DATA=0
for arg in "$@"; do
  case "$arg" in
    --delete-data) DELETE_DATA=1 ;;
    -h|--help) sed -n '2,9p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) die "unknown option: $arg (did you mean --delete-data?)" ;;
  esac
done

RUNTIME="$(detect_runtime)"
COMPOSE="$(detect_compose "$RUNTIME")"

load_configuration
if [ "$DELETE_DATA" -eq 1 ]; then
  for i in "${!VOLUME_DIRS[@]}"; do
    [ "${DIRS[$i]}" = "$ROOT/deploy/volumes/${VOLUME_DIRS[$i]}" ] \
      || die "automatic deletion supports only default deploy/volumes directories; remove custom storage manually after backing it up"
  done
fi

step "Stopping OneShelf"
compose_cmd down || die "could not stop the deployment; no data was deleted"
ok "containers stopped and removed"

if [ "$DELETE_DATA" -eq 0 ]; then
  say ""
  say "${_b}Your library has been kept.${_r} Nothing was deleted."
  if [ -f "$ROOT/.env" ]; then
    say ""
    say "It is still in:"
    for d in "${DIRS[@]}"; do say "    $d"; done
  fi
  say ""
  say "Start it again any time with ./install.sh"
  say "To delete the data as well, run: ./uninstall.sh --delete-data"
  exit 0
fi

# --- the destructive path, which is never the default ---------------------------------------------
say ""
say "${_red}This will permanently delete OneShelf's data directories:${_r}"
for d in "${DIRS[@]}"; do
  say "    $d"
done
say ""
say "That includes your library database, every downloaded and imported file, your saved source"
say "logins, and your OneShelf backups. It cannot be undone, and nothing else on this machine is"
say "touched. If you want to keep a copy, stop now and copy those directories somewhere safe."
say ""
printf 'Type exactly "delete my library" to continue: '
read -r answer || { say "Nothing was deleted."; exit 1; }
[ "$answer" = "delete my library" ] || { say "Nothing was deleted."; exit 1; }

for d in "${DIRS[@]}"; do
  [ -d "$d" ] || continue
  if ! rm -rf --one-file-system -- "$d" 2>/dev/null; then
    "$RUNTIME" run --rm -v "$d:/mnt:z" --user 0 --entrypoint sh \
      "$ONESHELF_IMAGE" -c 'find /mnt -xdev -mindepth 1 -delete' \
      >/dev/null 2>&1 || die "could not delete all data; remaining files are in $d"
    rmdir -- "$d" || die "could not remove $d"
  fi
  [ ! -e "$d" ] || die "data remains in $d"
  say "    removed $d"
done
say ""
say "OneShelf's data has been deleted. Your .env was left in place; delete it yourself if you want to."
