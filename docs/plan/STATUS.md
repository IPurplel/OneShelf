# Execution Status — the live task list

Updated: 2026-09-19 · Plan: `execution-plan.md` · Authoritative statuses: `../c0/traceability.md`

One work package is `IN_PROGRESS` at a time. One implementation task within it wherever practical.

## Work packages

| WP | Scope | Rows | Status |
|---|---|---|---|
| WP-R1 | Reading progress restoration | M26.15 | **VERIFIED** — BV-01 executed 2026-09-19 |
| WP-L1 | Shelf lifecycle | M22, M47 (INV-10, M23 hold) | **VERIFIED** — BV-02 executed 2026-09-19 |
| WP-R2 | Long Strip virtualization and preload | M26.6, M26.18 | **VERIFIED** — live check executed 2026-09-19 |
| WP-R3 | Book reader comfort | M26.22a, M26.22b | **VERIFIED** — live checks executed 2026-09-19 |
| WP-S1 | Settings completion | M32.14, M45 | **VERIFIED** — live check executed 2026-09-19 |
| WP-R4 | Reader affordances | M26.19, M26.21, M26.14, M26.12, M26.11, M26.2 | **VERIFIED** — live check executed 2026-09-19 |
| WP-E1 | Realtime event client | M36 | **IN_PROGRESS** |
| WP-D1 | Diagnostics | M43, DEF-diagnostics | NOT_STARTED |
| WP-R5 | Reader source switching and polish | M26.16, INV-25, M26.3b, M26.24 | NOT_STARTED |
| WP-G1 | Exclusion regression guards | 17 EX rows, M49 | NOT_STARTED |
| WP-B1 | Environment-blocked verification | M2, M2.1, M41.1 | **BLOCKED** |

Consequential rows that close when their causes do: M51 (with INV-25), M56 (with M2.1 and M36 — its
bounded-memory clause closed with M26.6).

## WP-R4 — done and verified

Download state in the top bar, Download Entire Work and the rest of More, page recovery
(Retry / Repair from Source / Skip), Mark as unread, the New filter, and the scrubber.

Backend needed for it: units carry `integrity` and `is_new`; `enqueue(repair=True)` clears the broken
copy first, without which the commit refuses to overwrite its own final path and repair fails on every
attempt; and `POST /api/follows/{id}/seen` — the service method existed with no endpoint, so "new"
could never have stopped being new.

Live, 2026-09-19: the state reads Downloaded, the scrubber moved to 3/3 in the work's direction, More
held all four actions, the drawer offered All/Unread/Downloaded/New, 0 axe violations, no console
errors.

## WP-S1 — done and verified

Reader, Downloads, Sources, Notifications and Advanced replaced their placeholders; the advanced knobs
sit behind disclosure per §45; the placeholder string is gone from both languages. Every control writes
a setting the engine already reads — where a knob had no backend (concurrency, retry counts) it is not
shown rather than faked.

Live, 2026-09-19: ten categories × two languages, all with real controls, no placeholders, **0 axe
violations**, advanced hidden then shown, no console errors.

Found on the way, both fixed with regression tests: **I-14** (the route-order guard walked only
`app.routes` and so saw 3 routes of 122 — it passed while proving nothing) and **I-15** (with the guard
fixed, `POST /api/downloads/{batch_id}/reorder` turned out to be unreachable behind `{action}`, so
reordering a queue — §16.1 — had never worked through the API).

## WP-R3 — done and verified

| # | Task | Status |
|---|---|---|
| 1 | EPUB: typeface, size, line spacing, margins, page theme, remembered per work | DONE |
| 2 | PDF: zoom, fit width, fit page, remembered per work | DONE |
| 3 | Both reachable from the reader itself | DONE |

Live, 2026-09-19. EPUB: the rendered document went 18px → 24px, line height 30.6 → 48, sepia, wider
margins, all surviving re-entry, with `sandbox=""` and the frame's own CSP untouched. PDF: fit width
1440 wide, fit page 514×772, zoom 643×965, re-entry unchanged. Zero axe violations, no console errors.

