# Findings — backend, adapters and Reader (2026-10-19)

Audited revision: `origin/main` `b9932e1` (audit branch `audit/backend-reader-20261019`).
Every finding is backed by direct evidence. BE-001…BE-010 and BE-014…BE-016 were reproduced by
probe, live run, or production observation. BE-011, BE-013 and BE-017 were partly reproduced (Range,
format, and disabled-source behaviour) and partly found by inspection. BE-012 and BE-018 were found by
code inspection, confirmed with `grep`. BE-019 was observed in the live suite, and its root cause is a
hypothesis. Probe scripts are in the git-ignored `qa-artifacts/be-audit-20261019/probes/`.
To run one, copy it into the named test directory, where it uses that directory's existing fixtures. Live
outputs are in `qa-artifacts/be-audit-20261019/live/`. Root causes are **confirmed** when the probe
isolates the mechanism. A cause is labelled **hypothesis** only when it is inferred and not isolated.

Priorities: **P0** data loss or a security breach that is exploitable now. **P1** a core flow broken in
production, or a security boundary weakened. **P2** a contract violation with real user impact.
**P3** a minor or hardening issue.

None of these overlap the closed ledger items I-01…I-90 in `docs/plan/ISSUES.md`.

---

## BE-001 · P1 · A remote session can rewrite the LAN trust boundary and keep access after LAN Recovery

- **Requirement:** Master §28.2 (trusted proxies only), §28.5 (LAN Recovery revokes remote access), §28.7,
  §48, INV-30.
- **Summary:** the API routes that define the inbound trust configuration (`POST /api/auth/networks`, and
  the trusted-proxy part of `POST /api/first-run/access-mode`) accept calls from an authenticated remote
  session as well as from the LAN. The trusted-proxy list also accepts any range, including public and
  catch-all prefixes. A remote session can therefore change who is treated as LAN, in a way that outlives
  the session and LAN Recovery.
- **Reproduction:** reproduced with an audit probe against the project's auth API fixtures. The exact steps
  are deliberately **kept out of this public repository until the fix ships**. They are stored in the
  owner's local, git-ignored evidence (`qa-artifacts/be-audit-20261019/private/BE-001-full.md`, probe
  `probes/test_audit_probe_auth.py`).
- **Expected:** only a genuine LAN or loopback peer can change network trust or the canonical hostname.
  Trusted proxies are restricted to private, loopback, or link-local ranges with a sane minimum prefix.
- **Root cause (confirmed):** no access-kind check on the boundary-defining routes (`api/auth.py:101`,
  `api/firstrun.py:107-116`). Proxy ranges are not validated (`auth/policy.py:76`, `:94`).
- **Impact:** converts a stolen or short-lived remote cookie into durable LAN-level access. Production has
  no passkey enrolled, so there is no exposure there today. It matters before remote access is enabled, and
  for every other self-hosted installation of this public project.
- **Fix:** add a `require_genuine_lan(request)` guard (`access.kind in {"loopback", "lan"}`) to the routes
  that define the boundary: `POST /api/auth/networks`, `POST /api/auth/hostname`, and First-Run access-mode
  writes. Make `AccessPolicy.update`/`set_trusted_proxies` refuse proxy ranges that are not private,
  loopback, or link-local, and refuse any prefix shorter than /8 (IPv4) or /32 (IPv6). Recommended but not
  strictly required by the spec: require passkey re-authentication (§28.6, "may require") for remote passkey
  deletion and recovery-code regeneration.
- **Tests and acceptance:** remote-session calls to each guarded route return 403 `LAN_REQUIRED`. Catch-all
  and public proxy ranges are refused (422). The private probe scenario ends with the attacker refused. The
  existing auth API suite stays green.

## BE-002 · P1 · Plugin classification defaults are ignored, so Arabic and other single-language sources are stored as `und`/`unknown`

