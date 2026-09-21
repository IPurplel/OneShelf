# Test Matrix — what carries each work package

Updated: 2026-09-19 · Plan: `execution-plan.md`

A row moves to `VERIFIED` in `../c0/traceability.md` only when the tests named here exist and pass. This
file is the link between a requirement and the test that holds it, kept current as each package lands.

## WP-R1 — Reading progress restoration (M26.15)

All eight tests pass, **and** the package's live criterion (BV-01) was executed on 2026-09-19 and passed.
M26.15 is `VERIFIED`.

| # | Test | File | State |
|---|---|---|---|
| 1 | `opens a unit where it was left rather than at the beginning` | `SequentialReader.test.tsx` | **passing** |
| 2 | `brings the stored page into view in Long Strip, where every page is on screen` | `SequentialReader.test.tsx` | **passing** |
| 3 | `clamps a stored position that is past the end of the unit` | `SequentialReader.test.tsx` | **passing** |
| 4 | `starts at the beginning when the library holds no position` | `SequentialReader.test.tsx` | **passing** |
| 5 | `writes nothing merely by resuming, so a newer tab is never overwritten` | `SequentialReader.test.tsx` | **passing** |
| 6 | `opens the book at the chapter it was left on` | `BookReader.test.tsx` | **passing** |
| 7 | `opens the document at the page it is given` | `PdfView.test.tsx` | **passing** |
| 8 | `is given the page the library holds, through the Book Reader that renders it` | `PdfView.test.tsx` | **passing** |

Test 8 was added during the package: tests 1–7 as planned would have covered the PDF component's own
contract but not the wiring that hands it the library's position, which is where the defect actually was.

Existing tests that must keep passing: `writes progress once the reader settles, carrying the revision it
last saw`, `carries the revision the library already holds, so the first write is not stale`, `flushes
progress when the tab is hidden`, `test_progress_writes_reject_stale_tabs_but_allow_explicit_changes`.

## WP-L1 — Shelf lifecycle (M22, M47; INV-10 and M23 hold)

Eight UI tests, five backend tests (three added during the review), and BV-02 executed live.

| # | Test | File | State |
|---|---|---|---|
| 1 | `asks before removing a work that has files or progress, and says what stays` | `WorkScreen.test.tsx` | **passing** |
| 2 | `keeps the files when that is the choice` | `WorkScreen.test.tsx` | **passing** |
| 3 | `deletes the files only when that is the explicit choice` | `WorkScreen.test.tsx` | **passing** |
| 4 | `removes at once when there is nothing to lose` | `WorkScreen.test.tsx` | **passing** |
| 5 | `changes nothing when the removal is cancelled` | `WorkScreen.test.tsx` | **passing** |
| 6 | `marks a work completed, and offers — never performs — deleting its files` | `WorkScreen.test.tsx` | **passing** |
| 7 | `says the same things in Arabic, where the interface mirrors` | `WorkScreen.test.tsx` | **passing** |
| 8 | `removes a work from a shelf row, with the same confirmation Work Details gives` | `ShelfScreen.test.tsx` | **passing** |
| 9 | `reports the deletions the library actually made, not the ones it predicted` | `WorkScreen.test.tsx` | **passing** (I-09) |
| 10 | `reports the same way when Completed offers to delete the files` | `WorkScreen.test.tsx` | **passing** (I-09) |
| 11 | `counts one file as one file, in both languages` | `WorkScreen.test.tsx` | **passing** (I-10) |
| 12 | `test_delete_files_touches_only_this_works_files` | `test_shelf_and_follow.py` | **passing** |
| 13 | `test_the_library_cannot_even_record_a_path_outside_its_root` | `test_shelf_and_follow.py` | **passing** |
| 14 | `test_a_symlink_standing_in_for_a_managed_file_is_refused_and_never_counted` | `test_shelf_and_follow.py` | **passing** (I-08) |

Already existing and still passing: `test_remove_from_shelf_offers_file_choices_and_keeps_other_state`,
`test_delete_files_keeps_follow_shelf_and_progress`, `test_completed_survives_new_releases_and_counts_them`,
`test_delete_managed_file_only_deletes_regular_files_inside_root`.

## WP-R2 — Long Strip virtualization and preload (M26.6, M26.18)

