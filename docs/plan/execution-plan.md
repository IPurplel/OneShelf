# OneShelf — Execution Plan for the Remaining Work

Created: 2026-09-18 · Authority: `docs/c0/traceability.md` (reconciled statuses) and the Master via
`docs/OneShelf_Final_Implementation_Meta_Prompt.md` · Live state: `STATUS.md` · Coverage: `TEST-MATRIX.md`
· Defects: `ISSUES.md`

Everything not `VERIFIED` in the reconciled matrix is here. Nothing else is in scope: no optional or
future work, no substitutes for blocked work.

## Working rules

1. One work package is `IN_PROGRESS` at a time; within it, one implementation task at a time wherever
   that is practical.
2. `IMPLEMENTED` is never `VERIFIED`. A row moves to `VERIFIED` only when a named test or a recorded
   gate check carries it.
3. After each verified task, `docs/c0/traceability.md` is updated in place, and `STATUS.md`,
   `TEST-MATRIX.md` and `ISSUES.md` are updated as required.
4. Every reproducible defect gets a regression test before it is fixed.
5. A work package is finished only when its verification criteria pass and its commits exist. The next
   package does not start before that.
6. Blocked work stays blocked. It is never approximated, stubbed or "verified" by a substitute.
7. A package reaches `VERIFIED` only when **every** criterion it declared has been executed. If a
   criterion cannot run here, it is recorded `BLOCKED_BY_ENVIRONMENT` with its blocker, the criterion is
   left as written, and the requirement row stays at `IMPLEMENTED`. A criterion is never rewritten,
   narrowed or dropped to let a row reach `VERIFIED`.

## Definition of Ready for a downstream package (user decision, 2026-09-19)

A package whose prerequisite could not be fully verified here may begin when **all four** hold of that
prerequisite:

1. it is fully implemented and committed; **and**
2. every executable test and review for it passes; **and**
3. every unexecuted verification criterion is explicitly recorded as `BLOCKED_BY_ENVIRONMENT`, with the
   original criterion preserved word for word; **and**
4. the blocked criterion is **not** a hard technical, persistence, security, migration or data-safety
   dependency of the downstream work.

If the blocked criterion could invalidate an assumption the next package relies on, the dependency stays
blocking and the next package does not start. The judgement is recorded per package, not assumed.

This changes when work may *begin*. It changes nothing about what `VERIFIED` means:

- blocked evidence is never converted into `VERIFIED`;
- verification criteria are never weakened;
- outstanding verification debt is never removed — it is tracked in the blocked-verification list in
  `STATUS.md` and re-run once the environment is repaired;
- **a C-phase may not be called fully `VERIFIED` while mandatory verification belonging to that phase
  remains blocked**;
- **final OneShelf completion may not be claimed while any required blocked verification is unresolved.**

## Status vocabulary

The five statuses of the traceability matrix, unchanged: `NOT_STARTED`, `IN_PROGRESS`, `IMPLEMENTED`,
`VERIFIED`, `BLOCKED`.

---

## WP-R1 — Reading progress restoration

**Authoritative rows:** M26.15 (Continue Reading restores exact same-source progress; Long Strip
approximate). Touches M26.23's guarantees without changing them.

**Definition of Ready**
- `GET /api/reader/units/{id}/progress` exists and is verified (`test_progress_can_be_read_back_so_a_reader_knows_the_revision_it_must_carry`). ✔
- Locator shapes are settled: sequential `{page}` (1-based), EPUB `{chapter}` (0-based), PDF `{page}` (1-based). ✔
- No schema change is required. ✔

**Implementation tasks**
1. `useProgress` returns the progress it read on mount, without writing anything.
2. `ReaderScreen` opens at the stored page (Single/Double), and in Long Strip scrolls that page into view.
3. `BookReader` opens at the stored chapter; `PdfView` opens at the stored page.
4. A locator that no longer fits the unit is clamped, never trusted blindly and never an error.
5. Restoring never records progress, so a restore cannot clobber a newer tab.