- **Requirement:** §9.2 classification precedence (plugin default is tier 3, *"an Arabic-only manga source
  may declare default language = Arabic"*), §3.1, §2.3, §24.2 layout families, §41.3 (Arabic metadata).
- **Reproduction (live, isolated instance):** search `ون بيس` → the 3asq hit has `language: "und"` and
  `content_type: null`. `POST /api/listings/open` then creates a Work with `content_type='unknown'` and
  `content_type_source='unknown'` and a Source Track with `language='und'`. The 3asq manifest declares
  `defaults: {language: ar, content_type: manga}`. Hindawi (`ar`/`book`) and arXiv (`en`) behave the same.
  Evidence: `live/live-main.json` and a direct DB query.
- **Production evidence:** `GET http://192.168.8.32:8420/api/works/6qn3mwijnbis` (Berserk via 3asq) returns
  `content_type: unknown`, track `language: und`. The live Work page reads **"unknown · Unknown
  language"** (`browser-live/desktop-6qn3mwijnbis.png`).
- **Root cause (confirmed):** `manifest.defaults` is read only by `search/url_resolve.py:89` (language) and
  `api/covers.py`. The search and bind paths never consult it: `search/grouping.py:189`
  (`listing.language or "und"`) and `api/discovery.py:184` (`body.content_type or "unknown"`).
  `manifest.defaults.content_type` is not read anywhere.
- **Impact:** source and language identity is wrong for every result whose recipe does not extract those
  fields. Follow binds `language=und` (seen live). Storage paths use `und/` and the `Other/` family instead of
  `Books/` or `Sequential Art/`. Text units lose `lang`/direction. RTL defaults cannot apply. This is the
  direct cause of BE-003 and BE-004.
- **Fix:** add one classification resolver, `classify(listing, package) -> (language, content_type,
  source)`, applying user override > explicit source value > `manifest.defaults` > Unknown. Call it from
  `SearchService` result building, `persist_listing`, `_bind`/`open_listing`, the URL resolver and import.
  Record `content_type_source='plugin_default'` and keep Unknown when no tier has a value. Add a migration
  (data-only and reversible) that reclassifies existing `und`/`unknown` rows created from a plugin with
  declared defaults. It must merge with any same-listing track that already carries the real language
  (BE-004) and never overwrite user-sourced values.
- **Tests and acceptance:** a packaged-fixture search for a source with defaults yields that language/type.
  An explicit source value beats the default, and a user override beats both. The migration fixes an
  `und` 3asq track without touching a user-set value. A 3asq Work page shows "manga · Arabic".

## BE-003 · P1 · Sequential (image) downloads fail for any Work whose content type is unknown

- **Requirement:** §16, §22 (CBZ per unit), §39, §41.3 (MangaDex/3asq CBZ packaging, Download Missing).
- **Reproduction (live, isolated instance):** download one unit of MangaDex "Oneshot", 3asq "One Piece",
  Tapas "Groovy, Kinda" and WEBTOON "Tower of God" after opening them from search or URL. Results: MangaDex
  and 3asq **FAILED** "file returned HTTP 416", Tapas **FAILED** `media_invalid`, WEBTOON **FAILED** "file
  returned HTTP 403". The jobs carry `output_format: "file"` with method `html_api`. The identical flows
  with `content_type` supplied (MangaDex "Gachiakuta", WEBTOON "Safely Endangered") **COMPLETED** as valid
  CBZs of 20 and 5 pages.
- **Root cause (confirmed):** `downloads/engine.py:192` picks the output by Work family
  (`family_for(content_type) == "Sequential Art"`), not by what the source delivers. With `unknown` it
  chooses `file`, then `_download_file` fetches only `resources[0]` (the first page image). That fetch
  happens under the `downloads` capability, without the reader recipe's `resource_headers` (hence WEBTOON's
  403). Validation then fails as "not a document", and the retry hits BE-007's Range bug (the 416).
- **Impact:** every MangaDex, 3asq, Tapas and WEBTOON download started from search or URL entry fails. In
  production that is every such Work, because of BE-002. A user cannot correct the type either (BE-012).
- **Fix:** derive the output from the resolved recipe, not the Work label. An image `reader` result gives
  CBZ, a text reader gives the text container, and `downloads` file descriptors give the original file. Only
  fall back to the family for ambiguous recipes. Apply the reader recipe's `resource_headers` to page fetches
  in the engine. Fixing BE-002 alone is insufficient: a source with no default type would still break.
- **Tests and acceptance:** a Test Source image-reader unit on a Work with `content_type='unknown'` downloads
  as a validated CBZ. A downloads-only unit still produces the original PDF/EPUB. Live smoke tests of
  MangaDex, 3asq (a chapter whose images exist), Tapas and WEBTOON each commit a CBZ.

## BE-004 · P2 · The same source listing becomes two Source Tracks depending on the entry path

