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
| I-07 | A unit opens at page 1 rather than where it was left, although the position is stored and read back | Traceability reconciliation, 2026-09-18 | WP-R1 tests 1–8 in `TEST-MATRIX.md`, plus BV-01 executed live on 2026-09-19 | Closed — M26.15 `VERIFIED` |
| I-08 | `delete_files()` swallowed a `PathSafetyError`, then deleted the asset row and counted the file as removed: it claimed a deletion that never happened and forgot a file still on disk. Path safety itself held | WP-L1 review, 2026-09-19 | `test_a_symlink_standing_in_for_a_managed_file_is_refused_and_never_counted`, `test_the_library_cannot_even_record_a_path_outside_its_root` | Closed |
| I-09 | The UI reported the removal summary's forecast count instead of the number the library said it deleted | WP-L1 review, 2026-09-19 | `reports the deletions the library actually made, not the ones it predicted`, `reports the same way when Completed offers to delete the files` | Closed |
| I-10 | Arabic used the plural for a count of one — "1 ملفات" | BV-02 live check, 2026-09-19 | `counts one file as one file, in both languages` | Closed |
| I-11 | A mounted page that has not loaded is zero pixels tall, so pages arriving above the viewport pushed the strip down and the reader drifted backwards: re-entry at the stored page 30 landed on page 23 | WP-R2 live check, 2026-09-19 — 163 unit tests had not caught it | `reserves each page's space before it loads, so the strip does not shift under the reader`, plus the live re-entry check | Closed |
| I-12 | The spacer estimate lived in a ref, so a measured height could differ from what had been rendered | WP-R2 review, 2026-09-19 | same test — one estimate now drives both the spacers and the reserved page heights | Closed |

| I-13 | Zooming a PDF makes its page pane scrollable, and the pane could not be reached from the keyboard (WCAG 2.1.1) — the same defect the sequential reader had in I-06 | WP-R3 live axe run, 2026-09-19 | `lets the keyboard reach the page area, which scrolls once it is zoomed` | Closed |

| I-14 | The route-order guard filtered `app.routes` with `hasattr(r, "methods")`, but included routers are nested wrappers in this FastAPI version, so it saw 3 routes of 122 and passed while proving nothing | WP-S1, 2026-09-19 | `test_the_guard_sees_the_whole_api_not_a_handful_of_routes` | Closed |
| I-15 | `POST /api/downloads/{batch_id}/reorder` was registered after `{action}` and returned 404 `UNKNOWN_ACTION`: reordering a queue (§16.1) had never worked through the API. The engine test calls the engine directly, which is why nothing noticed | Found by the repaired guard, 2026-09-19 | `test_reordering_a_queue_reaches_the_engine` | Closed |

| I-16 | `FollowService.mark_releases_seen` had no API endpoint, so release events could never be acknowledged and a "new" unit would have stayed new forever | WP-R4, 2026-09-19 | `test_units_say_which_of_them_are_new` (which now clears through `POST /api/follows/{id}/seen`) | Closed |
| I-17 | Repairing a unit failed on every attempt: the broken asset row stayed, so the commit refused to overwrite its own final path (`final path already exists`) | WP-R4, 2026-09-19 | `test_repair_downloads_a_broken_copy_again_through_the_normal_pipeline` | Closed |

| I-18 | `RedactingFilter` redacted the template and its arguments separately, so a call like `logger.warning("cookie=%s", value)` had its `%s` replaced by `[redacted]` and then raised `TypeError: not all arguments converted` inside `logging` — every logged diagnostic with arguments was lost, exactly the ones §43 exists to keep | WP-D1, 2026-09-19 | `test_redact.py::test_a_message_with_arguments_survives_redaction_and_still_says_what_happened` | Closed |

