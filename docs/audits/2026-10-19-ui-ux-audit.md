# OneShelf production UI/UX audit — 2026-10-19

## Executive summary

**Outcome: FAIL for full specification conformance; no P0 or P1 failure confirmed.** The live application rendered all seven primary destinations and ten Settings categories at 1440×900, 768×1024, and 390×844 without document overflow, uncaught JavaScript errors, or failed requests in the captured route pass. Real navigation, search, Work tabs, source details, confirmation dialogs, notifications, and mobile More also worked in the observed read-only flows. The approved forest-green, warm-paper, bookshelf identity remains recognizable across the three sizes.

Five confirmed frontend findings remain: Settings starts keyboard focus after the skip link and header; Search lacks the specified Grid/List switch; Downloads does not expose per-unit details or a path to open finished content; Sources omits the last successful check; and an empty Notifications drawer presents two enabled no-op actions. The first four are P2 and the last is P3. These are audit findings and proposed fixes only; **no application file or production data was changed**.

The owner's stated USD $20,000 value is treated as the quality expectation, not as an appraisal. This report does not certify the whole application: destructive and state-changing live flows were kept off the owner's library, several conditional states required fixtures, and the running production image revision is unverified.

## Baseline and method

- Source baseline: clean audit branch from `origin/main` at `b9932e1cc6c75279a578887f369c27bd31a2291e`. The unmerged `feature/text-reading-units` checkout and its uncommitted changes were excluded.
- Product authority: `docs/OneShelf_Final_Implementation_Meta_Prompt.md`, especially §§26, 29–32, 35–36, 44–47, plus `image refrence/oneshelf-library-home.png`. The reference's avatar and sample books are illustrative; the specification's no-avatar and real-content rules prevail.
- Live environment: `http://192.168.8.32:8420/`, Google Chrome 155.0.8059.84. The configured `@playwright/mcp@0.0.83` server was used through its stdio MCP protocol for real navigation, accessibility snapshots, screenshots, clicks, console messages, and network requests; direct Playwright scripts provided the broader matrix. The MCP tools were not exposed as native tools in this agent session, so `qa-artifacts/mcp_audit.py` called the existing project server without changing its configuration.
- Revision provenance: the live URL returned HTTP 200, but neither deployment checkout SHA nor running image revision was established during this audit. Browser observations therefore describe the live app as seen, not proven behavior of the audit branch. No server update, restart, or deployment was performed.
- Repeatable capture: `python scripts/agent/browser_check.py --path / --path /search --path /shelf --path /following --path /downloads --path /sources --path /settings` produced 14 desktop/mobile route captures. Additional read-only passes captured 51 route/viewport combinations and 31 safe interaction states. Screenshots and JSON are ignored in `qa-artifacts/` and may contain private library content; do not commit or publish them.
- Isolated state tests: the local production build at `http://127.0.0.1:4177/` used mocked APIs for source selection, Reader, loading/error states, and other data-changing flows. Theme and interface language were changed only in disposable Chrome contexts; both persisted through reload there.

**Coverage labels:** PASS means the stated behavior was observed in the named environment. FAIL means a reproduced specification mismatch. BLOCKED means a required live action would change the owner's data or an external state was unavailable. NOT TESTED means no adequate browser or fixture evidence was collected. Unit-test success alone does not upgrade a live journey to PASS.

## Complete frontend inventory and coverage matrix

The route registry defines `/`, `/search`, `/shelf`, `/following`, `/downloads`, `/sources`, `/settings`, `/settings/:section`, `/first-run`, `/works/:workId`, and `/read/:unitId`. The Settings sections are General, Reader, Downloads, Storage, Sources, Notifications, Backup, Remote Access, Advanced, and Developer. Shared conditional surfaces include mobile More, Notifications, Needs Attention, source/result choices, source details and registry review, removal/clear confirmations, import/install/backup/export/remote flows, Reader TOC/settings/source switch/search/marks/error recovery, and first-run steps.