- **Requirement:** §6.9 (cached and live copies of one source item must merge), §4.3, INV-27.
- **Reproduction:** open Standard Ebooks "Frankenstein" from search (track `und`), then resolve and open
  `https://standardebooks.org/ebooks/mary-shelley/frankenstein`. Work `5jtjzaqoxh2n` now has **two** tracks
  for the same listing key, `en` and `und`, each with its own catalog and units.
- **Root cause (confirmed):** the URL resolver applies `defaults.language` (`url_resolve.py:89`) but search
  does not (BE-002). `persist_listing` keys tracks by `(listing_id, language)`.
- **Impact:** progress, downloads and Follow split across duplicate tracks. The downloaded file belongs to
  only one of them.
- **Fix:** resolved by BE-002's single classifier. Its migration must merge the `und` twin into the
  classified track, re-pointing units, assets, progress and follows, with a pre-migration snapshot.
- **Tests:** opening one listing via search and via URL yields exactly one track. The migration merges an
  existing pair without data loss.

## BE-005 · P1 · Any unexpected exception leaves a download job stuck "active" forever (seen in production)

- **Requirement:** §16 state machine, §16.1 (Completed with Issues, Retry), §17, §30.4 (final failures
  notify), §46.
- **Production evidence:** `GET /api/downloads/e2gvnow3lv7r` shows job `t5gehagbczci` in `PREPARING`,
  attempts 1, no error. Production has **no storage location** (`GET /api/storage` → `roots: []`, First Run
  `pending`). The Downloads page shows "Active · 0 done · 1 waiting" indefinitely
  (`browser-live/desktop-downloads.png`).
- **Reproduction:** `probes/test_audit_probe_noroot.py` raises `RuntimeError: no storage location
  configured`, and the job stays `PREPARING` and is never runnable again. `probes/test_audit_probe_downloads.py::test_c1`
  shows the same for an oversized resource: `ResponseTooLarge` leaves the job in `DOWNLOADING`, with no
  history row and no notification.
- **Root cause (confirmed):** `_process` (`downloads/engine.py:486`) catches only a fixed list of
  exceptions. `RuntimeError` from `_choose_root`, `ResponseTooLarge`, `TooManyRedirects`, `KeyError` and
  `ValueError` from malformed descriptors, and similar errors escape. The runner only logs "download pass
  failed". Startup recovery re-queues the job into the same crash.
- **Fix:** (1) validate at `enqueue` and refuse with 409 `NO_STORAGE_LOCATION` and an actionable message
  when there is no available root. (2) Catch `Exception` in `_process` after the specific handlers and
  route it to a terminal `FAILED` with category `internal_error`, recording history and a notification.
  Map `ResponseTooLarge` to `too_large` and `TooManyRedirects` to `transport`. (3) Add a startup
  reconciliation that fails jobs stuck in active states with no live worker after N recoveries.
- **Tests:** no root → enqueue 409. An injected `RuntimeError`, `ResponseTooLarge` or `TooManyRedirects` →
  job `FAILED` with history and a notification. Recovery of a poisoned job ends `FAILED`, not looping.
- **Owner action (no code):** add a Storage Location on production (Settings → Storage or First Run), then
  cancel batch `e2gvnow3lv7r`.

## BE-006 · P1 · Long synchronous work blocks the event loop, freezing the API and the Reader

- **Requirement:** §15 and INV-26 (Reader and direct work never starved), §26.24, §34.9 (huge exports),
  §33, §56 (bounded memory and responsiveness).
- **Reproduction (isolated instance):** a Full Backup of 5 Works (82.5 MB) took 1.08 s. During it,
  `/api/health` polled every 50 ms had a **maximum latency of 1.06 s** against a median of 2 ms: the whole
  server stalled for the entire operation. The stall scales linearly, so a Full Backup of a 20 GB library
  would freeze the app for minutes.
- **Root cause (confirmed by inspection plus measurement):** the code base has no `to_thread` or executor.
  Backup creation, restore copies, export copying, storage migration, scanner checksumming,
  `sha256_file` on large artifacts, and `reader.local_file` (BE-011) all run synchronously inside
  `async def` handlers or runners.
- **Fix:** run CPU- and IO-heavy jobs (backup, restore, export, migration, scan, checksum, large file reads)
  in a worker thread with its own SQLite connection, and keep the event loop for orchestration. Report
  progress via events, keep write transactions short on the shared connection, and move these jobs to
  persisted background tasks rather than request-bound calls.
