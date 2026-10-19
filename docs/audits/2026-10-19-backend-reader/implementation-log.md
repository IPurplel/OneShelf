# Implementation log and checkpoint — repair of the 2026-10-19 audit

Owner approval: the complete repair plan (WP-1…WP-14) was approved on 2026-10-19. Production deployment and
merging into `main` remain the owner's decisions. This log is the durable checkpoint for any later session.

## Branches (stacked; each PR targets the previous phase)

| Phase | Branch | Base | Work packages | Findings |
|---|---|---|---|---|
| 1 | `repair/be-phase1-security-jobs` (PR #4) | `audit/backend-reader-20261019` (= `main` + audit docs) | WP-1, WP-2 | BE-001, BE-005, BE-015, BE-016 |
| 2 | `repair/be-phase2-classification` | phase 1 | WP-5, WP-6, WP-7 | BE-002, BE-003, BE-004, BE-012 |

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

## Next steps

Phase 3 (WP-8, WP-9, WP-3, WP-4), then Phase 4 (WP-10…WP-14). See
`repair-plan.md`.
