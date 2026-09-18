# Execution Status — the live task list

Updated: 2026-09-18 · Plan: `execution-plan.md` · Authoritative statuses: `../c0/traceability.md`

One work package is `IN_PROGRESS` at a time. One implementation task within it wherever practical.

## Work packages

| WP | Scope | Rows | Status |
|---|---|---|---|
| WP-R1 | Reading progress restoration | M26.15 | **IN_PROGRESS** |
| WP-L1 | Shelf lifecycle | M22, M47 (INV-10, M23 hold) | NOT_STARTED |
| WP-R2 | Long Strip virtualization and preload | M26.6, M26.18 | NOT_STARTED |
| WP-R3 | Book reader comfort | M26.22a, M26.22b | NOT_STARTED |
| WP-S1 | Settings completion | M32.14, M45 | NOT_STARTED |
| WP-R4 | Reader affordances | M26.19, M26.21, M26.14, M26.12, M26.11, M26.2 | NOT_STARTED |
| WP-E1 | Realtime event client | M36 | NOT_STARTED |
| WP-D1 | Diagnostics | M43, DEF-diagnostics | NOT_STARTED |
| WP-R5 | Reader source switching and polish | M26.16, INV-25, M26.3b, M26.24 | NOT_STARTED |
| WP-G1 | Exclusion regression guards | 17 EX rows, M49 | NOT_STARTED |
| WP-B1 | Environment-blocked verification | M2, M2.1, M41.1 | **BLOCKED** |

Consequential rows that close when their causes do: M51 (with INV-25), M56 (with M2.1, M36, M26.6).

## WP-R1 — current tasks

| # | Task | Status |
|---|---|---|
| 1 | `useProgress` returns the progress it read, without writing | TODO |
| 2 | `ReaderScreen` opens at the stored page; Long Strip scrolls to it | TODO |
| 3 | `BookReader` opens at the stored chapter; `PdfView` at the stored page | TODO |
| 4 | An outdated locator is clamped, never an error | TODO |
| 5 | Restoring records no progress | TODO |

## Log

| Date | Event |
|---|---|
| 2026-09-18 | Plan created from the reconciled matrix; WP-R1 started. |
