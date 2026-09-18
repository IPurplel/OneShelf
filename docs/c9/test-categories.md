# §53 — Test Categories: what covers each one

Recorded: 2026-09-18 · Authority: Master §53 · Deferred from the C9 gate until C2 existed

Master §53 names twenty-six categories of test and two rules about how the suite must behave. This is the
audit of each against the suite as it actually stands: **backend 794 passed, 4 deselected** (the live
source suite, which is the only thing that needs the real internet), **frontend 136 passed**.

One category had only an in-process variant and was filled during this audit; it is marked ★.

| # | Category | Where it is covered |
|---|---|---|
| 1 | Unit tests | `tests/unit/` — 27 modules: paths, schema, migrations, commit journal, integrity, access classifier, request guard, events, defaults, route order, egress policy and proxy, governor, plugin package/runtime/templates/transforms, sessions, search index/ranking/cache, auth policy/recovery/sessions, redaction |
| 2 | Integration tests | `tests/integration/` — 37 modules across auth, backup, restore, browser, catalog, downloads, export, generator, library, plugins, reader, search, sources, storage and the API |
| 3 | Deterministic local source failures | The OneShelf Test Source and its `__control` endpoint: `test_incomplete_pagination_is_never_complete`, `test_malformed_metadata_stays_unknown_and_invalidates_catalog`, `test_rate_limit_feeds_the_governor`, `test_redirect_to_unapproved_domain_is_blocked`, `test_large_catalog_and_collapse_are_both_reported_with_evidence` |
| 4 | Source adapter contract tests | `integration/sources/test_official_packages.py` (every shipped `.osp` runs its own packaged fixture tests), `integration/sources/test_capability_inputs.py`, `unit/plugins/test_package_validation.py` |
| 5 | Migration tests | `unit/test_db_migrations.py` — fresh migrate, idempotence, contiguity, rollback on failure, snapshot before migrating, and `test_newer_schema_is_refused_without_changes` |
| 6 | Crash / recovery | `unit/test_commit_journal.py` (including `test_crash_between_link_and_unlink_recovers`), `integration/test_startup_recovery.py`, `test_crash_during_download_recovers_without_duplicates` |
| 7 | Queue persistence / restart recovery ★ | `test_the_queue_survives_a_restart_and_a_new_engine_finishes_it` — the queue is re-read from SQLite by a **new** engine, source service and governor, so nothing is carried over in memory |
| 8 | Storage offline / reconnect | `test_offline_root_is_unavailable_not_mass_missing`, `test_root_reconnect_restores_previously_missing_assets`, `test_open_commit_on_unavailable_root_keeps_its_staging` |
| 9 | Catalog incomplete / suspicious / trust transitions | `integration/catalog/test_trust.py` — 13 tests covering first trust, incomplete refreshes, the 300→7 collapse, two consecutive matching checks, a different second candidate, explicit Trust This Catalog, and local content surviving a collapse |
| 10 | Session reconnect flows | `test_reconnect_replaces_atomically_and_resumes_waiters`, `test_unreadable_session_is_reported_as_needs_reconnect`, `test_auth_failure_waits_for_session_and_resumes_after_connect`, `test_use_my_session_flow_with_scoped_cookies` |
| 11 | Rate limits | `unit/net/test_governor.py`, `test_rate_limit_feeds_the_governor`, `test_rate_limited_media_waits_then_completes` |
| 12 | Download resume / validators | `test_resume_skips_pages_that_are_already_valid`, `test_changed_validator_restarts_the_file_instead_of_splicing`, `test_invalid_media_never_becomes_downloaded_content`, `unit/downloads/test_contract.py` |
| 13 | Corrupt media repair | `unit/test_integrity.py` (HTML for an image, empty/corrupt images, unsafe entry names, zip bomb), `test_size_change_marks_corrupt`, `test_merge_repairs_missing_or_corrupt_files_but_leaves_healthy_ones` |
| 14 | Path safety | `unit/test_paths.py` — separators and dot names, Arabic preserved and NFC-normalised, bidi overrides stripped, byte truncation, reserved names, escapes and symlinked escapes rejected, deletion confined to regular files inside a root |
| 15 | SSRF attempts | `unit/net/test_policy.py`, `unit/net/test_egress_proxy.py` (resolve-validate-pin, private and link-local targets, per-hop redirect checks, DNS rebinding through the browser proxy), `test_redirect_to_unapproved_domain_is_blocked` |
| 16 | Untrusted EPUB / HTML isolation | Frontend `epub.test.ts`, `BookReader.test.tsx` (empty `sandbox`, own CSP, blob-only resources), `pdf-isolation.test.ts`; backend `test_work_api.py` asserts `Content-Security-Policy: sandbox; default-src 'none'` on the file route |
| 17 | Remote CSRF / origin checks | `unit/test_request_guard.py`, `integration/test_auth_api.py`, and the live smoke in the C3 record (403 `CROSS_ORIGIN_REQUEST`, 421 `HOST_NOT_ALLOWED`) |
| 18 | Backup compatibility | `test_a_newer_backup_is_refused_by_an_older_application`, `test_an_older_backup_migrates_forward_in_staging_without_changing_the_file`, `test_preflight_reports_contents_plugins_and_compatibility` |
| 19 | Restore merge rules | `test_merge_adds_missing_records_but_keeps_current_user_decisions`, `test_merge_never_regresses_progress`, `test_replace_creates_a_safety_snapshot_first`, `test_missing_plugins_do_not_block_restore_and_are_reported`, `test_new_plugin_permissions_require_explicit_approval`, `test_marks_travel_in_a_library_backup` |
| 20 | Export resume / conflicts | `test_export_resumes_after_an_interruption`, `test_conflict_policies`, `test_one_failed_file_does_not_fail_the_export_and_can_be_retried`, `test_download_missing_requires_an_explicit_permanent_download_notice` |
| 21 | Arabic normalization | `unit/search/test_index.py::test_local_search_is_arabic_normalized_and_loose`, `unit/plugins/test_transforms.py::test_arabic_normalization_levels_without_stemming`, `test_safe_component_preserves_arabic_and_normalizes_to_nfc`, `test_search_including_arabic` |
| 22 | RTL / LTR UI | `shell.test.tsx::switches language and direction together…`, `a11y.test.tsx::keeps interface direction independent from a work's own text`, `SequentialReader.test.tsx::respects reading direction rather than assuming left to right`; screenshots `home-desktop-ar.png`, `settings-remote-ar.png` |
| 23 | Matching manual overrides | `integration/search/test_mapping_and_grouping.py` — `test_never_match_prevents_grouping_and_persists`, `test_unlink_survives_refresh_and_blocks_reassociation`, split and merge, and INV-03's "presentation only" check |
| 24 | Multi-tab progress non-regression | `test_progress_writes_reject_stale_tabs_but_allow_explicit_changes`, `test_progress_endpoints_and_stale_writes`, `test_progress_can_be_read_back_so_a_reader_knows_the_revision_it_must_carry`, and on the frontend `writes progress once the reader settles, carrying the revision it last saw`, `carries the revision the library already holds, so the first write is not stale`, `flushes progress when the tab is hidden` |
| 25 | Event / realtime updates | `unit/test_events.py` — ordering, a slow subscriber dropped with a resync rather than blocking the publisher, publishing from a worker thread, single-line JSON SSE encoding |
| 26 | Accessibility-critical interactions | `a11y.test.tsx` (skip link, named landmarks, every destination by keyboard, focus returned to the control that opened a drawer, Escape), `lets the keyboard reach the pages themselves, which scroll`, and axe-core over 21 page states in both languages with zero WCAG 2.1 A/AA violations |