| # | Test | File | State |
|---|---|---|---|
| 1 | `holds only a bounded window of a long chapter, not the whole of it` | `SequentialReader.test.tsx` | **passing** |
| 2 | `moves the window as the reader scrolls, and keeps the scroll height steady` | `SequentialReader.test.tsx` | **passing** |
| 3 | `preloads the next seven and the previous four, and no further` | `SequentialReader.test.tsx` | **passing** |
| 4 | `prefetches the band around a single page without putting it on screen` | `SequentialReader.test.tsx` | **passing** |
| 5 | `resumes inside the window, so virtualization does not lose the position` | `SequentialReader.test.tsx` | **passing** |
| 6 | `writes progress as the reader scrolls, with the revision it last saw` | `SequentialReader.test.tsx` | **passing** |
| 7 | `reads its position from the pages themselves, not from an estimated height` | `SequentialReader.test.tsx` | **passing** |
| 8 | `reserves each page's space before it loads, so the strip does not shift under the reader` | `SequentialReader.test.tsx` | **passing** (I-11) |
| 9 | `test_reader_settings_come_from_the_one_defaults_registry` | `test_work_api.py` | **passing** |

Live criterion executed 2026-09-19: 12 of 120 pages mounted, window follows the scroll, page 34 stored,
re-entry restores 34/120, no console errors.

## WP-R3 — Book reader comfort (M26.22a, M26.22b)

| # | Test | File | State |
|---|---|---|---|
| 1 | `lets the reader set type, spacing, margins and theme, without loosening the frame` | `BookReader.test.tsx` | **passing** |
| 2 | `remembers the reading comfort for this book` | `BookReader.test.tsx` | **passing** |
| 3 | `zooms in, out and back to the fit` | `PdfView.test.tsx` | **passing** |
| 4 | `fits the whole page when asked, and remembers the choice` | `PdfView.test.tsx` | **passing** |
| 5 | `lets the keyboard reach the page area, which scrolls once it is zoomed` | `PdfView.test.tsx` | **passing** (I-13) |

Live criteria executed 2026-09-19, both formats; the isolation tests still pass unchanged.

## WP-S1 — Settings completion (M32.14, M45, M30.10)

| # | Test | File | State |
|---|---|---|---|
| 1 | `has no category left saying it is coming later` | `SettingsScreen.test.tsx` | **passing** |
| 2 | `keeps the technical knobs behind disclosure, and writes what the reader chooses` | `SettingsScreen.test.tsx` | **passing** |
| 3 | `offers auto-download as the Master defines it: off, and with its own reach` | `SettingsScreen.test.tsx` | **passing** |
| 4 | `turns the Source Recovered notice on, which is off until asked for` | `SettingsScreen.test.tsx` | **passing** |
| 5 | `test_download_settings_are_the_ones_the_engine_actually_reads` | `test_library_api.py` | **passing** |
| 6 | `test_notification_preferences_are_the_ones_the_service_honours` | `test_shelf_api.py` | **passing** |
| 7 | `test_source_recovered_is_silent_unless_it_is_turned_on` | `test_health_and_notifications.py` | **passing** |
| 8 | `test_the_guard_sees_the_whole_api_not_a_handful_of_routes` | `test_route_order.py` | **passing** (I-14) |
| 9 | `test_reordering_a_queue_reaches_the_engine` | `test_library_api.py` | **passing** (I-15) |

Live criterion executed 2026-09-19: ten categories in both languages, real controls everywhere, no
placeholders, 0 axe violations.

## WP-R4 — Reader affordances (M26.2, M26.11, M26.12, M26.14, M26.19, M26.21)

| # | Test | File | State |
|---|---|---|---|
| 1 | `says whether this unit is on the device, and can fetch the whole work` | `SequentialReader.test.tsx` | **passing** |
| 2 | `marks a unit unread as readily as read` | `SequentialReader.test.tsx` | **passing** |
| 3 | `offers Retry, Repair from Source and Skip when a page will not load` | `SequentialReader.test.tsx` | **passing** |
| 4 | `moves through the unit with a scrubber that respects reading direction` | `SequentialReader.test.tsx` | **passing** |
| 5 | `filters the contents by what is new, as well as unread and downloaded` | `SequentialReader.test.tsx` | **passing** |
| 6 | `test_units_say_whether_their_local_copy_is_sound` | `test_work_api.py` | **passing** |
| 7 | `test_a_local_work_has_no_source_to_repair_from` | `test_work_api.py` | **passing** |
| 8 | `test_repair_downloads_a_broken_copy_again_through_the_normal_pipeline` | `test_engine.py` | **passing** |
| 9 | `test_units_say_which_of_them_are_new` | `test_shelf_api.py` | **passing** |

