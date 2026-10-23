# Requirement coverage matrix (2026-10-19)

Source of truth: `docs/OneShelf_Final_Implementation_Meta_Prompt.md` §F (Master §0–§56), §C (stages C0–C9),
§D1 (30 invariants). Audited revision: `origin/main` `b9932e1`.

## Statuses

- **PASS**: directly verified today by a named test that passed in today's run (**T**), a live check on the
  isolated instance (**L**), a production check (**P**), or an audit probe.
- **FAIL**: a reproducible defect (BE-xxx in `findings.md`). A row is FAIL if any mandatory clause fails, even
  when other clauses pass.
- **BLOCKED**: environment or access limits prevented verification.
- **NOT TESTED**: insufficient coverage by this audit. Frontend-owned behaviour is marked **FE**: it is out of
  backend scope, was not re-tested, and is left to Codex.
- **N/A**: governance or qualitative text with no runtime behaviour.

Scope tags: **M** mandatory v1, **O** optional or future, **X** explicitly excluded (guarded).

Today's baseline: `pytest -m "not browser and not live"` gave **1,485 passed, 1 skipped**, 90% line coverage
(`qa-artifacts/be-audit-20261019/pytest-main.log`). The browser-marked tests gave **8 passed**. The live suite
gave 6 passed, 1 skipped, 1 failed (BE-019). The 112 Registry packages validated and passed their packaged
tests 112/112.

## Master sections

