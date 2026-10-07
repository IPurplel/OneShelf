# UI bugfix verification — 2026-10-05

## What changed

- Work Details follows and unfollows the selected language and track. A source change within an already followed language uses the preferred-source endpoint, preserving its baseline. Track selection lives in `?track=` and survives reload and history navigation. Export uses that track too.
- Following renders separate Work rows for each language, links to each row's track, checks the requested language, and displays the Work title.
- Shelf Manage, Completed file offer, Storage Add, Backup Restore, Export Wizard, and Login Session use the shared native modal surface. Shelf, Settings, and Book Contents tabs now identify their controlled panels.
- Main screens show recoverable initial read errors and action errors. The Reader can retry a failed page, PDF load, or book file request. Download read-ahead uses the same bounded integer control as Reader settings.
- Work metadata, source labels, download states, backup counts, and date formatting use interface language labels.
- Chromium review found that the new PDF failure actions stretched across the whole screen and the sequential failure help text had poor contrast. The failure actions now sit in a centered group, and the help text inherits the Reader's foreground color.

## Verification

| Check | Result |
| --- | --- |
| `npm test --prefix frontend` | 315 passed across 33 files |
| `npm run build --prefix frontend` | TypeScript and Vite production build passed |
| `backend/.venv/bin/pytest backend/tests/integration/test_work_api.py backend/tests/integration/test_shelf_api.py backend/tests/integration/library/test_shelf_and_follow.py backend/tests/integration/export/test_export.py -q` | Passed |
| Chromium layout matrix | 66 cases passed at 390, 768, and 1440 pixels in English and Arabic |
| Chromium UX regressions | 7 scenarios passed |
| Extended Chromium audit | 98 checks passed across the same widths and languages, including Follow API calls, two-language rows, page/PDF failure recovery, and track URL history |
| `git diff --check` | Passed |

Screenshots: `/tmp/oneshelf-current-layout`, `/tmp/oneshelf-current-ux`, and `/tmp/oneshelf-current-extended`. The extended set includes English and Arabic Following with two languages, Shelf Manage, Storage Add, Backup Restore, Export, Login Session, Completed offer, Notifications, sequential page failure, and PDF failure. The browser audit uses controlled API responses; it does not assert live source availability.

## Comparison with earlier records

- [ISSUES.md](ISSUES.md): I-47 through I-50, I-52, and I-53 retain their recorded fixes. **I-51 MangaDex remains open.** The bundled adapter is still version 1.0.0. Its search recipe still reads `originalLanguage`, while its catalogue request filters `translatedLanguage[]` by the selected language. The adapter and snapshot have not been updated here.
- [UI layout verification](ui-layout-bugfix-verification.md): the previous 390/768/1440 responsive checks remain green in the current Chromium run. This pass also covers the newly affected dialogs and error states.
- [2026-09-30 UX verification](2026-09-30-ux-fixes-verification.md): the seven existing modal, search, import, and settings browser scenarios remain green. The six newly migrated dialogs and the Reader error states were checked separately.

No commit or push was made.

## 2026-10-06 targeted audit and fix pass

The six failures reproduced in the 2026-10-06 Chromium audit were fixed without changing the MangaDex adapter. The reviewable UI diff was verified in a clean worktree based on `origin/main`; unrelated text-format work in the shared checkout was not included. Before/after screenshots and the controlled request trace are stored in [2026-10-06 evidence](evidence/2026-10-06/).

