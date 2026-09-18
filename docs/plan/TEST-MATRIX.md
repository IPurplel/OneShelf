# Test Matrix — what carries each work package

Updated: 2026-09-18 · Plan: `execution-plan.md`

A row moves to `VERIFIED` in `../c0/traceability.md` only when the tests named here exist and pass. This
file is the link between a requirement and the test that holds it, kept current as each package lands.

## WP-R1 — Reading progress restoration (M26.15)

| # | Test | File | State |
|---|---|---|---|
| 1 | opens a unit at the stored page rather than at the beginning | `SequentialReader.test.tsx` | planned |
| 2 | brings the stored page into view in Long Strip | `SequentialReader.test.tsx` | planned |
| 3 | clamps a stored page that is past the end of the unit | `SequentialReader.test.tsx` | planned |
| 4 | starts at the beginning when the library has no position | `SequentialReader.test.tsx` | planned |
| 5 | restoring a position writes no progress | `SequentialReader.test.tsx` | planned |
| 6 | the Book Reader opens at the stored chapter | `BookReader.test.tsx` | planned |
| 7 | the PDF viewer opens at the stored page | `PdfView.test.tsx` | planned |

Existing tests that must keep passing: `writes progress once the reader settles, carrying the revision it
last saw`, `carries the revision the library already holds, so the first write is not stale`, `flushes
progress when the tab is hidden`, `test_progress_writes_reject_stale_tabs_but_allow_explicit_changes`.

## Later packages

Their tests are listed in `execution-plan.md` under each package and move here when the package starts.