**Tests required** (frontend, named in `TEST-MATRIX.md`)
- opens a unit at the stored page rather than at the beginning
- scrolls the stored page into view in Long Strip
- clamps a stored page that is past the end of the unit
- starts at the beginning when there is no stored position
- restoring writes no progress
- the Book Reader opens at the stored chapter; the PDF viewer at the stored page

**Verification criteria**
- The named tests pass; the whole frontend suite passes; `tsc` clean.
- Live: read to page 2 of a seeded unit, leave, re-enter — the reader opens on page 2, with no console errors.
- M26.15 → `VERIFIED` with the test names recorded in its Evidence cell.

**Security / persistence implications**
No new endpoint, no schema change, no new stored data. Restoring is read-only, so it cannot regress
progress (M26.23, INV-25). A malformed or outdated locator must not throw or jump to a wrong unit.

**Criterion state (2026-09-19):** all criteria executed and passing, including the browser re-entry
criterion (BV-01), once the host was rebuilt with `podman-init` and Chromium's missing libraries were
installed. M26.15 is `VERIFIED`.

**Expected commit(s)**
`fix(reader): resume a unit where it was left (M26.15)`

---

## WP-L1 — Shelf lifecycle

**Authoritative rows:** M22 (Remove confirms Keep/Delete Files; Completed rules), M47 (destructive wording),
with INV-10 and M23 as the invariants that must keep holding.

**Definition of Ready**
- Backend endpoints exist and are verified: `GET /api/shelf/{id}/removal-summary`, `DELETE /api/shelf/{id}`,
  `DELETE /api/works/{id}/files`, `POST /api/shelf/{id}` (favorite, pinned, completed).
- WP-R1 meets the downstream Definition of Ready above: implemented and committed (`d8a21a4`), all eight
  of its tests and the full suite passing, its one unexecuted criterion recorded
  `BLOCKED_BY_ENVIRONMENT` (E-01a) with the criterion preserved. **Point 4 judgement:** the blocked
  criterion is a browser re-entry check on where a *reader* opens a unit. Shelf lifecycle work touches
  shelf entries, files and follow state; it shares no persistence, security, migration or data-safety
  assumption with it, and no outcome of that check could invalidate anything WP-L1 relies on. The
  dependency is therefore not blocking.

**Implementation tasks**
1. Work Details: Remove from Shelf, opening the removal summary.
2. A confirmation that states what is removed, what remains, and the effect on files, progress, Follow and
   Shelf, with Keep Files and Delete Files as separate explicit choices (§47).
3. Mark Completed (and un-complete), including the optional delete-files offer that keeps metadata.
4. My Shelf: the same actions from a row, without leaving the screen.

**Tests required**
- removing from the shelf asks first, and names what will remain
- Keep Files removes the shelf entry and leaves the files
- Delete Files deletes files and keeps Follow and progress (INV-10 in the UI)
- marking Completed keeps the work on the shelf and offers, never performs, deletion
- cancelling changes nothing

**Verification criteria**
Named tests pass; full suite passes; live check that a removal dialog reads correctly in both languages;
M22 and M47 → `VERIFIED`; INV-10 keeps its existing evidence plus the UI test.

**Security / persistence implications**
These are the product's destructive actions. Nothing may delete without an explicit choice; the summary
must come from the backend rather than be guessed in the UI; a failed delete must leave the library
consistent and say so.

**Criterion state (2026-09-19):** all criteria executed and passing, including the live bilingual dialog
check (BV-02). Review against M22/M47/INV-10/M23 found three defects (I-08, I-09, I-10), each fixed with
a regression test. M22 and M47 are `VERIFIED`; INV-10 keeps its backend evidence and gains the UI tests.

**Expected commit(s)**
`feat(shelf): remove from shelf, keep or delete files, and mark completed (M22, M47)` — landed as
`24605eb`, with the review fixes in `198a3b0`

