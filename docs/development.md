# Development

## Backend (Python)

```sh
cd backend
python3 -m venv .venv
.venv/bin/pip install -r requirements.lock
.venv/bin/pip install -e .
.venv/bin/pytest                 # full suite; warnings are errors
```

Run locally (loopback only by default):

```sh
ONESHELF_DATA_DIR=.oneshelf-dev .venv/bin/python -m oneshelf
curl http://127.0.0.1:8420/api/health
```

| Variable | Default | Meaning |
|---|---|---|
| `ONESHELF_DATA_DIR` | `.oneshelf-dev` | application data (SQLite DB, migration snapshots) |
| `ONESHELF_HOST` / `ONESHELF_PORT` | `127.0.0.1` / `8420` | listen address |
| `ONESHELF_TRUSTED_NETWORKS` | empty (loopback only) | comma-separated CIDRs treated as trusted LAN |
| `ONESHELF_TRUSTED_PROXIES` | empty | comma-separated CIDRs whose `X-Forwarded-For` is honoured |

Remote (non-loopback, non-trusted-LAN) requests are refused until passkey authentication lands (C8).
Never point `ONESHELF_DATA_DIR` or storage roots at a real library while running tests or experiments.