| Finding | Cause and correction | Regression evidence |
| --- | --- | --- |
| Work track switch used stale actions | `useResource` exposed the previous query's data until the next effect ran. Responses are now tied to a request generation; changing track hides old details immediately, while refreshing the same query keeps its content. Work Details also rejects a response whose selected track differs from `?track=`. | Work tests delay EN→AR and A→B→A responses, assert no pending Follow/Reader action, and inspect the exact AR Follow body. Controlled Chromium trace records only the AR POST. |
| Mobile Book Reader controls were clipped and covered | The book toolbar did not wrap, and the app bottom navigation painted over the Reader. Book controls now wrap, the Reader hides the app navigation while open, and its bottom bar includes the safe-area inset. | Chromium checks every Reader button and the position indicator for viewport bounds and hit testing at 390, 768, and 1440px in English and Arabic. 390px screenshots show both locales. |
| Late Login Session creation leaked | Cancel saw no `login_id` while creation was pending, and the later response updated a closed component. Each dialog now records closure, deletes any late-created session exactly once, and keeps old and reopened dialogs separate. | Race tests cover late success, late failure, close/reopen, and normal login. Chromium request trace shows DELETE of the exact late `login_id`. |
| Empty EPUB spine rendered `1 of 0` | The parser returned an empty spine and the chapter effect requested index zero without handling rejection. The Reader now shows a localized recoverable failure before chapter rendering, catches chapter errors, and localizes malformed-file failures. | Tests cover empty spine, missing chapter references, malformed EPUB, and a valid one-chapter EPUB. Chromium shows an alert and Back to Work with no page error. |
| Completed save looked failed after summary GET error | One `try/catch` treated the successful POST and optional cleanup-summary GET as one mutation. The completed state now updates after POST, while summary failure has its own warning and GET-only retry. | Tests cover failed POST, successful POST/summary, failed summary, and successful retry. Chromium trace shows one successful POST followed by GET 503 and retry GET 200. |
| Bookmark failure had no feedback | Reader add actions discarded rejected mark promises. A shared EPUB/PDF mark-save handler now catches failures, shows an accessible alert, and retries the exact bookmark or highlight operation without optimistic state. | EPUB and PDF tests cover success, failure, retry, and highlight failure. Chromium shows the alert, no uncaught page error, and two bookmark POST attempts with the second saved. |

| Final check | Result |
| --- | --- |
| `npm test --prefix frontend` | 330 passed across 33 files; existing jsdom canvas and React `act()` messages remain warnings |
| `npm run build --prefix frontend` | TypeScript and Vite production build passed |
| Relevant Work, Shelf, Follow, Export, Login Session, and Reader backend tests | 132 passed |
| Chromium layout matrix | 154 passed at 390, 768, and 1440px in English and Arabic |
| Existing Chromium UX suite | 7 passed |
| Extended Chromium UI audit | 98 passed |
| Real-backend Chromium Reader suite | 6 scenarios passed |
| Targeted six-bug Chromium matrix | Passed at 390, 768, and 1440px in English and Arabic |
| Reader control geometry and hit testing | 6 viewport/locale cases passed; no clipped or covered controls, no horizontal overflow |

The final Chromium matrix ran against the production build served by Vite preview; a bundled font request returned HTTP 200. This keeps the captured English and Arabic screenshots representative of shipped typography.

Logs: `/tmp/oneshelf-ui-isolated-frontend.log`, `/tmp/oneshelf-ui-isolated-build.log`, `/tmp/oneshelf-ui-isolated-backend.log`, `/tmp/oneshelf-ui-isolated-layout.log`, `/tmp/oneshelf-ui-isolated-ux.log`, `/tmp/oneshelf-ui-isolated-extended.log`, `/tmp/oneshelf-ui-isolated-reader.log`, `/tmp/oneshelf-ui-isolated-reader-controls.log`, and `/tmp/oneshelf-ui-isolated-targeted.log`. The [request trace](evidence/2026-10-06/after/request-trace.json) and [targeted screenshots](evidence/2026-10-06/after/) include pending Work track loading, empty EPUB recovery, Completed summary warning, and bookmark error in both locales at 390px. [Reader screenshots](evidence/2026-10-06/reader/) cover all six viewport/locale combinations; [before-fix captures](evidence/2026-10-06/before/) show the original failures. **I-51 MangaDex remains open**; its adapter and snapshot were not changed in this pass.

## PR #1 review follow-up

Three review findings were reproduced and fixed on `fix/ui-six-audit-bugs` without changing the earlier six fixes.

| Finding | Cause and correction | Regression evidence |
| --- | --- | --- |
| Obsolete completion summary could offer file deletion | The summary response had no Work or completion-action identity. Each request now carries its Work ID and action generation; undo, another action, or changing Work invalidates it. The offer and its delete action are guarded by that identity and the current completed state. | Work tests hold a summary through Undo and a Work A→B switch, confirm no old dialog, and retain normal offer and GET-only retry coverage. Controlled Chromium holds the summary through Undo and confirms no modal or DELETE. |
| Failed Login Session cleanup was marked done | The login ID entered `deleted` before DELETE succeeded. Successful deletions and in-flight attempts are tracked separately. A transient failure receives one delayed retry; failed cleanup remains eligible for a later attempt. | Login tests cover a late login, a failed first DELETE followed by success, no duplicate successful cleanup, reopening, and normal cancel. Controlled Chromium records DELETE 503 then 200 for the old ID while the new session remains open. |
| Highlight retry could create two records | Retry sent an indistinguishable second POST. Each mark action now has a UUID operation ID reused on retry. Migration 0016 stores it with a unique index; the API returns the existing mark for the same operation and rejects reuse with different content. New IDs still create distinct highlights with the same text. Bookmark locator deduplication remains. | Backend tests cover normal marks, repeated highlight and bookmark operations, distinct highlight actions, and conflicting ID reuse. Frontend tests prove exact operation ID reuse across EPUB/PDF mark retries. |

