# C6 — Verification Report: Shelf, Follow, Health, Attention and Live Events

Recorded: 2026-09-17 · Branch: `c6/library-follow` (from `c5/downloads` @ `f859acd`) · Authority: Meta Prompt §C6
Status: **C6 gate passed** for the backend described below. My Shelf, Following, Notifications and Needs Attention screens are C2.

## Commands and results

```sh
cd backend
.venv/bin/pytest          # → 621 passed (C1 158 + C3 279 + C4 90 + C5 50 + C6 44), no warnings
```

No new dependencies.

## Gate checklist (Meta Prompt §C6)

| Gate item | Evidence | Result |
|---|---|---|
| First Follow baseline | `test_first_follow_baselines_without_flooding` (3 existing units become the baseline; the first check reports nothing and writes no release events) · API `test_follow_reports_new_releases_and_notifies_without_downloading` | Pass |
| Source change | `test_changing_preferred_source_baselines_without_flood_and_keeps_progress` (new Source Change Baseline, no flood, reading progress untouched) | Pass |
| Added irregular units | `test_only_genuinely_added_units_are_new` (a Special and a later chapter are both reported, by catalog comparison not numbering) | Pass |
| Existing-unit rename / reorder / reappearance | `test_metadata_changes_reordering_and_reappearance_are_not_new` | Pass |
| Complete status preservation | `test_completed_survives_new_releases_and_counts_them` (stays Completed, reports "2 releases since completion") | Pass |
| Independent Shelf / Follow / files / progress | `test_remove_from_shelf_offers_file_choices_and_keeps_other_state`, `test_delete_files_keeps_follow_shelf_and_progress`, `test_unfollow_is_immediate_with_undo_and_touches_nothing_else`, API `test_removal_summary_then_remove_keeps_follow_and_progress` (INV-10) | Pass |
| Notification actions never mark content read | `test_seen_state_is_independent_from_reading_state`, API `test_marking_notifications_seen_never_changes_reading_state` (INV-22) | Pass |
| Source / root deduplication | `test_repeated_problems_update_one_notification` (20 works → one reconnect notification with count 20), `test_low_storage_is_deduplicated_per_root` | Pass |
| Bounded history cleanup | `test_retention_is_bounded_by_age_and_count` (500 entries, then 30 days) | Pass |
| No browser notifications | `tests/unit/test_no_browser_notifications.py` (source scan for Notification/serviceWorker/push APIs and push dependencies; verified it detects a planted violation) | Pass |
| Multi-client updates | `test_domain_changes_reach_every_connected_client` (two subscribers receive shelf, follow and notification events) plus the SSE endpoint from C1 | Pass |
| Stale-progress protection | C5 `test_progress_writes_reject_stale_tabs_but_allow_explicit_changes` and the API `STALE_PROGRESS` test | Pass |
| Health thresholds, hysteresis and distinctions | `test_health_and_notifications.py` (one failure ≠ degraded; 3 → degraded, 6 → unavailable; recovery needs two successes; rate limit and auth are their own states; 404s never degrade; plugin version recorded with a plugin-update hint; active checks are low priority and never browser; evaluating changes no settings or jobs) · API `test_health_state_reflects_recorded_signals` | Pass |

## What C6 delivers (backend)

| Area | Modules |
|---|---|
| My Shelf: views, favourite/pin, completed, local-only search, removal summary, delete files | `library/shelf.py` |
| Follow: baselines, release detection, preferred-source change, unfollow with undo, schedule | `follow/service.py`, migration `0008_follow.sql` |
| Follow scheduler and Check Now / Check All | `follow/runner.py` |
| Capability health with hysteresis and explicit active checks | `health/service.py` |
| Notifications, grouping, Seen/Unseen, retention, Needs Attention | `notifications/service.py` |
| Failure notifications raised by the download engine | `downloads/engine.py` (`_notify_failure`) |
| API | `api/shelf.py`: shelf views/actions/removal, follows (+check, preferred source, undo), notifications (+mark all seen, clear seen, cleanup, attention filter), health state |

## Known limitations / carried forward (not gate failures)

- **Hero "relevant new-release Work"** (§31.4) can now be built on release events; it is wired with the Home screen in C2.
- **Undo for Unfollow** is kept in memory for the session; a restart drops the undo token (the follow itself is already removed, nothing else is affected).
- **Rate-limit notifications** stay status-only; the "prolonged and materially blocking" case (§30.6) needs the UI's blocking context and is revisited in C2.
- **Backup / import notifications** (§30.11) arrive with C7.
- **Export activity and backup history** stay separate stores by design (§35) and are implemented in C7.
- **Active health checks** are exposed as a service method; the Settings → Sources control that triggers them is C2.
