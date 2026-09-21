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
    case "$ONESHELF_RUNTIME" in podman|docker) ;; *) die "ONESHELF_RUNTIME must be podman or docker" ;; esac
    runtime_works "$ONESHELF_RUNTIME" || die "$ONESHELF_RUNTIME is installed but not responding (or absent)"
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
  local env_args=()
  [ ! -f "$ROOT/.env" ] || env_args=(--env-file "$ROOT/.env")
  ( cd "$ROOT" && $COMPOSE "${env_args[@]}" -p "${COMPOSE_PROJECT_NAME:-oneshelf}" -f "$COMPOSE_FILE_REL" "$@" )
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
  [ ! -e "$root/.env" ] && [ ! -L "$root/.env" ] || die ".env is not a regular file"
  (umask 077; set -o noclobber; cat "$root/.env.example" > "$root/.env")
  ok "created .env from .env.example"
}

env_value() {
  # A literal subset of dotenv, never shell code. Shell overrides match Compose precedence.
  local root="$1" key="$2" default="${3:-}" line value
  if [[ -v $key ]]; then printf '%s' "${!key}"; return; fi
  line="$(grep -E "^[[:space:]]*${key}[[:space:]]*=" "$root/.env" 2>/dev/null | tail -1 || true)"
  [ -n "$line" ] || { printf '%s' "$default"; return; }
  value="${line#*=}"
  value="$(printf '%s' "$value" | sed 's/^[[:space:]]*//; s/[[:space:]]*$//')"
  if [[ $value == \"* || $value == \'* ]]; then
    local quote="${value:0:1}" rest
    value="${value:1}"
    [[ $value == *"$quote"* ]] || die "invalid quoted value for $key in .env"
    rest="${value#*"$quote"}"
    [[ $rest =~ ^[[:space:]]*(#.*)?$ ]] || die "invalid trailing text for $key in .env"
    value="${value%%"$quote"*}"
  else
    value="$(printf '%s' "$value" | sed 's/[[:space:]][[:space:]]*#.*$//; s/[[:space:]]*$//')"
  fi
  [[ $value != *'$'* && $value != *'\'* && $value != *$'\n'* && $value != *$'\r'* ]] \
    || die "use a literal single-line value for $key (no interpolation or escapes)"
  printf '%s' "$value"
}

load_configuration() {
  # Export the exact values used for paths/probes so providers see the same configuration.
  local key value
  for key in ONESHELF_BIND ONESHELF_PORT ONESHELF_IMAGE ONESHELF_TRUSTED_NETWORKS \
      ONESHELF_TRUSTED_PROXIES ONESHELF_ALLOWED_HOSTS; do
    case "$key" in
      ONESHELF_BIND) value="$(env_value "$ROOT" "$key" 127.0.0.1)" ;;
      ONESHELF_PORT) value="$(env_value "$ROOT" "$key" 8420)" ;;
      ONESHELF_IMAGE) value="$(env_value "$ROOT" "$key" oneshelf:local)" ;;
      ONESHELF_ALLOWED_HOSTS) value="$(env_value "$ROOT" "$key" localhost)" ;;
      *) value="$(env_value "$ROOT" "$key" '')" ;;
    esac
    export "$key=$value"
  done
  [[ $ONESHELF_PORT =~ ^[0-9]{1,5}$ ]] && ((10#$ONESHELF_PORT > 0 && 10#$ONESHELF_PORT < 65536)) \
    || die "ONESHELF_PORT must be between 1 and 65535"
  [[ $ONESHELF_BIND =~ ^[a-zA-Z0-9.:-]+$ ]] || die "invalid ONESHELF_BIND"
  [[ $ONESHELF_IMAGE =~ ^[a-zA-Z0-9][a-zA-Z0-9./:@_-]*$ ]] || die "invalid ONESHELF_IMAGE"
  resolve_directories
}

resolve_directories() {
  local name key path canonical previous
  DIRS=()
  for name in "${VOLUME_DIRS[@]}"; do
    key="ONESHELF_$(printf '%s' "$name" | tr '[:lower:]' '[:upper:]')_PATH"
    # The example historically used singular PLUGIN and BACKUP; Compose uses those too.
    case "$name" in plugins) key=ONESHELF_PLUGIN_PATH ;; backups) key=ONESHELF_BACKUP_PATH ;; esac
    path="$(env_value "$ROOT" "$key" "./volumes/$name")"
    [[ -n $path && $path != *:* && $path != *$'\n'* && $path != *'$'* ]] || die "invalid $key: use a dedicated directory"
    case "$path" in /*) ;; *) path="$ROOT/deploy/${path#./}" ;; esac
    canonical="$(realpath -m -- "$path")" || die "cannot resolve $key"
    # Reject aliases/symlinks as well as system roots and ancestors of this checkout/home.
    [ "$canonical" = "$(realpath -ms -- "$path")" ] || die "refusing symlinked directory for $key"
    case "$canonical" in /|/home|/root|/etc|/var|/usr|/tmp|/opt|/srv|/mnt|/media|/run|/dev|/proc|/sys|/boot) die "unsafe directory for $key" ;; esac
    [[ "$ROOT/" != "$canonical/"* && "$HOME/" != "$canonical/"* ]] || die "unsafe directory for $key"
    for previous in "${DIRS[@]}"; do
      [[ "$canonical/" != "$previous/"* && "$previous/" != "$canonical/"* ]] || die "persistent directories must not overlap"
    done
    DIRS+=("$canonical")
    export "$key=$canonical"
  done
}

validate_custom_directories() {
  local i path found
  for i in "${!DIRS[@]}"; do
    path="${DIRS[$i]}"
    [ "$path" != "$ROOT/deploy/volumes/${VOLUME_DIRS[$i]}" ] || continue
    [ -d "$path" ] || continue
    [ ! -L "$path/.oneshelf-managed" ] || die "invalid ownership marker in custom storage"
    [ ! -f "$path/.oneshelf-managed" ] || continue
    found="$(find "$path" -mindepth 1 -maxdepth 1 -print -quit)" || die "cannot inspect custom storage safely"
    [ -z "$found" ] || die "custom storage is nonempty and not marked for OneShelf; see README before changing ownership"
  done
}

prepare_directories() {
  validate_custom_directories
  local path
  for path in "${DIRS[@]}"; do
    mkdir -p -- "$path" || die "cannot create a persistent directory; check permissions"
    if [ ! -e "$path/.oneshelf-managed" ]; then
      (umask 077; set -o noclobber; : > "$path/.oneshelf-managed") || die "cannot mark dedicated storage"
    fi
    say "    $path"
  done
}

fix_ownership_if_needed() {
  local image="$1"; shift
  local dirs=("$@") args=() d index=0
  for d in "${dirs[@]}"; do args+=(-v "$d:/mnt/$index:z"); index=$((index + 1)); done
  if "$RUNTIME" run --rm "${args[@]}" --user "$CONTAINER_UID" --entrypoint sh "$image" \
        -c 'for d in /mnt/*; do t=$(mktemp -d "$d/.oneshelf-write-test.XXXXXX") && rmdir "$t" || exit 1; done' \
        >/dev/null 2>&1; then
    return 0
  fi
  step "giving OneShelf's dedicated directories to the container user (uid $CONTAINER_UID)"
  "$RUNTIME" run --rm "${args[@]}" --user 0 --entrypoint sh "$image" \
      -c "chown -R -h -P $CONTAINER_UID:$CONTAINER_UID /mnt/*" >/dev/null 2>&1 \
    || die "could not adjust directory ownership; see README → Troubleshooting"
}

check_legacy_storage() {
  # Before adding nested mounts, refuse to conceal files from a pre-release deployment.
  "$RUNTIME" run --rm -v "$ONESHELF_DATA_PATH:/legacy:ro,z" --user 0 --entrypoint sh \
    "$ONESHELF_IMAGE" -c 'for name in plugins backups; do
      if [ -d "/legacy/$name" ]; then
        found=$(find "/legacy/$name" -mindepth 1 -maxdepth 1 -print -quit) || exit 1
        [ -z "$found" ] || exit 1
      fi
    done' >/dev/null 2>&1 \
    || die "legacy plugins/backups may exist beneath the data directory, or the storage check failed. Nothing was moved. See README → Legacy deployment storage before starting."
}

require_probe() {
  command -v curl >/dev/null 2>&1 || command -v wget >/dev/null 2>&1 \
    || die "install curl or wget to verify readiness and health"
}

verify_health() {
  local body
  body="$(probe "$1/api/health")" || return 1
  [[ $body =~ \"status\"[[:space:]]*:[[:space:]]*\"ok\" ]]
}

# --- readiness ------------------------------------------------------------------------------------
oneshelf_url() {
  local root="$1" bind port
  bind="$(env_value "$root" ONESHELF_BIND 127.0.0.1)"
  port="$(env_value "$root" ONESHELF_PORT "$ONESHELF_PORT_DEFAULT")"
  case "$bind" in 0.0.0.0) bind=127.0.0.1 ;; ::) bind="[::1]" ;; *:*) bind="[$bind]" ;; esac
  printf 'http://%s:%s' "$bind" "$port"
}

probe() {
  local url="$1"
  if command -v curl >/dev/null 2>&1; then
    curl --noproxy '*' -fsS --max-time 5 "$url" 2>/dev/null
  elif command -v wget >/dev/null 2>&1; then
    wget --no-proxy -qO- --timeout=5 "$url" 2>/dev/null
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
      if [[ $body =~ \"ready\"[[:space:]]*:[[:space:]]*true[[:space:]]*[,}] ]]; then printf '%s' "$body"; return 0; fi
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
  say "Inspect logs locally before sharing them; they may contain private information."
}
