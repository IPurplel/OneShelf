# UI layout bugfix verification

Implementation of [the approved handoff](ui-layout-bugfix-handoff.md), verified on 2026-09-25.

## Changes by review area

- **Layout:** removed the shared screen cap; kept the sidebar, padding, colors, fonts, wood, and hover treatment. Settings keeps a local readable form width. My Shelf measures its container using ResizeObserver and the existing CSS card widths/gaps. Every row, including the last, uses the same fixed columns. Home pairs can shrink, toolbar controls wrap, and long list-view actions wrap instead of overflowing.
- **Cards:** saved and live results occupy identical shelf columns, sharing the cover/caption rows. Errors remain inside the affected caption. Source-choice drawers render outside the shelf through a portal. Links, buttons, loading states, keyboard opening, dismissal, and focus return are preserved.
- **Navigation:** mobile More uses the existing drawer and destination/translation definitions. It exposes Downloads, Sources, Settings, and Notifications. Navigation closes the drawer. Settings derives its category from the URL and writes tab changes to browser history; missing/invalid categories show General.
- **Search and language:** source status uses API objects (`pending`, `cached`, `done`, `failed`), with Retry only for failures. Empty submissions clear the search; superseded streams close and stale stream/retry responses are ignored, including a query changed away and back. Failed retries report an error while retaining results. All language labels use one helper and the selected UI locale; `und` is translated in English/Arabic, with original-code fallback for unsupported/invalid codes.

No backend contracts, migrations, adapter snapshots, or user data were changed. Reader edits only pass the selected locale to the shared label helper. The supplied `image refrence/` directory and approved handoff remain intact.

## Verification commands and outcomes

| Command (from repository root unless noted) | Outcome |
| --- | --- |
| `cd frontend && npm test` | 252 passed across 29 files |
| `cd frontend && npm run build` | TypeScript and Vite production build passed |
| `cd backend && .venv/bin/pytest -m 'not live and not browser'` | 1,248 passed, 1 skipped, 15 deselected |
| `cd backend && .venv/bin/pytest -m browser` | 7 passed, 1,257 deselected |
| `backend/.venv/bin/python frontend/tests/layout_browser.py --screenshots /tmp/oneshelf-ui-after` | 154 layout cases passed, 0 failed; resize/history/Reader checks passed in both locales |
| `git diff --check` | Passed |

Existing jsdom canvas and React `act` warnings remain. There were no frontend test failures or unhandled retry rejections in the final run. External live-source tests were not run.

### Repeatable Chromium layout checks

Start the frontend in one terminal:

```sh
cd frontend
npm run dev -- --host 127.0.0.1
```

Then run the browser command above. The script supports `--url`, `--widths`, `--languages`, and `--screenshots`; for a quick mobile check:

```sh
backend/.venv/bin/python frontend/tests/layout_browser.py --widths 390
```

The full matrix uses 390, 768, 899, 900, 1440, 1920, and 2560px in English and Arabic. It exercises Home, My Shelf (grid and list), Search, Following, Downloads, Sources, General Settings, and Storage. The latter operational routes contain representative populated fixtures.

Assertions cover available main width, document overflow, shelf cover/plank/caption alignment, card dimensions, stable incomplete-row widths, toolbar reachability, intentional local shelf scrolling, keyboard-opened source drawers, focus return, errors inside their cards, failed-cover placeholders, and Search card geometry. Shelf counts include 0, 1, 7, and 17; Home and Search mix saved/live results and long English/Arabic titles. The script also resizes a mounted shelf across breakpoints and changes only its container width, checks empty Home, Settings reload and Back/Forward, mobile More, and Reader entry/exit in mobile and desktop shells.

The initial browser regression run reproduced 78 failures, including the 1180px cap, 490px mobile shelf overflow, and clipped/misaligned discovery cards. Expanded list-view checks subsequently reproduced 95px English / 65px Arabic overflow before the list-row fix. The focused final mobile run passed 22 cases in both locales.

### Visual review and limits

Before/after Home and Shelf screenshots at 390, 1440, and 2560px in both locales are under `/tmp/oneshelf-ui-before` and `/tmp/oneshelf-ui-after` in this environment. Compared the existing UI and supplied visual reference with the rendered fixes: sidebar, typography, palette, wooden planks, cover proportions, and restrained hover lift remain. Content uses the larger available width, shelf columns align, and mobile controls wrap.

Browser tests use real Chromium with origin-root `/api/` fixture interception; they do not read or mutate a real library. They verify representative UI states, not every live source or all management workflows. Firefox/WebKit and older browsers were not tested; shelf row alignment uses CSS subgrid. Backend browser tests independently passed against their own isolated fixtures.

Reader smoke checks preserve existing navigation: the current Work-page reading link omits `?work=`, so its Back link returns to My Shelf. A Reader URL carrying work context returns to that Work. This change deliberately preserves both paths.

## Review and delivery

A separate read-only reviewer found no Critical or Important application issues. Its two coverage gaps—Search card geometry and empty-only operational fixtures—were addressed in the final browser harness. No deferred review findings remain. Existing shared Drawer focus trapping and search transport-error behavior were outside this bounded change and were not modified.

Delivery includes the UI implementation, focused regressions, repeatable browser checks, and this verification record. The user authorized committing and pushing these changes to `main`. The supplied `image refrence/` directory remains local and untracked. Findings from the subsequent broader project audit remain separate, unresolved work.
