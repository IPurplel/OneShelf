# Execution Status — the live task list

Updated: 2026-09-19 · Plan: `execution-plan.md` · Authoritative statuses: `../c0/traceability.md`

One work package is `IN_PROGRESS` at a time. One implementation task within it wherever practical.

## Work packages

| WP | Scope | Rows | Status |
|---|---|---|---|
| WP-R1 | Reading progress restoration | M26.15 | **IMPLEMENTED** — built, tested and committed; verification incomplete (see below) |
| WP-L1 | Shelf lifecycle | M22, M47 (INV-10, M23 hold) | NOT_STARTED — not begun |
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

## WP-R1 — done

| # | Task | Status |
|---|---|---|
| 1 | `useProgress` returns the progress it read, without writing | DONE |
| 2 | `ReaderScreen` opens at the stored page; Long Strip scrolls to it | DONE |
| 3 | `BookReader` opens at the stored chapter; `PdfView` at the stored page | DONE |
| 4 | An outdated locator is clamped, never an error | DONE |
| 5 | Restoring records no progress | DONE |

### Verification state — corrected 2026-09-19

WP-R1 was marked VERIFIED on 2026-09-18 while one of its own criteria had not been executed. That was
wrong, and the status is withdrawn rather than the criterion softened.

| Criterion (from `execution-plan.md`, unchanged) | Result |
|---|---|
| The named tests pass; the whole frontend suite passes; `tsc` clean | **Executed, passed** — 8 tests; frontend 144; backend 794/4 deselected; `tsc` clean |
| Live: read to page 2, leave, re-enter — the reader opens on page 2, no console errors | **NOT EXECUTED — `BLOCKED_BY_ENVIRONMENT` (E-01a)**: Chromium cannot spawn on this host |
| M26.15 → `VERIFIED` with its test names recorded | **Withheld** — M26.15 is `IMPLEMENTED` until the criterion above runs |

A live locator round-trip against the running API was executed and passed. It exercises the contract the
browser step would exercise, but it is **not** a substitute for it and is not counted as one.

### Blocked verification steps

| Step | Package | Status | Unblocked by |
|---|---|---|---|
| Browser re-entry: leave a unit and come back to the same page | WP-R1 | `BLOCKED_BY_ENVIRONMENT` (E-01a) | A host whose PID 1 reaps children, or a fresh container; then re-run and move M26.15 to `VERIFIED` |
| Playwright screenshots and axe-core audits for later packages | WP-L1 onward | `BLOCKED_BY_ENVIRONMENT` (E-01a) | Same |

Environment defects are recorded in `ISSUES.md` under **Environment defects** (E-01, E-01a, E-01b).

## Log

| Date | Event |
|---|---|
| 2026-09-18 | Plan created from the reconciled matrix; WP-R1 started. |
| 2026-09-18 | WP-R1 built and committed (`d8a21a4`); M26.15 marked VERIFIED. |
| 2026-09-19 | **Correction:** that VERIFIED was not earned — the browser re-entry criterion had never run. M26.15 → `IMPLEMENTED`; the step is recorded `BLOCKED_BY_ENVIRONMENT` (E-01a); the criterion is unchanged. Environment defect E-01 recorded. WP-L1 not started. |
