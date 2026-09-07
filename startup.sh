#!/usr/bin/env bash
# The single deployment entry point. Docker builds the checked-out source.
set -euo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
COMPOSE=(docker compose --project-name oneshelf --file "$ROOT/deploy/docker-compose.yml")

fail() { printf 'Error: %s\n' "$*" >&2; exit 1; }
logs() { "${COMPOSE[@]}" logs --tail 60 oneshelf >&2 || true; }

printf 'OneShelf — checking Docker...\n'
command -v docker >/dev/null 2>&1 || fail 'Install Docker with Compose v2, start Docker, then run bash startup.sh again.'
docker compose version >/dev/null 2>&1 || fail 'Docker Compose v2 is required. Install or update the Compose plugin, then retry.'
docker info >/dev/null 2>&1 || fail 'Cannot access Docker. Start Docker and check that your user has permission to use it.'

# Never replace a previous installation with empty volumes or adopt another
# Compose project's container. A normal rerun has these labels and mounts.
STORAGE_FORMAT='{{index .Config.Labels "com.docker.compose.project"}}|{{index .Config.Labels "com.docker.compose.service"}}{{range .Mounts}}{{if eq .Destination "/data/manga"}}|{{.Type}}:{{.Name}}:{{.Destination}}{{end}}{{end}}{{range .Mounts}}{{if eq .Destination "/config"}}|{{.Type}}:{{.Name}}:{{.Destination}}{{end}}{{end}}'
EXPECTED_STORAGE='oneshelf|oneshelf|volume:oneshelf_downloads:/data/manga|volume:oneshelf_config:/config'
check_storage() {
    if [[ -n "$1" && "$1" != "$EXPECTED_STORAGE" ]]; then
        fail 'An existing OneShelf container uses a different deployment or storage. It has been left untouched. See docs/troubleshooting.md (Existing installation) before retrying.'
    fi
}
existing="$(docker container inspect --format "$STORAGE_FORMAT" oneshelf 2>/dev/null || true)"
check_storage "$existing"
# Compose discovers containers by labels, even after someone renames them.
containers="$(docker container ls --all --filter label=com.docker.compose.project=oneshelf --filter label=com.docker.compose.service=oneshelf --format '{{.ID}}')" || fail 'Could not inspect existing OneShelf containers. Check Docker and retry.'
while IFS= read -r container; do
    [[ -n "$container" ]] || continue
    existing="$(docker container inspect --format "$STORAGE_FORMAT" "$container")" || fail 'Could not inspect an existing OneShelf container. Check Docker and retry.'
    check_storage "$existing"
done <<< "$containers"

printf 'Building OneShelf (the first build can take several minutes)...\n'
"${COMPOSE[@]}" build || fail 'Build failed. Read the error above, fix it, and rerun bash startup.sh.'
printf 'Starting OneShelf...\n'
if ! "${COMPOSE[@]}" up -d; then
    logs
    fail 'Startup failed. Check the error above; another app may already be using port 8080.'
fi

printf 'Waiting for OneShelf to become healthy (up to 120 seconds)...\n'
ready=false
for ((elapsed = 0; elapsed <= 120; elapsed += 2)); do
    health="$(docker container inspect --format '{{if .State.Running}}{{if .State.Health}}{{.State.Health.Status}}{{else}}missing{{end}}{{else}}stopped{{end}}' oneshelf 2>/dev/null || true)"
    case "$health" in
        healthy) ready=true; break ;;
        starting) ;;
        *) logs; fail "OneShelf did not become ready (container status: ${health:-unknown}). Check the logs above." ;;
    esac
    if ((elapsed < 120)); then sleep 2; fi
done
if [[ "$ready" != true ]]; then
    logs
    fail 'OneShelf did not become healthy within 120 seconds. Check the logs above.'
fi

# Run as the application's user, using actual writes rather than access bits.
if ! "${COMPOSE[@]}" exec -T oneshelf python -c 'import tempfile; from app.config import settings; [tempfile.TemporaryFile(dir=p).close() for p in (settings.output_dir, settings.config_dir)]'; then
    logs
    fail 'OneShelf cannot write its downloads or settings volume. See docs/troubleshooting.md.'
fi

# Best effort: Linux first, then macOS. Never label loopback as a LAN address.
lan_addresses="$(
    {
        hostname -I 2>/dev/null || true
        if command -v ipconfig >/dev/null 2>&1; then
            ipconfig getifaddr en0 2>/dev/null || true
            ipconfig getifaddr en1 2>/dev/null || true
        fi
    } | awk '{for (i=1; i<=NF; i++) if ($i ~ /^[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+$/ && $i !~ /^(127\.|169\.254\.|0\.)/) print $i}' | sort -u
)"
printf '\nOneShelf is ready.\nLocal: http://localhost:8080\n'
if [[ -n "$lan_addresses" ]]; then
    while IFS= read -r address; do
        printf 'LAN:   http://%s:8080\n' "$address"
    done <<< "$lan_addresses"
else
    printf 'LAN: Open http://<host-LAN-IP>:8080 from another device. Find the host LAN IP in its network settings.\n'
fi
printf '\nUse the address of your Wi-Fi or Ethernet connection. Devices must share the same LAN.\n'
printf 'Keep access on a trusted network; OneShelf has no login.\n'
printf 'Downloads and settings are saved in Docker volumes. You can close this terminal.\n'
