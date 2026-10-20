# OneShelf UI repair roadmap — proposed, not implemented

This plan uses the confirmed findings and limits in [the 2026-10-19 audit](2026-10-19-ui-ux-audit.md). The approved OneShelf palette, literary type, bookshelf motif, RTL behavior, and Reader visual exception remain the design baseline. UI/UX Pro Max owns product direction; frontend-design-codex owns implementation and browser polish; frontend-a11y owns rendered accessibility. Claude Code owns the API contracts and Reader/download internals identified below. No application repair is authorized by this audit branch.

## Priority order and exact changes

| Order | Finding | Proposed change | Acceptance gate |
| --- | --- | --- | --- |
| 1 | **UI-001, P2 — Settings focus order** | In `SettingsScreen`, replace the selected category's document-level `scrollIntoView()` with scrolling of only the category rail. Keep the active tab visible after route changes, resize, and LTR/RTL changes without moving the page's sequential focus starting point. | Fresh direct loads of `/settings` and `/settings/reader` put first Tab on “Skip to content” at 1440, 768, and 390 px; header/nav and panel then follow in DOM order; arrow keys and selected-tab reveal still work. |
| 2 | **UI-003, P2 — Downloads detail/open journey** | Add an explicit expand/collapse control to each batch row, fetch `/api/downloads/{batch_id}` only when opened, show human-readable unit state/progress/error, and link available completed items to their Work or Reader. Keep batch actions at batch level and never imply a canceled/skipped job was downloaded. | Active, failed, canceled, and completed fixtures show correct per-unit status; a completed downloaded item opens the right Work/Reader; details work with keyboard and touch at all required widths; no extra detail requests for closed rows. |
| 3 | **UI-002, P2 — Search views** | Add Grid/List controls using the existing Shelf control semantics and Search result data. Preserve the selected query, scope chips, source provenance, progressive stream updates, and keyboard/source-choice behavior across view switches. | A populated result set switches between accessible cover grid and readable list at 1440, 768, and 390 px in English/Arabic; source selection opens the same concrete listing in either view; empty/loading/error views remain clear. |
| 4 | **UI-004, P2 — Source last success** | Display a short per-source last successful check or “Unknown/never checked” label alongside status. Use an aggregate list contract from Claude rather than an unbounded N+1 fetch of signal histories. | A known-success timestamp and no-success state render honestly; capability scope is clear; statuses update after source health events without layout clipping or raw diagnostic noise. |
| 5 | **UI-005, P3 — Empty notification actions** | Render bulk actions only for notification states where they can change something; preserve Clear Seen for seen entries even if no unseen count remains. | Empty center shows “Nothing new” without enabled no-op controls; unseen, seen, and attention-filtered fixtures expose only applicable actions. |

## Claude Code coordination

1. **BE-003 for UI-003:** Agree on a bounded read-only batch detail contract supplying Work ID/title, unit ID/label, availability, and user-facing job state/error category. Preserve the current download engine and source identity rules. Codex should not modify download endpoints or tables.
2. **BE-001 for UI-004:** Add an aggregate source-list last-success value or document an equally efficient existing contract. Define whether success is overall or capability-specific and how “never checked” is represented. Codex should not infer a healthy timestamp from registration or plugin version.
3. **BE-002 investigation:** Claude should check why one observed source Work returns Unknown type and language despite a category/language-bearing source, against the specification's classification precedence. Unknown remains a valid state; change only if the backend has concrete evidence it failed to apply. No UI issue is assigned until that is resolved.

## Regression and acceptance tests

- Add a focused browser regression for UI-001 on direct Settings loads in English/Arabic, light/dark, desktop/tablet/mobile. Assert the first Tab, focus order, selected category visibility, arrow navigation, and focus return after a modal.
- Add component and browser cases for UI-002 and UI-003 covering progressive result updates, source-choice identity, empty/error/loading states, batch detail request timing, unavailable content, and completed-item navigation. Use isolated fixtures; never mutate the owner's production library.
- Add source-list and notification fixtures for known/unknown last-success states and empty/seen/unseen/actionable inbox states. Check accessible names, timestamps, and RTL wrapping.
- Refresh `frontend/tests/ux_browser.py`'s two-source Search expectation: it currently expects direct Work navigation, whereas the specified UI first presents a source-choice drawer. Watch the corrected test fail against the stale expectation and pass against the intended source-choice flow.
- Run `npm test`, `npm run build`, the relevant existing browser suites, axe checks, and real Chrome screenshots/interactions at 1440×900, 768×1024, and 390×844. Recheck 320 px reflow, forced colors, dark theme, reduced motion, console errors, failed requests, and Reader controls after shared component changes.

## Release boundary

Implement fixes only after owner approval, on a new repair branch. Keep API/Reader changes with Claude Code. Commit and push with the repository's normal workflow, verify the remote SHA, then wait for the owner's manual deployment before claiming post-fix live verification. Record checkout SHA, running image provenance, browser results, and any remaining blocked journeys separately. Do not merge an audit screenshot or private library data into Git.