---

## WP-R2 — Long Strip virtualization and preload

**Authoritative rows:** M26.6 (bounded nearby render window; not fully decoded; restore approximate
scroll), M26.18 (preload ~next 7 / previous 4; Long Strip bounded window; advanced only), M56 (bounded
memory).

**Definition of Ready**
- WP-R1 is fully `VERIFIED`, BV-01 included, so the dependency that was recorded as blocking is
  discharged: the behaviour virtualization could break is now covered by an executed live check as well
  as by tests, and WP-R2 must keep both passing.
- A decision recorded here: the window is measured in pages around the current position, and the preload
  numbers come from the defaults registry rather than literals in the component.

**Implementation tasks**
1. Render only a bounded window of pages around the current position in Long Strip; keep the scroll
   height stable so the scrollbar does not jump.
2. Preload the next ~7 and previous ~4 pages; no further.
3. Restore the approximate relative scroll position on open.
4. Expose the window and preload sizes as advanced settings backed by the defaults registry.

**Tests required**
- a long chapter mounts only the window, not every page
- scrolling moves the window and keeps the scroll position stable
- preload reaches the next 7 and previous 4 and no further
- the approximate position is restored on reopen

**Verification criteria**
Named tests pass; a live check on a long seeded unit shows bounded DOM nodes; M26.6, M26.18 →
`VERIFIED`; M56's bounded-memory clause updated.

**Security / persistence implications**
None beyond memory behaviour; no new persisted state. Preload must respect the traffic governor for
online units so read-ahead cannot starve the Reader (INV-26).

**Criterion state (2026-09-19):** all criteria executed and passing, including the live check on a
120-page unit. Two defects found there (I-11, I-12) fixed with regression tests. M26.6 and M26.18 are
`VERIFIED`.

**Expected commit(s)**
`feat(reader): bound the Long Strip window and preload around it (M26.6, M26.18)` — landed as `92b83e2`

---

## WP-R3 — Book reader comfort

**Authoritative rows:** M26.22a (EPUB font family/size, line height, margins, theme), M26.22b (PDF zoom,
fit width/page).

**Definition of Ready**
- WP-R2 verified. ✔ (2026-09-19, live criterion included)
- The EPUB frame's CSP and empty sandbox stay exactly as they are; typography is injected by OneShelf's
  own stylesheet inside the frame document, never by the book.

**Implementation tasks**
1. EPUB settings: font family, size, line height, margins, theme, persisted per work like the other
   reader settings (§26.17 precedence).
2. PDF: zoom in/out/reset, fit width and fit page, persisted the same way.
3. Both reachable from the reader's own settings surface, not only from Settings.

**Tests required**
- an EPUB setting changes the rendered document and survives reopening
- typography is applied by OneShelf's stylesheet and the frame keeps `sandbox=""` and its CSP
- PDF zoom and fit change the rendered scale and survive reopening

**Verification criteria**
Named tests pass; the isolation tests still pass unchanged; M26.22a, M26.22b → `VERIFIED`.

**Security / persistence implications**
The document must not gain any ability to affect the app: no `allow-same-origin`, no script, no new CSP
directive beyond what already exists. Settings persist per viewer exactly like the current reader settings.

**Criterion state (2026-09-19):** all criteria executed and passing, live in both formats. One defect
found (I-13) fixed with a regression test. M26.22a and M26.22b are `VERIFIED`.

**Expected commit(s)**
`feat(reader): EPUB typography and PDF zoom and fit (M26.22a, M26.22b)` — landed as `fded8e0`

---

## WP-S1 — Settings completion

**Authoritative rows:** M32.14 (all ten categories), M45 (normal vs advanced disclosure for Downloads,
Reader, Sources).

**Definition of Ready**
- WP-R3 verified ✔ (2026-09-19), so the Reader panel has real settings to show.
- Every setting shown is one the backend already honours through the defaults registry; no new behaviour
  is invented in the UI.