| § | Requirement | Scope | Status | Evidence | Findings |
|---|---|---|---|---|---|
| 0 | Authority, scope discipline | — | N/A | Governance | — |
| 1 | Product vision | — | N/A | Qualitative | — |
| 2.1 | Docker first-class, persistent storage | M | **BLOCKED** | No `docker`/`podman` on this host (EB-1 still open). Production runs a container that answers healthy (P), but its image revision is unproven | — |
| 2.2 | Single user, no accounts | M | PASS | T `unit/exclusions/test_no_accounts_or_multi_user.py` | — |
| 2.3 | Arabic/English, RTL/LTR, Arabic normalisation | M | **FAIL** | Normalisation T `unit/search/*`. Arabic sources stored `und` (L, P) | BE-002 |
| 3.1 | Source and language integrity | M | **FAIL** | No silent switching (T). Language recorded wrongly and twin tracks created (L) | BE-002, BE-004 |
| 3.2 | Unknown is a valid state | M | PASS | T `test_runtime.py::test_unknown_classification_values_become_unknown`, search tests | — |
| 3.3 | Local content independence | M | PASS | L: CBZ read with plugin disabled. T `reader/test_disconnect.py` | — |
| 3.4 | No hidden destructive behaviour | M | **FAIL** | Probe C4: Repair deletes the copy before a replacement exists | BE-009 |
| 4.1–4.2 | Work, Source Listing | M | PASS | T `search/test_mapping_and_grouping.py` | — |
| 4.3 | Source Track (never blended) | M | **FAIL** | L: two tracks for one listing (`en` and `und`) | BE-004 |
| 4.4 | Reading Unit fields, numbering precedence, user correction | M | **FAIL** | Fields and order T. No user-correction write path | BE-012 |
| 4.5–4.6 | Volumes; Local Source Track | M | PASS | T `test_local_import.py`, `test_scanner.py` | — |
| 5.1–5.6 | Catalog trust (complete only, 300→7, recovery, trusted-only ops, missing units, completion) | M | PASS | T `catalog/test_trust.py`. L refresh states `unchanged` and `incomplete` | — |
| 6.1 | Local-first, progressive search | M | PASS | L: SSE `local → partial… → complete`, per-source status. T `test_search_service.py` | — |
| 6.2–6.5 | FTS index, normalisation, ranking, type compatibility | M | PASS | T `unit/search/test_index.py`, `test_ranking.py` | — |
| 6.6–6.8 | Soft group vs hard mapping, missing metadata, unit identity | M | PASS | T `test_mapping_and_grouping.py` | — |
| 6.9 | Same-source duplicate resolution | M | **FAIL** | L: SE Frankenstein produces twin tracks | BE-004 |
| 6.10 | No matcher telemetry | X | PASS | T `unit/test_no_matcher_telemetry.py` | — |
| 7 | Discovery cache TTL/cap/namespacing | M | PASS | T `unit/search/test_cache.py` | — |
| 8 | Direct URL entry | M | PASS | L: Tapas, WEBTOON and SE URLs resolved and opened (see BE-004 for the language inconsistency) | BE-004 |
| 9.1 | Standard capabilities | M | PASS | Registry sweep 112/112. T `test_capability_inputs.py` | — |
| 9.2 | Classification precedence | M | **FAIL** | Plugin-default tier unused, user tier unwritable. Traceability row M9.2 overstated | BE-002, BE-012 |
| 9.3–9.4 | Declarative packages; bounded safe transforms | M | PASS | T `test_package_validation.py`, `test_transforms.py` (re2). Sweep | — |
| 9.5 | Trust labels | M | PASS | T `test_labels.py`, `test_first_party_trust.py` | — |
| 9.6–9.7 | Native adapters rare; restricted RPC excluded | M/X | PASS | T `test_boundaries_and_native_adapters.py`, `test_no_executable_plugins_or_rpc.py` | — |
| 10 | Install, update, disable, uninstall, rollback, permission review | M | PASS | T `plugins/test_lifecycle.py`, `test_registry_lifecycle.py`. L disable/enable via API | — |
| 11 | SSRF: redirects, DNS, private targets, browser path | M | PASS | T `unit/net/test_policy.py`, `test_egress_proxy.py`. Inspection of `net/http.py` and `egress_proxy.py` (pinned validated resolution, per-hop checks) | — |
| 12 | Generator and repair | M | PASS (T only) | T `integration/generator/*` (5 files). Not exercised live by this audit | — |
| 13 | Use My Session | M | PASS (Test Source) / **BLOCKED** (real source) | T `unit/sessions`, `test_engine.py::test_auth_failure_waits_for_session…`. No real adapter declares auth (sweep) | — |
| 14 | Extraction Contract (source, language, required output, method) | M | **FAIL** | T `unit/downloads/test_contract.py`. L: the required output is chosen from Work type, not recipe | BE-003 |
| 15 | Traffic governor priorities and fairness | M | PASS | T `unit/net/test_governor.py`, reader-saturation tests. Non-network blocking is tracked in BE-006 | BE-006 |
| 16 | Download engine (16.1 batches, 16.2 concurrency, 16.3 retry, 16.4 resume, 16.5 integrity, 16.6 cancel, 16.7 history) | M | **FAIL** | 16.2/16.5/16.6/16.7 T and L. 16.3/16.4 probe C2. Stuck jobs in production. Sequential downloads fail live | BE-003, BE-005, BE-007, BE-016, BE-018 |
| 17 | Crash-safe commit journal, idempotent recovery | M | **FAIL** | T `unit/test_commit_journal.py` (fault points). Probe C5: journal wedged at `verified` | BE-008 |
| 18 | SQLite WAL, migrations, consistent snapshots | M | PASS | T `unit/test_db_migrations.py`, migration tests. Inspection of `db/connection.py` (WAL, FULL, `BEGIN IMMEDIATE`) | — |
| 19 | Auto-download while reading | M | PASS | T `reader/test_reading.py`, `test_defaults_reach_every_layer.py` | — |
| 20 | Follow and release detection | M | **FAIL** | P: live follow, baseline 404, no flood, unfollow keeps Shelf. Probe C12: flood when no trusted catalog | BE-010 |
| 21 | Source health | M | PASS | T `test_health_and_notifications.py`. L: Gutenberg goes `unavailable` after a threshold of 10 | BE-014 (adapter) |
| 22 | My Shelf | M | **FAIL** | Shelf T and P. Multiple formats cannot coexist by choice | BE-013 |
| 23 | Shelf / Follow / Files independence | M | PASS | T `test_shelf_and_follow.py`. P: unfollow kept Shelf, Favorite and Pin | — |
| 24.1–24.4 | Roots, layout, per-root staging, path safety | M | PASS | T `unit/test_roots.py`, `test_paths.py` | BE-002 (layout family) |
| 24.5 | Disk space guard | M | **FAIL** | Download preflight ignores known size | BE-018 |
| 24.6 | Storage unavailable | M | **FAIL** | No mass-missing (T). Wrong "0 bytes remain" notification | BE-016 |
| 24.7–24.8 | Manual changes; resumable migration | M | PASS | T `test_scanner.py`, `storage/test_migration.py`. Probe C5 scan marked `missing_local_file` | — |
| 25 | Staging cleanup order | M | PASS | T `test_startup_recovery.py`. L/P `/api/ready` order `recover_jobs → recover_commits → reconcile → clean_staging` | — |
| 26.1–26.10, 26.12–26.14, 26.17–26.18, 26.24 | Reader shell, modes, input, fit, zoom, TOC, end-of-unit, settings, preload, loading | M | FE | Frontend suite and ledger WP-R1…R5. P: reader renders | — |
| 26.11, 26.15, 26.23 | Progress models, Continue Reading, multi-tab | M | PASS | L stale write → 409. T progress tests | — |
| 26.16 | Source indicator and switching | M | PASS | T `unit/reader/test_alternatives.py` | BE-004 |
| 26.19 | Download state in the Reader | M | **FAIL** | Download from the Reader fails for `unknown` image Works | BE-003 |
| 26.20 | Reader Cache | M | PASS | T cache eviction and protection tests | BE-017 (descriptors) |
| 26.21 | Error recovery | M | **FAIL** | Cached pages unusable when the source is disabled. Repair deletes early | BE-017, BE-009 |
| 26.22 | Book Reader (EPUB/PDF bookmarks, highlights, search) | M | PASS (backend) | T `reader/test_marks.py`. L file serving. FE rendering | BE-011 |
| 27 | Untrusted content isolation | M | PASS | L: sandbox CSP and nosniff on pages and files. T `test_text_sanitise.py` | — |
| 28.1 | Local/LAN trusted | M | PASS | T `unit/test_access.py`. P LAN access unauthenticated | — |
| 28.2 | LAN trust boundary / trusted proxies | M | **FAIL** | Probe C6 | BE-001 |
| 28.3–28.4 | Passkeys, internal identity | M | PASS | T `integration/auth/test_passkeys.py` | — |
| 28.5 | Recovery | M | **FAIL** | LAN Recovery does not end attacker access (C6) | BE-001 |
| 28.6–28.7 | Remote sessions, cookies, Origin/CSRF | M | PASS | T `unit/auth/test_sessions.py`, `unit/test_request_guard.py`, `unit/test_no_token_storage.py` | — |
| 29 | First Run | M | PASS | T `test_auth_api.py::test_first_run…`. P: production First Run still `pending` with no storage root (owner action) | BE-005 |
| 30 | In-app notifications (classes, grouping, seen vs read, dedupe, cleanup) | M | PASS | T `test_health_and_notifications.py`, `unit/test_no_browser_notifications.py` | BE-016 |
| 31 | Home discovery semantics | M | PASS | T `search/test_url_and_home.py`. P home renders | — |
| 32 | UI/UX visual direction | M | FE | P: 18 page loads (desktop and mobile), 0 console errors or failed requests (`browser-live/report.json`) | — |
| 33.1–33.2, 33.4–33.9 | Library/Full backup, format, compatibility, preflight, restore modes, schedule, location | M | PASS | T `backup/test_backup.py`, `test_restore.py`. L full backup verified. P library backup created and verified, weekly automatic backups on 10-08 and 10-15 | — |
| 33.3 | Hard exclusions | M | **FAIL** | Probe C11 | BE-015 |
| 33.10 | Built-in encryption | O | N/A | Not a v1 requirement | — |
| 34 | Export | M | PASS (T only) | T `export/test_export.py` (I-60, I-69). Not exercised live | BE-013 (selected formats) |
| 35 | History separation | M | PASS | Inspection: separate tables and APIs. T history-clearing tests | — |
| 36 | Multi-client live updates | M | PASS | T `unit/test_events.py`. Inspection: bounded queues with `resync` | — |
| 37 | Import | M | PASS | T `test_local_import.py`, `unit/test_import_suggestions.py` | — |
| 38 | Library scanner | M | PASS | T `test_scanner.py`. Probe C5 | — |
| 39 | ComicInfo / packaging | M | PASS | L: CBZ `ZIP_STORED` with original bytes plus `ComicInfo.xml` (21 members for 20 pages) | — |
| 40 | API documentation | M | PASS | `docs/api.md`, `docs/development.md` endpoint tables match the routes probed | — |
| 41 | Initial source suite (8 real plus Test Source) | M | **FAIL** | See `adapter-inventory.md` | BE-002, BE-003, BE-014 |
| 42 | Default values | M | PASS | T `unit/test_defaults.py`, `test_defaults_reach_every_layer.py` | BE-018 |
| 43 | Local diagnostics | M | PASS | T `unit/diagnostics/*`. L `/api/diagnostics/recent` shows bounded, redacted entries | — |
| 44–47 | Attention, disclosure, error and destructive UX | M | FE | Backend attention feed T. Messages: BE-016, BE-017 | BE-016, BE-017 |
| 48 | Security summary | M | **FAIL** | Inbound boundary | BE-001, BE-015 |
| 49 | Explicit exclusions | X | PASS | T `unit/exclusions/*` (guards checked by violation) | — |
| 50 | Non-goals | — | N/A | — | — |
| 52 | Subsystem boundaries | M | PASS | Inspection (module layout). Note BE-006 | — |
| 53 | Testing expectations | M | **FAIL** | The suite is broad, but the live suite is red, there is no real-source auth or browser coverage, and the product path differs from the live test path | BE-003, BE-019 |
| 54–55 | Final design state; instructions | — | N/A | — | — |
| 56 | Retained requirements (bounded memory, stable IDs, …) | M | **FAIL** | Bounded memory | BE-011 |

