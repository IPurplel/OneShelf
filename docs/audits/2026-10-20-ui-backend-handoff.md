# UI repair API handoff to Claude Code — 2026-10-20

This is the frontend contract requested for the approved UI-003 and UI-004 repairs. Codex changed no backend, database, adapter, download-engine, or Reader-engine files. Fixture coverage is distinct from a real backend integration pass.

## BE-003 / UI-003: download batch detail

**Existing route:** `GET /api/downloads/{batch_id}`. Keep the current batch summary and ordered `jobs` array. The frontend opens this route only when the user expands one batch, and refreshes only an open batch after `download.batch` or `download.job`. A closed Downloads page requests only `GET /api/downloads`.

Each job currently supplies `id`, `reading_unit_id`, uppercase `state`, `method`, `attempts`, `error_category`, `last_error`, `queue_position`, and `bytes_done`. Add these presentation fields to each job without altering queue semantics:

| Field | Type and meaning |
| --- | --- |
| `work_id` | Stable Work ID or null if no Work can be resolved. |
| `work_title` | User-facing Work title or null; never a raw ID presented as a title. |
| `track_id` | Source Track for the job, if known; preserves source identity in Reader links. |
| `unit_title` | User-facing reading-unit title or null. |
| `available` | Boolean: true only when the completed unit's content is currently openable; false for missing/offline/uncommitted content. |
| `bytes_total` | Nonnegative integer or null when size is unknown. `bytes_done` remains the authoritative transferred count. |

`COMPLETED` with `available: true` exposes the Reader route `/read/{reading_unit_id}?work={work_id}&track={track_id}`. `COMPLETED` with `available: false`, `FAILED`, `CANCELED`, and queued states do not claim the unit can be opened. A missing `available` field is accepted for compatibility with the current API, but the frontend cannot certify that a historical completed asset still exists from the old payload alone. The Reader route itself remains the final authority for a valid open. Failed jobs should provide a stable error category and a safe user-facing message; avoid leaking credentials or private URLs through `last_error`.

The batch summary currently counts skipped selections but its `jobs` array excludes them. For per-unit skipped details, add an ordered `skipped_units` array with `{ reading_unit_id, unit_title, reason }`, or document a bounded equivalent. Until supplied, the frontend shows the honest aggregate skipped count and explains that those selections never entered the queue. Define pagination or a maximum response size for very large batches before considering the detail route fully bounded.

**Errors:** Preserve typed 404 for an unknown batch and retryable 5xx for temporary failure. Do not return a partial success payload as if detail were complete. **Acceptance:** The frontend can show real titles, current availability, active progress, failed/canceled/skipped states, and a completed unit opens the same Work/Reader context the batch refers to. Validate this against an isolated backend fixture with real committed assets. The current UI's enriched-job tests are contract fixtures; they are not backend integration evidence.

## BE-001 / UI-004: aggregate source last success

**Route:** `GET /api/sources`. Add `last_successful_check_at` to every source object as an ISO-8601 UTC timestamp or `null`. Define it as the most recent **successful overall source health check across capabilities**, sourced from actual check/health evidence. Do not use install time, registration time, plugin version, latest attempt, or a follow check that did not succeed. `null` means the source has never had a successful check. An omitted field means an older API, so the frontend displays **Unknown**, not “Never checked.” Invalid timestamps also display Unknown.

The frontend formats the timestamp in the selected English/Arabic locale and displays it alongside source status. It performs one aggregate list request; it does not fetch `/api/sources/{id}/health` for every row. When source health changes, publish an SSE `source.health` event with at least `{ source_id }`; the frontend re-reads the aggregate list and never trusts an event timestamp as source of truth. Existing `source.session` behavior remains.

**Errors:** A failed list request retains the normal screen error/retry flow. The optional field must not turn a transient health-check failure into a fabricated success time. **Acceptance:** A success followed by a failed check still shows the last successful time; a never-checked source returns null; English/Arabic views render both states; list load remains one API request regardless of source count; the `source.health` event refreshes the visible value. The current frontend fixture verifies this contract, while live integration is **BLOCKED** until the backend publishes the field and event.

## BE-002 metadata investigation

The audit observed one Work with `content_type: unknown` and track language `und` while its source advertised concrete category/language. Unknown remains a valid product state. Claude should compare classification precedence and available evidence before changing metadata; no UI defect or frontend workaround is assigned.
