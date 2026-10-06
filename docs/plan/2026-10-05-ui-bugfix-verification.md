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
