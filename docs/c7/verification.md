# C7 — Verification Report: Storage Management, Import, Backup, Restore and Export

Recorded: 2026-09-17 · Branch: `c7/storage-backup-export` (from `c6/library-follow` @ `ca49d60`) · Authority: Meta Prompt §C7
Status: **C7 gate passed** for the backend described below. The Storage, Import, Backup/Restore and Export screens are C2.

## Commands and results

```sh
cd backend
.venv/bin/pytest          # → 673 passed (622 from C1–C6, 51 new in C7), no warnings
```

No new dependencies.

## Gate checklist (Meta Prompt §C7)

| Gate item | Evidence | Result |
|---|---|---|
| Unavailable destination / root | `test_migration_refuses_an_unavailable_or_overlapping_destination`, `test_offline_root_is_reported_and_never_mass_marked_missing`, C1 `test_unmounted_root_is_unavailable_not_deleted`, `test_local_import.py::test_unavailable_root_fails_before_writing`, export `test_destination_preflight_rejects_missing_or_unwritable_targets` | Pass |
| Space reserve | `test_migration_refuses_a_destination_without_enough_space`, C1 `test_reserve_is_five_percent_capped_at_five_gib`, `test_preflight_keeps_reserve_free`, `test_insufficient_space_is_rejected` | Pass |
| Resumable root migration | `test_migration_copies_verifies_and_switches_without_deleting_the_old_copy`, `test_migration_resumes_after_an_interruption_without_recopying` (the second run copies only what was left; already-copied files are verified, not re-copied) | Pass |
| Old-data preservation (never delete automatically) | `test_migration_copies_verifies_and_switches_without_deleting_the_old_copy`, `test_old_copy_is_removed_only_on_an_explicit_request` | Pass |
| Mount-path-only change | `test_a_mount_path_change_only_remaps_and_validates` (marker plus asset sampling, no copying), C1 `test_remap_root_to_new_mount_path_without_copy`, `test_remap_refuses_path_that_is_not_this_root` | Pass |
| Scanner: manual deletion / relocation | C1 `test_scanner.py` (missing marked but records kept, relocation recovered by id and checksum, different content not adopted, symlinks not followed, staging never a candidate), API `test_storage_overview_and_scan` | Pass |
| Import: Copy default, explicit Move, provenance | `test_local_import.py` (copy default, move deletes the original only after commit, invalid file rejected with no side effects, crash mid-commit recovers to one registration), API `test_import_upload_review_and_commit`, `test_unsupported_import_is_rejected` | Pass |
| Import uncertainty | `test_import_suggestions.py` (exact title with a compatible type is confident; two candidates are never auto-associated; incompatible types are not offered; weak matches are offered but never confident) — anything uncertain comes back as a choice (Choose Work / Create Local Work), never an automatic merge | Pass |
| Backup secret scanning | `test_backup_excludes_every_secret_and_rebuildable_store` — the archive is scanned byte-for-byte for the session key material and the encrypted `secrets.db`, and every excluded or rebuildable table is asserted empty (INV-19) | Pass |
| Consistent snapshots | `test_snapshot_is_consistent_even_if_the_library_changes_during_the_backup` (writes committed while `sqlite3.backup()` runs do not appear in the archive), `test_library_backup_holds_state_but_no_reading_files`, `test_full_backup_includes_only_the_selected_works` | Pass |
| Failed verification does not rotate prior backups | `test_retention_keeps_four_verified_backups_and_never_rotates_before_verifying` (a corrupt new archive fails verification and all four earlier verified backups survive), `test_verification_detects_a_tampered_archive` | Pass |
| Seven-day schedule with catch-up | `test_schedule_is_seven_days_with_catch_up_after_downtime`; `backup/runner.py` runs the missed backup at the next opportunity after downtime and raises a Needs Attention notification only on failure | Pass |
| Backup location warning | `test_same_physical_disk_warning`, API `test_backup_restore_round_trip` (`location_warning.same_device_as_library`) | Pass |
| Version incompatibility | `test_a_newer_backup_is_refused_by_an_older_application`, `test_an_older_backup_migrates_forward_in_staging_without_changing_the_file` (the archive's bytes and hash are unchanged after preflight) | Pass |
| Replace safety snapshot | `test_replace_creates_a_safety_snapshot_first` (the snapshot exists and verifies before anything is replaced) | Pass |
| Deterministic merge conflict cases | `test_merge_adds_missing_records_but_keeps_current_user_decisions`, `test_merge_never_regresses_progress`, `test_merge_repairs_missing_or_corrupt_files_but_leaves_healthy_ones`, API `test_backup_restore_round_trip` | Pass |
| Plugin absence / permission review | `test_missing_plugins_do_not_block_restore_and_are_reported`, `test_new_plugin_permissions_require_explicit_approval` (reported for review; never granted by a restore) | Pass |
| Export interruptions / conflicts / per-file failures | `test_export_resumes_after_an_interruption` (per-item state; completed files are not re-copied), `test_conflict_policies` (Skip Identical / Replace / Keep Both), `test_one_failed_file_does_not_fail_the_export_and_can_be_retried` | Pass |
| Export scope, including Selected Works | `test_selected_works_export_as_one_job_without_mixing_them` (one job, one contract per work, one folder per work and language), API `test_export_accepts_several_selected_works`; unit scopes come from the contract's `unit_ids` | Pass |
| Export copies originals, no conversion | `test_export_copies_originals_without_touching_the_library` (byte-identical copies; library rows and files unchanged), `test_missing_content_offers_choices_and_never_converts_formats`, `test_zip_output_stores_already_compressed_files`, `test_sequential_units_default_to_cbz_while_books_keep_their_original` (§34.4: the default only picks among files that already exist), API `test_export_preview_and_run` | Pass |
| History cleanup preserves files | `test_history_cleanup_never_deletes_exported_files` (job records go, exported files stay), API `test_export_preview_and_run` | Pass |
| Explicit missing-content download notice | `test_download_missing_requires_an_explicit_permanent_download_notice` — `start()` raises `ExportBlocked` unless the caller acknowledges the exact disclosure, and the download then goes through the normal permanent commit pipeline (INV-21) | Pass |
| Local content exports with the plugin absent | `test_local_only_content_exports_without_any_plugin` | Pass |

## What C7 delivers (backend)

| Area | Modules |
|---|---|
| Resumable storage migration, remap, discard old copy | `storage/migration.py`, migration `0009_storage.sql` |
| Library and Full Backup, verification, retention, schedule, location warning | `backup/service.py`, `backup/runner.py` |
| Restore preflight, forward migration in staging, Replace with Safety Snapshot, deterministic Merge | `restore/service.py` |
| Export contract, preview, resumable copy, conflict policies, retry, history cleanup | `export/service.py`, migration `0010_export.sql` |
| Conservative import association | `importer/suggest.py` |
| HTTP surface for all of the above | `api/storage.py` |

## Notes and decisions

- **Local imports are now indexed for search.** `register_local_import` writes the work's search rows inside the same commit-journal transaction (`search/index.py::write_work_index`), so an imported work is findable in local-first search and can be suggested as an association target for the next import. The gap was found by the API gate test; a failing unit test (`test_locally_imported_work_is_searchable`) was written first.
- **Upload display name.** `/api/import/uploads` takes an optional `filename` query parameter used only as a label for the suggested title. The stored path is always the opaque upload id, so a client-supplied name can never influence where bytes land.
- **Backup exclusions are by construction.** `secrets.db`, the key file and `cache.db` are never opened by the backup service. The excluded authoritative tables (commit journal, download jobs and batches, search index, health signals, storage-migration bookkeeping, source session refs) are cleared from the snapshot copy, which is vacuumed before it is archived.
- **Success is silent.** A completed scheduled backup raises no notification (§30.11); only a failure creates one, dedupe key `backup-failed`, resolved on the next success.

## Open items for review

D-C7-01 … D-C7-10 are recorded in `docs/c0/conflict-review-ledger.md` §12. Three want your decision:

| ID | Item |
|---|---|
| D-C7-01 | Merge restores records missing from the current library, including Shelf entries deliberately removed after the backup was taken. The Master has no tombstones, so a removal cannot be told apart from a loss. |
| D-C7-02 | Export output layout is one folder per work and language, `<Work Title> (<language>)/`, with the `oneshelf-export.json` sidecar inside it; ZIP wraps that same folder. |
| D-C7-04 | Backup retention is four verified archives in one backup location; several simultaneous backup locations are not modelled in v1. |
