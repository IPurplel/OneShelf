# C1 — Verification Report: Architecture, Persistence, Safe Local Foundation

Recorded: 2026-09-17 · Branch: `c1/foundation` (from `docs/c0-baseline`) · Authority: Meta Prompt §C1
Status: **C1 gate passed** for the backend foundation described below. UI surfaces for these capabilities belong to C2+.

## Environment

| Item | Value |
|---|---|
| Python | 3.14.7 (host), project venv `backend/.venv` (not committed) |
| SQLite | 3.51.2 (FTS5 available) |
| Dependencies | pinned in `backend/requirements.lock`; declared in `backend/pyproject.toml` |
| Runtime deps | fastapi 0.141.1, starlette 1.6.0, uvicorn 0.53.0, pillow 12.3.0, pypdf 6.19.0, defusedxml 0.7.1 |
| Dev deps | pytest 9.1.1, httpx2 2.13.0 (Starlette 1.6's recommended TestClient transport) |
| Test policy | all warnings are errors, with one narrowly targeted ignore for a third-party anyio alias used inside `starlette.testclient` |

Dependency sources: the package index metadata on PyPI for each package (versions resolved on 2026-09-17). Pillow AVIF/WebP decode support verified at runtime (`PIL.features.check`).

## Commands and results

```sh
cd backend
python3 -m venv .venv && .venv/bin/pip install -r requirements.lock && .venv/bin/pip install -e .
.venv/bin/pytest            # → 158 passed, 0 failed, no warnings
```

Real-process smoke test (scratch data directory, loopback):

| Check | Result |
|---|---|
| `python -m oneshelf` starts, migrates, runs startup recovery | "Application startup complete"; `oneshelf.db` created |
| `GET /api/health` | `{"status":"ok","schema_version":1,"access":"loopback"}` |
| `GET /api/health` with forged `X-Forwarded-For: 203.0.113.9` from loopback | still `loopback` (header ignored; no trusted proxy) |
| `GET /api/events` | SSE `id: 0 / event: hello` frame |
| uvicorn options | `proxy_headers=False` confirmed (uvicorn's default is `True`, which would rewrite the peer address) |
| Shutdown | clean |

## Gate checklist (Meta Prompt §C1)

| Gate item | Evidence | Result |
|---|---|---|
| Schema migration / recovery | `tests/unit/test_db_migrations.py` (WAL/FULL/FK; transactional rollback of failed DDL; contiguous versions; newer schema refused byte-for-byte unchanged; consistent pre-migration snapshot via online backup API) · `tests/integration/test_app.py::test_newer_database_schema_refuses_to_start` | Pass |
| Same-title / source / language / format collisions | `tests/unit/test_schema.py` (same-title Works; one track per work+source+language; repeated unit numbers legal; source key identity; asset path unique per root; one asset per unit+format+variant) · `tests/integration/test_local_import.py` (same-title local works get distinct paths; PDF+EPUB coexist on one unit; same format twice refused without overwrite; languages → separate local tracks) | Pass |
| Path / symlink safety | `tests/unit/test_paths.py` (traversal, absolute, drive, UNC, NUL, symlinked dir escape, symlinked file, delete only regular files in root, hostile titles/sources/languages, bidi controls stripped, Arabic preserved, UTF-8 byte truncation, reserved names) · schema CHECK rejects absolute asset paths | Pass |
| Unavailable roots | `tests/unit/test_roots.py` (marker missing/mismatch/path missing → unavailable) · `tests/integration/test_scanner.py::test_offline_root_is_unavailable_not_mass_missing` · import refuses before writing · commit recovery skips offline roots untouched · staging cleanup skips offline roots | Pass |
| Crash injection around final rename and DB registration | `tests/unit/test_commit_journal.py` (crash after journal / move / verify / register; crash between link and unlink; failing registrar; lost staging; torn final write; persistent registrar failure isolated) · `tests/integration/test_local_import.py::test_crash_mid_commit_recovers_to_one_registration` | Pass |
| Repeatable reconciliation | second `recover()` reports `changed == 0`; second `reconcile()` reports `changed == 0` | Pass |
| No incomplete artifact marked downloaded/registered | corrupt final after move → aborted, never registered; staged copy validated before commit (HTML-as-image, corrupt/empty images, truncated PDF, broken EPUB spine, zip bombs, zip-slip names, XML entity attacks rejected) | Pass |
| Isolated test data | every test uses pytest `tmp_path`; no real library paths | Pass |

## What C1 delivers (backend)

| Area | Module | Notes |
|---|---|---|
| Defaults registry (§42, D2) | `oneshelf/settings/defaults.py` | single immutable source |
| SQLite policy + migrations (§18) | `oneshelf/db/connection.py`, `oneshelf/db/migrate.py`, `oneshelf/db/schema/0001_initial.sql` | 21 domain tables incl. future-phase boundaries (catalog snapshots, follows, jobs, notifications, backups, exports, session refs) |
| Stable IDs | `oneshelf/domain/ids.py` | 12-char lowercase base32 |
| Storage roots, disk guard, remap (§24.1, §24.5–24.6, §24.8 remap) | `oneshelf/storage/roots.py` | identity marker `<root>/.oneshelf/root.json` |
| Safe naming / containment (§24.2, §24.4) | `oneshelf/storage/paths.py`, `oneshelf/storage/layout.py` | Family / Work [id] / Language / Source / Unit [id].ext |
| Per-root staging (§24.3) | `oneshelf/storage/staging.py` | same-filesystem check; owner metadata |
| Commit journal (§17) | `oneshelf/storage/commit.py` | pending → moved → verified → registered → done |
| Integrity validation (§16.5, §39) | `oneshelf/integrity/validators.py` | content sniffing; CBZ/PDF/EPUB |
| Local import (§4.6, §22, §37) | `oneshelf/importer/service.py` | Copy default, explicit Move; explicit Choose Work / Create Local Work |
| Scanner (§24.7, §38) | `oneshelf/storage/scanner.py` | missing / corrupt / restored / relocated-by-ID |
| Staging cleanup + startup order (§17, §25) | `oneshelf/storage/staging_cleanup.py`, `oneshelf/services/startup.py` | recover jobs → commits → reconcile → proven-orphan cleanup |
| Access boundary (§28.1–28.2, K4) | `oneshelf/api/access.py`, `oneshelf/api/middleware.py` | remote denied until C8 passkeys |
| Event bus + SSE (§36, K5) | `oneshelf/events/bus.py`, `GET /api/events` | non-blocking fan-out with resync |
| App entry | `oneshelf/api/app.py`, `python -m oneshelf` | `ONESHELF_DATA_DIR`, `ONESHELF_TRUSTED_NETWORKS`, `ONESHELF_TRUSTED_PROXIES`, `ONESHELF_HOST`, `ONESHELF_PORT` |

## Persistent record ownership and cleanup classes

| Record / location | Owner | Cleanup class |
|---|---|---|
| `works`, `work_aliases`, `source_listings`, `source_tracks`, `reading_units` | catalog/import services | authoritative; never removed by cleanup; FK-restricted while assets exist |
| `assets` + managed files | storage/commit journal | authoritative; only explicit user Delete Files (later phase) removes files; scanner only updates `integrity`/`relative_path` |
| `shelf_entries`, `follows`, `reading_state`, `work_mappings`, `user_overrides` | user actions | authoritative; independent of each other |
| `commit_journal` | commit engine | kept (done/aborted) as local history; bounded retention to be defined with Download History (C5) |
| `imports` | importer | operation history; bounded with other histories (C6/C7) |
| `<root>/.oneshelf/staging/*` | staging owner (import/download) | proven-orphan cleanup after recovery: success leftovers 24 h, resumable partials 7 d, unknown areas 7 d, never while a commit or owner is open |
| `snapshots/pre-migration-*.db` | migration runner | kept; retention policy to be defined with backups (C7) |
| `storage_roots` + `root.json` marker | storage | authoritative; roots are never deleted automatically |

## Known limitations / carried forward (not gate failures)

- **OneShelf Test Source skeleton (K5)** was not started in C1; it moves to C3, where the network transport it exercises exists. Recorded in traceability (M41.2).
- **Confident import association** (OneShelf export metadata / managed IDs) is not implemented; C1 import requires an explicit decision, per §37 "never aggressively merge". Planned with C4 matching / C7 import.
- **A2 warning heuristic** (all clients from one gateway) and trusted-network setup UI belong to C8 first run.
- **Remote Origin/CSRF** enforcement is moot while all remote requests are denied; implemented with passkey sessions in C8.
- **Storage migration copy flow** (§24.8 preflight → copy → verify → switch) is C7; C1 implements mount-path remap only.
- **Commit journal / import history retention** bounds are defined with the history subsystems in C5–C7.
- **Container verification** remains blocked on this host (EB-1).