| Frontend area | Implemented components and conditional surfaces inventoried |
| --- | --- |
| Shell/shared | `App`, `Header`, `Sidebar`, `BottomNav`, theme/i18n, `WorkCard`, `CoverPlaceholder`, `Shelf`/`ShelfCase`, `Drawer`, `ModalSurface`, `ConfirmDialog`, `LoadingState`, `FilePicker`; mobile More, notification/attention drawers, focus/escape, loading and fallbacks |
| Discovery/library | `HomeScreen`, `SearchScreen`/`ResultCard` and source-choice drawer, `ShelfScreen`/`RemoveFromShelf`, `FollowingScreen`, `WorkScreen`, `ExportWizard`; empty/populated, filters, tabs, mapping/source choices, removal/completion/export confirmations |
| Operations | `DownloadsScreen`; `SourcesScreen`, `RegistryPanel`, `InstallPanel`, `LoginSession`; batch states/actions, source filters/details, registry review, install/reconnect/rollback/remove paths |
| Settings/onboarding | `SettingsScreen` plus Reader, Download, Source, Notification, Storage, Import, Backup, Remote, Advanced, and Generator panels; `FirstRunScreen`; category overflow, validation, progress, backup/restore, remote/passkey, generator, first-run steps |
| Reader | `ReadRoute`, `ReaderScreen`, `BookReader`, `PdfView`, `ContentsDrawer`, `SettingsPanel`, `BookSettings`, `SourceSwitch`, `HighlightPane`, `DownloadToRead`, marks/progress notices; sequential, EPUB/PDF/text modes, controls, TOC, search/marks, source switch, loading/error/retry/end-of-unit |

| Page or feature and state | Desktop | Tablet | Mobile | Fixture or limitation |
| --- | --- | --- | --- | --- |
| Shell, desktop sidebar, mobile nav/More, header navigation | PASS | PASS | PASS | MCP click and screenshots; keyboard focus assessed separately |
| Home Hero, Continue Reading, latest/recent sections, cover fallback | PASS | PASS | PASS | Trending absent on live data; fixture layout covers populated section |
| Search initial, query submission, progressive results, source filters | PASS | PASS | PASS | Live query was read-only; 6/7 sources had answered after 18 s, with useful results still visible |
| Search Grid/List switch | FAIL | FAIL | FAIL | UI-002; specified control absent |
| Search source choice → Work detail | BLOCKED | BLOCKED | BLOCKED | PASS in isolated two-source fixture; live `/api/listings/open` is a state-changing POST |
| My Shelf tabs, query, sort, Grid/List, populated and empty filter | PASS | PASS | PASS | Read-only local/client interactions; removal execution BLOCKED live |
| Following empty state and route to find Works | PASS | PASS | PASS | Populated updates/attention states PASS in component/fixture checks; live Follow mutation BLOCKED |
| Downloads batch rows, aggregate progress, clear-history confirmation/cancel | PASS | PASS | PASS | Pause/cancel/retry/clear execution BLOCKED live; fixture/component tests exercised controls |
| Downloads per-unit details and open-finished-work journey | FAIL | FAIL | FAIL | UI-003; detail API exists but UI has no drilldown or completed-content link |
| Sources filters, list, status, details drawer, close with Escape | PASS | PASS | PASS | Install, disable, rollback, remove, login-session mutation BLOCKED live; fixture tests cover several states |
| Sources last successful check | FAIL | FAIL | FAIL | UI-004; list does not show it |
| Source Registry, install-from-file, permission review | PASS | PASS | PASS | Rendered live; installation/permission approval BLOCKED live; fixture/component tests cover reviews |
| Settings General and ten category panels | PASS | PASS | PASS | All categories rendered; theme/language persistence PASS in isolated browser profiles |
| Settings backend-backed saves, import, storage migration, backup/restore, remote passkeys, generator | BLOCKED | BLOCKED | BLOCKED | Component/browser fixture coverage varies; no real library or remote-auth mutation |
| Settings initial keyboard focus order | FAIL | FAIL | FAIL | UI-001; direct-load first Tab misses skip link and header |
| Work detail header, Read/Details/Sources tabs and unit index | PASS | PASS | PASS | Existing Shelf Work; Continue/Download/Follow/Export execution BLOCKED live |
| First-run welcome | PASS | PASS | PASS | Storage step PASS on mobile; desktop/tablet storage step and later access-mode/finish/persistence NOT TESTED |
| Notifications empty drawer and Escape | PASS | PASS | PASS | Empty no-op controls FAIL (UI-005); seen/clear execution BLOCKED live |
| Needs Attention populated/actionable drawer | NOT TESTED | NOT TESTED | NOT TESTED | Live count was zero; component test covers behavior but no rendered populated browser state captured |
| Sequential Reader presentation, responsive controls, page loading/progress | BLOCKED | BLOCKED | BLOCKED | PASS in isolated Chrome/browser fixture; live Reader writes progress |
| EPUB, PDF, downloaded Arabic text Reader | BLOCKED | BLOCKED | BLOCKED | PASS in isolated API/browser reader test; live formats unavailable without changing library state |
| Reader source switch, multi-unit next/previous, touch pinch/zoom, multi-tab conflict | NOT TESTED | NOT TESTED | NOT TESTED | Relevant unit tests exist, but full rendered end-to-end scenarios were not captured |
| Loading, empty, error, retry, confirmation and localization states | PASS | PASS | PASS | Selected live empty/confirmation states plus fixture browser checks; exhaustive backend failure variants NOT TESTED |
| Rendered accessibility automated scan | PASS | PASS | PASS | Axe reported no tagged WCAG/best-practice violations on 12 routes × 3 sizes; manual focus-order FAIL |
| Reflow at 320 px, forced colors and reduced motion | PASS | NOT TESTED | PASS | Seven primary routes had 0 px document overflow at 320 px; forced-colors screenshots and reduced-motion fixture runs captured |

