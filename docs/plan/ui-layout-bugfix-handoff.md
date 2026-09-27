# Approved UI layout and bugfix implementation plan

## Handoff

The user approved this plan with “Implement the plan,” then requested implementation in a new window. Implementation has not started. Proceed with the approved changes without asking for plan approval again.

User priorities: use the available width across most pages, preserve the existing visual design, and avoid regressions. Read the repository instructions and authoritative product specification before implementation. Preserve the untracked `image refrence/` directory and all user data.

## Confirmed findings

Browser inspection used the real frontend with intercepted API fixtures, not a live user library.

- At a 2560px viewport, `.screen` uses only 1180px of the 2220px available inside the main area's padding. The cap is in `frontend/src/styles/shell.css`.
- At 390px, My Shelf expands the document to 880px. `ShelfScreen` chunks entries into six-item rows; mobile CSS overrides their flexible columns with fixed-width columns while overflow remains visible. The toolbar also exceeds its container.
- Home overflows at 390px because `.home__pair` has a 440px minimum column width.
- Home's unbound live discovery results stack two cards per column and clip covers. `ResultCard` adds a grid wrapper around `WorkCard`, breaking the shelf's cover/caption grid placement.
- Mobile More changes panel state to `more` in `App.tsx`, but no corresponding panel is rendered.
- `/settings/storage` displays General because `SettingsScreen` initializes local category state without reading the route.
- Search treats `source_status` values as strings, but the backend sends objects such as `{ "state": "done" }`. Working and cached sources therefore receive Retry buttons too.
- Submitting an empty search leaves previous results/status because the effect returns before resetting the update.
- `Intl.DisplayNames` renders language code `und` as “root.” Both the language helper and WorkCard's duplicate formatter need attention.

## Layout implementation

- Remove the shared screen width cap. Retain sidebar dimensions, page padding, colors, typography, and wooden shelves. Keep readable text/form width constraints local to their content.
- Replace My Shelf's fixed six-item chunks with rows calculated from the actual shelf container width using ResizeObserver. Use existing desktop/mobile card widths and gaps; update on resize. Keep final-row column widths aligned with full rows rather than stretching a few books across the page.
- Normalize linked works and live discovery results into identical shelf columns, with covers above the plank and captions below. Keep errors within their card and source-choice drawers outside shelf grid flow. Preserve cover links/buttons, busy states, and keyboard interaction.
- Let Home's paired sections shrink below 440px. Wrap shelf toolbar controls on narrow screens. Correct overflow at its source rather than globally hiding horizontal overflow. Preserve deliberate horizontal scrolling inside Home shelves.

## Functional implementation

- Render mobile More using the existing drawer component. Include Downloads, Sources, Notifications, and Settings. Close on navigation; preserve Escape dismissal and focus return. Reuse destination and translation definitions.
- Derive Settings category from the route. Tab selection updates the URL. Reload and Back/Forward retain the correct category. Missing or invalid categories show General.
- Correct the frontend search status type to match API objects with pending, cached, done, and failed states. Offer Retry only for failed sources. Update test fixtures to the real API contract.
- Reset search results/status on empty submission; close superseded streams and ignore stale retry responses after query changes. Report retry errors without clearing existing results.
- Consolidate language formatting into one helper using the selected UI locale. Translate und as Unknown language in English and Arabic. Preserve fallback to the original code for unsupported/invalid codes.
- No backend API contract changes or database migrations are required.

## Verification

- Add focused regressions for More destinations, dismissal and focus; Settings deep links and history; real search status objects; clearing searches; stale retry responses; failed retries; and translated unknown-language labels.
- Add repeatable real-browser Playwright layout checks at widths 390, 768, 899, 900, 1440, 1920, and 2560 in English and Arabic. Current Vitest tests use jsdom with CSS disabled and cannot validate geometry.
- Assert page content fills the available main width, no document-level horizontal overflow, aligned shelf covers/planks, readable card sizes, reachable controls, and functioning local shelf scrolling.
- Cover empty, single-item, populated, and incomplete shelf rows; mixed saved/live results; long titles; failed covers; and open drawers.
- Review before/after screenshots. Smoke-test main routes and Reader entry/exit. Preserve Reader behavior.
- Run frontend tests and build, non-live backend tests, and backend browser tests. Record exact outcomes and any genuine limitations. Keep layout, navigation, and search changes separately reviewable.

## Baseline and environment

Before implementation on 2026-09-25:

- `cd frontend && npm test && npm run build`: 235 tests passed; TypeScript and production build passed. Existing jsdom canvas and React act warnings were emitted.
- `cd backend && .venv/bin/pytest -m 'not live and not browser'`: 1248 passed, 1 skipped, 15 deselected.
- `cd backend && .venv/bin/pytest -m browser`: 7 passed, 1257 deselected.
- External live-source tests were not run. These baseline results do not establish that all application behavior is bug-free.
- Use `backend/.venv/bin/python` for Playwright; its Chromium installation is available. System Python's Playwright expects a different, missing browser version.
- The investigation's Vite server was stopped. Start a fresh local server for verification.
- Browser interception should match origin-root `/api/` URLs, not a broad `**/api/**` pattern: that broad pattern also intercepts Vite source modules under `/src/api/` and prevents the app from loading.
- Temporary investigation screenshots may remain under `/tmp/oneshelf-audit-*.png`; use them only if present. The visual reference is `image refrence/oneshelf-library-home.png`.
- The known MangaDex adapter-language issue remains a separate adapter task. Do not modify bundled adapter snapshots as part of these UI fixes.