Defect found by the live check: **I-13** — zoom makes the PDF pane scrollable, and it was not reachable
from the keyboard (WCAG 2.1.1), exactly as I-06 had been for the sequential reader.

## WP-R2 — done and verified

| # | Task | Status |
|---|---|---|
| 1 | A bounded window around the reader in Long Strip; spacers keep the strip's height | DONE |
| 2 | Preload the next 7 and previous 4 — the window in Long Strip, a quiet prefetch in Single/Double | DONE |
| 3 | Position read from the pages themselves, and progress written as the reader scrolls | DONE |
| 4 | The numbers come from the §42 registry via `GET/POST /api/reader/settings` | DONE |

Live, 2026-09-19: a 120-page unit mounted **12** pages; the window followed the scroll (first page 13 →
29); the library held page 34; re-entry restored **34 / 120** exactly; no console errors.

Two defects the unit tests missed and the live check caught: **I-11** (an unloaded page is zero pixels
tall, so pages arriving above the viewport pushed the reader backwards — re-entry at 30 landed on 23) and
the spacer estimate living in a ref where it could disagree with what was rendered. Both fixed with
regression tests.

## WP-L1 — done and verified

| # | Task | Status |
|---|---|---|
| 1 | Work Details: Remove from Shelf, showing what the library says will be removed | DONE |
| 2 | The confirmation: what goes, what remains, Keep Files vs Delete Files as separate choices | DONE |
| 3 | Mark Completed and un-complete, offering — never performing — deletion | DONE |
| 4 | My Shelf: the same actions from a row (list layout; the grid keeps the shelf motif) | DONE |

### The nine confirmations, and what carries each

| Confirmation | Evidence |
|---|---|
| Keep Files removes Shelf membership but preserves managed files | `test_remove_from_shelf_offers_file_choices_and_keeps_other_state` |
| Keep Files preserves Follow state | same test — `follows` count unchanged (INV-10) |
| Keep Files preserves reading progress | same test — `read_state` still `partial` |
| Delete Files removes only the intended managed files | `test_delete_files_touches_only_this_works_files` (added in review) |
| Delete Files does not implicitly Unfollow | `test_delete_files_keeps_follow_shelf_and_progress` |
| Delete Files does not erase reading progress | same test — `read_state` still `read`; §22 requires progress to survive |
| Mark Completed persists independently of later new releases | `test_completed_survives_new_releases_and_counts_them` |
| UI wording describes destructive vs non-destructive effects | the WP-L1 UI tests including Arabic, and BV-02 live in both languages |
| Filesystem deletion is path-safe and cannot escape the managed root | `test_the_library_cannot_even_record_a_path_outside_its_root` (schema CHECK), `test_a_symlink_standing_in_for_a_managed_file_is_refused_and_never_counted`, `test_delete_managed_file_only_deletes_regular_files_inside_root` |

Three defects found in review and fixed with regression tests: I-08, I-09, I-10 in `ISSUES.md`.

## WP-R1 — done

| # | Task | Status |
|---|---|---|
| 1 | `useProgress` returns the progress it read, without writing | DONE |
| 2 | `ReaderScreen` opens at the stored page; Long Strip scrolls to it | DONE |
| 3 | `BookReader` opens at the stored chapter; `PdfView` at the stored page | DONE |
| 4 | An outdated locator is clamped, never an error | DONE |
| 5 | Restoring records no progress | DONE |

### Verification state — BV-01 executed 2026-09-19

WP-R1 was marked VERIFIED on 2026-09-18 while one of its own criteria had not been executed. That was
wrong, and the status is withdrawn rather than the criterion softened.

| Criterion (from `execution-plan.md`, unchanged) | Result |
|---|---|
| The named tests pass; the whole frontend suite passes; `tsc` clean | **Executed, passed** — 8 tests; frontend 155; backend 797/4 deselected; `tsc` clean |
| Live: read to page 2, leave, re-enter — the reader opens on page 2, no console errors | **Executed 2026-09-19, passed** — "2 / 3" before leaving and after returning, the rendered element was `/pages/2`, the library held `{page: 2}`, zero console errors |
| M26.15 → `VERIFIED` with its test names recorded | **Done** |

