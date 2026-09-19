# Execution Status — the live task list

Updated: 2026-09-19 · Plan: `execution-plan.md` · Authoritative statuses: `../c0/traceability.md`

One work package is `IN_PROGRESS` at a time. One implementation task within it wherever practical.

## Work packages

| WP | Scope | Rows | Status |
|---|---|---|---|
| WP-R1 | Reading progress restoration | M26.15 | **IMPLEMENTED — VERIFICATION BLOCKED (E-01a)** |
| WP-L1 | Shelf lifecycle | M22, M47 (INV-10, M23 hold) | **IN_PROGRESS** |
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

## WP-L1 — current tasks

| # | Task | Status |
|---|---|---|
| 1 | Work Details: Remove from Shelf, showing what the library says will be removed | TODO |
| 2 | The confirmation: what goes, what remains, Keep Files vs Delete Files as separate choices | TODO |
| 3 | Mark Completed and un-complete, offering — never performing — deletion | TODO |
| 4 | My Shelf: the same actions from a row | TODO |

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

### Blocked-verification list

**This list is the verification debt.** Nothing leaves it by being reworded. Every entry is re-run once
E-01 is repaired, and only then may the row it belongs to reach `VERIFIED`. While an entry here belongs
to a C-phase, that phase is not fully `VERIFIED`; while any entry remains, OneShelf is not complete.

| # | Blocked check, as originally written | Package | Row | Phase | Re-run when |
|---|---|---|---|---|---|
| BV-01 | "Live: read to page 2 of a seeded unit, leave, re-enter — the reader opens on page 2, with no console errors." | WP-R1 | M26.15 | C2 | E-01 repaired; then M26.15 → `VERIFIED` |
| BV-02 | "live check that a removal dialog reads correctly in both languages" | WP-L1 | M22, M47 | C2 | E-01 repaired; then the language check runs against the built UI |
| BV-03 | Playwright screenshots and axe-core audits for every package from WP-L1 onward | WP-L1+ | M32.x, M45 | C2 | E-01 repaired |

Downstream packages may still begin, under the four-part rule in `execution-plan.md`, when the blocked
check is not a hard dependency of theirs. That judgement is recorded in each package's Definition of
Ready. It does not discharge the debt above.

Environment defects are recorded in `ISSUES.md` under **Environment defects** (E-01, E-01a, E-01b).

## Log

| Date | Event |
|---|---|
| 2026-09-18 | Plan created from the reconciled matrix; WP-R1 started. |
| 2026-09-18 | WP-R1 built and committed (`d8a21a4`); M26.15 marked VERIFIED. |
| 2026-09-19 | **Correction:** that VERIFIED was not earned — the browser re-entry criterion had never run. M26.15 → `IMPLEMENTED`; the step is recorded `BLOCKED_BY_ENVIRONMENT` (E-01a); the criterion is unchanged. Environment defect E-01 recorded. WP-L1 not started. |
| 2026-09-19 | User decision: downstream gates amended to the four-part rule. WP-R1 tracked as **IMPLEMENTED — VERIFICATION BLOCKED (E-01a)**; BV-01 stays on the blocked-verification list. WP-L1 started under point 4 (no shared persistence, security, migration or data-safety assumption). |
