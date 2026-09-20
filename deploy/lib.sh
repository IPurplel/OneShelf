#!/usr/bin/env bash
# Shared helpers for install.sh, update.sh and uninstall.sh.
#
# Sourced, never executed. Everything here is deliberately quiet about what it finds on the machine:
# OneShelf does not install a container runtime, does not reach for sudo, and does not touch anything
# on the host that is not its own.

set -euo pipefail

ONESHELF_PORT_DEFAULT=8420
COMPOSE_FILE_REL="deploy/compose.yaml"
VOLUME_DIRS=(data plugins keys content backups)
CONTAINER_UID=10001

# --- output ---------------------------------------------------------------------------------------
if [ -t 1 ] && [ -z "${NO_COLOR:-}" ]; then
  _b=$'\033[1m'; _r=$'\033[0m'; _red=$'\033[31m'; _grn=$'\033[32m'; _ylw=$'\033[33m'
else
  _b=""; _r=""; _red=""; _grn=""; _ylw=""
fi
say()  { printf '%s\n' "$*"; }
step() { printf '%s==>%s %s\n' "$_b" "$_r" "$*"; }
ok()   { printf '%s  ok%s %s\n' "$_grn" "$_r" "$*"; }
warn() { printf '%s  !%s  %s\n' "$_ylw" "$_r" "$*" >&2; }
die()  { printf '%serror%s %s\n' "$_red" "$_r" "$*" >&2; exit 1; }

# --- repository root ---------------------------------------------------------------------------
repo_root() {
  local here
  here="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
  printf '%s' "$here"
}

require_repo_root() {
  local root="$1"
  [ -f "$root/$COMPOSE_FILE_REL" ] || die "run this from the OneShelf repository root (no $COMPOSE_FILE_REL here)"
}

# --- runtime detection -----------------------------------------------------------------------------
# A runtime counts only if it actually answers. An installed binary that cannot talk to its service is
# worse than none, because the error it produces later is far less clear than the one produced here.
runtime_works() {
  local runtime="$1"
  command -v "$runtime" >/dev/null 2>&1 || return 1
  "$runtime" info >/dev/null 2>&1
}

detect_runtime() {
  local candidate
  if [ -n "${ONESHELF_RUNTIME:-}" ]; then
    command -v "$ONESHELF_RUNTIME" >/dev/null 2>&1 \
      || die "ONESHELF_RUNTIME=$ONESHELF_RUNTIME is not on PATH"
    printf '%s' "$ONESHELF_RUNTIME"
    return 0
  fi
  for candidate in podman docker; do
    if runtime_works "$candidate"; then printf '%s' "$candidate"; return 0; fi
  done
  # Installed but not answering: say which, so the person knows what to fix.
  for candidate in podman docker; do
    if command -v "$candidate" >/dev/null 2>&1; then
      die "$candidate is installed but not responding to '$candidate info'.
  If it needs a service, start it (for example: systemctl --user start podman.socket,
  or systemctl start docker), then run this again. OneShelf will not start it for you."
    fi
  done
  die "no container runtime found.
  OneShelf runs in a container and does not install one for you. Install either:
    Fedora / RHEL:  sudo dnf install podman podman-compose
    Debian/Ubuntu:  sudo apt install podman podman-compose
    or Docker Engine with the Compose plugin: https://docs.docker.com/engine/install/
  Then run ./install.sh again."
}

# --- compose provider ------------------------------------------------------------------------------
# Printed as a single string; callers run it with `compose_cmd`, never by expanding it unquoted.
detect_compose() {
  local runtime="$1"
  if [ -n "${ONESHELF_COMPOSE:-}" ]; then printf '%s' "$ONESHELF_COMPOSE"; return 0; fi
  if "$runtime" compose version >/dev/null 2>&1; then printf '%s compose' "$runtime"; return 0; fi
  if [ "$runtime" = podman ] && command -v podman-compose >/dev/null 2>&1; then
    printf 'podman-compose'; return 0
  fi
  if [ "$runtime" = docker ] && command -v docker-compose >/dev/null 2>&1; then
    printf 'docker-compose'; return 0
  fi
  die "$runtime is available but no Compose provider is.
  Install one of:
    Fedora / RHEL:  sudo dnf install podman-compose
    Debian/Ubuntu:  sudo apt install podman-compose
    Docker:         the Compose plugin (docker compose version)
  Then run this again."
}

compose_cmd() {
  # shellcheck disable=SC2086  # COMPOSE is a deliberately word-split command prefix
  ( cd "$ROOT" && $COMPOSE -f "$COMPOSE_FILE_REL" "$@" )
}