### Core journey disposition

1. Home → Search → Results → Work detail: **PASS in isolated fixture; live Work opening BLOCKED** because it posts to `/api/listings/open`.
2. Search → Select source → Open reading content: **PASS through source choice and Work in fixture; Reader opening from a live source NOT TESTED**.
3. My Shelf → Work → Continue Reading: **PASS through Work detail live; Continue BLOCKED live** because it records progress. Isolated Reader entry passed.
4. Reader → next/previous unit → save/resume: **PARTIAL**; isolated save/resume and source-order unit tests pass, but the complete multi-unit browser journey is **NOT TESTED**.
5. Source management → adapter details/status: **PASS** read-only at all three viewports; last-success timestamp **FAIL**.
6. Downloads → progress → open downloaded work: progress **PASS**, open-from-Downloads **FAIL** (UI-003).
7. Following → updates → Notifications: empty Following and Notifications **PASS**; populated live chain **NOT TESTED**.
8. Settings → change option → persistence: interface theme/language **PASS** in disposable browser profiles; backend-backed preferences **BLOCKED live**.
9. Error, empty, unavailable, loading states: selected live and fixture states **PASS**; all external failure variants **NOT TESTED**.
10. Reader mobile direction/scroll/controls: **PASS** in isolated Reader fixture for available modes; live Reader and pinch/multi-unit gestures **NOT TESTED**.

## Confirmed UI issues

### UI-001 — Settings direct load skips initial keyboard controls