## Acceptance invariants (Master §51 / Meta Prompt §D1)

| INV | Status | Evidence | Findings |
|---|---|---|---|
| 1 Suspicious or incomplete catalogs never erase trusted state | PASS | T `catalog/test_trust.py` | — |
| 2 Source and language never switch silently | PASS | T contract and fallback tests (no switch observed). Language *recording* is BE-002 | BE-002 |
| 3 Soft group is never identity | PASS | T `test_mapping_and_grouping.py` | — |
| 4 User overrides survive refresh | **FAIL** | No override can be created, so the property is unverifiable | BE-012 |
| 5 Unknown metadata is not negative evidence | PASS | T ranking and matching tests | — |
| 6 Unknown quality never blocks | PASS | T | — |
| 7 Reading ≠ downloading | PASS | T. L online reads created no assets | — |
| 8 Auto-download OFF by default | PASS | T `test_defaults*.py` | — |
| 9 Follow never auto-downloads | PASS | T. P: live Follow check created no jobs | — |
| 10 Remove / Unfollow / Delete Files independent | PASS | T. P: unfollow kept Shelf | — |
| 11 Local content readable without source, plugin or network | PASS | L plugin disabled → local CBZ readable. T `test_disconnect.py` | — |
| 12 Reader content cannot reach privileged actions | PASS | L CSP sandbox and nosniff. T sanitiser and isolation tests | — |
| 13 No arbitrary plugin code | PASS | T exclusion guards. Sweep | — |
| 14 No arbitrary plugin filesystem paths | PASS | T `unit/test_paths.py` | — |
| 15 No plugin SSRF | PASS | T `unit/net/*` | — |
| 16 Incomplete downloads never appear completed | PASS | T invalid-media tests. L failed jobs left no assets | — |
| 17 Commit crash recoverable idempotently | **FAIL** | Probe C5: journal wedged, error on every boot | BE-008 |
| 18 Offline storage ≠ mass deletion | PASS | T `test_scanner.py` | BE-016 (message) |
| 19 Backups exclude sessions and tokens | **FAIL** | Probe C11 (remote-session token hashes, recovery verifier) | BE-015 |
| 20 Export never silently modifies the library | PASS | T `test_export.py` | — |
| 21 Download Missing Then Export notice | PASS (T) / FE | T export flow. FE copy | — |
| 22 Notifications never alter reading state | PASS | T | — |
| 23 Clearing history never deletes content | PASS | T `test_batch_controls_and_history_clearing` | — |
| 24 Navigation follows Source Track order | PASS | T irregular, Special, 3.5 fixtures | — |
| 25 Cross-source progress approximate | PASS | T `test_alternatives.py` | — |
| 26 Background browser work cannot starve the Reader | PASS | T saturation test (network). See BE-006 for non-network blocking | BE-006 |
| 27 Search results are Works | PASS | L search payloads group provenance per Work | BE-004 (tracks) |
| 28 Covers are presentation only | PASS | T `test_open_and_covers.py` | — |
| 29 No matcher telemetry | PASS | T `test_no_matcher_telemetry.py` | — |
| 30 Remote passkey, session and CSRF boundary; LAN trusted | **FAIL** | Probe C6 | BE-001 |

