# C5 — Verification Report: Downloads, Recovery and Online Reading

Recorded: 2026-09-17 · Branch: `c5/downloads` (from `c4/catalog-search` @ `2daa840`) · Authority: Meta Prompt §C5
Status: **C5 gate passed** for the backend described below, with one item carried forward (browser-method downloads, see limitations). Reader and Downloads screens are C2; Follow, notifications and health states are C6.

## Commands and results

```sh
cd backend
.venv/bin/pytest          # → 577 passed (C1 158 + C3 279 + C4 90 + C5 50), no warnings
```

No new dependencies.

## Gate checklist (Meta Prompt §C5)

| Gate item | Evidence | Result |
|---|---|---|
| Restart / queue recovery | `test_engine.py::test_crash_during_download_recovers_without_duplicates` (crash mid-download → `recover()` re-queues → completes once) · `services/startup.py::_recover_download_jobs` runs before reconciliation and staging cleanup · `DownloadRunner.start()` recovers on boot | Pass |
| Partial batch success and Retry All Failed | `test_partial_batch_success_and_retry_all_failed` (2 completed, 1 failed → `completed_with_issues`; retry re-queues only the failed job; successful units survive) · API `POST /api/downloads/{id}/retry-failed` | Pass |
| Range / If-Range and changed ETag | `test_changed_validator_restarts_the_file_instead_of_splicing` (partial file + changed validator → clean restart; final file parses as the new version) · resume path sends `Range` + `If-Range` and only appends on `206` with an unchanged validator | Pass |
| HTML-as-media and corruption | `test_invalid_media_never_becomes_downloaded_content` (HTML served as PNG, and a truncated PNG) → job FAILED `media_invalid`, no asset row, no final file (INV-16) | Pass |
| Crash at every commit boundary | C1 `test_commit_journal.py` (after journal/move/verify/register, link-without-unlink, failing registrar) now also replays the `download` registrar; `services/registrars.py` includes it so startup recovery completes interrupted download commits | Pass |
| Independent HTTP / browser limits | C3 `test_governor.py` (browser capacity independent, background browser preempted, reserved foreground HTTP slot) | Pass |
| Reader priority under saturated background work | `test_reader_stays_responsive_while_downloads_saturate_the_governor` (40 queued units downloading; a Reader page still returns in < 3 s) | Pass |
| Reading without permanent download | `test_reading_online_never_downloads_permanently`, API `test_reading_online_is_not_a_download` (no assets, no files, no batches) | Pass |
| Enabled engagement trigger | `test_engagement_threshold_and_genuine_interaction` (off by default; below 12% nothing; no interaction nothing; 12% + interaction queues once) | Pass |
| Leaving the Work cancels unstarted read-ahead | `test_leaving_the_work_cancels_unstarted_read_ahead_only` (4 queued cancelled, the started job and the unit being read continue) | Pass |
| Cache eviction protections | `test_cache_eviction_protects_the_current_unit_and_permanent_files` (open unit's pages survive eviction; downloaded units are read locally and never enter the cache) | Pass |
| Waits rather than blind retries | `test_rate_limited_media_waits_then_completes` (429 → `WAITING_FOR_RATE_LIMIT` with `next_attempt_at`) · `test_auth_failure_waits_for_session_and_resumes_after_connect` (→ `WAITING_FOR_SESSION`, resumes after reconnect) | Pass |
| History separate from content | `test_history_records_methods_and_clearing_keeps_content_and_progress`, API `test_batch_controls_and_history_clearing` (INV-23) | Pass |

## What C5 delivers (backend)

| Area | Modules |
|---|---|
| Extraction Contracts, method precedence, Smart Retry and fallback policy | `downloads/contract.py` (+ scoped `settings` table) |
| Download engine: batches, jobs, windowed scheduling, resume manifests, integrity, packaging, commit | `downloads/engine.py`, migration `0007_downloads.sql` |
| Background runner and startup recovery | `downloads/runner.py`, `services/startup.py` |
| Reader Cache (TTL/cap/LRU with protections) | `reader/cache.py` |
| Reader backend: local/online pages, progress with revisions, auto-download while reading | `reader/service.py` |
| API | `api/library.py`: `POST/GET /api/downloads`, batch and job actions, reorder, `DELETE /api/downloads/history`, reader pages (sandboxed content headers), progress, mark read/unread, engagement, leave work |

## Known limitations / carried forward (not gate failures)

- **Browser-method downloads and interrupted browser manifests** are not exercised yet: the method exists in the contract and browser retrieval works (C3), but no packaged source declares a browser reader recipe, so resume-after-interruption for browser manifests moves to C9 with the generator and the real §41 sources.
- **Repair of a single page** (§16.5) is available through re-running a job; a targeted per-page repair action belongs with the Reader UI (C2) and is not yet exposed.
- **Cancel keep-partial** is a setting (`downloads.keep_partial_on_cancel`); the Settings screen is C2.
- **Notifications** for failures, rate limits and reconnects are C6; C5 records the states and history rows they will present.
- **Untrusted document isolation** (§27) is enforced on the content route (sandbox CSP, nosniff, no store); the isolated viewer itself is C2.
- **Auto-download read-ahead** currently follows the unit's own track; "current + read ahead" across preferred-source changes is revisited with Follow in C6.