- **Priority / area:** P2, accessibility and Settings navigation. **Browser:** Chrome 155 at 1440×900, 768×1024, and 390×844.
- **Reproduce:** Open `/settings` or `/settings/reader` directly in a fresh tab; press Tab once. Compare with `/` in a fresh tab.
- **Expected:** First Tab reaches “Skip to content”, then header/nav in logical order. **Actual:** On Settings, first Tab lands on the category step button at tablet/mobile widths or the Settings panel at desktop width. Home starts at “Skip to content”. This is a WCAG 2.4.3 Focus Order (Level A) concern requiring repair and assistive-technology retest; it is not a whole-site conformance determination.
- **Evidence:** `qa-artifacts/focus-report.json`; `qa-artifacts/focus-settings-390.png`; compare `qa-artifacts/forced-320-settings.png`. Removing `Element.prototype.scrollIntoView` in an isolated diagnostic context restored the first focus to the skip link.
- **Cause:** `SettingsScreen.tsx` calls `scrollIntoView()` on its selected category during layout effect. This changes Chrome's sequential focus starting point without intentionally moving DOM focus. **Fix:** scroll only the category container to reveal the active tab, leaving document focus navigation unchanged.
- **Risk / acceptance / regression:** Category visibility must remain correct in LTR/RTL and after resize. Direct-load and client-navigation tests at desktop/tablet/mobile must find skip link first, then header controls, and preserve tablist arrow-key behavior and focus return.

### UI-002 — Search has no specified Grid/List option

- **Priority / area:** P2, Search results. **Browser:** Chrome 155 at all three required viewports.
- **Reproduce:** Open Search, submit a query with results, inspect result controls above the cards.
- **Expected:** A usable Grid/List option per Master §32.7. **Actual:** Results are a cover grid only; no layout control or list mode appears. My Shelf already has the pattern.
- **Evidence:** `qa-artifacts/interactions/desktop-search-results.png`, `tablet-search-results.png`, `mobile-search-results.png`; Search component contains no layout state or toggle.
- **Cause / fix:** Search renders `.search__results` in one layout. Add an accessible Grid/List switch using the Shelf control convention; keep source choice, progressive updates, and cover hierarchy functional in both modes.
- **Risk / acceptance / regression:** Do not reset query/source filters or lose result identity while changing view. Browser regression should switch views during progressive results in English/Arabic at 390, 768, and 1440 px and open the selected source from each view.

### UI-003 — Downloads hides job details and cannot open completed content

- **Priority / area:** P2, Downloads. **Browser:** Chrome 155 at all three required viewports.
- **Reproduce:** Open Downloads with an active or completed batch. Try to inspect a unit or open a completed Work from the row.
- **Expected:** Expandable per-unit details per Master §32.11 and a route from finished content to its Work/Reader. **Actual:** Only batch state, aggregate counts, progress bar, and batch actions appear; no row expansion or completed-content link exists.
- **Evidence:** `qa-artifacts/browser/20261019-192317/{desktop,mobile}-downloads.png`, `qa-artifacts/deep/tablet-downloads.png`, and `qa-artifacts/fixture-download-completed-390.png`. In the isolated completed-job fixture, the page showed “Completed · 1 done” with zero links or expansion controls. Read-only `GET /api/downloads/{batch_id}` returned a `jobs` array, while `DownloadsScreen.tsx` requests only the batch list.
- **Cause / fix:** Add on-demand batch-detail expansion, accessible job labels/states/progress, and Work/Reader links only when corresponding content is available. Coordinate with Claude on a compact presentation contract: current job payload exposes `reading_unit_id` but no Work title, Work ID, or unit label.
- **Risk / acceptance / regression:** Avoid N+1 detail requests until a row opens; preserve live progress updates, queue actions, empty/error states, and source identity. Test active, failed, canceled, and completed batches, navigation to a downloaded item, and mobile row wrapping.

### UI-004 — Sources omits last successful check

