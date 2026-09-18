# Issues — defects found, and the test that holds each one shut

Updated: 2026-09-18 · Plan: `execution-plan.md`

Every reproducible defect is recorded here with the regression test written for it. A defect is closed
only when its test exists and fails without the fix.

| # | Defect | Found by | Regression test | State |
|---|---|---|---|---|
| I-01 | The backups list crashed on every row (`bytes(undefined)`) and could never show "verified": the panel read `size_bytes`/`verified`, which the API does not return | Live run, 2026-09-18 | `test_backup_restore_round_trip` (API now reports `size_bytes` and `present`), `says when an archive's file is no longer where it was` | Closed |
| I-02 | The seven-day backup schedule drifted from its own archives: `create()` stamped `created_at` from the wall clock while `due()` compared against the injected clock | Full suite, 2026-09-18 | `test_schedule_is_seven_days_with_catch_up_after_downtime` (now passes for the right reason) | Closed |
| I-03 | Olive, amber and the wizard step labels failed WCAG AA as small text on paper | axe-core, 2026-09-18 | axe-core run over 21 page states, zero violations | Closed |
| I-04 | Progress stopped being written for any unit already read: the reader began at revision 0, so its first write was stale, and the recovery path called a `GET .../progress` endpoint that did not exist (405) | Live run, 2026-09-18 | `test_progress_can_be_read_back_so_a_reader_knows_the_revision_it_must_carry`, `carries the revision the library already holds, so the first write is not stale` | Closed |
| I-05 | Smart fit did nothing: pages rendered at their own pixel size | Live run, 2026-09-18 | `fits a page to the reading area rather than leaving it at its own pixel size` | Closed |
| I-06 | The scrolling page area could not be reached from the keyboard (WCAG 2.1.1) | axe-core, 2026-09-18 | `lets the keyboard reach the pages themselves, which scroll` | Closed |
| I-07 | A unit opens at page 1 rather than where it was left, although the position is stored and read back | Traceability reconciliation, 2026-09-18 | WP-R1 tests 1–8 in `TEST-MATRIX.md`, led by `opens a unit where it was left rather than at the beginning` | Closed |
