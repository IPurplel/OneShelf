# Issues — defects found, and the test that holds each one shut

Updated: 2026-09-19 · Plan: `execution-plan.md`

Every reproducible defect is recorded here with the regression test written for it. A defect is closed
only when its test exists and fails without the fix.

| # | Defect | Found by | Regression test | State |
|---|---|---|---|---|
| I-01 | The backups list crashed on every row (`bytes(undefined)`) and could never show "verified": the panel read `size_bytes`/`verified`, which the API does not return | Live run, 2026-09-18 | `test_backup_restore_round_trip` (API now reports `size_bytes` and `present`), `says when an archive's file is no longer where it was` | Closed |
| I-02 | The seven-day backup schedule drifted from its own archives: `create()` stamped `created_at` from the wall clock while `due()` compared against the injected clock | Full suite, 2026-09-18 | `test_schedule_is_seven_days_with_catch_up_after_downtime` (now passes for the right reason) | Closed |
| I-03 | Olive, amber and the wizard step labels failed WCAG AA as small text on paper | axe-core, 2026-09-18 | axe-core run over 21 page states, zero violations | Closed |
| I-04 | Progress stopped being written for any unit already read: the reader began at revision 0, so its first write was stale, and the recovery path called a `GET .../progress` endpoint that did not exist (405) | Live run, 2026-09-18 | `test_progress_can_be_read_back_so_a_reader_knows_the_revision_it_must_carry`, `carries the revision the library already holds, so the first write is not stale` | Closed |
| I-05 | Smart fit did nothing: pages rendered at their own pixel size | Live run, 2026-09-18 | `fits a page to the reading area rather than leaving it at its own pixel size` | Closed |
| I-06 | The scrolling page area could not be reached from the keyboard (WCAG 2.1.1) | axe-core, 2026-09-18 | `lets the keyboard reach the pages themselves, which scroll` | Closed |
| I-07 | A unit opens at page 1 rather than where it was left, although the position is stored and read back | Traceability reconciliation, 2026-09-18 | WP-R1 tests 1–8 in `TEST-MATRIX.md`, led by `opens a unit where it was left rather than at the beginning` | Fixed; **verification incomplete** — the browser re-entry check is blocked by E-01, so M26.15 stays `IMPLEMENTED` |

## Environment defects

These are defects of the machine this work runs on, not of OneShelf. They are recorded separately because
they block verification steps, and a blocked step must never be quietly dropped from a criterion.

| # | Defect | Measured | Effect | State |
|---|---|---|---|---|
| E-01 | **PID 1 does not reap children.** PID 1 on this host is `sleep infinity`, which never calls `wait()`. Every orphaned process is reparented to it and stays a zombie for the life of the container. | 2026-09-19: `pids.current` 1997 of `pids.max` 2048; 1564 zombies; all 1564 have `ppid = 1`; `ps -p 1` → `sleep infinity` | The cgroup PID limit is ~51 slots from exhaustion, so new processes and threads fail | Open — not fixable from inside this session |
| E-01a | **Chromium cannot spawn.** Playwright launches fail during startup. | `pthread_create: Resource temporarily unavailable (11)`, then `Browser.new_page: Target crashed`, and the browser process exits on `SIGKILL` | Every browser-based verification is blocked: Playwright screenshots, axe-core audits, and WP-R1's browser re-entry check | `BLOCKED_BY_ENVIRONMENT` |
| E-01b | **Tooling fails intermittently under the same pressure.** Reported by the user as stop hooks intermittently failing with `EAGAIN` / `SIGABRT`; observed here as Go's runtime aborting (`runtime: failed to create new OS thread (have 13 already; errno=11)` → `fatal error: newosproc`) when vitest's esbuild workers start, and as shell commands returning exit code 144 when a signal lands mid-command | Same cause as E-01 | Worked around by `vitest --no-file-parallelism`; not a fix | Open |

**What would clear E-01:** a host whose PID 1 reaps (a real init, `--init`, or `tini`), or a fresh
container. Nothing inside this session can reap another process's children.

**Rule this enforces:** while E-01a stands, any verification criterion that needs a browser is recorded
as `BLOCKED_BY_ENVIRONMENT` and its requirement row stays at `IMPLEMENTED`. The criterion is not
rewritten, softened or removed to let a row reach `VERIFIED`.
