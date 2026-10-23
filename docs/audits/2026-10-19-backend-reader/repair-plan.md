# Repair plan — for owner approval (2026-10-19)

**Status: PROPOSED.** No application code was changed by this audit. Each work package (WP) below becomes a
branch and PR only after the owner approves it. Within a WP, a regression test that fails on today's `main`
is written first (TDD), as `docs/plan/ISSUES.md` requires ("closed only when its test exists and fails
without the fix").

Ordering rule: security first, then the pipeline foundations other fixes depend on, then identity and
classification (which needs a data migration), then performance, then the rest. Findings are in
`findings.md`.

## R0 · Owner actions on production (no code, can happen today)

| # | Action | Why |
|---|---|---|
| R0-1 | Settings → Storage (or finish First Run): add a Storage Location for the library | Production has `roots: []`. Every download hangs (BE-005) |
| R0-2 | Downloads: Cancel batch `e2gvnow3lv7r` (job `t5gehagbczci`, stuck `PREPARING`) | Clears the never-ending "1 waiting" |
| R0-3 | Sources: decide whether to update bundled **Gutenberg 1.0.0 → Registry 2.0.1** (fixes the always-failing search by removing search; URL entry only), **Standard Ebooks 1.0.0 → 1.1.1**, **arXiv 1.0.0 → 1.0.1** | BE-014. A product decision, because Gutenberg 2.0.1 drops search |
| R0-4 | Remote access stays off until WP-1 ships | BE-001 needs a remote session to exploit. None exists today |

## Dependency graph

```
WP-1 (security) ─────────────────────────────── independent
WP-2 (job failure safety) ──► WP-3 (resume) ──► WP-4 (replace-commit: re-download + repair)
WP-5 (override write path) ──► WP-6 (classifier + migration) ──► WP-7 (output from recipe)
WP-8 (off-loop heavy work) ──► WP-9 (streaming + Range)
WP-10 … WP-13 independent, after WP-2
WP-14 adapters (OneShelf-Adapters repo), anytime
```

## Work packages

### WP-1 · Lock the trust boundary to genuine LAN (BE-001, BE-015) · P1

- **Modules:** `oneshelf/api/auth.py` (new `require_genuine_lan`; apply it to `/networks` and `/hostname`.
  `/lan-recovery` already checks the access kind; optionally add passkey re-auth for remote passkey
  deletion), `oneshelf/api/firstrun.py` (access-mode writes),
  `oneshelf/auth/policy.py` (`_require_private_proxies`, minimum prefix), `oneshelf/backup/service.py`
  (`EXCLUDED_TABLES` += `remote_sessions`, `remote_recovery`, `remote_credentials`, `webauthn_challenges`).
- **Safeguards:** LAN and loopback behaviour is unchanged. Existing stored proxy settings that are now invalid
  are *reported* at startup (diagnostic plus Needs Attention), never silently dropped. Restore already
  ignores these tables.
- **Regression tests:** remote session → 403 `LAN_REQUIRED` on each guarded route. Proxies `0.0.0.0/0`,
  `::/0` and `203.0.113.0/24` → 422. The private BE-001 probe scenario ends refused. A backup
  contains zero rows in the four tables. A table-inventory guard fails when a new table is neither in the
  backup allow-list nor excluded.
- **Acceptance:** `pytest tests/integration/test_auth_api.py tests/integration/backup` is green, plus the new
  tests.

### WP-2 · No job is ever stranded in an active state (BE-005, BE-016) · P1

- **Modules:** `oneshelf/downloads/engine.py`. In `enqueue`, validate an available root and raise
  `NoStorageLocation`. In `_process`, after the specific handlers, `except Exception` →
  `_handle_failure(category="internal_error")`. Map `ResponseTooLarge` → `too_large` and `TooManyRedirects`
  → `transport`. In `recover()`, cap recoveries per job. In `batch()`, add a `canceled` state. Also
  `oneshelf/api/library.py` (409 `NO_STORAGE_LOCATION`) and `oneshelf/notifications/service.py` (new
  `storage_unavailable(root)`, real free bytes in `low_storage`).
- **Safeguards:** terminal `FAILED` keeps the staging area for the resumable window (§25). No content is
  deleted. History and notification go through the existing paths.
- **Regression tests:** convert the audit probes `test_c1`, `test_c1b` (no root) and ResponseTooLarge /
  TooManyRedirects into product tests that assert `FAILED`, a history row and one notification. A poisoned
  job recovered three times ends `FAILED`. An all-canceled batch → `canceled`. Offline root → the
  `storage-unavailable:<root>` notification.

### WP-3 · Correct direct-file resume and retry (BE-007, BE-019) · P2

- **Modules:** `oneshelf/downloads/engine.py::_download_file` (record `Content-Length`; resume only when
  `bytes < expected`; treat 416 as a clean restart; discard the body after a validation failure),
  `retry_job` (reset the file manifest unless `resume=True`), `oneshelf/net/http.py` (explicit
  `resp.close()`/`release()` on exceptions inside the response context).
- **Safeguards:** a changed validator still never splices (the existing test is kept). `If-Range` is still
  sent.
- **Regression tests:** probe `test_c2` → `COMPLETED`. Test Source `interrupted` plus a read timeout under
  `-W error::ResourceWarning` → no leak. The existing ETag-change test stays green.

### WP-4 · Replace-commit: re-download and Repair never orphan or pre-delete (BE-008, BE-009) · P2

- **Modules:** `oneshelf/storage/commit.py` (a registration `kind: "download_replace"` whose registrar
  atomically updates the existing non-`ok` asset row; the old file moves to
  `<root>/.oneshelf/staging/trash/` at `moved` and is deleted only at `done`). In
  `oneshelf/downloads/engine.py`, remove `_clear_broken_copy` from `enqueue`, and pick replace-registration
  when the unit has a non-`ok` asset of the same format and variant. In `register_download`, use an upsert
  for non-`ok` rows.
- **Safeguards:** fault injection at every journal step (existing `FAULT_POINTS` plus the new trash step).
  Recovery must be idempotent (INV-17). A healthy `ok` asset is never replaced (§33.7 parallel).
- **Regression tests:** probes `test_c4` (source offline → the asset and file remain) and `test_c5` (→
  `COMPLETED`, journal `done`, no orphan, second boot is a no-op). A crash at each step and repeated recovery
  give one asset row and no trash leftovers.

### WP-5 · User override write path (BE-012) · P2 · prerequisite for WP-6

- **Modules:** a new `oneshelf/library/overrides.py` service (`set`/`clear` on `user_overrides`, events).
  `oneshelf/api/works.py` (`PATCH /api/works/{id}`), `PATCH /api/tracks/{id}` (language, with explicit
  `confirm_identity_change`), `PATCH /api/reading-units/{id}` (user number, title, type). Read-side
  application in `api/works.py`, `reader/alternatives.py` and `catalog/trust.py::_materialize` (never write
  over override-backed fields).
- **Safeguards:** overrides are separate rows, so they can be cleared to revert. Backup and restore already
  carry `user_overrides`, and restore merge keeps current overrides (§33.7).
- **Regression tests:** classification precedence (user > source > plugin default > Unknown). An override
  survives catalog refresh, plugin update and restore merge (INV-4). Correct traceability row M9.2 when this
  lands.

### WP-6 · One classifier for language and content type, plus a data migration (BE-002, BE-004) · P1

- **Modules:** a new `oneshelf/plugins/classification.py::classify(listing|details, package, overrides)`,
  called from `search/service.py` (result building), `search/grouping.py::persist_listing`,
  `api/discovery.py::_bind`/`open_listing`, `search/url_resolve.py`, and `importer/service.py`. Use
  `content_type_source` values `user | source | plugin_default | unknown`. Add migration `0021`
  (data-only, using the pre-migration snapshot the migrator already takes): reclassify `und`/`unknown` rows
  created from plugins with declared defaults, and **merge twin tracks** of one listing (re-point units by
  `source_unit_key`, assets, `reading_state`, bookmarks, highlights, follows and release events, then
  delete the empty twin). Never touch user-sourced values. Storage paths are **not** renamed (§24.2: no
  automatic moves). Only DB rows change.
- **Safeguards:** a dry-run report endpoint (`GET /api/maintenance/reclassification-preview`) before the
  migration runs on production. The migration is idempotent and runs inside the migrator's per-migration
  transaction. FK check on.
- **Regression tests:** fixture searches for sources with defaults yield their language and type. Opening
  via search then URL yields one track. Migration fixtures: an `und` 3asq track becomes `ar`/`manga`; a twin
  pair merges with progress and assets kept; a user-set value is untouched; a second run is a no-op.

### WP-7 · Required output comes from the recipe, not the Work label (BE-003) · P1

- **Modules:** `oneshelf/downloads/engine.py::enqueue` (`output_format` from `package.recipes`: an image
  reader → `cbz`, a text reader → `text`, `downloads` → `file`; family only as a tiebreak) and
  `_download_pages` (apply the reader recipe's `resource_headers`, as the Reader already does).
- **Regression tests:** a Test Source image unit on a Work with `content_type='unknown'` → a valid CBZ. A
  downloads-only unit → the original PDF. Live smoke tests (MangaDex, WEBTOON, Tapas, 3asq on a chapter with
  live images) each commit a CBZ. Change `tests/live` so it no longer injects content types, which closes
  the test/product path gap.

### WP-8 · Heavy work off the event loop (BE-006) · P1

- **Modules:** a new `oneshelf/services/worker.py` (a bounded thread pool, each worker with its own
  `open_database()` connection). Move to it: `backup/service.py::create`/`verify`, `restore/service.py`,
  `export/service.py` copy loop, `storage/migration.py`, `storage/scanner.py::reconcile(verify_checksums)`,
  and `storage/hashing.sha256_file` for files over 8 MB. API handlers become "start job → return id", with
  progress over the event bus.
- **Safeguards:** worker write transactions stay short with `BEGIN IMMEDIATE` and the 5 s busy timeout. The
  SQLite online backup API is thread-safe per connection. Persisted job rows keep them resumable after a
  restart.
- **Regression tests:** during a synthetic 500 MB backup, export or scan, p99 `/api/health` and reader-page
  latency stays under 250 ms. Backup bytes and verification are unchanged. A restart mid-job resumes or
  fails cleanly.

### WP-9 · Stream transport and Range-capable local files (BE-011) · P2

- **Modules:** `oneshelf/net/http.py` (`stream_to(path, offset)` writing chunks, still capped and policy
  checked), `downloads/engine.py` (use it for files and pages), `api/library.py::reader_file` (a
  `FileResponse` with `Range`, same CSP, nosniff and Content-Disposition), and `reader/service.py::local_file`
  (returns a path, not bytes).
- **Regression tests:** tracemalloc peak under 32 MB for a 200 MB download and a 200 MB file serve.
  `Range: bytes=0-99` → 206 with 100 bytes. The header-isolation tests stay green.

### WP-10 · Follow baseline pending until a catalog is trusted (BE-010) · P2

- **Modules:** `oneshelf/follow/service.py` (`baseline kind = "pending"` when there is no trusted catalog;
  the first trusted check sets the baseline silently).
- **Regression tests:** probe `test_c12` → 0 new on the first trusted check, then 1 new after an added unit.

### WP-11 · Format selection for multi-format units (BE-013) · P2

- **Modules:** a new `GET /api/reading-units/{id}/formats` (the `downloads` descriptors), the enqueue body
  `formats: []`, and the contract `output_format` per job. The engine's `_download_file` chooses the
  descriptor by format. Export reads all formats present.
- **Regression tests:** EPUB then PDF of one SE unit → two assets on one Work. An unknown format → 422.

### WP-12 · Reader failure honesty and offline cache (BE-017) · P3

- **Modules:** `reader/service.py` (check `response.status` → `CapabilityError("source_failed")` plus a
  health signal; an LRU and TTL bound on `_descriptors`; one refresh on 403/404; persist descriptors next to
  Reader Cache entries) and `api/library.py` (502 `SOURCE_FAILED`, 409 `SOURCE_UNAVAILABLE`).
- **Regression tests:** an upstream 404 → 502 carrying the status. Plugin disabled → `SOURCE_UNAVAILABLE`,
  and cached pages are still served. The descriptor cache stays bounded. An expired URL triggers exactly one
  refresh.

### WP-13 · Preflight with real sizes (BE-018) · P3

- **Modules:** `downloads/engine.py` (pass `FileDescriptor.size_bytes`, or a windowed batch sum).
- **Regression tests:** a file that would cross the reserve fails before any byte is fetched.

### WP-14 · Adapters (OneShelf-Adapters repository, not Core) (BE-014) · P2

- A-1 Gutenberg: drop or replace the gutendex search (or use the trailing-slash URL), and keep 2.0.1's
  `www.gutenberg.org` catalog.
- A-2 Hindawi/Safahat: Latin queries are redirected to `http://`. Use the canonical lowercase https path,
  or declare `stop_when: not_found` semantics.
- A-3 3asq: derive the special or prologue type for "0A–0D"-style units. Do not report number `0` for
  lettered units.
- A-4 MangaDex: upstream the 1.0.2 translation-language fix as 1.0.3. Then resync the bundled snapshot with
  `python -m plugins.sync_snapshot` and drop `UPSTREAM.json.local_changes`.
- Add a packaged `health` case to MangaDex.
- **Acceptance:** the Registry CI is green, and the `tests/live` suite is green against the refreshed
  bundle.

## Cross-agent handoffs to Codex (frontend)

| ID | Depends on | What the UI needs |
|---|---|---|
| H-1 | WP-2 | Downloads: show 409 `NO_STORAGE_LOCATION` with a "Manage storage" action. Render batch `canceled` and job `internal_error`/`too_large`. Stop showing "1 waiting" for terminal jobs |
| H-2 | WP-1 | Settings → Access: network, proxy and hostname editors read-only for remote sessions, with the `LAN_REQUIRED` explanation |
| H-3 | WP-5 / WP-6 | Work details: edit content type, title and aliases, track language (with an identity-change confirmation) and unit number. Show `content_type_source` subtly. Language and RTL defaults follow the corrected classification |
| H-4 | WP-11 | A format picker on Download (unit and batch), and the available formats on the Work page |
| H-5 | WP-12 | Reader errors: `SOURCE_FAILED` (with status) vs `SOURCE_UNAVAILABLE` vs `DOWNLOAD_REQUIRED`. Offline cached pages stay readable |
| H-6 | WP-2 | A Notifications/Needs Attention item for `storage-unavailable:<root>`, distinct from Low Storage |
| H-7 | WP-9 | PDF viewer: use Range loading (pdf.js `rangeChunkSize`) against `/file` |
| H-8 | WP-10 | Following: a "baseline pending: first check will set it" state |
| H-9 | WP-8 | Backup, export, restore and scan become async jobs, with progress via events |

## Regression-test summary (per finding)

| Finding | Test that must fail on today's `main` and pass after the fix |
|---|---|
| BE-001 | `test_auth_api.py::test_remote_session_cannot_change_trust_boundary`, `test_proxies_must_be_private` |
| BE-002 / BE-004 | `test_search_applies_plugin_defaults`, `test_search_and_url_yield_one_track`, `test_migration_0021_*` |
| BE-003 | `test_engine.py::test_image_reader_unit_on_unknown_work_packages_cbz` |
| BE-005 | `test_engine.py::test_no_storage_location_is_refused_at_enqueue`, `test_unexpected_error_fails_the_job` |
| BE-006 | `test_responsiveness.py::test_api_stays_responsive_during_full_backup` |
| BE-007 | `test_engine.py::test_complete_body_then_failure_restarts_cleanly` |
| BE-008 | `test_engine.py::test_redownload_of_missing_file_replaces_the_record` |
| BE-009 | `test_engine.py::test_repair_keeps_the_old_copy_until_the_new_one_is_verified` |
| BE-010 | `test_shelf_and_follow.py::test_follow_before_trusted_catalog_does_not_flood` |
| BE-011 | `test_memory.py::test_large_download_and_file_serve_are_streamed`, `test_reader_file_supports_range` |
| BE-012 | `test_overrides.py::test_precedence`, `test_override_survives_refresh_update_restore` |
| BE-013 | `test_engine.py::test_two_formats_one_unit_one_work` |
| BE-015 | `test_backup.py::test_backup_excludes_remote_auth_tables`, `test_every_table_is_classified` |
| BE-016 | `test_engine.py::test_all_canceled_batch_state`, `test_offline_root_notifies_unavailable` |
| BE-017 | `test_reading.py::test_upstream_404_is_reported_as_source_failure`, `test_cached_pages_survive_disabled_source` |
| BE-018 | `test_engine.py::test_preflight_uses_known_size` |
| BE-019 | `test_http.py::test_read_timeout_releases_connection` (with `-W error::ResourceWarning`) |

## Verification after each WP

1. `pytest -m "not live"` is green, with zero new warnings (warnings are errors).
2. The relevant audit probe (in `qa-artifacts/be-audit-20261019/probes/`) now fails its *defect* assertion,
   meaning the defect is gone. The probe is then promoted into the product suite with corrected expectations.
3. For WP-3/6/7/12/14: `ONESHELF_LIVE_SOURCES=1 pytest tests/live` plus the audit live harness on an
   isolated instance.
4. Push, then **READY — AWAITING USER-MANAGED DEPLOYMENT**. After the owner deploys, run browser checks
   (`scripts/agent/browser_check.py`) and read-only API evidence on 192.168.8.32 (AGENTS.md gate).

## Unverified features and remaining risks

| Item | Status | Why / what would close it |
|---|---|---|
| Docker build, restart and recreation (§2.1, REL-08) | BLOCKED | No container runtime here (EB-1). Needs a host run of `install.sh` and `update.sh` |
| Running backend image revision on production | Unproven | The frontend assets MATCH `b9932e1` and the schema is v20 (= main). The app does not report a backend commit. Consider adding `GET /api/version` with the image's git SHA |
| Use My Session, reconnect, browser escalation against a real source | BLOCKED | No Registry adapter declares `auth` or `browser`. Covered only by the Test Source |
| 104 community adapters' live behaviour | NOT TESTED live | Static validation and packaged tests only (112/112) |
| Export, restore and the generator end-to-end on real data | NOT TESTED live | Covered by the suite. Restore deliberately not run against production |
| Expiring CDN URLs (MangaDex@Home) | Not confirmed | No expiry within 37 min (README §3) |
| Tapas download with the type supplied | NOT TESTED | Inferred from the shared root cause (BE-003) |
| RTL / vertical reading direction and all Reader UI modes | FE | Codex scope. Depends on BE-002 for Arabic defaults |
| `feature/text-reading-units` | Risk | 9 commits ahead and **44 behind** `main`. Its features already landed on `main` in another form. The primary checkout has **36 uncommitted files** on it (another agent's work, untouched by this audit). Merging the branch would revert main's later work, so rebase or retire it deliberately |
| Bundled snapshot vs Registry drift | Risk | 7 of 8 behind, MangaDex divergent (BE-014) |
| One shared SQLite connection for all async work | Risk | Correct today (no threads). WP-8 must give workers their own connections |
