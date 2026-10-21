# Implementation log and checkpoint — repair of the 2026-10-19 audit

Owner approval: the complete repair plan (WP-1…WP-14) was approved on 2026-10-19. Production deployment and
merging into `main` remain the owner's decisions. This log is the durable checkpoint for any later session.

## Branches (stacked; each PR targets the previous phase)

| Phase | Branch | Base | Work packages | Findings |
|---|---|---|---|---|
| 1 | `repair/be-phase1-security-jobs` (PR #4) | `audit/backend-reader-20261019` (= `main` + audit docs) | WP-1, WP-2 | BE-001, BE-005, BE-015, BE-016 |
| 2 | `repair/be-phase2-classification` (PR #5) | phase 1 | WP-5, WP-6, WP-7 | BE-002, BE-003, BE-004, BE-012 |
| 3 | `repair/be-phase3-responsiveness` (PR #7) | phase 2 | WP-3, WP-4, WP-8, WP-9 | BE-006, BE-007, BE-008, BE-009, BE-011, BE-019 |
| 4 | `repair/be-phase4-functional` | phase 3 | WP-10, WP-11, WP-12, WP-13, WP-14 | BE-010, BE-013, BE-014, BE-017, BE-018 |
| — | OneShelf-Adapters `fix/core-audit-20261019` (OneShelf-Adapters PR #5) | adapters `main` | WP-14 (adapters) | BE-014 |

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
Live product journey on this branch (2026-10-20): **4 passed** (MangaDex, 3asq, WEBTOON, Tapas; one chapter each through the streaming transport and off-loop commit, each CBZ opened). Recorded on PR #7.

## Phase 4 — remaining functional defects and adapters

| Finding | Ledger | Fix | Regression tests |
|---|---|---|---|
| BE-010 | I-100 | `follow/service.py`: a Follow made with no trusted catalog has a *pending* baseline (no baseline row); the first check that finds a trusted catalog sets it silently. Also for source changes and Undo. `FollowStatus.baseline_pending` | `test_shelf_and_follow.py::test_i100_*` (3). `test_audit_regressions.py::test_following_a_second_language_keeps_both_baselines` now gives both tracks a trusted catalog first (intent unchanged) |
| BE-013 | I-103 | `formats` on `POST /api/downloads` (one job and one asset per chosen format); `choose_file` (the chosen format, else EPUB > PDF > CBZ); `format_unavailable` is terminal; `GET /api/reading-units/{id}/formats`; `ExtractionContract.file_format` | `test_engine.py::test_i103_*` (4), `test_library_api.py::test_i103_*` |
| BE-018 | I-108 | Once the file is chosen, its declared size (less what is staged) is checked against the reserve before fetching | `test_engine.py::test_i108_*` |
| BE-017 | I-107 | `reader/service.py`: non-200 pages raise `SOURCE_FAILED` with the status and record health (404 as missing content). A 403/404/410 refreshes the page list once (expiring links). The page-list memory is an LRU of 256 units with a 30-minute TTL, and an empty listing is never remembered. Page lists persist beside the Reader Cache, so cached pages stay readable while the source is disabled; otherwise `SOURCE_UNAVAILABLE` (409) | `test_reading.py::test_i107_*` (5), `test_library_api.py::test_i107_*` |
| BE-014 | I-104 | Core: `net/http.py::secure_redirect` follows a same-host redirect to plain http over https (Safahat). The bundled snapshot is synced from OneShelf-Adapters `8955ff7` (Gutenberg 2.0.1, MangaDex 1.0.3, 3asq 1.0.2, and the rest at their Registry versions); the MangaDex local hotfix is gone. Adapters: OneShelf-Adapters PR #5 (MangaDex 1.0.3 with the translation-language fields and a health test; 3asq 1.0.2, where lettered units "0A"…"0P" get no number) | `test_http_stream.py::test_i104_*` (6). Adapters: `./tools/check-all` (264 tests, Registry verified), `tests/test_official_3asq_numbering.py`. Live: Hindawi Latin query → genuine empty result |

Test infrastructure:
- Test Source: an `editions` unit (PDF then EPUB, the EPUB with a declared size), and opt-in `expiring_pages`
  and `missing_pages` scenarios.
- `tests/fixtures/official-adapters-frozen/`: the pre-refresh official adapters. Mechanism tests read them, so
  a snapshot refresh no longer changes what those tests test.
- Live suite: the Gutenberg test resolves a book by its address (2.0 has no search, per robots.txt). The arXiv
  test skips when arXiv rate-limits or times out (E-03).

Live checks, 2026-10-20: `tests/live/test_product_journey.py` on this branch gave **4 passed**: MangaDex 1.0.3, 3asq 1.0.2, WEBTOON and Tapas 1.0.1, each a CBZ that opened. `tests/live/test_source_suite.py` gave 7 passed. arXiv was **BLOCKED** at the
source: 429 Too Many Requests, then a read timeout. The earlier WEBTOON failure (BE-019's leaked socket) no
longer occurs.

Isolated full-app check (all four phases plus the unchanged frontend, built locally; fresh data on port 8432;
no production involvement):
- With no storage location, a download is refused with 409 `NO_STORAGE_LOCATION`. After adding one:
  - 3asq from an Arabic search opens as **manga · Arabic** (`plugin_default`), and its chapter downloads as a
    CBZ that the Reader shows locally.
  - Hindawi opens as **book · Arabic**, and `/formats` lists EPUB and PDF.
  - A background Library Backup completes with status 200.
  - With MangaDex disabled, an online unit's context stays `images`, its page list answers, and its cached
    pages are served (`origin=cache`).
- `scripts/agent/browser_check.py` over 10 routes at desktop and mobile size (Home, Search, Downloads,
  Sources, Settings, three Works, two Readers): **0 console errors, 0 page exceptions, 0 failed requests**.
- The Work page shows "Manga · Arabic" where production shows "unknown · Unknown language".
- Evidence (screenshots and report) is kept out of the repository in the session scratchpad.
- Observation for Codex, not a backend matter: in the Long Strip reader at 1440 px the page sits at the left
  with black space to its right. Production shows the same.

Gutenberg trade-off (owner decision on deploy): on an existing installation the bundled Gutenberg 2.0.1 asks
for new network permissions, so it waits for review (a Plugin Update notification). Search goes away only
when the owner approves it. 1.0.0's search used endpoints that gutenberg.org's and Gutendex's robots.txt
disallow, and it timed out on every query.

Known limit (I-100): Follows created by older builds with an empty baseline cannot be told apart from Follows
of a genuinely empty catalog, so they are left as they are.

Tests: `pytest -m "not browser and not live"` gives **1,581 passed, 1 skipped**.

## Merge order

1. OneShelf PR #4 (phase 1) → `main`.
2. OneShelf PR #5 (phase 2), retargeted to `main`.
3. OneShelf PR #7 (phase 3), retargeted to `main`.
4. OneShelf-Adapters PR #5, with a merge commit so `8955ff7` stays on its `main`, then publish the Registry.
5. OneShelf phase 4 PR, retargeted to `main`.

After deploying: add a Storage Location, cancel batch `e2gvnow3lv7r`, run the reclassification preview then
apply, and review the Gutenberg update. Then run the browser verification on production (AGENTS.md).
