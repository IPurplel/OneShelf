# Implementation log and checkpoint — repair of the 2026-10-19 audit

Owner approval: the complete repair plan (WP-1…WP-14) was approved on 2026-10-19. Production deployment and
merging into `main` remain the owner's decisions. This log is the durable checkpoint for any later session.

## Branches (stacked; each PR targets the previous phase)

| Phase | Branch | Base | Work packages | Findings |
|---|---|---|---|---|
| 1 | `repair/be-phase1-security-jobs` | `audit/backend-reader-20261019` (= `main` + audit docs) | WP-1, WP-2 | BE-001, BE-005, BE-015, BE-016 |

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

## Next steps

Phase 2 (WP-5 → WP-6 → WP-7), then Phase 3 (WP-8, WP-9, WP-3, WP-4), then Phase 4 (WP-10…WP-14). See
`repair-plan.md`.
