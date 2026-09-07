# OneShelf development

The supported deployment entry point is `bash startup.sh`. It builds local
source through `deploy/docker-compose.yml` and `deploy/Dockerfile`. There is
no frontend build step.

## Tests

For development checks, install `requirements-dev.txt` into an isolated Python
environment. The application dependencies are pinned in `requirements.txt`.

```bash
python -m pytest -q
python -m pyflakes app tests
bash -n startup.sh
```

The test suite uses saved HTML and fake network clients. Startup tests run the
real Bash script against a simulated Docker CLI; they do not build a container.
Run these tests on Linux or another environment with `/bin/bash` and `/bin/sh`.

Before releasing deployment changes, also validate the resolved Compose
configuration and run a clean installation on a Docker-capable host. Confirm
browser startup, health, writable volumes, restart/recreation persistence, and
UI/API/live progress from another LAN device.

## Code layout

- `app/adapters/`: identify source platforms and extract titles, chapters, and files.
- `app/session.py` and `app/browser.py`: browser sessions and page retrieval.
- `app/fetcher.py`: HTTP requests, retries, and image fetching.
- `app/queue.py` and `app/packager.py`: resumable jobs and archive creation.
- `web/`: browser UI, served by the application.
- `tools/optimize_cbz.py`: optional utility for existing CBZ files.

For a new source adapter, subclass `Adapter`, implement its extraction methods,
and register it in the adapter registry. Prefer DOM fingerprints to hostname
checks when supporting a shared site theme. Add saved HTML fixtures and test
both useful matches and unrelated searches that should return nothing.

[HANDOFF.md](../HANDOFF.md) preserves historical source investigations. Treat
its measurements as observations from those sessions, not current guarantees
about external sites or deployment instructions.
