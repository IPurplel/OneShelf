# Test Matrix — what carries each work package

Updated: 2026-09-19 · Plan: `execution-plan.md`

A row moves to `VERIFIED` in `../c0/traceability.md` only when the tests named here exist and pass. This
file is the link between a requirement and the test that holds it, kept current as each package lands.

## WP-R1 — Reading progress restoration (M26.15)

All eight tests pass. Passing tests are not the whole of this package's verification: its browser
re-entry criterion has not run (`BLOCKED_BY_ENVIRONMENT`, E-01a), so M26.15 stays `IMPLEMENTED`.

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

## Later packages

Their tests are listed in `execution-plan.md` under each package and move here when the package starts.