**Implementation tasks**
1. Reader, Downloads, Sources, Notifications and Advanced panels replace their placeholders.
2. Normal settings first, advanced behind disclosure, per §45's list.
3. The placeholder string and its Arabic peer are removed.

**Tests required**
- each category shows real settings and no "coming with" placeholder
- an advanced setting is hidden until disclosed
- changing a setting persists and is read back

**Verification criteria**
Named tests pass; axe-core clean on every category in both languages; M32.14, M45 → `VERIFIED`.

**Security / persistence implications**
Settings that change network or storage behaviour (concurrency, reserve, trusted networks) must be
validated by the backend, never trusted from the client.

**Criterion state (2026-09-19):** all criteria executed and passing, including the live axe run over
every category in both languages. Two defects found on the way (I-14, I-15) fixed with regression tests.
M32.14, M45 and M30.10 are `VERIFIED`.

**Expected commit(s)**
`feat(settings): the remaining panels and their advanced disclosure (M32.14, M45)` — landed as
`b7383d7`, with the route and settings-endpoint fixes in `9874a85`

---

## WP-R4 — Reader affordances

**Authoritative rows:** M26.19 (compact download state, Download Entire Work), M26.21 (Retry / Repair from
Source / Skip), M26.14 (Mark as unread), M26.12 (New filter), M26.11 (scrubber), M26.2 (top bar and More).

**Definition of Ready**
- WP-S1 verified ✔ (2026-09-19)
- The backend already has: per-unit and per-work download enqueue, `mark-unread`, page repair through the
  download engine's same-method repair.

**Implementation tasks**
1. Compact download state in the reader's top bar; Download Entire Work on Work Details and in More.
2. Page failure: Retry, Repair from Source, Skip — never a silent delete.
3. Mark as unread beside Mark as read.
4. New filter in the contents drawer.
5. A scrubber in the bottom bar, respecting reading direction.
6. More gains Change Source (WP-R5 wires the switching itself), Repair and Work Details.

**Tests required**
- the reader shows whether the unit is downloaded, and Download Entire Work enqueues the work
- a failed page offers Retry, Repair from Source and Skip, and repair goes through the download engine
- Mark as unread returns the unit to unread
- the New filter shows only units new since the last baseline
- the scrubber moves to a page and respects RTL

**Verification criteria**
Named tests pass; M26.11, M26.12, M26.14, M26.19, M26.21 → `VERIFIED`; M26.2 → `VERIFIED` once More is
complete (its Change Source entry may land with WP-R5).

**Security / persistence implications**
Repair from Source must use the same method and contract as the original download (INV-02) and go through
the normal validated commit, never a side path.

**Criterion state (2026-09-19):** all criteria executed and passing, live included. Two defects found
(I-16, I-17) fixed with regression tests. M26.2, M26.11, M26.12, M26.14, M26.19 and M26.21 are
`VERIFIED`.

**Expected commit(s)**
`feat(reader): download state, page recovery, unread, filters and the scrubber (M26.11–M26.21)` —
landed as `53a3141`

---

## WP-E1 — Realtime event client

**Authoritative rows:** M36 (real-time channel with polling fallback; no cloud), M56's realtime clause.

**Definition of Ready**
- WP-R4 verified ✔ (2026-09-19)
- `GET /api/events` exists and is verified (`tests/unit/test_events.py`).

**Implementation tasks**
1. One shared client that subscribes to `/api/events`, with reconnection and a polling fallback.
2. Downloads, Notifications, Needs Attention, Sources health and reader progress consume it.
3. A dropped-subscriber resync re-reads the affected resource rather than guessing.

**Tests required**
- a download event updates the Downloads screen without a refetch of everything
- a dropped connection falls back to polling and recovers
- a resync re-reads rather than invents state

**Verification criteria**
Named tests pass; live check that a download started in one tab appears in another; M36 → `VERIFIED`.

