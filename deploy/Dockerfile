# OneShelf: self-hosted personal reading library (Master §2.1).
#
# One image, one process: the ASGI core plus the in-process browser used only when a source genuinely
# needs it. Persistent state lives on mounts, never in the image.
# The interface is built first and copied in, because in a container there is one process and one
# origin: the API serves the SPA it was built with (§2.1).
FROM node:22-slim AS web
WORKDIR /web
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY frontend/ ./
RUN npm run build


FROM python:3.13-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PLAYWRIGHT_BROWSERS_PATH=/opt/playwright

# Chromium's runtime libraries; the browser itself is installed by Playwright below.
RUN apt-get update && apt-get install -y --no-install-recommends \
        ca-certificates curl libnss3 libnspr4 libatk1.0-0 libatk-bridge2.0-0 libcups2 libdrm2 \
        libxkbcommon0 libxcomposite1 libxdamage1 libxfixes3 libxrandr2 libgbm1 libasound2 libpango-1.0-0 \
        libcairo2 fonts-liberation fonts-noto-core fonts-noto-cjk \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY backend/pyproject.toml backend/requirements.lock ./
RUN pip install --no-cache-dir -r requirements.lock

COPY backend/ /app/
RUN pip install --no-cache-dir --no-deps . \
    && python -m playwright install chromium

COPY --from=web /web/dist /app/web

# Separate mounts (Master §2.1, §13, §33.9): application data, plugin store, the session key on its own
# volume, library content, and backups. None of them are baked into the image.
ENV ONESHELF_DATA_DIR=/data \
    ONESHELF_PLUGIN_DIR=/plugins \
    ONESHELF_SESSION_KEY_FILE=/keys/session.key \
    ONESHELF_WEB_ROOT=/app/web \
    ONESHELF_HOST=0.0.0.0 \
    ONESHELF_PORT=8420
VOLUME ["/data", "/plugins", "/keys", "/content", "/backups"]

RUN useradd --system --uid 10001 --home /app oneshelf \
    && mkdir -p /data /plugins /keys /content /backups \
    && chown -R oneshelf:oneshelf /app /data /plugins /keys /content /backups
USER oneshelf

EXPOSE 8420
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD curl -fsS "http://127.0.0.1:${ONESHELF_PORT}/api/ready" || exit 1

CMD ["python", "-m", "oneshelf.api.app"]