The status was withdrawn on 2026-09-18 rather than kept on a caveat, and is granted now because the
criterion itself ran — not because the environment changed.

### Blocked-verification list

**This list is the verification debt.** Nothing leaves it by being reworded. Every entry is re-run once
E-01 is repaired, and only then may the row it belongs to reach `VERIFIED`. While an entry here belongs
to a C-phase, that phase is not fully `VERIFIED`; while any entry remains, OneShelf is not complete.

**Nothing is currently blocked.** The list is kept because it is the ledger: entries are discharged by
being executed, never by being reworded.

| # | Blocked check, as originally written | Package | Row | Executed | Result |
|---|---|---|---|---|---|
| BV-01 | "Live: read to page 2 of a seeded unit, leave, re-enter — the reader opens on page 2, with no console errors." | WP-R1 | M26.15 | 2026-09-19 | **PASS** — page 2 before and after, `/pages/2` rendered, `{page: 2}` stored, no console errors |
| BV-02 | "live check that a removal dialog reads correctly in both languages" | WP-L1 | M22, M47 | 2026-09-19 | **PASS** — English and Arabic, `dir=rtl` when mirrored, what-is-removed and what-stays both present, Keep and Delete separate, 0 axe violations, no console errors. Screenshots: `shelf-remove-en.png`, `shelf-remove-ar.png` |
| BV-03 | Playwright screenshots and axe-core audits for every package from WP-L1 onward | WP-L1+ | M32.x, M45 | ongoing | Executed per package from WP-L1 (BV-02 covers its surfaces); continues with each package |

Environment defects are in `ISSUES.md` under **Environment defects**: E-01, E-01a and E-01b resolved by
the Podman `--init` rebuild, and E-02 (missing Chromium libraries) fixed on the rebuilt host.

## Log

| Date | Event |
|---|---|
| 2026-09-18 | Plan created from the reconciled matrix; WP-R1 started. |
| 2026-09-18 | WP-R1 built and committed (`d8a21a4`); M26.15 marked VERIFIED. |
| 2026-09-19 | **Correction:** that VERIFIED was not earned — the browser re-entry criterion had never run. M26.15 → `IMPLEMENTED`; the step is recorded `BLOCKED_BY_ENVIRONMENT` (E-01a); the criterion is unchanged. Environment defect E-01 recorded. WP-L1 not started. |
| 2026-09-19 | User decision: downstream gates amended to the four-part rule. WP-R1 tracked as **IMPLEMENTED — VERIFICATION BLOCKED (E-01a)**; BV-01 stays on the blocked-verification list. WP-L1 started under point 4 (no shared persistence, security, migration or data-safety assumption). |
| 2026-09-19 | WP-R4 built, reviewed, verified live and committed (`53a3141`); M26.2, M26.11, M26.12, M26.14, M26.19, M26.21 → `VERIFIED`. WP-E1 started. |
| 2026-09-19 | WP-S1 built, reviewed, verified live and committed (`b7383d7`); M32.14, M45 and M30.10 → `VERIFIED`. Route-order guard repaired (I-14) and queue reordering fixed (I-15) in `9874a85`. WP-R4 started. |
| 2026-09-19 | WP-R3 built, reviewed, verified live and committed (`fded8e0`); M26.22a and M26.22b → `VERIFIED`. WP-S1 started. |
| 2026-09-19 | WP-R2 built, reviewed, verified live and committed (`92b83e2`); M26.6 and M26.18 → `VERIFIED`, M56's bounded-memory clause closed. WP-R3 started. |
| 2026-09-19 | Host rebuilt with `podman-init`. Blocker re-verified rather than assumed: the seven browser tests still failed, diagnosed fresh as **E-02** (missing `libnspr4.so`), fixed by installing the libraries — then all seven passed. BV-01 and BV-02 executed and passed. M26.15, M22, M47 → `VERIFIED`. Three defects found in the WP-L1 review (I-08, I-09, I-10) fixed with regression tests. WP-L1 closed; WP-R2 started. |