**Security / persistence implications**
Same-origin only, cookie-carrying, no third-party transport. Events carry identifiers, never content.

**Criterion state (2026-09-19):** all criteria executed and passing, including the two-tab live check.
M36 is `VERIFIED`.

**Expected commit(s)**
`feat(events): one realtime client for the live screens (M36)` — landed as `0bfdd2f`

---

## WP-D1 — Diagnostics

**Authoritative rows:** M43 (operational diagnostics only, 7 d or 100 MB rotating, redacted), DEF-diagnostics.

**Definition of Ready**
- WP-E1 verified ✔ (2026-09-19)
- `diagnostics/redact.py` and its tests exist; the retention default already sits in the registry.

**Implementation tasks**
1. A rotating diagnostics store bounded by both 7 days and 100 MB, whichever comes first.
2. Redaction at write time on every record that reaches it.
3. Settings → Advanced can open and clear it; nothing leaves the machine.

**Tests required**
- rotation drops by age and by size, whichever binds first
- a record with a cookie, token or auth header is written redacted
- no matcher decision reaches it (extends `test_no_matcher_telemetry.py`)

**Verification criteria**
Named tests pass; M43, DEF-diagnostics → `VERIFIED`; INV-29 keeps its guard.

**Security / persistence implications**
The store is local, bounded and redacted. It must never hold passwords, cookies, tokens, auth headers or
sensitive bodies (§43), and is excluded from backups by construction (§33.3).

**Expected commit(s)**
`feat(diagnostics): a bounded, redacted local diagnostics store (M43, DEF-diagnostics)`

---

## WP-R5 — Reader source switching and remaining polish

**Authoritative rows:** M26.16 (source indicator, manual switching, same-language alternatives, layout
warning, Start This Unit / Try Approximate Position), INV-25 (cross-source progress approximate/manual),
M26.3b (Hidden by Default / Minimal), M26.24 (skeletons, one-time centre hint).

**Definition of Ready**
- WP-D1 verified.
- Work Details' track switching is the model for what the reader offers; nothing may map positions across
  sources.

**Implementation tasks**
1. A subtle source indicator in the reader and manual switching to a same-language alternative.
2. On switching: Start This Unit or Try Approximate Position, stated as approximate, never guessed.
3. A layout warning when the alternative's layout differs.
4. Hidden by Default / Minimal control mode.
5. Layout-preserving skeletons and the one-time centre-tap hint.

**Tests required**
- switching source in the reader never claims an exact position
- Start This Unit and Try Approximate Position both exist and say what they do
- the Minimal mode hides the bars until summoned
- the hint appears once and never again

**Verification criteria**
Named tests pass; M26.16, M26.3b, M26.24 → `VERIFIED`; INV-25 → `VERIFIED` with its affordances.

**Security / persistence implications**
None new; the hint flag is a per-viewer convenience and a blocked storage read is not an error.

**Criterion state (2026-09-20):** all criteria executed and passing, live included. Scope was extended by
two rows the matrix had carried as "Missing" since C2 — M26.5's download shortcut and M32.9's shelf sort —
because they were the last genuine gaps outside the blocked set. M26.16, M26.3b, M26.24, INV-25, M26.5 and
M32.9 are `VERIFIED`; M51 closed with INV-25. Two defects found in review (I-19, I-20) fixed with
regression tests.

**Expected commit(s)**
`feat(reader): source switching, minimal controls and loading polish (M26.16, M26.3b, M26.24)` — landed as
`347311e`, with `41fc656` for the two additional rows

---

## WP-G1 — Exclusion regression guards

**Authoritative rows:** the 17 §49 exclusions currently carried by inspection — EX-01, EX-02, EX-04, EX-08,
EX-11, EX-14, EX-15, EX-16, EX-17, EX-18, EX-19, EX-20, EX-21, EX-22, EX-24, EX-26, EX-27 — plus M49.