| Follow-up check | Result |
| --- | --- |
| `npm test --prefix frontend` | 334 passed across 34 files |
| `npm run build --prefix frontend` | TypeScript and Vite production build passed |
| Relevant backend integration and migration tests | 156 passed |
| Controlled Chromium completion/Login races | 6 viewport/locale cases passed at 390, 768, and 1440px in English and Arabic |
| Original six-bug Chromium matrix | 6 viewport/locale cases passed again |
| Real-backend Chromium Reader suite | 6 scenarios passed again with migration 0016 |
| `git diff --check` | Passed |

The [follow-up screenshots and request trace](evidence/2026-10-06/pr-review/) preserve the delayed completion summary and failed-then-successful Login Session DELETE. Browser responses in this race test are controlled fixtures. **I-51 MangaDex remains open**; the adapter was not touched.

## 2026-10-07 PR #1 LAN HTTP mark-ID follow-up

OneShelf supports plain-HTTP access from trusted LAN devices. `crypto.randomUUID()` is absent outside a secure context, so mark creation could fail before the save handler caught an error. There was no existing frontend UUID helper. A small `newOperationId()` helper now uses `randomUUID()` when present and otherwise makes a valid UUID v4 from `crypto.getRandomValues()`; it never uses `Math.random()`. Both mark entry paths use the helper, and `useMarkSave` generates the ID inside its error handler's `try` block. A retry keeps the original ID; a new action gets a new one. The backend idempotency migration and service from the preceding follow-up are unchanged.

Unit tests explicitly provide `randomUUID()` and then remove it while retaining `getRandomValues()`. They check UUID v4 shape, Bookmark and Highlight POSTs, retry identity, and a different ID for a new highlight action. The Chromium regression removes `randomUUID` from `Crypto.prototype` before the app loads while retaining native `getRandomValues`; it saves and retries both mark types in EN and AR at 390px. Loopback `127.0.0.1` is treated as potentially trustworthy by Chromium, so this setup reproduces the relevant crypto API surface, not an actual private-LAN origin. The [screenshots and request trace](evidence/2026-10-07-lan-mark-ids/) preserve that result. The existing Login Session race tests now explicitly close their reopened session after assertions so cleanup cannot leak into a later test; no Login Session production code changed.

| Check | Result |
| --- | --- |
| `npm test --prefix frontend` | 335 passed across 34 files |
| `npm run build --prefix frontend` | TypeScript and Vite production build passed |
| Backend mark, schema, and migration tests | 29 passed |
| Existing EPUB/PDF mark retry tests | 34 focused tests passed |
| Chromium fallback mark regression | EN and AR at 390px passed |
| Original six-bug Chromium matrix | All 6 viewport/locale cases passed again |
| `git diff --check` | Passed |

**I-51 MangaDex remains open**; the adapter is untouched.

## 2026-10-07 post-PR1 UI audit fixes

The nine findings from the fresh `origin/main` audit were reproduced with controlled Chromium responses and fixed on the isolated `fix/ui-post-pr1-audit` branch. The shared checkout was not used for edits. Evidence from this pass is in [2026-10-07 post-PR1 UI](evidence/2026-10-07-post-pr1-ui/); `frontend/tests/post_pr1_ui_browser.py` regenerates the targeted captures against the app under test.