# --- configuration ---------------------------------------------------------------------------------
# An existing .env is the person's own file: it is read, never rewritten.
ensure_env() {
  local root="$1"
  if [ -f "$root/.env" ]; then
    ok "using your existing .env (left exactly as it is)"
    return 0
  fi
  [ -f "$root/.env.example" ] || die "no .env.example in the repository; cannot create a default .env"
  cp "$root/.env.example" "$root/.env"
  chmod 600 "$root/.env"
  ok "created .env from .env.example"
}

env_value() {
  # Reads one key from .env without sourcing it, so a stray line cannot run anything.
  local root="$1" key="$2" default="${3:-}" line
  line="$(grep -E "^${key}=" "$root/.env" 2>/dev/null | tail -1 || true)"
  if [ -z "$line" ]; then printf '%s' "$default"; else printf '%s' "${line#*=}"; fi
}

# --- OneShelf's own directories ----------------------------------------------------------------------
prepare_directories() {
  local root="$1" name path
  for name in "${VOLUME_DIRS[@]}"; do
    path="$(env_value "$root" "ONESHELF_$(printf '%s' "$name" | tr '[:lower:]' '[:upper:]')_PATH" "./volumes/$name")"
    case "$path" in
      /*) : ;;                       # absolute: used as given
      *)  path="$root/deploy/${path#./}" ;;
    esac
    mkdir -p "$path"
    printf '%s\n' "$path"
  done
}

# The container runs as an unprivileged user (uid 10001). Where the runtime cannot already write to a
# bind mount, ownership of *OneShelf's own directories only* is corrected through the runtime itself —
# no sudo, nothing outside these paths, and no loosening of permissions.
fix_ownership_if_needed() {
  local image="$1"; shift
  local dirs=("$@") args=() d
  for d in "${dirs[@]}"; do args+=(-v "$d:/mnt/$(basename "$d")"); done
  if "$RUNTIME" run --rm "${args[@]}" --user "$CONTAINER_UID" --entrypoint sh "$image" \
        -c 'for d in /mnt/*; do touch "$d/.oneshelf-write-test" && rm -f "$d/.oneshelf-write-test" || exit 1; done' \
        >/dev/null 2>&1; then
    return 0
  fi
  step "giving OneShelf's own directories to the container user (uid $CONTAINER_UID)"
  "$RUNTIME" run --rm "${args[@]}" --user 0 --entrypoint sh "$image" \
      -c "chown -R $CONTAINER_UID:$CONTAINER_UID /mnt/*" >/dev/null 2>&1 \
    || warn "could not adjust ownership automatically; if OneShelf cannot write, see README → Troubleshooting"
}

# --- readiness ------------------------------------------------------------------------------------
oneshelf_url() {
  local root="$1" bind port
  bind="$(env_value "$root" ONESHELF_BIND 127.0.0.1)"
  port="$(env_value "$root" ONESHELF_PORT "$ONESHELF_PORT_DEFAULT")"
  [ "$bind" = "0.0.0.0" ] && bind=127.0.0.1
  printf 'http://%s:%s' "$bind" "$port"
}

probe() {
  local url="$1"
  if command -v curl >/dev/null 2>&1; then
    curl -fsS --max-time 5 "$url" 2>/dev/null
  elif command -v wget >/dev/null 2>&1; then
    wget -qO- --timeout=5 "$url" 2>/dev/null
  else
    return 2
  fi
}

wait_for_ready() {
  # Tries are configurable so the test suite does not have to wait out a real timeout.
  local url="$1" tries="${2:-${ONESHELF_READY_TRIES:-60}}" body i
  local delay="${ONESHELF_READY_DELAY:-2}"
  for ((i = 1; i <= tries; i++)); do
    if body="$(probe "$url/api/ready")"; then
      case "$body" in *'"ready": true'*|*'"ready":true'*) printf '%s' "$body"; return 0 ;; esac
    elif [ "$?" -eq 2 ]; then
      warn "neither curl nor wget is available, so readiness cannot be checked from here"
      return 3
    fi
    sleep "$delay"
  done
  return 1
}

diagnose() {
  local url="$1"
  warn "OneShelf did not become ready at $url"
  say ""
  say "What usually helps:"
  say "  1. Look at the log:      $COMPOSE -f $COMPOSE_FILE_REL logs --tail=50"
  say "  2. Check it is running:  $COMPOSE -f $COMPOSE_FILE_REL ps"
  say "  3. Check the port is free: something else may already be on $(env_value "$ROOT" ONESHELF_PORT "$ONESHELF_PORT_DEFAULT")"
  say ""
  say "The last few lines of OneShelf's own log:"
  compose_cmd logs --tail=30 2>&1 | sed 's/^/    /' || true
}
