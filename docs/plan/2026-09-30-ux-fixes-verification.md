# UI/UX fixes — verification, 2026-09-30

## Changes

- Import clears the previous review when another file is selected, ignores stale upload responses, and blocks duplicate import submissions.
- Search stores submitted queries in the URL, restores them through browser history and reloads, and supports explicit resubmission of the same query.
- Failed search streams show a retry action. Partial results remain visible after failure and while retrying.
- Reader numeric settings validate empty values, bounds, and integer requirements before saving. Rejected drafts remain visible with an associated error and retry action; overlapping writes are blocked. Successful saves use the API's authoritative response.
- Failed download-settings loads show an error and a working retry action.
- Drawers, confirmation dialogs, and shelf removal share a native modal surface. Keyboard focus remains inside, the background is inert, Escape cancels, and focus returns to the opener. Parent rerenders no longer reset reader-settings focus. Close labels are localized.

No backend API, database migration, or dependency changes.

## Automated checks

Run from the repository root, with Vite running for browser checks:

```sh
npm test --prefix frontend
npm run build --prefix frontend
npm run dev --prefix frontend -- --host 127.0.0.1 --port 5174
backend/.venv/bin/python frontend/tests/ux_browser.py --url http://127.0.0.1:5174
backend/.venv/bin/python frontend/tests/layout_browser.py --url http://127.0.0.1:5174 --widths 390 768 1440 --screenshots /tmp/oneshelf-ux-layout-fixed
backend/.venv/bin/python frontend/tests/reader_browser.py
```

| Check | Result |
| --- | --- |
| Frontend suite | 282 tests passed across 32 files |
| TypeScript and production build | Passed |
| Focus, import, search, and settings browser regressions | All 7 scenarios passed |
| Layout/browser matrix | 66 cases passed; English and Arabic at 390, 768, and 1440 pixels, plus resize and reader checks |
| Isolated real-backend reader checks | EPUB, PDF, mixed formats, legacy links, recoverable errors, and progress/engagement/leave passed |
| Git whitespace check | Passed |

Existing React `act` and jsdom canvas warnings still appear in the frontend suite. They were present in the pre-change baseline; all tests pass.

## Regression evidence

Before implementation, new tests failed for stale import reviews, reversed upload response order, duplicate imports, bookmarked/back-navigation searches, and failed streams. Settings tests failed for invalid values, rejected writes, overlapping saves, and failed initial loads. Chromium reproduced focus escaping the mobile drawer, missing initial focus on shelf removal, and focus resetting after a reader setting changed.

A review also found that Retry briefly removed partial search results. An additional assertion reproduced this, and now passes.

The existing layout browser test had an outdated reader fixture. It now serves the unit-context endpoint and checks the current work/track return links.

## Evidence and limits

Screenshots were captured and inspected in `/tmp/oneshelf-ux-verification` and `/tmp/oneshelf-ux-layout-fixed`. They are local run artifacts, not required repository files.

UI failure cases use controlled API responses in real Chromium. The reader integration uses an isolated real backend and temporary library. Live source availability, a full deployment, other browser engines, and screen-reader operation were not tested by this change.