Live criterion executed 2026-09-19 against a real library.

## WP-E1 — Realtime event client (M36)

| # | Test | File | State |
|---|---|---|---|
| 1 | `tells a screen to re-read when the library says something changed` | `live.test.tsx` | **passing** |
| 2 | `falls back to polling while the stream is down, and stops once it is back` | `live.test.tsx` | **passing** |
| 3 | `re-opens the stream after an error, and keeps the screens fed meanwhile` | `live.test.tsx` | **passing** |
| 4 | `re-reads on a resync rather than guessing what it missed` | `live.test.tsx` | **passing** |
| 5 | `follows the library live, re-reading only what changed` | `DownloadsScreen.test.tsx` | **passing** |

Live criterion executed 2026-09-19 with two tabs sharing one stream.

## WP-D1 — Diagnostics (M43, DEF-diagnostics)

| # | Test | File | State |
|---|---|---|---|
| 1 | `keeps what it is given, redacted, under the category it was filed` | `unit/diagnostics/test_store.py` | **passing** |
| 2 | `refuses a category the Master does not name` | `unit/diagnostics/test_store.py` | **passing** |
| 3 | `drops what is older than seven days` | `unit/diagnostics/test_store.py` | **passing** |
| 4 | `drops the oldest first when it no longer fits in a hundred megabytes` | `unit/diagnostics/test_store.py` | **passing** |
| 5 | `clearing leaves nothing behind` | `unit/diagnostics/test_store.py` | **passing** |
| 6 | `a message with arguments survives redaction and still says what happened` (I-18) | `unit/diagnostics/test_redact.py` | **passing** |
| 7 | `the diagnostics store takes operational records only` (INV-29) | `unit/test_no_matcher_telemetry.py` | **passing** |
| 8 | `a matching pass writes nothing to the diagnostics store` (INV-29) | `unit/test_no_matcher_telemetry.py` | **passing** |
| 9 | `diagnostics are local, bounded and clearable` | `integration/test_app.py` | **passing** |
| 10 | `a source failure becomes a local diagnostic` | `integration/sources/test_test_source_pipeline.py` | **passing** |
| 11 | `a check that fails leaves a diagnostic saying why` | `integration/library/test_shelf_and_follow.py` | **passing** |
| 12 | `shows what the local diagnostics hold, and can clear them` | `SettingsScreen.test.tsx` | **passing** |

Live criterion executed 2026-09-20 (`wpd1.py` PASS): real failures filled the store, the panel read its
bounds, nothing sensitive was written, clearing emptied it, axe clean.

## WP-R5 — Reader source switching and remaining polish (M26.16, INV-25, M26.3b, M26.24, M26.5, M32.9)

| # | Test | File | State |
|---|---|---|---|
| 1 | `a same-language source with the same chapter is offered confidently` | `unit/reader/test_alternatives.py` | **passing** |
| 2 | `another language is never offered as an alternative` (INV-02) | `unit/reader/test_alternatives.py` | **passing** |
| 3 | `a source that does not have this chapter says so rather than guessing` | `unit/reader/test_alternatives.py` | **passing** |
| 4 | `two candidates with the same number are not a confident match` | `unit/reader/test_alternatives.py` | **passing** |
| 5 | `a unit with no number of its own is never matched by position` | `unit/reader/test_alternatives.py` | **passing** |
| 6 | `a chapter and a special sharing a number are not the same unit` | `unit/reader/test_alternatives.py` | **passing** |
| 7 | `the local files track is an alternative like any other` | `unit/reader/test_alternatives.py` | **passing** |
| 8 | `the reader can ask what another source offers for this unit` | `integration/test_work_api.py` | **passing** |
| 9 | `asking about a unit that is not here is a plain 404` | `integration/test_work_api.py` | **passing** |
| 10 | `says which source and language this unit is being read from` | `SourceSwitch.test.tsx` | **passing** |
| 11 | `offers another source's copy of this unit without ever claiming the same page` | `SourceSwitch.test.tsx` | **passing** |
| 12 | `says so plainly when the other source's copy cannot be found, and offers its track instead` | `SourceSwitch.test.tsx` | **passing** |
| 13 | `opens an approximate position as approximate, and says so` (INV-25) | `SourceSwitch.test.tsx` | **passing** |
| 14 | `hides the bars until they are summoned, in the minimal control mode` | `SourceSwitch.test.tsx` | **passing** |
| 15 | `shows the centre-tap hint once, and never again` | `SourceSwitch.test.tsx` | **passing** |
| 16 | `holds each page's place while it loads, rather than collapsing the strip` | `SourceSwitch.test.tsx` | **passing** |
| 17 | `opens the track the reader sent it to, rather than the preferred one` | `WorkScreen.test.tsx` | **passing** |
| 18 | `gives its tabs something to control, so a screen reader can follow them` (I-19) | `WorkScreen.test.tsx` | **passing** |
| 19 | `starts the next unit clean, rather than carrying the last one's failures into it` (I-20) | `SequentialReader.test.tsx` | **passing** |
| 20 | `downloads this unit from the keyboard, like every other reading action` (M26.5) | `SequentialReader.test.tsx` | **passing** |
| 21 | `sorts the shelf by title or by when a work arrived, without asking the library again` (M32.9) | `ShelfScreen.test.tsx` | **passing** |