| I-19 | Work Details' tabs carried `role="tab"` but there was no `tabpanel` anywhere and no `aria-controls`: assistive technology was told about a tab that controlled nothing | WP-R5 review, 2026-09-20 | `gives its tabs something to control, so a screen reader can follow them` | Closed |
| I-20 | One reader stays mounted as the unit changes, and page-level state outlived its unit: a page that failed in one chapter was shown as failed in the next, which opened at the previous chapter's page with its end-of-unit card already up | WP-R5 review, 2026-09-20 | `starts the next unit clean, rather than carrying the last one's failures into it` | Closed |

## Environment defects

These are defects of the machine this work runs on, not of OneShelf. They are recorded separately because
they block verification steps, and a blocked step must never be quietly dropped from a criterion.

| # | Defect | Measured | Effect | State |
|---|---|---|---|---|
| E-01 | **PID 1 did not reap children.** PID 1 was `sleep infinity`, which never calls `wait()`, so every orphan became a permanent zombie. | 2026-09-19 (old container): 1997 of 2048 PIDs; 1564 zombies, all with `ppid = 1` | The cgroup PID limit ran out; new processes and threads failed | **Resolved 2026-09-19** — ai-box recreated with Podman `--init` / `podman-init`. Re-measured: `PID 1 = /run/podman-init -- sleep infinity`, 11 processes, **0 zombies**, 60/2048 PIDs |
| E-01a | **Chromium could not spawn** under E-01. | `pthread_create: Resource temporarily unavailable (11)` → `Target crashed` → `SIGKILL` | Blocked every browser verification | **Resolved 2026-09-19** — but see E-02: on the rebuilt host the launch failed again for a *different* reason, which was fixed rather than assumed to be this one |
| E-01b | **Tooling failed intermittently** under the same pressure: stop hooks with `EAGAIN`/`SIGABRT` (user-reported), Go aborting with `newosproc` when vitest started workers, shells returning 144 | Same cause as E-01 | Worked around with `vitest --no-file-parallelism` | **Resolved with E-01** — the full suite now runs with default parallelism |
| E-02 | **Chromium's system libraries were missing** from the recreated container. Diagnosed fresh rather than attributed to E-01: the launch failed in 0.8 s on a host with 0 zombies | `chrome-headless-shell: error while loading shared libraries: libnspr4.so: cannot open shared object file` | The seven `-m browser` backend tests and every Playwright check failed | **Resolved 2026-09-19** — `sudo dnf install nss nspr atk at-spi2-atk cups-libs libdrm libxkbcommon libX{composite,damage,fixes,randr} mesa-libgbm alsa-lib pango cairo libxshmfence`; the seven tests then passed in 13 s |

**Blocker re-verification, 2026-09-20.** Checked rather than carried forward:

| Blocker | Checked | Result |
|---|---|---|
| EB-1 — no container runtime | `which docker podman buildah nerdctl`; `/var/run/docker.sock`, `/run/podman/podman.sock` | **Still blocking.** Nothing is installed and no socket is mounted, so M2 and M2.1 cannot be verified here. The host's `podman-init` fix was to the container this session runs *in*; it did not put a runtime inside it |
| EB-3 — outbound access | `https://example.com` → 200, `https://gutendex.com/books` → 301, DNS resolves | **Resolved.** The live source suite can reach the internet from here |
| 3asq / Al-Aasheq | `getent hosts 3asq.org` | **Still blocking, same cause.** The name does not resolve from this environment |
| Tapas, Safahat/Hindawi, WEBTOON reader | `getent hosts tapas.io`, `www.hindawi.org`, `www.webtoons.com` | **Not environment-blocked.** All three resolve. Their blockers are technical — episode data in script state, JavaScript-rendered book pages, a viewer that builds its images in JavaScript — and the answer to each is justified browser escalation or the underlying XHR, which is work in scope, not a blocked verification. Recorded as outstanding work rather than as a blocker |

**History kept deliberately.** E-01 and E-01a are recorded as resolved, not deleted: they explain why
BV-01 and BV-02 sat unexecuted, and why M26.15 was withdrawn from `VERIFIED` on 2026-09-19 rather than
kept on a caveat. Neither is a current blocker.

**The rule they produced still stands:** a verification criterion that cannot be executed is recorded
`BLOCKED_BY_ENVIRONMENT` with its wording preserved, and its row stays at `IMPLEMENTED`. What changed is
that nothing is currently blocked that way.
