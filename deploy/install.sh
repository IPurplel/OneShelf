#!/usr/bin/env bash
# Native install for a Debian/Ubuntu LXC container.
#
# Use this path when the container is unprivileged and has no nesting enabled,
# which rules out Docker. It installs Chromium's system dependencies, builds a
# venv, and registers a systemd service.
#
#   curl -fsSL .../install.sh | sudo bash
# or
#   sudo ./deploy/install.sh

set -euo pipefail

APP_USER="${APP_USER:-mangadl}"
APP_DIR="${APP_DIR:-/opt/manga-downloader}"
DATA_DIR="${DATA_DIR:-/data/manga}"
CONFIG_DIR="${CONFIG_DIR:-/etc/manga-downloader}"
PORT="${PORT:-8080}"

SOURCE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

log()  { printf '\033[1;34m==>\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33m!!\033[0m %s\n' "$*" >&2; }
die()  { printf '\033[1;31mxx\033[0m %s\n' "$*" >&2; exit 1; }

[[ $EUID -eq 0 ]] || die "Run this as root (sudo $0)"

if ! command -v apt-get >/dev/null 2>&1; then
  die "This installer targets Debian/Ubuntu. On another distro, install Python 3.11+, run 'playwright install --with-deps chromium', and adapt the unit file."
fi

# ---------------------------------------------------------------- packages

# xvfb is a display server that renders into memory. It is what lets the app
# escalate to a *headful* browser inside a container with no X server, which is
# how the interactive Cloudflare challenge gets cleared without user help.
log "Installing system packages"
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y -qq --no-install-recommends \
  python3 python3-venv python3-pip ca-certificates curl \
  xvfb gnupg

PYTHON_VERSION="$(python3 -c 'import sys; print("%d.%d" % sys.version_info[:2])')"
log "Found Python ${PYTHON_VERSION}"
python3 -c 'import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)' \
  || die "Python 3.11+ required, found ${PYTHON_VERSION}. On Debian 11, enable backports or use the Docker path."

# ------------------------------------------------------------------- user

if ! id "$APP_USER" >/dev/null 2>&1; then
  log "Creating service user '$APP_USER'"
  useradd --system --create-home --home-dir "/home/${APP_USER}" --shell /usr/sbin/nologin "$APP_USER"
fi

# ------------------------------------------------------------------ files

log "Installing application to ${APP_DIR}"
mkdir -p "$APP_DIR" "$DATA_DIR" "$CONFIG_DIR"
cp -r "${SOURCE_DIR}/app" "${SOURCE_DIR}/web" "${SOURCE_DIR}/requirements.txt" "$APP_DIR/"

if [[ ! -f "${CONFIG_DIR}/config.yaml" ]]; then
  cp "${SOURCE_DIR}/config.example.yaml" "${CONFIG_DIR}/config.yaml"
  sed -i "s|^output_dir:.*|output_dir: ${DATA_DIR}|" "${CONFIG_DIR}/config.yaml"
  sed -i "s|^config_dir:.*|config_dir: ${CONFIG_DIR}|" "${CONFIG_DIR}/config.yaml"
  log "Wrote ${CONFIG_DIR}/config.yaml"
else
  log "Keeping existing ${CONFIG_DIR}/config.yaml"
fi

# -------------------------------------------------------------------- venv

log "Creating virtualenv"
python3 -m venv "${APP_DIR}/venv"
"${APP_DIR}/venv/bin/pip" install --quiet --upgrade pip
"${APP_DIR}/venv/bin/pip" install --quiet -r "${APP_DIR}/requirements.txt"

# Installs Chromium plus the ~20 shared libraries it links against. This is the
# step the Docker image gets for free.
log "Installing Chromium and its system libraries (this takes a few minutes)"
"${APP_DIR}/venv/bin/playwright" install --with-deps chromium

# patchright is version-matched to playwright, so it resolves the same Chromium
# build that was just downloaded. This registers it and is a no-op if so;
# non-fatal because the app degrades to stock Playwright without it.
if [[ -x "${APP_DIR}/venv/bin/patchright" ]]; then
  "${APP_DIR}/venv/bin/patchright" install chromium >/dev/null 2>&1 \
    || warn "patchright browser registration failed; stock Playwright will be used"
fi

# Real Chrome, when the licence terms suit you. Playwright's bundled Chromium
# is an unsigned developer build missing the proprietary codecs a shipped
# browser has, and a bot check can tell the difference. Entirely optional:
# set INSTALL_CHROME=0 to skip, and the app falls back to bundled Chromium.
if [[ "${INSTALL_CHROME:-1}" == "1" ]] && ! command -v google-chrome >/dev/null 2>&1; then
  log "Installing Google Chrome (set INSTALL_CHROME=0 to skip)"
  if curl -fsSL https://dl.google.com/linux/linux_signing_key.pub \
       | gpg --dearmor -o /usr/share/keyrings/google-chrome.gpg 2>/dev/null; then
    echo "deb [arch=amd64 signed-by=/usr/share/keyrings/google-chrome.gpg] http://dl.google.com/linux/chrome/deb/ stable main" \
      > /etc/apt/sources.list.d/google-chrome.list
    apt-get update -qq \
      && apt-get install -y -qq --no-install-recommends google-chrome-stable \
      || warn "Chrome install failed; bundled Chromium will be used instead"
  else
    warn "Could not fetch Google's signing key; bundled Chromium will be used"
  fi
fi

chown -R "${APP_USER}:${APP_USER}" "$APP_DIR" "$DATA_DIR" "$CONFIG_DIR"

# ------------------------------------------------------------------ systemd

log "Installing systemd service"
sed -e "s|@APP_USER@|${APP_USER}|g" \
    -e "s|@APP_DIR@|${APP_DIR}|g" \
    -e "s|@CONFIG_DIR@|${CONFIG_DIR}|g" \
    -e "s|@DATA_DIR@|${DATA_DIR}|g" \
    -e "s|@PORT@|${PORT}|g" \
    "${SOURCE_DIR}/deploy/manga-downloader.service" > /etc/systemd/system/manga-downloader.service

systemctl daemon-reload
systemctl enable --now manga-downloader.service

sleep 3
if systemctl is-active --quiet manga-downloader.service; then
  IP="$(hostname -I 2>/dev/null | awk '{print $1}')"
  log "Running. Open http://${IP:-<container-ip>}:${PORT}"
  log "Logs:    journalctl -u manga-downloader -f"
  log "Output:  ${DATA_DIR}"
else
  warn "Service failed to start. Check: journalctl -u manga-downloader -n 60 --no-pager"
  exit 1
fi
