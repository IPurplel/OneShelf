# OneShelf API

The HTTP surface as it exists today (107 routes), with the auth boundary and the event stream.
Authority: Master §40; written from the routers in `backend/oneshelf/api/`.

## Conventions

- JSON in, JSON out. Errors are `{"error": {"code": "UPPER_SNAKE", "message": "a sentence for a person"}}`
  with a meaningful status: 401 unauthenticated, 403 refused, 404 unknown, 409 conflicting state,
  422 rejected input, 429 rate limited by a source, 502 the source failed. `SOURCE_FAILED` adds `"category"`
  (the engine's reason) beside the sentence, never inside it.
- `GET /api/works/{id}` units carry `download_state` (`queued` | `downloading` | `failed` | null, from the unit's
  latest job) and `size_bytes` (its files on this device, or null). `GET /api/home` Continue Reading items and a
  `continue_reading` hero carry a work-level `fraction` and `next_unit_id`.
- `GET /api/downloads` batches carry `label`, `created_at`, `total`, `works` (up to 3 `{work_id, title}`) and
  `works_total`; finished jobs in a batch's detail carry `storage_root_name`.
- `GET /api/follows` rows carry `source_name`; a follow never checked yet reads `checking`, not `degraded`, and is
  first checked within minutes. `GET /api/stats` counts the shelf and the files present on this device.
- A `download-failed:<unit>` notification is titled "<chapter> · <work>", its summary is a sentence, its payload is
  `{reading_unit_id, unit_id, work_id, track_id, source_id, category}`, and it resolves when that unit downloads.
- `DELETE /api/units/{unit}/files` and `DELETE /api/works/{work}/files` answer `{deleted_files, freed_bytes}`;
  `POST /api/shelf/batch` accepts `delete_files`; `GET /api/shelf?view=downloaded` lists works with files here.
- Every state-changing request must be same-origin (`Origin` / `Sec-Fetch-Site`), and every request's `Host`
  must be allowlisted. Both are enforced before routing.
- Remote clients need the `oneshelf_remote` session cookie; loopback and genuine LAN clients do not.
  Only `POST /api/auth/sign-in/options` and `POST /api/auth/sign-in` are reachable remotely without it.
- Times are ISO-8601 UTC. Identifiers are opaque strings.

## Health and events

| Route | Purpose |
|---|---|
| `GET /api/health` | Liveness: status, schema version, how this client was classified. |
| `GET /api/ready` | Readiness: migrations applied, startup recovery finished, storage locations seen. Used by the container healthcheck. |
| `GET /api/events` | Server-sent events. One stream for progress and domain changes: downloads, catalogue refreshes, shelf, follows, notifications, health. Clients render from these rather than polling. |

## Sources and sessions (§9–13)

| Route | Purpose |
|---|---|
| `GET /api/sources` | Installed sources, versions, state, capabilities, permissions. |
| `POST /api/sources/uploads` · `POST /api/sources/install` | Upload an `.osp`, review it, then install with approved permissions. |
| `POST /api/sources/{id}/approve` · `/disable` · `/enable` · `/rollback` · `DELETE /api/sources/{id}` | Lifecycle, including rollback to the previous version. |
| `GET|DELETE /api/sources/{id}/session` · `POST /api/sources/{id}/session/validate` | Source session state, disconnect, re-check. |
| `POST /api/sources/{id}/login` · `GET /api/logins/{id}/frame` · `POST /api/logins/{id}/{input,complete}` · `DELETE /api/logins/{id}` | Use My Session: a screencast login in a Core-owned browser. Raw passwords are never stored. |
| `GET /api/sources/{id}/health` · `GET /api/sources/{id}/health/state` | Capability health signals and the current state with hysteresis. |
| `GET /api/registry[?refresh=true&category=Manga&language=AR]` | The Registry set against the library: per plugin `version`, `category` (nullable), `languages` (ordered codes or `Multi`), `trust_label` (claimed), `signed` (a trusted signature verified), `trust_basis` (`signature` | `first_party` | `none`), `effective_trust`, `api`, `state` (`installed`, `available`, `update_available`, `pending_review`, `installed_newer`, `incompatible`), `installed_version`, `plugin_state`, `channel`, `installed_trust`. Repeat `category` or `language` to select several values; `Multi` matches any language. `{"configured": false}` when none is set; **502 `REGISTRY_UNAVAILABLE`** when it cannot be read. Reading changes nothing. |
| `POST /api/registry/review-package` `{plugin_id, version?}` | Downloads, hash-checks, validates and packaged-tests the package without installing it: `permissions`, `added_permissions`, `tests_passed`, `test_failures`, `effective_trust`, `sha256`, `state`. 422 `REVIEW_REJECTED` (bad hash or signature, requires a newer OneShelf, invalid package). |
| `POST /api/registry/install` `{plugin_id, version?, approved_permissions, sha256?}` | Installs or updates through the normal pipeline; with `sha256` (from the review) it is refused unless the package is still exactly those bytes. Approves a version already waiting for review when its stored bytes match. The plugin becomes `channel = registry`. |

## Discovery, identity and catalogues (§5–8)

| Route | Purpose |
|---|---|
| `GET /api/search?q=…[&category=Manga&language=AR]` | Local-first search as SSE: `local` → `partial` → `complete`. Repeat either scope parameter to select several values. Only matching installed searchable sources run; an adapter with no category matches only unscoped category searches, while `Multi` matches any language. Updates include scoped `sources_total` and unscoped `sources_available`. Never blocks on a slow source. |
| `POST /api/search/retry` `{query, source_id, categories?, languages?}` · `POST /api/resolve-url` · `GET /api/home` | Retry one source within the same scope, open a source URL directly, the Home surface. |
| `POST /api/listings/bind` | Bind a source listing to a Work (creating one when needed). |
| `GET /api/tracks/{id}/catalog` · `POST /api/tracks/{id}/catalog/refresh` · `/trust` | Catalogue state, a refresh, and "Trust This Catalog" for a suspicious one. |
| `POST /api/mappings/{merge,split,unlink,never-match}` | Durable user decisions about identity; they always win over source refreshes. |
| `GET /api/discover/sources` | Sources that can be browsed, with the lists each offers (`latest`, `trending`). See ADR 0004. |
| `GET /api/discover/list?source=…&kind=latest\|trending&page=1..50` | One page of a source's own list, grouped into Works like search results, each with `on_shelf`. Returns `has_more` and `cached`. `422 INVALID_FEED`, `404 SOURCE_UNAVAILABLE`, `429 RATE_LIMITED`, `502 SOURCE_FAILED` (with `category`). |
| `GET /api/discover/random?from=sources[&source=…]` · `?from=library[&content_type=…]` | A surprise: a work from a source's list that is not on the shelf (`reason`: source and list), or a shelf work not started yet (`reason.kind = not_started`). `{"item": null, "reason": null}` when there is none. |

## Downloads and reading (§16–19, §26–27)

| Route | Purpose |
|---|---|
| `POST /api/downloads` · `GET /api/downloads[/{batch}]` | Queue a batch, watch batches and jobs. |
| `POST /api/downloads/{batch}/{pause,resume,retry-failed,cancel}` · `/reorder` · `POST /api/downloads/jobs/{job}/{retry,cancel}` | Control durable jobs. |
| `DELETE /api/downloads/history` | Clear history only; content and progress are untouched. |
| `GET /api/reader/units/{id}/pages` · `/pages/{index}` | Page list and page bytes, served with `Content-Security-Policy: sandbox`, `nosniff`, `no-store`. |
| `POST /api/reader/units/{id}/progress` · `/mark-read` · `/mark-unread` · `/engagement` · `POST /api/reader/works/{id}/leave` | Progress with a monotonic revision (stale tabs cannot rewind it), explicit read state, engagement for auto-download, and leaving a work. |

## Shelf, follow and attention (§20–23, §30, §44)

| Route | Purpose |
|---|---|
| `GET /api/shelf` | Views (all, saved, reading, completed, favourites), local-only search. |
| `POST /api/shelf/{work}` · `GET /api/shelf/{work}/removal-summary` · `DELETE /api/shelf/{work}` · `DELETE /api/works/{work}/files` | Save, see exactly what removal would do, remove, delete files — each independent. |
| `GET /api/follows` · `POST /api/follows/{work}` · `/check` · `/preferred-source` · `POST /api/follows/check-all` · `POST /api/follows/undo` · `DELETE /api/follows/{work}` | Follow with baselines, manual checks, preferred source changes, immediate unfollow with undo. |
| `GET /api/notifications[?attention=true]` · `POST /api/notifications/{mark-all-seen,clear-seen,cleanup}` | In-app notifications and Needs Attention. Seen state never changes reading state. |

## Storage, import, backup, restore, export (§24–25, §33–34, §37–38)

| Route | Purpose |
|---|---|
| `GET /api/storage` · `POST /api/storage/roots` · `/{root}/default` · `/{root}/remap` · `/{root}/migrate` · `POST /api/storage/migrations/{id}/discard-old-copy` · `POST /api/storage/scan` | Locations with space and reserve, resumable migration, mount remap, reconciliation. Old storage is never deleted automatically. |
| `POST /api/import/uploads?filename=` · `POST /api/import` | Review an upload (format, pages, association suggestions), then import by Copy or Move. |
| `GET|POST /api/backups` · `POST /api/backups/verify` | Library and Full backups, retention, due state, same-disk warning. |
| `POST /api/restore/preflight` · `POST /api/restore` | Compatibility, plugins and permissions first; then Merge or Replace with a Safety Snapshot. |
| `POST /api/export/preview` · `POST /api/export` · `GET /api/export/{job}` · `POST /api/export/{job}/retry-failed` · `DELETE /api/export/history` | A resumable one-way copy of one or several works; history cleanup never deletes exported files. |

## Remote access and first run (§28–29)

| Route | Purpose |
|---|---|
| `GET /api/auth/state` | Passkeys, sessions, recovery state, trusted networks, the single-gateway warning. |
| `POST /api/auth/hostname` · `POST /api/auth/networks` | The canonical HTTPS hostname and the trusted network configuration. |
| `POST /api/auth/passkeys/register/options` · `/register` · `DELETE /api/auth/passkeys/{id}` | Registration needs LAN, a Recovery Code or an existing session. The first passkey returns the Recovery Code once. |
| `POST /api/auth/sign-in/options` · `/sign-in` · `/sign-out` | The passkey ceremony; the session token only ever travels in an HttpOnly cookie. |
| `GET /api/auth/sessions` · `DELETE /api/auth/sessions/{id}` · `POST /api/auth/sessions/revoke-others` | Session list with labels and activity, revoke one or all others. |
| `POST /api/auth/recovery/regenerate` · `POST /api/auth/lan-recovery` | A new code invalidates the old one; LAN Recovery clears remote auth only and says so. |
| `GET /api/first-run` · `POST /api/first-run/{storage,access-mode,finish}` | The short setup flow. Nothing else is gated on it. |

## Adapter generator (§12)

| Route | Purpose |
|---|---|
| `POST /api/generator/drafts` · `GET /api/generator/drafts[/{id}]` | Discover a site from a URL; the preview carries recipes, per-capability confidence, the permissions an install would ask for, the domains rejected as ads or analytics, and every fetch discovery made. |
| `POST /api/generator/drafts/{id}/test` | Run the draft's packaged tests offline against the captured pages. |
| `POST /api/generator/drafts/{id}/generate` · `/install` | Generate writes a validated `.osp` and reports `installed: false`; installing is a separate call with its own permission approval. |
| `POST /api/generator/drafts/{id}/submission` | Write a submission bundle to disk. Nothing is published. |
| `POST /api/generator/repair/{plugin_id}/diagnose` · `/repair/{plugin_id}` · `/repair/{plugin_id}/activate` | Diagnose the installed adapter, produce a validated new version with a selector diff, then activate it explicitly. |
| `POST /api/generator/test-source/markup` | Development only: switch the bundled Test Source's markup to exercise repair. 404 unless the Test Source is enabled. |

## Events

`GET /api/events` emits named events with JSON payloads. Every client sees the same stream, so two browser tabs
stay consistent: download and job progress, catalogue refresh outcomes, shelf and follow changes, notification
create and resolve, source health transitions, and import, backup and export activity.
