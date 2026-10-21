# Resolution of the 2026-10-19 findings

Every finding of the audit, the fix, the test that holds it, and where the fix is. Nothing is merged into
`main` or deployed yet: each phase is a pull request awaiting the owner's review. `findings.md` and
`coverage-matrix.md` are kept as the audit-time record; this page is the current state.

| Finding | Ledger | P | Resolution | Regression evidence | Branch / PR |
|---|---|---|---|---|---|
| BE-001 | I-91 | P1 | Trust-boundary settings are LAN-only; proxy ranges validated; unsafe stored proxies ignored and reported | `test_auth_api.py::test_i91_*`; private probe now refused | phase 1, #4 |
| BE-002 | I-92 | P1 | One classifier for search, URL entry and open/bind (source value > plugin default > Unknown); previewable repair of existing data | `test_classification*.py`, `test_reclassify.py` | phase 2, #5 |
| BE-003 | I-93 | P1 | The required output follows the source's recipe (image reader → CBZ) | `test_engine.py::test_i93_*`; live product journey 4/4 (twice) | phase 2, #5 |
| BE-004 | I-94 | P2 | One track per listing and language; `und` tracks upgraded in place; twins merged by the repair | `test_classification_api.py::test_i94_*`, `test_reclassify.py` | phase 2, #5 |
| BE-005 | I-95 | P1 | No storage location → 409 at enqueue; every unexpected error ends the job `FAILED`; recovery fails exhausted jobs | `test_engine.py::test_i95_*` | phase 1, #4 |
| BE-006 | I-96 | P1 | Heavy jobs on worker threads with their own connections; engine validation, hashing and commit off the loop; optional background tasks | `test_responsiveness.py` (1,170 ms → 2 ms), `test_engine.py::test_i96_*` (2.05 s → < 250 ms) | phase 3, #7 |
| BE-007 | I-97 | P2 | Resume only real partials, and only on a matching 206; 416 or a changed version start over; Retry starts a file over | `test_http_stream.py::test_i97_*`, `test_engine.py::test_i97_*` | phase 3, #7 |
| BE-008 | I-98 | P2 | Replace-commit updates the existing asset row; no orphan, journal completes | `test_engine.py::test_i98_*`, `test_commit_journal.py` | phase 3, #7 |
| BE-009 | I-99 | P2 | The old copy is set aside, not deleted, until the new one is registered; restored on abort | `test_engine.py::test_i99_*` (incl. crash at every step) | phase 3, #7 |
| BE-010 | I-100 | P2 | Pending Follow baseline until the first trusted catalog | `test_shelf_and_follow.py::test_i100_*` | phase 4 |
| BE-011 | I-101 | P2 | Downloads stream to disk; local files served in byte ranges | `test_http_stream.py::test_i101_*`, `test_work_api.py::test_i101_*` | phase 3, #7 |
| BE-012 | I-102 | P2 | `PATCH /api/works/{id}`, `PATCH /api/reading-units/{id}`; corrections survive refresh and restore | `test_overrides.py`, `test_restore.py::test_i102_*` | phase 2, #5 |
| BE-013 | I-103 | P2 | Format choice on download; formats listing; EPUB > PDF > CBZ default | `test_engine.py::test_i103_*`, `test_library_api.py::test_i103_*` | phase 4 |
| BE-014 | I-104 | P2 | Same-host http redirect followed over https (Hindawi); snapshot refreshed (Gutenberg 2.0.1, MangaDex 1.0.3, 3asq 1.0.2, …); adapter fixes upstream | `test_http_stream.py::test_i104_*`; adapters `check-all` + `test_official_3asq_numbering.py`; live Hindawi | phase 4 + OneShelf-Adapters #5 |
| BE-015 | I-105 | P3 | Remote-auth tables excluded from backups; every table classified | `test_backup.py::test_i105_*` | phase 1, #4 |
| BE-016 | I-106 | P3 | "Storage location unavailable" notification; real free bytes; `canceled` batch state | `test_engine.py::test_i106_*` | phase 1, #4 |
| BE-017 | I-107 | P3 | Upstream status reported; expiring links refreshed; bounded page-list cache; cached pages readable with the source off; `SOURCE_UNAVAILABLE` | `test_reading.py::test_i107_*`, `test_library_api.py::test_i107_*` | phase 4 |
| BE-018 | I-108 | P3 | Preflight with the declared size before fetching | `test_engine.py::test_i108_*` | phase 4 |
| BE-019 | I-109 | P3 | Connections closed on error; no leak after read timeouts | `test_http_stream.py::test_i109_*`; live suite no longer fails on it | phase 3, #7 |

## What is still open, and why

| Item | State |
|---|---|
| Production verification of the fixes | Waits for the owner to merge and deploy; then browser checks per AGENTS.md |
| Existing production data (Berserk `und`/`unknown`, any twin tracks) | Fixed only when the owner runs the reclassification preview and applies it |
| Gutenberg search on existing installations | The bundled 2.0.1 waits for the owner's permission review; approving it removes the (robots.txt-disallowed, always failing) search |
| Frontend for the new contracts | Codex handoffs H-1…H-9 (`handoffs-codex.md`) |
| Follows created before I-100 with an empty baseline | Indistinguishable from a genuinely empty catalog; left as they are |
| arXiv live check | BLOCKED at the source on 2026-10-20 (429, then a timeout); it passed during the audit on 2026-10-19 |
| Docker build and restart (EB-1) | BLOCKED: no container runtime in this environment |
| Real-source Use My Session / browser escalation | No adapter declares them; covered by the Test Source only |
| BE-001 exploit details | Kept in the owner's ignored evidence until the fix is deployed |
