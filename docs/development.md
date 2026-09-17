# Development

## Backend (Python)

```sh
cd backend
python3 -m venv .venv
.venv/bin/pip install -r requirements.lock
.venv/bin/pip install -e .
.venv/bin/python -m playwright install chromium   # browser retrieval and Use My Session login
.venv/bin/pytest                                     # full suite; warnings are errors
.venv/bin/pytest -m "not browser"                    # skip real-Chromium tests
```

Never install `scrapling[fetchers]` (or any stealth/fingerprint package): OneShelf uses Scrapling's parser only,
and `tests/unit/test_no_stealth.py` fails if stealth tooling appears.

Run locally (loopback only by default):

```sh
ONESHELF_DATA_DIR=.oneshelf-dev .venv/bin/python -m oneshelf
curl http://127.0.0.1:8420/api/health
```

| Variable | Default | Meaning |
|---|---|---|
| `ONESHELF_DATA_DIR` | `.oneshelf-dev` | application data (SQLite DB, plugins, secrets.db, snapshots) |
| `ONESHELF_HOST` / `ONESHELF_PORT` | `127.0.0.1` / `8420` | listen address |
| `ONESHELF_TRUSTED_NETWORKS` | empty (loopback only) | comma-separated CIDRs treated as trusted LAN |
| `ONESHELF_TRUSTED_PROXIES` | empty | comma-separated CIDRs whose `X-Forwarded-For` is honoured |
| `ONESHELF_ALLOWED_HOSTS` | empty (IP literals and `localhost` only) | extra host names accepted in the `Host` header |
| `ONESHELF_SESSION_KEY_FILE` | `<data_dir>/keys/session.key` | source-session encryption key; mount on separate storage in deployments |
| `ONESHELF_REGISTRY_URL` | unset (no registry) | `https://…/index.json` static index or `file:///path/to/mirror` |
| `ONESHELF_REGISTRY_TRUSTED_KEYS` | unset | `key-id:base64-ed25519-public-key,…` for Official/Verified labels |
| `ONESHELF_DEV_TEST_SOURCE` | off | enables the OneShelf Test Source loopback exception (development only) |
| `ONESHELF_DEV_TEST_SOURCE_ADDRESS` | unset | `127.0.0.1:PORT` where `python -m testsource PORT` runs |

Remote (non-loopback, non-trusted-LAN) requests are refused until passkey authentication lands (C8).
Never point `ONESHELF_DATA_DIR` or storage roots at a real library while running tests or experiments.

## OneShelf Test Source

```sh
.venv/bin/python -m testsource 8421
ONESHELF_DEV_TEST_SOURCE=1 ONESHELF_DEV_TEST_SOURCE_ADDRESS=127.0.0.1:8421 ONESHELF_DATA_DIR=.oneshelf-dev .venv/bin/python -m oneshelf
.venv/bin/python -c "from testsource.build import build_package; build_package('testsource.osp')"
curl -X POST --data-binary @testsource.osp -H 'Content-Type: application/octet-stream' http://127.0.0.1:8420/api/sources/uploads
```

Scenarios are controlled with `POST /__control` on the Test Source (e.g. `{"big_collapsed": true}`, `{"paged_mode": "fail_page_3"}`,
`{"rate_limit_remaining": 2}`, `{"expire_sessions": true}`). Test login: `reader` / `correct horse`.

## API surfaces so far

| Area | Endpoints |
|---|---|
| Health / events | `GET /api/health`, `GET /api/events` (SSE) |
| Sources | `GET /api/sources`, `POST /api/sources/uploads`, `POST /api/sources/install`, `POST /api/sources/{id}/approve`, `POST /api/sources/{id}/{disable,enable,rollback}`, `DELETE /api/sources/{id}`, `GET /api/sources/{id}/health` |
| Registry | `GET /api/registry`, `POST /api/registry/install` |
| Sessions / login | `GET|DELETE /api/sources/{id}/session`, `POST /api/sources/{id}/session/validate`, `POST /api/sources/{id}/login`, `GET /api/logins/{id}/frame`, `POST /api/logins/{id}/{input,complete}`, `DELETE /api/logins/{id}` |
| Discovery | `GET /api/search` (SSE: `local` → `partial` → `complete`), `POST /api/search/retry`, `POST /api/resolve-url`, `GET /api/home` |
| Library identity | `POST /api/listings/bind`, `POST /api/mappings/{merge,split,unlink,never-match}` |
| Catalog trust | `GET /api/tracks/{id}/catalog`, `POST /api/tracks/{id}/catalog/refresh`, `POST /api/tracks/{id}/catalog/trust` |
| Downloads | `POST /api/downloads`, `GET /api/downloads[/{batch}]`, `POST /api/downloads/{batch}/{pause,resume,retry-failed,cancel,reorder}`, `POST /api/downloads/jobs/{job}/{retry,cancel}`, `DELETE /api/downloads/history` |
| Shelf | `GET /api/shelf` (views and `q=` local search), `POST /api/shelf/{work}`, `GET /api/shelf/{work}/removal-summary`, `DELETE /api/shelf/{work}`, `DELETE /api/works/{work}/files` |
| Follow | `GET /api/follows`, `POST /api/follows/{work}`, `POST /api/follows/{work}/{check,preferred-source}`, `POST /api/follows/check-all`, `DELETE /api/follows/{work}`, `POST /api/follows/undo` |
| Notifications / health | `GET /api/notifications[?attention=true]`, `POST /api/notifications/{mark-all-seen,clear-seen,cleanup}`, `GET /api/sources/{id}/health/state` |
| Reader | `GET /api/reader/units/{id}/pages`, `GET /api/reader/units/{id}/pages/{index}` (sandboxed bytes), `POST /api/reader/units/{id}/progress`, `POST /api/reader/units/{id}/{mark-read,mark-unread,engagement}`, `POST /api/reader/works/{id}/leave` |

Remote clients are refused until C8; LAN and loopback clients are served per `ONESHELF_TRUSTED_NETWORKS`.
