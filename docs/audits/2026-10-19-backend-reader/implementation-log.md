# Implementation log and checkpoint — repair of the 2026-10-19 audit

Owner approval: the complete repair plan (WP-1…WP-14) was approved on 2026-10-19. Production deployment and
merging into `main` remain the owner's decisions. This log is the durable checkpoint for any later session.

## Branches (stacked; each PR targets the previous phase)

| Phase | Branch | Base | Work packages | Findings |
|---|---|---|---|---|
| 1 | `repair/be-phase1-security-jobs` (PR #4) | `audit/backend-reader-20261019` (= `main` + audit docs) | WP-1, WP-2 | BE-001, BE-005, BE-015, BE-016 |
| 2 | `repair/be-phase2-classification` (PR #5) | phase 1 | WP-5, WP-6, WP-7 | BE-002, BE-003, BE-004, BE-012 |
| 3 | `repair/be-phase3-responsiveness` | phase 2 | WP-3, WP-4, WP-8, WP-9 | BE-006, BE-007, BE-008, BE-009, BE-011, BE-019 |

Worktree used: `/tmp/oneshelf-repair` (its venv is a symlink to the audit worktree's venv). The primary
checkout `Oneshelfv1/` and its uncommitted work are untouched.

## Phase 1 — security and download stability

| Finding | Ledger | Fix | Regression tests (all failed before the fix) |
|---|---|---|---|
| BE-001 | I-91 | `api/auth.py::lan_only` guards `/api/auth/networks`, `/api/auth/hostname`, `/api/first-run/access-mode`. `auth/policy.py` validates proxy ranges (explicit private/CGNAT/loopback/link-local/ULA list, maximum width /8 or /32). Stored unsafe proxies are ignored and reported (`ignored_proxies`) | `tests/integration/test_auth_api.py::test_i91_*` (4 tests, 10 cases). The private BE-001 probe now ends 403/401/401 |
| BE-015 | I-105 | `backup/service.py`: the remote-auth tables are excluded, and a `KEPT_TABLES` inventory was added | `tests/integration/backup/test_backup.py::test_i105_*` |
| BE-005 | I-95 | `downloads/engine.py`: `NoStorageLocation` at enqueue (API 409), terminal `too_large`, `TooManyRedirects` → `transport`, a catch-all → `internal_error`, recovery fails exhausted jobs (`interrupted`). `downloads/contract.py` `TERMINAL`. `reader/service.py` auto-download skips quietly | `tests/integration/downloads/test_engine.py::test_i95_*` (5) |
| BE-016 | I-106 | `batch()` `canceled` state. `notifications/service.py::storage_unavailable`. Real free bytes for low storage | `test_engine.py::test_i106_*` (2) |

Deviation from the plan text: the plan said stored unsafe proxies are "reported, never silently dropped". They
are reported **and not honoured**. Honouring them would keep the vulnerability open. The stored value is kept,
so the person can see and correct it.

Tests: the full `pytest -m "not browser and not live"` gives **1,505 passed, 1 skipped** (baseline 1,485 + 20 new). One pre-existing test
(`test_open_and_covers.py::test_unlinked_source_track_cannot_refresh_from_old_listing`) initially received the
new 409 before its expected 422. The storage check now runs after the per-unit checks, so the more specific
refusal wins, and that test passes unchanged.

## Phase 2 — metadata, classification, manga and comic downloads

| Finding | Ledger | Fix | Regression tests |
|---|---|---|---|
| BE-012 | I-102 | `library/overrides.py` (corrections stored in `user_overrides`, mirrored into the columns readers use, and re-applied after every catalog refresh and restore merge). `PATCH /api/works/{id}`, `PATCH /api/reading-units/{id}` | `tests/integration/library/test_overrides.py` (4), `test_restore.py::test_i102_*` (confirmed failing without the post-merge re-application) |
| BE-002 | I-92 | `plugins/classification.py`: one classifier (source value > plugin default > Unknown) used by search, URL resolution and `/api/listings/{open,bind}`. Works record `content_type_source` | `tests/unit/plugins/test_classification.py` (5), `tests/integration/test_classification_api.py` (5) |
| BE-004 | I-94 | `persist_listing` upgrades an `und` track in place (and its Follow) instead of twinning, and reuses the single known track for a language-less request. `library/reclassify.py` provides a preview (`GET /api/maintenance/reclassification`) and an apply (`POST`, with a snapshot, one transaction, idempotent) for existing data | `test_classification_api.py::test_i94_*`, `tests/integration/library/test_reclassify.py` (4, including the rollback test) |
| BE-003 | I-93 | `downloads/engine.py::required_output` comes from the recipe, not the Work label | `test_engine.py::test_i93_*` (4). Live: `tests/live/test_product_journey.py`, 4/4 passed on 2026-10-19 (MangaDex, 3asq as `ar`/`manga`, WEBTOON as `unknown` → CBZ, Tapas as `comic`) |

Test Source change: the `unlabelled` work (no type or language in its results, like 3asq) and a `manga` default
type in its manifest, so the default path runs in the ordinary suite.

Migration safety (WP-6):
- The repair is explicit: preview, then apply. It never runs at startup, so production data changes only when
  the owner applies it.
- A consistent snapshot is written to `<data>/snapshots/pre-reclassification-*.db` before any write. The whole
  repair runs in one transaction; a forced failure leaves the library unchanged (tested).
- A second apply is a no-op (tested). User-sourced types and local-only Works are never touched.
- Files are never renamed. Already-downloaded files keep their old `und/` and `Other/` folders (§24.2: no
  automatic moves).

Guard update: `tests/unit/test_suite_is_isolated.py` now allows every live test under `tests/live/`, not only
the original file.

Tests: `pytest -m "not browser and not live"` gives **1,528 passed, 1 skipped**.

## Phase 3 — responsiveness, streaming, resume and safe replacement

| Finding | Ledger | Fix | Regression tests |
|---|---|---|---|
| BE-011 | I-101 | `net/http.py::HttpClient.stream_to` writes bodies to disk in 64 KiB chunks. The engine's pages and files go through `SourceService.fetch_resource_to`. `/api/reader/units/{id}/file` is a Range-capable `FileResponse` | `tests/unit/net/test_http_stream.py::test_i101_*` (48 MiB streamed at a peak under 8 MiB; the size cap still holds), `test_work_api.py::test_i101_*` (206 with the same isolation headers) |
| BE-007 | I-97 | `stream_to` appends only on a 206 for exactly the asked offset and the same version; 416, a full answer or a changed version start over. The engine resumes only a file shorter than its known total and discards a body that fails validation. `retry_job` resets the file | `test_http_stream.py::test_i97_*` (3), `test_engine.py::test_i97_*` (2) |
| BE-019 | I-109 | `fetch` and `stream_to` share one redirect and policy loop that closes the connection on any error | `test_http_stream.py::test_i109_*` (no ResourceWarning after read timeouts) |
| BE-008, BE-009 | I-98, I-99 | Replace-commit: a commit may name the copy it replaces. The journal retires the old file into the commit's staging area, moves the verified artifact in, deletes the old file only after registration, and restores it on abort. The registrar updates the existing asset row. Enqueue deletes nothing and skips units with a sound copy | `test_engine.py::test_i98_*` (2), `test_i99_*` (7, including crash at each of five points), `tests/unit/test_commit_journal.py` (replacing-commit crashes at every point, same path and renamed title; aborted replacement restores the old copy) |
| BE-006 | I-96 | `services/worker.py`: backup, verify, restore preflight and restore, export, scan, import and migration run in worker threads with their own SQLite connection. The engine's validation, packaging and hashing run in threads and its commit on a worker. `services/tasks.py` + `?background=true` turns those jobs into tasks (202, `GET /api/tasks/{id}`, `task.finished` event) | `tests/integration/test_responsiveness.py` (worst `/api/health` during a 96 MB Full Backup: 1,170 ms before, 2 ms after; background-task outcome and failure), `test_engine.py::test_i96_*` (engine event-loop lag: 2.05 s before, under 250 ms after) |

Notes:
- The online Reader still fetches pages into memory (they are capped at 64 MiB by `fetch` and go straight to the
  Reader Cache). Only downloads and local-file serving stream.
- WP-8's request-bound endpoints were kept for compatibility; `?background=true` is additive (H-9).
- An unexpected regression during the engine offload (a dropped variable in an edit) was caught by the suite
  (38 failures) and fixed before commit; the saved WIP patch is no longer needed.

Tests: `pytest -m "not browser and not live"` gives **1,560 passed, 1 skipped**.
Live product journey on this branch: recorded below once the run finishes.

## Next steps

Phase 4: WP-10 (Follow baseline pending), WP-11 (format selection), WP-12 (Reader errors and descriptor cache),
WP-13 (preflight with known sizes), WP-14 (adapters and Registry reconciliation); handoffs H-4, H-5, H-8.