## The two rules about the suite itself

> Do not run destructive tests against the user's real library data. Use isolated test data and the
> OneShelf Test Source.

Held mechanically, not by habit, in `tests/unit/test_suite_is_isolated.py`:

- no test module reaches outside its own temporary directory (`Path.home()`, `expanduser`, `~/`, absolute
  `/home` or `/var` paths, or the working directory). `/etc/passwd` is deliberately *not* forbidden: it
  appears only as a hostile input that path safety and package validation must reject;
- every `ONESHELF_DATA_DIR` a test configures is a temporary one;
- `live/test_source_suite.py` is the only module marked `live`, so a normal run touches no network.

## INV-29 — matching diagnostics never become telemetry

`tests/unit/test_no_matcher_telemetry.py` is the standing audit the invariant asks for (§51.29: "review
persistent records, diagnostics, network calls and cleanup"):

| What was reviewed | Finding |
|---|---|
| Persistent records | No shipped table or column carries a decision, score, candidate or event vocabulary. `work_mappings` holds exactly `{id, kind, listing_id, work_id, other_work_id, decided_by, created_at}` — the mapping the library needs, not a dataset about how it was reached. The test pins that column set. |
| A real matching pass | Grouping then mapping grows only `works`, `source_listings`, `source_tracks`, `search_index` and `work_mappings`. Nothing else is written. |
| Diagnostics | A grouping pass emits no log records at all. Application logging is exception logging in the three runners; `diagnostics/redact.py` redacts at write time. |
| Network calls | No module carries a hardcoded endpoint, and a default install has `registry_url is None` and no trusted keys, so there is nowhere to report to unless the person configures a registry themselves (ledger A1). |
| Cleanup | The discovery cache is rebuildable and namespaced by source and plugin version in a physically separate `cache.db`; clearing it cannot touch authoritative state. |

## What this audit did not cover

**EB-1 stands.** Docker build, restart and recreation against isolated mounts still need a host with a
container runtime; none exists here. Everything else in §53 is covered above.
