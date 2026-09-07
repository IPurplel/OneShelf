# Built on Microsoft's official Playwright image: Chromium and its ~20 system
# libraries are already present and version-matched to the Playwright package,
# which removes the single biggest source of install pain in a container.
FROM mcr.microsoft.com/playwright/python:v1.49.1-jammy

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    MD_CONFIG_FILE=/config/config.yaml \
    MD_OUTPUT_DIR=/data/manga \
    MD_CONFIG_DIR=/config

WORKDIR /app

# Real Chrome, and this is not optional polish - it is what makes the image able
# to clear a bot check at all.
#
# app/browser.py:detect_channel("auto") prefers `chrome`, then `msedge`, and
# only then falls back to the Chromium baked into this base image. That bundle
# is Chromium 131, and 131 *never* clears the Cloudflare challenge - measured,
# and recorded in HANDOFF.md alongside the version that does (149+). Without a
# real Chrome here, every Cloudflare-fronted source fails while the app looks
# like it is working. deploy/install.sh installs Chrome for the native path for
# exactly this reason; this is the container's equivalent.
#
# Non-fatal on failure, like install.sh: a build where Google's repo is
# unreachable, or on an architecture Chrome does not ship for, should still
# produce a working image - just one that clears fewer challenges.
ARG INSTALL_CHROME=1

# xvfb renders into memory, so the app can escalate to a headful browser inside
# the container - which is what clears the interactive Cloudflare challenge.
USER root
RUN apt-get update \
 && apt-get install -y --no-install-recommends xvfb gnupg ca-certificates curl \
 && if [ "$INSTALL_CHROME" = "1" ]; then \
      ( curl -fsSL https://dl.google.com/linux/linux_signing_key.pub \
          | gpg --dearmor -o /usr/share/keyrings/google-chrome.gpg \
        && echo "deb [arch=amd64 signed-by=/usr/share/keyrings/google-chrome.gpg] http://dl.google.com/linux/chrome/deb/ stable main" \
             > /etc/apt/sources.list.d/google-chrome.list \
        && apt-get update \
        && apt-get install -y --no-install-recommends google-chrome-stable ) \
      || echo "WARNING: Chrome install failed; bundled Chromium will be used and Cloudflare sites will likely fail" ; \
    fi \
 && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt \
 && patchright install chromium

COPY app/ ./app/
COPY web/ ./web/

# The base image ships a non-root `pwuser`. Running the browser as root is both
# unnecessary and awkward with Chromium's sandbox.
#
# PLAYWRIGHT_BROWSERS_PATH is /ms-playwright in this base image, and the
# `patchright install` above ran as root — so anything it added there is
# root-owned. Making it readable is what keeps pwuser able to launch the
# browser; without it the app falls back or fails at the first fetch.
RUN mkdir -p /data/manga /config \
 && chown -R pwuser:pwuser /app /data /config \
 && chmod -R a+rX "${PLAYWRIGHT_BROWSERS_PATH:-/ms-playwright}" 2>/dev/null || true
USER pwuser

EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=5s --start-period=40s --retries=3 \
    CMD python -c "import urllib.request,sys; \
sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8080/api/health', timeout=4).status==200 else 1)"

CMD ["python", "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8080"]
