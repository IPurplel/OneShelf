# Frontend handoffs for Codex — backend repair of the 2026-10-19 audit

Each handoff names the backend contract that is already implemented on the stated branch. Until that branch
merges, the frontend can build against the contract. The backend is the source of truth for codes and
payloads. Handoff IDs H-1…H-9 match `repair-plan.md`.

## H-1 · Downloads: nowhere to store, terminal failures, canceled batches (WP-2, branch `repair/be-phase1-security-jobs`)

- **Feature:** Downloads screen, Download buttons on the Work page, Reader download action.
- **API contract changes:**
  - `POST /api/downloads` → **409** `{"error": {"code": "NO_STORAGE_LOCATION", "message": "…"}}` when the
    library has no default Storage Location and no `root_id` is given. No batch is created.
  - Job `error_category` can now be `internal_error` (unexpected failure), `too_large` (the resource exceeds
    the transfer limit; never retried), `interrupted` (the worker died more often than the retry budget), or
    `storage_unavailable`.
  - `GET /api/downloads/{batch}` `state` can now be **`canceled`** (every job canceled, none completed).
- **Expected UI behaviour:**
  - On 409 `NO_STORAGE_LOCATION`: no optimistic "queued" state. Show an inline notice ("Add a storage
    location to download") with a **Manage storage** action (Settings → Storage).
  - Terminal jobs (`FAILED`) never render as "waiting". Show the category in plain language. Show Retry for
    `internal_error`, `interrupted`, `transport`, `storage_unavailable`. For `too_large` show no Retry, only an
    explanation.
  - A `canceled` batch is labelled "Canceled", not "Completed".
- **Error and success states:** success is unchanged. Errors are as above.
- **Frontend tests:** enqueue 409 shows the notice and the action, with no batch card. Each new category
  renders its copy (ar/en). A `canceled` batch label.
- **Acceptance:** with no storage location, clicking Download shows the notice. On production after merge,
  the stuck "1 waiting" card cannot recur.

## H-2 · Settings → Access: boundary settings are LAN-only (WP-1, branch `repair/be-phase1-security-jobs`)

- **Feature:** Settings → Access/Remote, First Run access-mode step.
- **API contract changes:** `POST /api/auth/networks`, `POST /api/auth/hostname` and `POST
  /api/first-run/access-mode` return **403** `LAN_REQUIRED` for remote sessions. Proxy ranges outside private,
  CGNAT, loopback, link-local or ULA space, or wider than /8 (IPv4) or /32 (IPv6), return **422**
  `INVALID_NETWORK` with an explanatory message. `GET /api/auth/state` → `network.ignored_proxies: string[]`
  (stored entries that are no longer honoured).
- **Expected UI behaviour:** when `access === "remote"`, render these editors read-only with the text "Can only
  be changed from a device on your network." Show the 422 message under the proxy field. If
  `ignored_proxies` is non-empty, show a Needs-Attention-style warning listing them, with a link to edit.
- **Frontend tests:** a remote-state fixture shows read-only editors. A 422 message renders. The ignored-proxy
  warning renders.
- **Acceptance:** no network or hostname edit is possible from a remote session in the UI. The API refuses it
  regardless.

## H-6 · Notifications: storage unavailable is distinct from low storage (WP-2, branch `repair/be-phase1-security-jobs`)

- **Feature:** Notifications, Needs Attention.
- **API contract:** a new notification with `dedupe_key` `storage-unavailable:<root_id>`, title "Storage
  location unavailable", action `manage_storage`, `data.storage_root_id`. Low Storage now carries the real
  `free_bytes`.
- **Expected UI behaviour:** an Important item with the Manage storage action. Do not phrase it as "low
  storage". Localise the title and summary (ar/en) from the dedupe-key prefix rather than displaying backend
  English.
- **Frontend tests:** the notification renders with its action, in Arabic and English.
- **Acceptance:** unplugging a storage location shows "unavailable", never "0 bytes remain".

## H-3 · Work details: user corrections and honest classification (WP-5/6/7, branch `repair/be-phase2-classification`)

- **Feature:** Work details header and unit list, Reader title, Settings → Maintenance.
- **API contract changes:**
  - `PATCH /api/works/{id}` with a body containing any of `{"content_type": "manga"|"manhwa"|"manhua"|"comic"|"book"|"novel"|"paper"|"other"|null, "title": string|null}`. Only the fields sent change. `null` clears the user's correction and restores what it replaced. Returns the same payload as `GET /api/works/{id}`. Errors: 422 `INVALID_CORRECTION`, 404 `WORK_NOT_FOUND`.
  - `PATCH /api/reading-units/{id}` with a body containing any of `{"number": string|null, "title": string|null, "unit_type": "chapter"|"special"|"extra"|"prologue"|"epilogue"|"one_shot"|"other"|null}`. Returns the Work payload. Errors: 422 `INVALID_CORRECTION`, 404 `UNIT_NOT_FOUND`.
  - `work.content_type_source` is one of `user | source | plugin_default | unknown`.
  - Search results and `/api/resolve-url` now carry the plugin's default language and type where the source is silent (3asq → `ar`/`manga`). The UI already echoes them to `/api/listings/open`; no change is needed there.
  - `GET /api/maintenance/reclassification` returns a preview with no writes: `{applied: false, count, changes: [{kind: work_type|track_language|track_merge, work_id, detail}]}`. `POST` applies it, after a database snapshot, and returns `{applied: true, snapshot, count, changes}`.
- **Expected UI behaviour:**
  - Work details: an "Edit details" control for type and title. Each unit's More menu gets a "Correct number/title/type" control.
  - Show "(your correction)" subtly when `content_type_source === "user"`. Offer "Use source value" (sends `null`).
  - Never show "unknown · Unknown language" when a value is known.
  - Settings → Maintenance (advanced): "Repair library classification". It shows the preview list in plain language ("Berserk: language Unknown → Arabic", "merge duplicate Arabic track") with a single Apply button. After applying, show the result and the snapshot path.
- **Errors:** 422 messages render under the field. The Apply button is disabled while a request is pending.
- **Frontend tests:** an edit round-trip, clearing a correction, the 422 message, the preview list with an empty state, and apply → refreshed counts. Arabic and English.
- **Acceptance:** on a library with old `und` tracks, the preview lists them and Apply fixes them. A 3asq Work then shows "manga · Arabic". A corrected unit number survives a catalog refresh.

## H-7 · PDF/EPUB reader: load the file in ranges (WP-9, branch `repair/be-phase3-responsiveness`)

- **Feature:** the Book Reader (pdf.js for PDF; the EPUB loader).
- **API contract change:** `GET /api/reader/units/{id}/file[?format=]` is now a streamed `FileResponse`. It sends
  `Accept-Ranges: bytes`, answers `Range: bytes=a-b` with **206** and `Content-Range`, and supports `If-Range`.
  The headers are unchanged: `Content-Security-Policy: sandbox; default-src 'none'`, `nosniff`, `no-store`,
  `Cross-Origin-Resource-Policy: same-origin`, `Content-Disposition: inline`.
- **Expected UI behaviour:** give pdf.js the URL with range loading enabled (`disableRange: false`,
  `rangeChunkSize` ≈ 1 MiB, `disableAutoFetch: true`), so the first page renders before a large file finishes
  downloading. EPUB can keep loading the whole file.
- **Error and success states:** 404 `FILE_NOT_AVAILABLE` and 404 `UNIT_NOT_FOUND` are as before.
- **Frontend tests:** the PDF viewer requests ranges (a network assertion in the browser test) and still renders
  page 1. A missing file still shows the existing message.
- **Acceptance:** a 200 MB PDF shows its first page without waiting for the whole file. Memory in the browser
  stays bounded.

## H-9 · Long library jobs as background tasks (WP-8, branch `repair/be-phase3-responsiveness`)

- **Feature:** Settings → Backup (create Full or Library backup, restore), Export, Storage (migrate, scan).
- **API contract (additive; the synchronous form still works):**
  - Add `?background=true` to `POST /api/backups`, `POST /api/restore`, `POST /api/export`,
    `POST /api/export/{job}/retry-failed`, `POST /api/storage/roots/{id}/migrate` or `POST /api/storage/scan`.
    The answer is **202** `{"task_id", "kind", "state": "running"}`. Input errors are still answered
    immediately: 422 `MIGRATION_REFUSED`, 409 `PERMANENT_DOWNLOAD_NOTICE_REQUIRED`, 422 `EXPORT_REFUSED`.
  - `GET /api/tasks/{task_id}` returns `{id, kind, state: running|completed|failed, started_at, finished_at,
    status, result}`. `result` is exactly the body the synchronous call would have returned, including
    `{"error": {code, message}}` on failure; `status` is its HTTP status. 404 `TASK_NOT_FOUND` after a restart.
  - Event `task.finished` `{task_id, kind, state}` on `/api/events`.
- **Expected UI behaviour:** start these jobs with `background=true` and show a calm in-progress state on that
  panel (not a blocking spinner). The rest of the app stays usable. On `task.finished`, fetch the task and render
  the result or the error with the existing copy. If the page reloads mid-job, the list views (backups, export
  jobs, migrations) already show persisted state; the task handle itself is optional.
- **Frontend tests:** a 202 → progress → `task.finished` → success flow for backup and export. A failed task
  renders its error code's copy. Navigating away and back keeps the panel consistent.
- **Acceptance:** a multi-GB Full Backup never ties up a request; the Reader and the rest of the UI stay
  responsive while it runs (the backend measures a worst `/api/health` delay of 2 ms during a 96 MB backup).

## H-4 · Download format choice (WP-11, branch `repair/be-phase4-functional`)

- **Feature:** the Download action for a book unit (Work page, unit menu) and "Download all" for books.
- **API contract changes:**
  - `GET /api/reading-units/{id}/formats` returns `{unit_id, formats: [{format, variant, size_bytes, supported,
    downloaded}]}`, in the source's order. `supported` is true for `epub`, `pdf` and `cbz`, the formats OneShelf
    keeps as originals. It also lists local copies the source no longer offers. Errors: 404 `UNIT_NOT_FOUND`,
    409 `SOURCE_UNAVAILABLE`, 409 `SESSION_REQUIRED`, 429 `RATE_LIMITED`, 502 `SOURCE_FAILED`.
  - `POST /api/downloads` accepts an optional `formats: ["epub"|"pdf"|"cbz", …]`. Each format is its own job and
    its own file of the same unit. A format the source does not offer fails as `format_unavailable` (not
    retried). A format already downloaded is counted in `skipped`. Any other value is refused with 422.
  - Without `formats`, the backend takes the first keepable format the source offers, in the order EPUB, PDF,
    CBZ.
  - Work payload: `units[].formats` already lists every downloaded format.
- **Expected UI behaviour:** when a unit's source offers more than one supported format, the Download action
  opens a small chooser (checkboxes, preselected EPUB) showing sizes where known. Already-downloaded formats
  are shown as such. Unsupported formats are listed but disabled, with "OneShelf cannot keep this format".
  With one format, keep today's one-click Download.
- **Frontend tests:** the chooser appears only for multi-format units, and the request carries `formats`. A
  `format_unavailable` job renders its copy. Arabic and English.
- **Acceptance:** a Hindawi book offered as EPUB and PDF can be kept in both, under one Work.

## H-5 · Reader: say what happened (WP-12, branch `repair/be-phase4-functional`)

- **Feature:** the Reader's page and text error states, and opening a unit whose source is disabled.
- **API contract changes:**
  - `GET /api/reader/units/{id}/pages`, `/pages/{n}` and `/text` can answer **409 `SOURCE_UNAVAILABLE`** (the
    source is disabled or not installed and the item is not cached). Before, this came back as
    `DOWNLOAD_REQUIRED`.
  - A page the source lost answers **502 `SOURCE_FAILED`** with a message such as `not_found: page 3: the
    source answered HTTP 404`. Before, it was 404 `PAGE_NOT_FOUND` "html returned instead of image".
  - Already-cached pages of an online unit stay readable while its source is disabled or offline. Their
    responses carry `X-OneShelf-Origin: cache`.
  - `GET /api/reader/units/{id}/context` no longer reports `kind: "download"` for a unit whose source is
    merely disabled. It reports the unit's normal kind.
- **Expected UI behaviour (§26.21, §46):**
  - `SOURCE_UNAVAILABLE`: "This source is turned off. Downloaded and already-viewed pages are still readable."
    Offer **Open Sources**; never show Download.
  - `SOURCE_FAILED` for one page: the existing Retry / Skip page controls, with "The source no longer has
    this page". Do not mark the whole unit broken.
  - No automatic source switch in either case.
- **Frontend tests:** each error code renders its copy and actions. A cached page renders while the source
  is disabled. Arabic and English.
- **Acceptance:** with a source disabled, a previously read chapter still opens on its cached pages. An
  unread one says the source is off, not "download required".

## H-8 · Following: a baseline that waits for the first trusted catalogue (WP-10, branch `repair/be-phase4-functional`)

- **Feature:** Following list and the Follow button on the Work page.
- **API contract change:**
  - `POST /api/follows/{work}` and `.../preferred-source` can return `baseline_kind: "pending"` (the
    catalogue has never been trusted yet; previously `first_follow` with `baseline_units: 0`).
  - The Following status has `baseline_pending: true` until the first successful check sets the baseline
    silently. That check reports `up_to_date` with no new units.
- **Expected UI behaviour:** while `baseline_pending`, show a quiet note under the Follow state: "Following
  starts once this source's chapter list loads." Never show "N new" for the catalogue that existed when it
  was followed.
- **Frontend tests:** the note renders for a pending Follow and disappears after a check. Arabic and English.
- **Acceptance:** following a Work whose catalogue failed to load, then checking once it loads, shows no
  flood of "new" chapters.

All nine handoffs (H-1…H-9) are now written.

## Observation (not a backend contract)

In the Long Strip reader at 1440×900, a page narrower than the viewport sits against the left edge with black
space to its right. This is seen on production (3asq Berserk, 2026-10-19) and on the repaired build (3asq
Romance Dawn, 2026-10-20). §26.7 asks for centred single pages; consider centring the strip too. No API is
involved.

## Answers to Codex's handoff of 2026-10-20 (`docs/audits/2026-10-20-ui-backend-handoff.md`, PR #6)

Implemented on `repair/be-ui-contracts`, stacked on phase 4. The contracts are as requested, with these
precise semantics:

**UI-003 — `GET /api/downloads/{batch_id}`**
- Each job adds `work_id`, `work_title`, `track_id` and `unit_title` (null when unresolvable).
- `available` is true only for a `COMPLETED` job whose unit the Reader would open from this device right now.
  That is the copy the Reader opens (the unit's oldest `ok` record, in the format the job produced), with its
  storage location connected and marked as OneShelf's, and the file in it. A read-only location still opens.
  It is false for a deleted, missing, corrupt or unverified copy, a disconnected location, or a path OneShelf
  will not follow. A job whose file was deleted, or that finished before jobs were linked to their files,
  reports what the unit has now, because the Reader opens the unit, not the job. The Reader and this field use
  one shared function (`oneshelf/library/copies.py`), so they cannot disagree.
- Deleting a Work's files (`DELETE /api/works/{id}/files`) failed with a 500 for any downloaded or imported
  file, after the file was already gone, and left a record that still said `ok` (I-110). It now succeeds:
  the jobs stay in history with `available: false`, and the unit can be downloaded again.
- A copy whose file disappeared from a connected location is no longer skipped as `already_downloaded`. The
  new download replaces it (I-98). A copy on a disconnected location is still skipped, so a unit is never
  downloaded twice.
- The frontend should treat a missing `available` (an older backend) as "not known", which means not
  openable. It should also re-read an open batch on `shelf.changed`, which carries `action: "files_deleted"`
  when files are deleted. Both are done on `repair/ui-download-availability`, a PR into PR #6's branch.
- `bytes_total`: for a finished job, what it transferred; for jobs finished before `bytes_done` existed, the
  stored file's size. For a whole file in progress, the size the source announced. Otherwise null (image
  pages have no announced size).
- `bytes_done` is now kept current from the job's manifest.
- `last_error` is redacted: URLs lose secret-looking parameters, and known credential patterns are removed.
  Use `error_category` for copy.
- `skipped_units`: `[{reading_unit_id, unit_title, reason}]`, where `reason` is `already_downloaded` or
  `already_queued`. It is `null` for batches created before this change.
- Bounds: `?offset=0&limit=500`, with `limit` from 1 to 1000. Responses carry `jobs_total`, `skipped_total`,
  `offset` and `limit`, and `skipped_units` is paged with the same window.
- An unknown batch is 404 `BATCH_NOT_FOUND`; it used to be a 500.

**UI-004 — `GET /api/sources`**
- `last_successful_check_at` is the last time any capability of the source succeeded, as ISO-8601 UTC.
  `null` means it has never succeeded. That is said only when every check of the source is on record, which
  holds for sources installed after migration 0021. For a source installed earlier with no success on record,
  the field is **omitted**, and the UI already shows that as Unknown. Its earlier successes may have been
  pruned before the record began, so "Never checked" would be a guess. The first success fills it in.
- It is kept in a durable summary, so it survives the 7-day pruning of health signals, and a failure never
  clears it.
- Event `source.health` `{source_id}` fires when a source's outcome changes, and otherwise at most once a
  minute per source. Re-read the list when it arrives.

**BE-002 metadata.** Fixed in phase 2 (I-92, PR #5). Search, URL entry and opening a result now apply
Master §9.2 (source value > plugin default > Unknown), so 3asq shows "Manga · Arabic". Existing rows such as
production's Berserk are fixed by the owner running the reclassification preview and apply (H-3). Unknown
remains a valid state when neither the source nor the plugin says anything (MangaDex "Oneshot").