**Definition of Ready**
- WP-R5 verified.
- The existing guards are the model: `test_no_browser_notifications.py`, `test_no_stealth.py`,
  `test_no_matcher_telemetry.py`, `test_suite_is_isolated.py`.

**Implementation tasks**
1. One guard module per family: account/multi-user, plugin execution model, matching shortcuts,
   social/commercial surfaces, bypass techniques.
2. Each asserts against the shipped code, routes and dependencies, not against prose.

**Tests required**
- a guard per listed exclusion, failing if the excluded thing appears

**Verification criteria**
Guards pass; deliberately introducing a violation makes the right guard fail (checked once, reverted);
the 17 rows and M49 → `VERIFIED`.

**Security / persistence implications**
None; these are tests. They must not weaken by matching only comments.

**Criterion state (2026-09-20):** all criteria executed and passing. The violation check was run for
eight guards; two did not catch theirs and were strengthened (an ownership column added by `ALTER`, and
`dedup_store` past a word boundary). The 17 EX rows and M49 are `VERIFIED`.

**Expected commit(s)**
`test(exclusions): standing guards for the §49 exclusions (M49)` — landed as `a6208e7`

---

## WP-B1 — Environment-blocked verification

**Authoritative rows:** M2, M2.1 (Docker), M41.1 (3asq, Tapas, Safahat/Hindawi, the WEBTOON reader).

**Criterion state (2026-09-21):** M41.1 is `VERIFIED` — all eight sources ship and were verified live, none needing browser escalation. Only the container runtime remains, for M2 and M2.1; M56's Docker clause waits on the same thing and nothing else.

**Status: BLOCKED. Not started, not substituted, not approximated.**

| Blocker | What would unblock it |
|---|---|
| No container runtime on this host (`docker`, `podman` absent) | A host with Docker or Podman: `docker compose up -d --build`, then restart and recreate the container and confirm the library survives on the isolated mounts |
| ~~`3asq.org` does not resolve~~ | **Cleared 2026-09-21.** A dead domain, not an unreachable host: the source is at `3asq.online`. Built, verified live, and shipped — M41.1 is `VERIFIED`. |
| Tapas keeps episode data in script state and disallows `/search` by robots | Justified browser escalation or the underlying XHR, then a package with the capabilities that are genuinely available |
| Safahat/Hindawi book pages render with JavaScript | Browser escalation or an API, then a package |
| The WEBTOON reader builds its images with JavaScript | Browser escalation for the reader capability |

No task in any other package may claim to cover these.

## WP-REL handoff continuation

The 2026-09-20 Codex handoff audit found all Claude release work committed and preserved it.
See `release-handoff.md` for the bounded release plan and fresh evidence. Release-only script,
container configuration and documentation gaps were reproduced and repaired with regressions and an
independent review; application phases remain unchanged. The current explicit user requirement
supersedes the previous publication dependency on the Fedora gate: publish safely, then leave actual
container/clean-clone installation verification open until the host evidence exists.

Remaining mandatory gate: execute `../c9/verification.md` §3a on Fedora, review recorded persistence,
schema, uid, healthcheck, update and uninstall evidence, and only then reconcile M2/M2.1/M56 and the
runtime-dependent REL rows. No container runtime is installed inside ai-box.

## WP-REG — Official Source Registry (REL-12…REL-15), 2026-09-21

T1 lifecycle and trust in `PluginManager` (review, sha binding, ownership, disabled preservation, API
compatibility) → T2 registry hardening (path confinement, bounded sizes, cached failures) → T3 API
(`GET /api/registry`, `POST /api/registry/review-package`, sha-bound install, degraded start) → T4
`plugins.registry_tool` and the generated `registry/` → T5 HTTPS default and key-absence guards → T6 Sources
UI (three sections, review, remove, en/ar) → T7 records, live verification, push. Status in `STATUS.md`;
REL-14 waits for the owner's signing key.