**Totals (computed from the table):** 26 PASS, 4 FAIL (INV-4, 17, 19, 30), 0 BLOCKED, 0 NOT TESTED.

## Implementation stages (Meta Prompt §C gates)

| Stage | Gate status | Blocking findings |
|---|---|---|
| C0 baseline and traceability | PASS with correction: traceability M9.2 is overstated | BE-012 |
| C1 architecture, persistence, local slice | **FAIL** | BE-008, BE-009 |
| C2 UI shell and local reading slice | FE (not re-tested). Backend reading slice PASS | — |
| C3 declarative runtime, sessions, network policy | PASS (real-source auth BLOCKED: no adapter uses it) | — |
| C4 catalog trust, discovery, identity | **FAIL** | BE-002, BE-004, BE-012 |
| C5 downloads, recovery, online reading | **FAIL** | BE-003, BE-005, BE-007, BE-011, BE-017 |
| C6 Shelf, Follow, health, attention, events | **FAIL** | BE-010, BE-013, BE-016 |
| C7 storage, import, backup, restore, export | **FAIL** | BE-006, BE-015, BE-018 |
| C8 remote access and First Run | **FAIL** | BE-001 |
| C9 generator, initial suite, deployment verification | **FAIL / BLOCKED** | BE-014, BE-019. Docker BLOCKED (EB-1) |

## Section-row tally (master table above)

| Status | Rows |
|---|---|
| PASS (incl. "PASS (T only)", "PASS (backend)", and §13 "PASS (Test Source) / BLOCKED (real source)") | 51 |
| FAIL | 23 |
| BLOCKED | 1 (§2.1), plus the real-source half of §13 |
| FE (frontend-owned, not re-tested) | 3 |
| N/A | 5 |

Computed by parsing the table's status column (83 rows). One row can cover several subsections.