Live criteria executed 2026-09-20 (`wpr5.py` and `wpr5b.py`, both PASS) against two seeded same-language
alternatives — one that matched confidently, one that did not.

## WP-G1 — Exclusion regression guards (17 EX rows, M49)

| # | Guard module | Covers | State |
|---|---|---|---|
| 1 | `exclusions/test_no_accounts_or_multi_user.py` (4 tests) | EX-01, EX-02 | **passing** |
| 2 | `exclusions/test_no_executable_plugins_or_rpc.py` (3) | EX-04 (and EX-03's architecture) | **passing** |
| 3 | `exclusions/test_no_translation_or_ai_matching.py` (4) | EX-08, EX-11 | **passing** |
| 4 | `exclusions/test_no_social_or_commercial_surfaces.py` (5) | EX-16 to EX-22 | **passing** |
| 5 | `exclusions/test_no_bypass_or_screenshot_extraction.py` (7) | EX-24, EX-26, EX-27 | **passing** |
| 6 | `exclusions/test_no_dedup_or_annotation_system.py` (5) | EX-14, EX-15 | **passing** |
| 7 | `exclusions/test_every_exclusion_is_guarded.py` (3) | M49 — all 30 items of §49 | **passing** |
| 8 | `test_work_api.py::test_the_same_file_imported_twice_is_stored_twice` | EX-14, behaviourally | **passing** |

Verified by violation on 2026-09-20: eight deliberate violations introduced one at a time, each caught
by the right guard, each reverted. Two guards were strengthened when they did not catch theirs.

## WP-B1 (part) — the three available sources (M41.1)

| # | Test | File | State |
|---|---|---|---|
| 1 | `the expected adapters ship` (seven packages) | `integration/plugins/test_official_packages.py` | **passing** |
| 2 | `an official adapter passes the tests it ships with` (7 packages) | same | **passing** |
| 3 | `an official adapter declares what it can and cannot do` (7 packages) | same | **passing** |
| 4 | `a recipe may declare the headers its resources need` | `unit/plugins/test_package_validation.py` | **passing** |
| 5 | `resource headers may not smuggle credentials or spoof the hop` (4) | same | **passing** |
| 6 | `a recipe may follow the url its own catalog captured` | same | **passing** |
| 7 | `following a url without saying it is absolute is refused rather than silently encoded` | same | **passing** |
| 8 | `an absolute url can be requested as it was given` | `unit/plugins/test_templates.py` | **passing** |
| 9 | `the absolute encoder refuses anything that is not a plain http url` (7) | same | **passing** |
| 10 | `a json response can say where its markup is` | `unit/plugins/test_runtime.py` | **passing** |
| 11 | `markup_at only makes sense for a json response` | same | **passing** |
| 12 | `an item template can use the recipe's own inputs` (I-23) | same | **passing** |
| 13 | `a recipe can say which headers its resources need` | `integration/sources/test_test_source_pipeline.py` | **passing** |
| 14 | `webtoon work catalog and the episode images` | `live/test_source_suite.py` | **passing (live)** |
| 15 | `tapas series episodes and the episode images` | same | **passing (live)** |
| 16 | `hindawi search book and a real epub` | same | **passing (live)** |

Live criteria executed 2026-09-20 with `ONESHELF_LIVE_SOURCES=1`: seven live tests pass. Each new one
opens the artefact it fetched — images through the download path's own validators and into a CBZ the
integrity validator accepts, and an EPUB opened as a zip with its mimetype checked.

## WP-B1 (part) — 3asq at its current domain (M41.1)

| # | Test | File | State |
|---|---|---|---|
| 1 | `the source id carries no domain so a move never forks identity` | `unit/plugins/test_3asq_package.py` | **passing** |
| 2 | `the canonical domain is the one that answers` | same | **passing** |
| 3 | `it asks for one permission and no more` | same | **passing** |
| 4 | `the policy refuses everything that is not this source` (7 cases: old domain, old scheme, private, lookalike, file://) | same | **passing** |
| 5 | `the policy allows the source itself` | same | **passing** |
| 6 | `a site that answers 404 past the last page is finished not broken` | `unit/plugins/test_runtime.py` | **passing** |
| 7 | `a 404 on the very first page is still a failure` | same | **passing** |
| 8 | five packaged cases — search, work, catalog, reader, latest | `plugins/official/oneshelf.3asq/tests/tests.yaml` | **passing** |
| 9 | `3asq search series chapters and a real page` | `live/test_source_suite.py` | **passing (live)** |

The packaged `latest` fixture keeps a real coverless series and a translator's external link, so I-26
cannot return. Installation and activation were checked through `/api/sources/install`: state `active`,
capabilities search, work, catalog, reader, latest, and one permission requested.

## WP-REL — installation and the served interface (REL-01…REL-06)

| # | Test | File | State |
|---|---|---|---|
| 1 | Docker detected when it is the one that works | `tests/deploy/test_install_scripts.py` | **passing** |
| 2 | Podman detected, and preferred where both answer | same | **passing** |
| 3 | no runtime at all: clear failure, install instructions, never sudo | same | **passing** |
| 4 | installed but not answering: says which and how to start it | same | **passing** |
| 5 | an explicit `ONESHELF_RUNTIME` is honoured | same | **passing** |
| 6 | Compose plugin used when present | same | **passing** |
| 7 | standalone `podman-compose` used when the plugin is missing | same | **passing** |
| 8 | a runtime with no Compose at all is a clear failure | same | **passing** |
| 9 | first run creates `.env` from the example, mode 600 | same | **passing** |
| 10 | an existing `.env` is never overwritten, and is honoured | same | **passing** |
| 11 | running install again changes nothing it should not | same | **passing** |
| 12 | only OneShelf's own five directories are created | same | **passing** |
| 13 | no secret is ever printed | same | **passing** |
| 14 | a readiness failure fails the install, with diagnostics | same | **passing** |
| 15 | a failing container command fails the install | same | **passing** |
| 16 | update refuses before an install | same | **passing** |
| 17 | update refuses with local changes, and says the library is untouched | same | **passing** |
| 18 | update continues without git and still verifies | same | **passing** |
| 19 | **uninstall keeps every byte of the library by default** | same | **passing** |
| 20 | uninstall refuses an unknown option | same | **passing** |
| 21 | deleting data requires typing the whole sentence | same | **passing** |
| 22 | deleting data removes its own directories and nothing else | same | **passing** |
| 23 | the scripts are executable in git | same | **passing** |
| 24 | shellcheck | same | *skipped — not installed here* |
| 25 | the interface is served at the root | `tests/integration/test_web_ui.py` | **passing** |
| 26 | its assets are served too | same | **passing** |
| 27 | a client route falls back to the interface rather than 404 | same | **passing** |
| 28 | the API still answers as the API | same | **passing** |
| 29 | nothing outside the web root can be reached (3 cases) | same | **passing** |
| 30 | the interface is behind the same boundary as everything else | same | **passing** |
| 31 | without a built interface the API still runs | same | **passing** |

Live 2026-09-21, outside a container: the real `vite build` output served from the API origin — `/`,
a hashed asset, a deep link, `/api/health` still JSON, `/api/nope` still 404 — and the full UI
rendered in Chromium with no console errors.

**Not covered here:** anything that needs a container runtime. REL-08's gate is unexecuted.

## WP-REL — clean-clone check against the published repository (2026-09-21)

Run from a clone of `https://github.com/IPurplel/OneShelf` in an isolated temporary directory, using
nothing from the development checkout.

| # | Check | Result |
|---|---|---|
| 1 | every file an install needs is present in the clone | **pass** (11 of 11) |
| 2 | `install.sh`, `update.sh`, `uninstall.sh` executable after clone | **pass** |
| 3 | no `.env`, `deploy/volumes` or `backend/var` came with it | **pass** |
| 4 | all four scripts parse (`bash -n`) | **pass** |
| 5 | with no runtime, `install.sh` refuses clearly and exits 1 | **pass** |
| 6 | with a runtime, it detects Compose, creates `.env`, creates its five directories, passes `--env-file` and `-p oneshelf`, builds, starts | **pass** |
| 7 | readiness failure is reported honestly when nothing is running | **pass** |
| 8 | the container actually starts and serves | **not run — needs a runtime (REL-08)** |

## WP-REL — official sources included automatically (REL-10, REL-11)

| # | Requirement test | Where | State |
|---|---|---|---|
| 1 | fresh database: all eight installed and active | `test_bundled_sources.py`, `test_bundled_sources_api.py` | **passing** |
| 2 | restart: no duplicate plugin or version rows | `test_restarting_changes_nothing_and_duplicates_nothing` | **passing** |
| 3 | application restart: bootstrap stays idempotent | same, and `test_restarting_the_application_keeps_the_person_s_choices` | **passing** |
| 4 | disabled source stays disabled across restarts | `test_a_source_the_person_disabled_stays_disabled_across_restarts` | **passing** |
| 5 | uninstalled source is never reinstalled | `test_a_source_the_person_removed_is_never_reinstalled` | **passing** |
| 6 | mappings, Shelf, Follow, progress survive an update | `test_an_update_leaves_the_library_that_depends_on_the_source_untouched` | **passing** |
| 7 | same version: no reinstall | `test_restarting_changes_nothing…`, `test_the_build_is_deterministic…` | **passing** |
| 8 | newer version, same permissions: validated update with rollback | `test_a_newer_bundled_version_updates_through_the_normal_path_keeping_rollback` | **passing** |
| 9 | newer version, more permissions: pending review, not approved | `test_a_newer_version_asking_for_more_goes_to_review…` | **passing** |
| 10 | broken package: never partially active | `test_a_broken_adapter_is_never_active…`, `test_an_adapter_whose_own_tests_fail…` | **passing** |
| 11 | production image carries the adapters | `test_image_contains_bundled_sources.py` (static); host gate (real container) | **static passing; container not run** |
| 12 | `GET /api/sources` lists all eight after a fresh start | `test_a_fresh_start_lists_all_eight_official_sources_as_active` | **passing** |

Also: disabled sources are not updated; a hand-reinstalled source is the owner's; a rolled-back source is not
rolled forward; an interrupted bootstrap resumes; failures are retried only when the package changes; an
existing library is recorded as skipped; Needs Attention is raised and cleared; readiness is never blocked.
Four guards verified by mutation. Frontend: the "Official · Bundled" label and the First Run copy.

## Later packages

Their tests are listed in `execution-plan.md` under each package and move here when the package starts.

## Release handoff verification (2026-09-20 workspace date)

The later handoff review extends, rather than replaces, the original 23 script cases above.
`backend/tests/deploy/`: **58 passed, 1 skipped** (ShellCheck unavailable). Runtime commands are stubbed;
Git repositories, filesystem operations, script execution and HTTP healthcheck responses are real.

Added evidence covers successful install/rerun, health JSON rejection, missing probe tools, explicit
Compose env-file and shell overrides, quoted values, custom plugin/backup paths, directory failures,
unsafe/overlapping/symlink paths, nondestructive uninstall without mkdir, purge restrictions, real Git
fast-forward/ahead/divergence and linked-worktree checks, ownership failure, legacy-store refusal,
nonempty unmarked custom storage, and image-level legacy and healthcheck guards.

Fresh full backend: **989 passed, 1 skipped, 8 live tests deselected**. Frontend: **196 passed**;
`npm run build` passes (typecheck included). Container execution is not represented by these totals.
Live results and public clean-clone evidence are in `release-handoff.md`.
