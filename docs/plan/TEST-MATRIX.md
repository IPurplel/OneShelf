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

## Later packages

Their tests are listed in `execution-plan.md` under each package and move here when the package starts.