- **Priority / area:** P2, Sources status visibility. **Browser:** Chrome 155 at all three required viewports.
- **Reproduce:** Open Sources and inspect an installed source row and its More drawer.
- **Expected:** Main source list shows status and last successful check per Master §32.12, with an honest Unknown/never state when absent. **Actual:** Status appears, but no last-success time appears in either location.
- **Evidence:** `qa-artifacts/browser/20261019-192317/{desktop,mobile}-sources.png`, `qa-artifacts/interactions/mobile-source-details-settled.png`; `/api/sources` currently has no last-success field. Separate `/api/sources/{id}/health` signals include timestamps.
- **Cause / fix:** Add a succinct last-success label to rows. Prefer a single aggregate API field agreed with Claude rather than fetching every source's signal history on page load; show Unknown when no successful signal exists.
- **Risk / acceptance / regression:** Avoid misleading “healthy” timestamps from unrelated capabilities and excessive requests. Test recently successful, failed, and never-checked sources in English/Arabic and narrow layouts.

### UI-005 — Empty Notifications drawer offers enabled no-op actions

- **Priority / area:** P3 polish, Notifications empty state. **Browser:** Chrome 155 at 390×844; also present in desktop/tablet drawer text.
- **Reproduce:** With zero notifications, open the bell drawer after the slide animation settles.
- **Expected:** “Nothing new” is the sole empty-state message, or bulk actions are disabled. **Actual:** “Mark all as seen” and “Clear seen” remain enabled above “Nothing new”.
- **Evidence:** `qa-artifacts/notifications-empty-settled.png`; both buttons were enabled in the observed empty drawer.
- **Cause / fix:** `NotificationsDrawer` renders bulk controls regardless of list length. Hide or disable actions when no matching entries exist, while keeping them available for relevant seen/unseen states.
- **Risk / acceptance / regression:** Do not hide Clear Seen when seen entries actually exist. Test empty, unseen-only, seen-only, and Needs Attention filtered views.

## Visual, accessibility, Reader, and diagnostic assessment

- **Desktop, 1440×900:** The forest sidebar, warm canvas, Home shelves, Work header, and paper operational screens followed the approved identity; no document overflow appeared in the captured routes. Search's absent view switch and Downloads' missing drilldown are functional gaps, not a reason to redesign those surfaces.
- **Tablet, 768×1024:** Bottom navigation and horizontal Settings categories appeared without document overflow. Source and Settings content remained readable; UI-001 affects the first keyboard stop here.
- **Mobile, 390×844:** Bottom navigation, shelf cards, search results, confirmations, and settled source/notification drawers fit the viewport. Search's fixed grid and the missing Downloads drilldown limit small-screen use. The first captured drawer frames looked translucent because they were taken during the 260 ms entrance animation; a settled capture measured an opaque `rgb(255, 252, 245)` drawer. This was rejected as a false finding.
- **Polish, not a confirmed defect:** In the single-page Reader fixture, the mobile top toolbar wraps to several rows before auto-hide. Its controls were reachable and no content was permanently obscured; consider grouping only if later user testing shows repeated interference. Several Home covers used the intended placeholder while off-screen lazy images had not loaded; the audit did not classify those pending images as broken assets.
- **Accessibility:** Axe's tagged scan of 12 routes at three sizes reported no automated violations; a separate Reader fixture scan at 1440, 768, and 390 px also reported none. Manual keyboard testing found UI-001, which automated scans missed. Light mode was reviewed across primary routes; dark mode and Arabic RTL were reviewed on Settings at all three sizes. Forced colors and 320 px reflow were checked on seven primary routes with no two-dimensional page overflow; reduced motion was exercised in fixture browser runs. `prefers-contrast: more`, text-spacing overrides, screen-reader spoken output, and pinch-gesture alternatives were **not tested**. WCAG conformance is **not** claimed.
- **Reader:** Isolated browser checks passed EPUB, PDF, mixed-format entry, downloaded Arabic text in RTL, bookmark/resume, genuine scroll progress/leave, and mobile/tablet/desktop control reachability. The Reader screenshot at 390 px shows a content-first black canvas with a wrapped but reachable top toolbar. The true production Reader, multi-unit navigation, source switching, pinch zoom, and multi-tab races remain outside live-safe coverage.
- **Console/network:** The repeatable browser check reported no console errors, page exceptions, failed requests, or HTTP ≥400 responses for its 14 captures. The 51-route pass also found no console/network errors or document overflow after load. MCP console and network tools were called for Home, Sources, and Settings. A search query progressed from 5/7 to 6/7 source responses by 18 s without clearing useful local/results content; the remaining source's completion was not established.
- **Fixture browser suites:** The existing layout suite passed 110 cases across widths and English/Arabic; remaining UX passed 54 issue/locale/viewport groups; post-PR1 passed 89 checks; Work visual passed 36 checks. Reader controls, high-visual, targeted bugfix, review-race, visual-main integration, and isolated Reader API scripts also passed. These suites use controlled fixture data and do not prove the corresponding live conditional states.
- **Performance and test risk:** `npm run build` passed, with Vite warning that the main JavaScript chunk is 546.86 kB minified (160.25 kB gzip). This is a measurement, not a confirmed user-facing slowdown. `npm ci` reported five untriaged dependency advisories (one moderate, two high, two critical); this UI audit did not establish production exploitability. `npm test` passed 456 tests across 40 files, while emitting jsdom canvas and React `act(...)` warnings. `frontend/tests/ux_browser.py` failed its `search_history_and_failure` case because it expects a two-source result to navigate directly; the current UI correctly opens the explicit source-choice drawer, verified in an isolated browser. Update that stale regression before using it as a gate; the failure is test expectation drift, not a confirmed application defect.