- **Tests:** during a synthetic 500 MB backup, export or scan, p99 `/api/health` and reader-page latency
  stays under 250 ms. Backup output is byte-identical before and after the change.

## BE-007 · P2 · Direct-file resume asks for an unsatisfiable range after a complete body, so the job fails with 416

- **Requirement:** §16.3 (5xx and timeouts are retryable), §16.4 (Range/If-Range resume, never splice).
- **Reproduction:** `probes/test_audit_probe_downloads.py::test_c2` (a Test Source PDF, the first validation
  fails transiently, and an RFC-conformant server answers 416). The retry sends `Range: bytes=40442-` for a
  file of exactly 40442 bytes, and the job ends `FAILED: file returned HTTP 416`. Live, the same mechanism
  turned BE-003 into a 416 failure.
- **Root cause (confirmed):** `_download_file` (`engine.py:586-607`) keeps the full body and validator in the
  manifest after a 200. Any later failure (validation, or a commit error) makes the next attempt send a
  Range from EOF. `retry_job` (`engine.py:360`) never clears `manifest_json`/staging, so a manual Retry
  fails the same way.
- **Fix:** resume only when `bytes < Content-Length` (record the expected length). Treat 416 or a complete
  stored body as "restart clean". Discard the partial after a validation failure (the bytes are known bad).
  `retry_job` resets the file manifest unless the user explicitly asks to resume.
- **Tests:** a complete body plus forced validation failure → the retry refetches with 200 and commits. A
  416 → a clean restart. A changed ETag never splices (the existing test stays green).

## BE-008 · P2 · Re-downloading a unit whose file is missing or corrupt orphans the new file and wedges the commit journal

- **Requirement:** §16.5, §17 (idempotent recovery), §24.7, §38, INV-16/17.
- **Reproduction:** `probes/test_audit_probe_downloads.py::test_c5`. Download a unit, delete the file
  manually, run a scan (`missing_local_file`), then Download again without repair. The job ends `FAILED:
  storage_error: final path already exists`. The commit journal stays at **`verified`** forever. The new file
  sits on disk, unregistered, and the asset row still says `missing_local_file`.
- **Root cause (confirmed):** `register_download` uses `INSERT OR IGNORE` and conflicts on
  `UNIQUE(reading_unit_id, format, variant)` with the stale row. It then raises `CommitError` after the file
  was moved. Retries hit "final path exists". Each startup's `CommitEngine.recover()` re-raises on that
  entry. Only the Reader's Repair button passes `repair=True`; the Work page Download button does not.
- **Fix:** the registrar upserts an existing non-`ok` asset for the same unit, format and variant (update
  path, size, sha and integrity to `ok`) instead of inserting. The engine treats a unit whose only assets are
  non-`ok` as a repair automatically, but without BE-009's early delete. Recovery finishes or aborts such
  entries deterministically.
- **Tests:** the C5 scenario ends `COMPLETED` with one `ok` asset row, journal `done`, and no orphan files.
  A second startup is a no-op.

## BE-009 · P2 · Repair deletes the existing copy before a replacement exists

- **Requirement:** §14 (*"redownload full unit into temp → validate → atomic replace"*), §26.21 (never
  silently delete), §3.4.
- **Reproduction:** `probes/test_audit_probe_downloads.py::test_c4`. A CBZ marked `corrupt` by a scan, then
  a Repair while the source is unreachable. Immediately at enqueue, the asset row and the file are both
  gone. The job then fails, and the user is left with nothing: not even the readable pages of a mostly-good
  file, nor the record that a copy existed.
- **Root cause (confirmed):** `enqueue(repair=True)` calls `_clear_broken_copy` (`engine.py:128`) inside the
  enqueue transaction. The file unlink is not transactional, so a later `ValueError` in the same enqueue
  rolls back the rows but not the deletion.
- **Fix:** keep the broken asset until the new artifact is verified. Commit through the journal with a
  `replace` registration that atomically swaps the asset row, renames the old file to staging-trash, and
  deletes it only after `done`. This is the same mechanism BE-008 needs.
- **Tests:** a Repair with the source offline leaves the asset row and file untouched. A Repair that
  succeeds leaves exactly one `ok` asset and no trash. A crash at each journal step stays recoverable.

