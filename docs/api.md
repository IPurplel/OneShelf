# OneShelf API

The HTTP surface as it exists today (107 routes), with the auth boundary and the event stream.
Authority: Master §40; written from the routers in `backend/oneshelf/api/`.

## Conventions

- JSON in, JSON out. Errors are `{"error": {"code": "UPPER_SNAKE", "message": "a sentence for a person"}}`
  with a meaningful status: 401 unauthenticated, 403 refused, 404 unknown, 409 conflicting state,
  422 rejected input, 429 rate limited by a source, 502 the source failed.
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
| `GET /api/registry` · `POST /api/registry/install` | Optional registry index; nothing is contacted unless a registry URL is configured. |

## Discovery, identity and catalogues (§5–8)

| Route | Purpose |
|---|---|
| `GET /api/search` | Local-first search as SSE: `local` → `partial` → `complete`. Never blocks on a slow source. |
| `POST /api/search/retry` · `POST /api/resolve-url` · `GET /api/home` | Retry one source, open a source URL directly, the Home surface. |
| `POST /api/listings/bind` | Bind a source listing to a Work (creating one when needed). |
| `GET /api/tracks/{id}/catalog` · `POST /api/tracks/{id}/catalog/refresh` · `/trust` | Catalogue state, a refresh, and "Trust This Catalog" for a suspicious one. |
| `POST /api/mappings/{merge,split,unlink,never-match}` | Durable user decisions about identity; they always win over source refreshes. |

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
