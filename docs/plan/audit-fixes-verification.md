# Audit fixes verification

Checks run on 2026-09-29 against the audit fixes.

| Check | Result |
| --- | --- |
| `cd backend && .venv/bin/pytest --tb=short` | 1,287 passed, 1 skipped, 8 deselected |
| `cd backend && .venv/bin/pytest tests/integration/export/test_export.py --tb=short` | 25 passed, including the final missing-unit ZIP regression added during the full run |
| `cd frontend && npm test` | 267 passed across 32 files |
| `cd frontend && npm run build` | Passed, including TypeScript checking |
| `backend/.venv/bin/python frontend/tests/reader_browser.py` | All six scenarios passed against the production build and an isolated library |
| `git diff --check` | Passed |

## Fixes verified

- Export validates the selected work, source and language; uses the configured clock for job history;
  stages and verifies output before publication; refuses destination symlinks; and records renamed files.
- ZIP export preserves existing files under `keep_both`, separates works with identical titles,
  handles invalid existing archives as conflicts, and waits for all selected content before publication.
  Content downloaded after job creation is included when the job runs again.
- Missing content is reported as an issue instead of an empty successful export. Automatic downloading
  within export is not implemented; content must finish downloading before retrying the export.
- Reader links preserve the work and track. Legacy unit-only links and explicit EPUB/PDF selection work.
- Reader progress saves are serialized per unit and recover after a failed initial revision request.
  Stale queued positions are discarded when another tab has a newer revision.
- Genuine sequential-reader interaction sends engagement events. Reader links back to Work Details
  flush progress and send the leave event after outstanding engagement requests.
- Migration retains its temporary staging links as ownership evidence for recovery after interruption.
  These links do not share content between library assets.

The browser scenarios cover EPUB, PDF and mixed-format Work entry; legacy unit-only entry;
a recoverable missing-work error; and scrolling that saves progress and sends engagement/leave events.

An independent code review identified export retry and progress-recovery edge cases. Those findings
were reproduced, fixed and covered by regression tests; the follow-up review found no remaining blockers
within its scope.

## Limits

Live source availability and deployment on a container host were not verified by this run.
The bundled MangaDex adapter remains at 1.0.0; its translation-language update is still open as I-51,
although Core API 1.1 supports the required available-language field.