## BE-010 · P2 · Following before a catalog is trusted floods "new releases" on the first successful check

- **Requirement:** §20 (*"First Follow creates baseline, does not flood"*), §5.4, INV-9 neighbourhood.
- **Reproduction:** `probes/test_audit_probe_follow.py`. Bind a listing, Follow before any trusted catalog
  exists (`baseline_units=0`), then let the catalog become trusted and check. The result is `new_releases`
  with **all 9 units** reported new. This is realistic whenever the open-time catalog fetch fails or is
  incomplete (Gutenberg's 1.0.0 search and catalog transport failures, rate limits).
- **Root cause (confirmed):** `FollowService._baseline` (`follow/service.py:89`) stores an empty baseline
  when `trusted_catalog` is `None`, and `check` treats every trusted key as new.
- **Fix:** mark the baseline `pending` when no trusted catalog exists. The first check that obtains a
  trusted catalog establishes the baseline silently, which matches the Source Change Baseline semantics.
- **Tests:** follow without a trusted catalog → the first trusted check reports 0 new. A unit added after
  that → 1 new.

## BE-011 · P2 · Whole resources and documents are buffered in memory (not streamed)

- **Requirement:** §16 "streamed transport", §34.9 (do not load into RAM), §56 (avoid loading huge works into
  RAM), C5 gate.
- **Evidence (inspection):** `HttpClient.fetch` accumulates the body in a `bytearray` and then copies it to
  `bytes` (`net/http.py:133-137`), so peak memory is about 2× the body, with `MAX_RESOURCE_BYTES` = 256 MiB.
  `_download_file` and `_download_pages` hold whole bodies before writing them.
  `GET /api/reader/units/{id}/file` serves `reader.local_file()` = `path.read_bytes()`
  (`reader/service.py:306`): a whole PDF or EPUB per request, read synchronously (BE-006), with no `Range`
  support for pdf.js. The engine docstring says "streamed transport with resume", but there is no streaming.
- **Fix:** add `HttpClient.stream_to(path, …)` that writes chunks to the staging file, with Range
  continuation from the on-disk length. Use it for files and pages. Serve local files with `FileResponse`
  (Range-capable) plus the same sandbox and nosniff headers.
- **Tests:** a tracemalloc ceiling during a 200 MB Test Source file download and a 200 MB local-file serve
  (peak < 32 MB). A `Range` request returns 206. The headers are unchanged.

## BE-012 · P2 · No write path exists for user overrides (classification, unit numbering, metadata)

- **Requirement:** §9.2 tier 1 (user override), §4.4 (*"user correction overrides derived numbering"*),
  INV-4, §22 Import "Choose Work".
- **Evidence:** the `user_overrides` table (`0001_initial.sql:121`) and `reading_units.user_number` are read
  (`api/works.py`, `reader/alternatives.py`) and carried by backup and restore. The read-side number
  precedence is tested by writing `user_number` with raw SQL (`tests/integration/test_work_api.py:250`).
  **No API or service writes either one.** `docs/c0/traceability.md` row M9.2 claims `VERIFIED` with
  "precedence tests" and a "Work details edit" surface. No classification-precedence test and no edit
  endpoint exist (`grep` over `backend/tests` and `backend/oneshelf/api`).
- **Impact:** users cannot correct a wrong type, language or number. Combined with BE-002, the live Berserk
  Work cannot be fixed from the UI. The INV-4 "preserved on refresh" property is untestable because no
  override can be created.
- **Fix:** add `PATCH /api/works/{id}` (content type, display title, aliases), `PATCH /api/tracks/{id}`
  (language, behind an explicit confirmation because it changes identity), and `PATCH
  /api/reading-units/{id}` (user number, display title, unit type), all writing `user_overrides`. Apply
  overrides in readers and refresh paths (`CatalogTrust._materialize` must not clobber them). Set the
  traceability row M9.2 back to IN_PROGRESS until this lands. Codex handoff: H-3.
- **Tests:** precedence (user > source > plugin default > Unknown). An override survives catalog refresh,
  plugin update and restore merge (INV-4).

## BE-013 · P2 · Multi-format sources cannot choose a format, and only the first file is ever downloaded

- **Requirement:** §22 (*"multiple formats may coexist"*), §41.3 (Standard Ebooks: *"multiple formats,
  format selection"*), §34.1 (selected formats), §14 (Required output in the Extraction Contract).
- **Evidence:** `POST /api/downloads` has no format field. `_process` calls `_download_file(…, resources[0],
  …)`. For Standard Ebooks "Frankenstein" the engine stored only the first descriptor (EPUB). The other
  offered files are unreachable.
- **Fix:** expose the `downloads` descriptors through `GET /api/reading-units/{id}/formats`. Add
  `formats: [..]` to the enqueue body, recorded as the contract's `output_format`. Let one unit hold one
  asset per `(format, variant)` (the schema already allows this). Default to a source preference order
  (EPUB > PDF > other).
- **Tests:** downloading EPUB then PDF for one unit yields two assets on one Work with no duplicate Work. An
  unknown format is refused. Export honours the selected formats.

## BE-014 · P2 · The bundled official adapter snapshot is stale, and two bundled adapters fail live

- **Requirement:** §41.1 (initial suite works), §10 (update and rollback), §21 (health), G5 (evidence
  ledger).
- **Evidence:**
  - Bundled `oneshelf.gutenberg 1.0.0` search times out on every query. The recipe calls
    `gutendex.com/books?search=` without a trailing slash, which costs a slow 301 (about 27 s) plus about 16
    s for the real response, beyond the search budget. Source health is **`unavailable`** after 10
    failures. Registry `2.0.1` drops search entirely and moves to `www.gutenberg.org`. Production still runs
    the bundled 1.0.0 (`GET /api/sources` on 192.168.8.32, channel `bundled`), as do Standard Ebooks 1.0.0
    and arXiv 1.0.0.
  - Bundled `oneshelf.hindawi 1.0.0` sends Latin queries to `safahat.org/search/keyword/<q>/`, which 301s to
    `http://…/<lowercased>/`. The plain-http hop is refused as `blocked`, so every global search records a
    Hindawi failure.
  - Bundled `oneshelf.mangadex 1.0.2` is a local hotfix (`UPSTREAM.json` `local_changes`) that diverges from
    Registry `1.0.1`. Production runs Registry 1.0.1, so the 1.0.2 translation-language fix is not live, and
    a later upstream "1.0.2" would collide by version. `docs/development.md` says the snapshot is "never
    edited by hand".
  - 3asq: units "0A"…"0D" all show number `0`, and every unit type is `unknown`. Many older chapters' images
    404 at the source (an upstream content loss, reported correctly as invalid media).
- **Fix:** refresh the bundled snapshot from OneShelf-Adapters, using `python -m plugins.sync_snapshot`.
  Upstream the MangaDex fix as 1.0.3 so the local hotfix can be removed. Handoff A-1…A-4 to OneShelf-Adapters
  covers the Gutenberg trailing slash and fixture, the Hindawi Latin-query and http redirect, and 3asq
  numbering and special types. Core addition: a source that answers a 3xx to a disallowed scheme for a
  *query* should record `content_missing`, not a health failure. Hypothesis: whether that is desirable needs
  an owner decision.
- **Tests:** packaged tests for each repaired adapter. The live suite (`tests/live`) is green for the
  bundled set.

## BE-015 · P3 · Backups carry remote-auth material that §33.3 excludes

- **Requirement:** §33.3 (never include active remote UI sessions, recovery code), INV-19, §48.
- **Reproduction:** `probes/test_audit_probe_backup.py`. After enrol and sign-in, the Library Backup's
  `library.db` contains `remote_sessions` 1 (an unrevoked token hash, valid 30 days), `remote_recovery` 1
  (scrypt verifier plus salt) and `remote_credentials` 1. Restore does not re-import these tables.
- **Root cause (confirmed):** `backup/service.py:36` `EXCLUDED_TABLES` omits `remote_sessions`,
  `remote_recovery`, `remote_credentials` and `webauthn_challenges`.
- **Impact:** low. Tokens are random and stored hashed, and the verifier is scrypt. It is still a breach of a
  hard exclusion, and the INV-19 test evidently does not inspect these tables.
- **Fix:** add the four tables to `EXCLUDED_TABLES`. Extend the INV-19 test to assert that every table not
  on an allow-list is either excluded or reviewed, so new tables cannot slip in.
- **Tests:** the C11 probe asserts all four counts are 0. A table-inventory guard test.

## BE-016 · P3 · Storage problems are reported as "Low storage: 0 bytes remain", and a batch of canceled jobs reads "Completed"

- **Requirement:** §24.6 (*Storage Location Unavailable* is distinct), §30.7, §46, §16.1.
- **Evidence:** `_notify_failure` (`engine.py:656`) maps both `storage_full` and `storage_unavailable` to
  `low_storage(free_bytes=0)`. `DownloadEngine.batch()` returns `completed` when every job was canceled
  (production shows "Completed · 0 done · 1 canceled").
- **Fix:** add a `storage_unavailable(root)` notification (dedupe `storage-unavailable:<root>`) and pass real
  free bytes. Add a `canceled` batch state.
- **Tests:** an offline root yields the unavailable notification. An all-canceled batch is `canceled`.

## BE-017 · P3 · Online page failures hide the upstream status, and reader descriptors are cached for the life of the process

- **Requirement:** §26.21 error recovery, §46, §21 health, §26.20 (cache identity and validator), G4
  (expiring resource URLs).
- **Evidence:** `_fetch_online_page` validates image bytes without checking `response.status`, so a 404 HTML
  page surfaces as `PAGE_NOT_FOUND: page 1: html returned instead of image`, and no health signal is
  recorded. `ReaderService._descriptors` (`reader/service.py:220`) is an unbounded per-process dict that is
  never invalidated. **Expiry hypothesis (not confirmed):** MangaDex@Home page URLs from descriptors fetched at 19:50 UTC
  still loaded at 20:27 UTC (37 min). No expiry was observed. The refresh-on-403/404 fix is defensive only.
- **Also observed (isolated instance, `reader-checks.log`):** with the source plugin **disabled**, an online
  unit answers 409 `DOWNLOAD_REQUIRED` "This book has to be downloaded before it can be read". `_file_only`
  treats an unavailable plugin as a download-only source. Its already-cached pages also become unreachable,
  because the descriptor lookup fails before the Reader Cache is consulted. That breaks §26.21: *"If source
  unavailable … cached online pages remain usable where possible"*.
- **Fix:** map non-200 statuses to `source_failed:<status>` (502) and record a health signal. Give the
  descriptor cache an LRU bound and a TTL, and re-run `reader` once on a 403/404 or expired URL before
  failing. Report `SOURCE_UNAVAILABLE` (not `DOWNLOAD_REQUIRED`) when the plugin is disabled or missing.
  Persist page descriptors with the cache entries, keyed by source, unit identity and validator, so cached
  pages stay readable offline.
- **Tests:** a 404 page → 502 `SOURCE_FAILED` with the status. The descriptor cache stays bounded. An
  expired URL triggers exactly one refresh.

## BE-019 · P3 · A source read timeout leaks the HTTP connection

- **Requirement:** §15 (bounded resources and fairness), §43 (bounded diagnostics). Operational hygiene.
- **Evidence:** in the project's own live suite (`ONESHELF_LIVE_SOURCES=1 pytest tests/live`), the Gutenberg
  test skipped on `SocketTimeoutError`. The *next* test (WEBTOON) then failed on
  `PytestUnraisableExceptionWarning: unclosed <socket … raddr=('2606:4700:3031::ac43:ae84', 443)>`. That
  address is `gutendex.com` (`getent ahosts`). Log: `qa-artifacts/be-audit-20261019/pytest-live.log`.
- **Root cause (hypothesis):** a connection abandoned mid-read (or the slow 301 hop that precedes it) is not
  released or closed when `HttpClient.fetch` raises `FetchFailed`. Under sustained timeouts this leaks file
  descriptors until the client session closes.
- **Fix:** on any exception inside the response context, call `resp.close()` (or `release()`) explicitly.
  Add a test that injects a read timeout against the Test Source's `interrupted` endpoint with
  `-W error::ResourceWarning`.
- **Tests:** the timeout test passes with ResourceWarnings as errors. The live suite is green when a source is
  slow.

## BE-018 · P3 · Disk-space preflight for downloads ignores known sizes

- **Requirement:** §24.5 (expected-size preflight for large operations).
- **Evidence:** `engine.py:458` always passes `expected_bytes=0`, even when `FileDescriptor.size_bytes` is
  known. Import, export, restore and migration do pass sizes.
- **Fix:** pass the descriptor size, or the sum for a batch window. **Tests:** a file that would cross the
  reserve fails preflight before fetching.
