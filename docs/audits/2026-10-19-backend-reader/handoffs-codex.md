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

## H-3, H-4, H-5, H-7, H-8, H-9

Written when their work packages land (Phases 2–4); see `implementation-log.md`.