| Finding | Root cause and fix | Verification |
| --- | --- | --- |
| Sequential Reader controls clipped at 390px | Only the Book Reader toolbar wrapped. The sequential toolbar now wraps its full set of controls, permits long labels to break, and keeps its stage and bottom bar within the mobile safe area. | [Geometry and hit-test matrix](evidence/2026-10-07-post-pr1-ui/reader-toolbar-geometry.json) and [EN](evidence/2026-10-07-post-pr1-ui/sequential-toolbar-en-390.png)/[AR](evidence/2026-10-07-post-pr1-ui/sequential-toolbar-ar-390.png) mobile screenshots. All controls were inside the viewport and hit-testable at 390, 768, and 1440px in both locales, with no document overflow or app-navigation overlap. |
| Backup preflight from an old dialog overwrote the open archive | Preflight had no archive/request identity. Opening and closing now advance a generation; only a response for the current generation and archive may enable Restore. Late success and late failure are ignored. | Unit tests cover A→B, late A error, and reopening A. [Browser trace](evidence/2026-10-07-post-pr1-ui/backup-preflight-trace.json) retains B's 222 works after A's 111 works arrives and records a Restore request for B. |
| Replace Restore submitted twice | The button had no pending lock. A synchronous ref lock prevents repeat pointer or keyboard activation before React renders the disabled busy button; failure unlocks an intentional retry. | Unit tests cover double-click, Enter while pending, failure and retry. [Browser trace](evidence/2026-10-07-post-pr1-ui/restore-submit-trace.json) records one POST while pending and a second only after the first fails and the user retries. |
| Export preview showed an old destination | Preview state was an unlabelled response. It now carries the exact request-body key and generation; changing content, format or destination invalidates it. Late success/failure is ignored, and Export requires a current matching preview. | Unit tests cover A→B, A→B→A, late failure, and export body. [Browser trace](evidence/2026-10-07-post-pr1-ui/export-preview-trace.json) retains B's visible review and exports to B after A arrives late. |
| Storage Add submitted twice | Add remained active until the POST completed. A synchronous lock and disabled busy state allow one request, then release on failure for deliberate retry. | Unit tests cover double-click, Enter and retry. [Browser trace](evidence/2026-10-07-post-pr1-ui/storage-add-trace.json) records one POST, a visible new root, and no stale error. |
| Sequential Repair failure was silent | The Repair POST's rejected promise was left uncaught by `.finally()`. A catch now shows a localized `role=alert` error; another Repair clears it on success, while page Retry remains independent. | Unit and [EN/AR Chromium trace](evidence/2026-10-07-post-pr1-ui/reader-repair-trace.json) cover 503, visible feedback, successful Repair retry, page Retry, and zero page errors. |
| Zero-page sequential unit was blank | A successful empty page array flowed into normal rendering without an empty branch. The Reader now shows a localized accessible explanation and a track-preserving Back to Work link without fetching page images. | EN/AR unit tests and [browser trace](evidence/2026-10-07-post-pr1-ui/reader-empty-trace.json), with [EN](evidence/2026-10-07-post-pr1-ui/empty-pages-en-390.png)/[AR](evidence/2026-10-07-post-pr1-ui/empty-pages-ar-390.png) screenshots. |
| ARIA tabs ignored arrow keys | Work, Shelf and Settings had click-only tab buttons. A shared tablist handler implements arrow/Home/End navigation and roving `tabIndex`, activating the focused tab and panel in DOM order in both locales. | Focused EN/AR tests plus [72-case Chromium keyboard matrix](evidence/2026-10-07-post-pr1-ui/tabs-keyboard-matrix.json) across 390, 768 and 1440px. |
| Export said `file(s)` | English summary and completion strings used literal pseudo-plurals. Separate singular/plural string keys, following the existing shelf pattern, now render 0/1/2 correctly; Arabic wording remains unchanged. | Count-specific unit tests and [browser trace](evidence/2026-10-07-post-pr1-ui/export-plural-trace.json), with a [one-file screenshot](evidence/2026-10-07-post-pr1-ui/export-one-file-en-390.png). |

| Check | Result |
| --- | --- |
| `npm test --prefix frontend` | 355 passed across 35 files; existing jsdom canvas and React `act()` warnings remained non-failures |
| `npm run build --prefix frontend` | TypeScript and Vite production build passed |
| Targeted post-PR1 Chromium script | 89 checks passed with controlled fixtures |
| PR1 six-fix and review-race Chromium suites | EN/AR at 390, 768, and 1440px passed |
| PR1 LAN mark-ID Chromium suite | EN and AR passed |
| Book Reader control Chromium suite | EN/AR at 390, 768, and 1440px passed; nine controls reachable in each case |

No backend code changed, so backend tests were not required for this pass. The existing PR1 completion, Login Session cleanup, EPUB/PDF, and mark retry regressions remain covered by the passing frontend and Chromium suites. Browser source/API data in this section used controlled fixtures. **I-51 MangaDex remains open** and the adapter was not changed.
