# Keep this image version aligned with requirements.txt.
FROM mcr.microsoft.com/playwright/python:v1.49.1-jammy

LABEL org.opencontainers.image.title="OneShelf" \
      org.opencontainers.image.description="Manga, comic, book and web novel downloader." \
      org.opencontainers.image.source="https://github.com/IPurplel/OneShelf" \
      org.opencontainers.image.licenses="MIT"

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    MD_CONFIG_FILE=/config/config.yaml \
    MD_OUTPUT_DIR=/data/manga \
    MD_CONFIG_DIR=/config

WORKDIR /app
USER root

# Chrome is available for linux/amd64. Xvfb provides a virtual display when the
# browser needs one; it does not guarantee completion of interactive checks.
RUN apt-get update \
 && apt-get install -y --no-install-recommends xvfb gnupg ca-certificates curl \
 && curl -fsSL https://dl.google.com/linux/linux_signing_key.pub -o /tmp/chrome-key.pub \
 && gpg --batch --dearmor -o /usr/share/keyrings/google-chrome.gpg /tmp/chrome-key.pub \
 && echo "deb [arch=amd64 signed-by=/usr/share/keyrings/google-chrome.gpg] https://dl.google.com/linux/chrome/deb/ stable main" \
      > /etc/apt/sources.list.d/google-chrome.list \
 && apt-get update \
 && apt-get install -y --no-install-recommends google-chrome-stable \
 && rm -f /tmp/chrome-key.pub \
 && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt \
 && patchright install chromium

COPY app/ ./app/
COPY web/ ./web/

# Empty named volumes inherit these directory permissions on first creation.
RUN mkdir -p /data/manga /config \
 && chown -R pwuser:pwuser /app /data /config \
 && chmod -R a+rX "${PLAYWRIGHT_BROWSERS_PATH:-/ms-playwright}"
USER pwuser

EXPOSE 8080
HEALTHCHECK --interval=10s --timeout=5s --start-period=40s --retries=3 \
    CMD python -c "import os,urllib.request; urllib.request.urlopen('http://127.0.0.1:' + os.environ.get('MD_PORT','8080') + '/api/health', timeout=4)"

# Read the configured address and port through the application.
CMD ["python", "-m", "app.main"]