## Claude-owned dependencies and limitations

- **BE-001 — Source status contract:** `/api/sources` lacks aggregate last-success data. Coordinate an efficient field with capability/source scope and Unknown semantics for UI-004; the existing per-source health-signal route is diagnostic evidence, not an efficient list contract.
- **BE-002 — Work metadata hypothesis:** One observed Work API returned `content_type: unknown` and a track language of `und` while its installed source advertises a concrete category/language. Unknown is valid under the specification, so this is a hypothesis for Claude to investigate against classification precedence, not a confirmed UI defect. The UI accurately displayed the API values.
- **BE-003 — Download presentation contract:** Batch detail includes jobs and reading-unit IDs but not the Work and unit labels/links needed by UI-003. Coordinate a read-only, bounded representation without changing download-engine internals.
- No Claude-owned files were edited. No real library deletes, Follow changes, downloads, source installs/disables, backup restores, remote credentials, or Reader progress writes were performed. The live image revision and several conditional feature states remain unverified.

## Evidence and reproducibility

All paths below are relative to the audit worktree and ignored by Git. The index for route screenshots is `qa-artifacts/browser/20261019-192317/report.json`; the three-viewport route inventory is `qa-artifacts/deep/report.json`; interaction outcomes are `qa-artifacts/interactions/report.json`; MCP calls/snapshots/network/console are `qa-artifacts/mcp/report.json`; axe results are `qa-artifacts/axe/report.json` and `qa-artifacts/reader-axe.json`; focus and persistence diagnostics are `qa-artifacts/focus-report.json` and `qa-artifacts/theme-language.json`. The corresponding ignored Python capture scripts sit beside these files. Use a trusted LAN runtime and the documented project browser setup to reproduce; do not publish private screenshots or session material.

Local repeat commands from this worktree are `python qa-artifacts/live_deep.py`, `python qa-artifacts/live_interactions.py`, `python qa-artifacts/mcp_audit.py`, and `python qa-artifacts/axe_live.py`. The first two are read-only against the live library; the MCP script clicks only navigation and detail drawers; the axe script injects the local checker without saving state. The fixture checks used `npm run preview -- --host 127.0.0.1 --port 4177` plus the browser tests named above and `backend/.venv/bin/python frontend/tests/reader_browser.py` against its isolated temporary backend.
