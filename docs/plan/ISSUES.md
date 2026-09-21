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

| I-21 | WEBTOON's catalog could not paginate: `episodeList?titleNo=..&page=N` 301s to the canonical list URL and drops the page, so every page returned the same nine episodes and a six-hundred-episode series stopped with `repeated_page` | WEBTOON live check, 2026-09-20 | `test_webtoon_work_catalog_and_the_episode_images` (asserts >300 units and `complete`), plus the packaged catalog case against the API fixture | Closed |
| I-22 | `extract_number` took the first number in "[Season 3] Ep. 227", so episode 227 became chapter 3 — six hundred episodes renumbered into three, against INV-24 | WEBTOON live check, 2026-09-20 | packaged catalog case with a season-numbered episode in its fixture, and the live check's `max(number) > 200` | Closed |
| I-23 | A recipe's own inputs never reached its item templates. Package validation allowed them, the runtime did not pass them, so a one-unit catalog's `unit_key` rendered as nothing and every item was dropped — reported as a catalog validation failure rather than as the wiring gap it was | Hindawi, 2026-09-20 | `test_an_item_template_can_use_the_recipe_s_own_inputs` | Closed |
| I-24 | A recipe could be validated as "follows a URL the catalog produced", but the renderer percent-encoded the whole URL into a path segment, so such a request could never have reached anything | WEBTOON reader, 2026-09-20 | `test_an_absolute_url_can_be_requested_as_it_was_given`, and a bare `{url}` is now refused at validation (`test_following_a_url_without_saying_it_is_absolute_is_refused_rather_than_silently_encoded`) | Closed |
| I-25 | Three shipped adapters declared a `catalog` capability their packaged tests never exercised | `test_official_packages.py`, 2026-09-20 | each now ships a catalog case against the fixture it already had | Closed |

| I-26 | Two ways 3asq's listings silently dropped real series: a series with no cover image has an empty thumbnail block, so reading its link from there lost it (four series in five pages of the latest feed); and a title block can hold the translator's own external link before the series link, so a page's first entry could be read as pointing at x.com | 3asq live verification, 2026-09-21 | the packaged `latest` case, whose fixture keeps a real coverless entry and a translator link, with both anchors pinned to a series URL | Closed |

| I-27 | The container image built an API with no interface: the Dockerfile copied only `backend/`, so every container deployment would have served an API and no UI — while `vite.config.ts` had said since C2 that the SPA is served from the same origin in production | Found while writing `install.sh`, 2026-09-21 | `tests/integration/test_web_ui.py` (9 cases, including that the API still 404s as the API and that a remote client is refused at the interface too) | Closed |

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
| ~~3asq / Al-Aasheq~~ | `getent hosts 3asq.org` | **Resolved 2026-09-21 — not an environment blocker at all.** The reading was right and the conclusion was wrong: `3asq.org` is a dead domain, and the site moved to `3asq.online`, which resolves and answers everything. The adapter now ships and is verified live. Kept here because the lesson is worth keeping: *a host that does not resolve may be a moved source, not an unreachable one* — check whether the name is still the right name before recording it as blocked. |
| Tapas, Safahat/Hindawi, WEBTOON reader | `getent hosts tapas.io`, `www.hindawi.org`, `www.webtoons.com` | **Not environment-blocked.** All three resolve. Their blockers are technical — episode data in script state, JavaScript-rendered book pages, a viewer that builds its images in JavaScript — and the answer to each is justified browser escalation or the underlying XHR, which is work in scope, not a blocked verification. Recorded as outstanding work rather than as a blocker |

| E-03 | **gutendex.com times out intermittently.** Diagnosed rather than assumed, twice: the adapter returns the right titles and the right EPUB URL on a retry, and the failures are `SocketTimeoutError` on reading the socket. Re-checked 2026-09-21 after the plugin-runtime changes, in case they were the cause: they are not — search returns 8 items complete and downloads 1 entry complete, four consecutive times | Observed 2026-09-20 and 2026-09-21, interleaved with successful runs | The Gutenberg live test failed intermittently | **External, not a product defect.** OneShelf reports it honestly — incomplete, with a `transport` issue, rather than a short list. The live suite now skips on exactly that signature and nothing else (`reached()`), so a third-party outage stops reporting itself as a OneShelf defect while a real extraction failure still fails loudly. The test itself was not weakened |

**History kept deliberately.** E-01 and E-01a are recorded as resolved, not deleted: they explain why
BV-01 and BV-02 sat unexecuted, and why M26.15 was withdrawn from `VERIFIED` on 2026-09-19 rather than
kept on a caveat. Neither is a current blocker.

**The rule they produced still stands:** a verification criterion that cannot be executed is recorded
`BLOCKED_BY_ENVIRONMENT` with its wording preserved, and its row stays at `IMPLEMENTED`. What changed is
that nothing is currently blocked that way.

## Release handoff findings (2026-09-20 workspace date)

| ID | Finding | Resolution and evidence | State |
|---|---|---|---|
| I-28 | Scripts could report success without a probe tool or with unhealthy JSON; process substitution hid mkdir failure | Nonzero failures, explicit health JSON check, synchronous directory preparation; deployment regressions | Fixed in release scripts; runtime gate pending |
| I-29 | Script dotenv parsing, exported overrides, singular plugin/backup keys and Compose env-file resolution disagreed | One resolved/exported configuration, explicit root env-file, quoted literal values; deployment regressions | Fixed; runtime gate pending |
| I-30 | Purge/custom paths could delete or recursively change unrelated data; default uninstall created directories | Canonical non-overlapping paths, no symlink parents, explicit managed custom directories, default-only confirmed purge, error propagation | Fixed; runtime gate pending |
| I-31 | Fedora mounts lacked SELinux labels; plugin/backup mounts were unused; bridge forwarding concealed peer IP | Shared labels, actual nested store targets, host networking and configured-listener healthcheck; ADR 0003 | Implemented; Fedora host evidence required |
| I-32 | `deploy/.dockerignore` did not protect the repository-root build context | Root `.dockerignore` excludes env, databases, runtime directories, Git and dev dependencies | Fixed by inspection; image build gate pending |
| I-33 | Updater accepted unsafe Git states and recommended unsupported schema downgrade | Real Git-state regressions, fast-forward-only origin/main, script re-entry; migration-aware recovery guidance | Fixed in script tests |
| I-34 | New nested mounts could conceal legacy data, including when an old updater pulls the new release | Script preflight plus independent image startup guard on read-only legacy data view; original bytes retained | Fixed in regressions; runtime gate pending |
| I-35 | `PluginManager._record` re-enabled a disabled plugin whenever any version activated (upload, Registry, approve) | Disabled state preserved inside `_record` for every path; regression tests; caught by mutation | Fixed |
| I-36 | A Registry package location could point at another repository on the same host (raw.githubusercontent.com serves all of GitHub) | `resolve_package_url` confines packages beneath the index's own directory; plain relative `.osp` segments only | Fixed |
| I-37 | A registry URL refused by Core's policy stopped the application from starting | `UnavailableRegistry`: the Registry reports it, the library starts; `test_when_the_registry_is_unreachable_everything_else_still_works` | Fixed |
| I-38 | A `/api/registry/review` route tripped the §49 social-surface guard | Route is `/api/registry/review-package`; the guard was not weakened | Fixed |
| I-39 | An update waiting for review could not be approved from the Registry (`already_installed`) | Installing it again from its review approves it when the stored bytes match the reviewed sha256 | Fixed |
| I-40 | Live check: a removed source was still listed under Installed sources with an untranslated state | Filtered from the installed list; the Registry offers it as Not installed; regression test | Fixed |

No verified application UI, source recipe, database migration or core behavior was rewritten.
