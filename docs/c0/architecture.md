# C0 — Implementation Architecture Baseline

Recorded: 2026-09-17 · Authority: Meta Prompt §C0.7, Master §52 · Stack: UD-1
Status: **design baseline, not implemented.** Exact dependency versions are chosen in C1 from current official docs (EB-4). Nothing is installed.

## 1. Shape

A single-user, self-hosted **modular monolith**:

- **Backend:** one Python ASGI process (FastAPI/Starlette candidates). In-process asyncio schedulers/workers; Playwright Chromium subprocesses managed by Core; a Core-owned local egress proxy for browser traffic (K2).
- **Frontend:** a React + TypeScript + Vite SPA served by the backend, with ar/en i18n and RTL/LTR.
- **State:** SQLite as the source of truth (WAL). Managed files live on Storage Roots.
- **Realtime:** Server-Sent Events, with a polling fallback (§36).
- **Deployment:** Docker image with separate mounts for app data, session key, library roots and backups (§2.1, §13, §33.9).
- **No cloud services** and no OneShelf account (§2.1–2.2).

## 2. Subsystem boundaries (Master §52)

```
backend/oneshelf/
  api/            HTTP routes, request/response schemas, SSE endpoint,
                  access classifier (loopback / trusted LAN / remote), auth middleware,
                  Origin + CSRF enforcement for remote state-changing calls
  services/       application services: orchestrate domain + infrastructure; no source-specific logic
  domain/         entities/value objects and invariants (Work, SourceListing, SourceTrack,
                  LocalSourceTrack, ReadingUnit, Asset, ExtractionContract, Unknown-aware metadata)
  settings/       single defaults registry (§42, D2) + scoped settings precedence
  db/             connections (WAL, busy timeout, serialized writer), migrations, repositories, snapshots
  storage/        storage roots, safe naming/paths, per-root staging, commit journal,
                  disk-space guard, scanner/reconciliation, root migration
  net/            egress policy (allowlist, redirect + DNS revalidation, private-target blocking),
                  HTTP client, browser manager + egress proxy, Source Traffic Governor
  plugins/        .osp schema + validator, safe-transform library (bounded), recipe runtime,
                  lifecycle (install/update/disable/uninstall/rollback), registry client (A1)
  sessions/       encrypted source session store, per-source isolated contexts, validate/reconnect
  catalog/        catalog fetch orchestration, completeness evidence, snapshots, trust/suspicion
  search/         normalization (Arabic, loose ة↔ه, no stemming), FTS5 index, ranking tiers,
                  grouping (Soft Group) vs mapping (Hard Mapping, overrides), discovery cache, URL resolution
  downloads/      batches, per-unit jobs, state machine, windowed scheduler, workers, retry/backoff,
                  resume manifests, integrity validation, packaging (CBZ/ComicInfo), extraction policy
  reader/         online fetch path, Reader Cache, progress (revisioned), bookmarks/highlights,
                  auto-download-while-reading trigger, content isolation endpoints
  follow/         follow bindings, baselines, release detection, schedule
  health/         passive signals, thresholds/hysteresis, low-priority active checks
  notifications/  logical dedupe, grouping, Seen/Unseen, persistent/transient, retention; Needs Attention view
  backup/         Library/Full backup, .osbackup format, verification, rotation, restore preflight/merge/replace
  export/         export contracts, persistent jobs, conflicts, checksums
  importer/       CBZ/PDF/EPUB import (Copy default / Move), association
  events/         in-process event bus → SSE fan-out
  auth/           passkeys (WebAuthn), recovery code verifier, remote UI sessions, LAN recovery
  diagnostics/    bounded rotating operational diagnostics with write-time redaction
  generator/      Scrapling-based discovery → .osp draft → review/test/validate → local install; repair
frontend/         app shell, screens, components, readers (sequential, EPUB, PDF), i18n, SSE client
test_source/      OneShelf Test Source: deterministic fault server (dev-only network exception)
plugins/official/ declarative .osp packages for the §41 suite
deploy/           Dockerfile, compose example, entrypoint/readiness
docs/             architecture, API/events, plugin + generator format, ops, evidence ledgers
tests/            unit, integration, contract, migration, crash/recovery, security, e2e
```

**Boundary rules**
- Source-specific logic lives only in `.osp` recipes (and rare reviewed native adapters, §9.6). `downloads/`, `storage/`, `db/` and `services/` stay generic (§52).
- Recipes return typed metadata and resource descriptors. They never touch HTTP clients, the DB, paths or credentials (Meta Prompt G4).
- Only `net/` performs outbound requests. Only `storage/` builds filesystem paths. Only `sessions/` decrypts session material, and only to attach it inside `net/` for scoped domains/capabilities.
- `diagnostics/` redacts at write time; cookies, tokens, auth headers and sensitive bodies are never persisted (§43).

## 3. Persistent state

| Store | Class | Contents | Backup |
|---|---|---|---|
| `oneshelf.db` | Authoritative | Works, aliases/title history, source listings, source tracks (incl. local), reading units, assets (`storage_root_id` + relative path, size, checksum, integrity), user overrides and mappings (Merge/Split/Unlink/Never Match), classification overrides, catalog snapshots (current/previous trusted + bounded candidates with completeness/suspicion), release events, Shelf entries (Saved/Favorite/Pin/Completed), Follow bindings + baselines, reading progress (revisioned) and read state, bookmarks/highlights, reader settings (per Work), batches/jobs/manifests/checkpoints, commit journal, extraction contracts + method preferences, plugins/versions/permissions/provenance, health signals, notifications, download history, export jobs/activity, import records, backup records, storage roots, settings, remote auth (passkey credentials, recovery code verifier, remote UI sessions) | Library/Full backup via consistent snapshot, **excluding** remote UI sessions, recovery verifier and staging/job transient rows (§33.3) |
| `cache.db` | Rebuildable | Discovery cache (namespaced by source + plugin version/schema), Reader Cache index | Never backed up |
| Reader Cache blobs | Rebuildable | Temporary online-reading resources (TTL 7 d, 5 GB, LRU with protections) | Never |
| `secrets.db` | Protected | Encrypted per-source session state (cookies, localStorage, IndexedDB, sessionStorage handling) | Never |
| Session key file | Protected, **separate mount** | Session master key | Never |
| Storage roots | Content | `<root>/<family>/<Work>/<Language>/<Source>/files`, `<root>/.oneshelf/staging/` | Full Backup: selected content only |
| Plugin store | Persistent | Installed `.osp` versions (active + rollback) | Names/versions only (§10) |
| Diagnostics | Bounded | Rotating files, 7 d / 100 MB | Never |

Identity rules: stable internal IDs for every entity; display, raw and search text are separate columns; numbers never form Reading Unit identity (C10); checksums and covers never form Work identity (§38, INV-28); absolute host paths are never identity (§24.1).

## 4. State machines (documented before C1 persistence work; each gets transition tests)

1. **Catalog snapshot:** `FETCHING → INCOMPLETE` (terminal; never trusted) | `FETCHING → COMPLETE → {TRUSTED | SUSPICIOUS}`. `SUSPICIOUS → TRUSTED` only via two consecutive complete matching checks or explicit Trust This Catalog. Keep current + previous trusted; bounded candidates (§5).
2. **Download job (per Reading Unit):** `QUEUED → PREPARING → DOWNLOADING → VERIFYING → PACKAGING → COMMITTING → COMPLETED`, with `PAUSED`, `WAITING_FOR_SESSION`, `WAITING_FOR_RATE_LIMIT`, `RETRY_WAIT`, `FAILED`, `CANCELED`, `RECOVERING` (§16). Server-side-validated control transitions (pause/resume/cancel/retry/reorder).
3. **Batch aggregate:** derived: Active / Paused / Completed / Completed with Issues / Failed (§16.1).
4. **Commit journal:** `PENDING → MOVED → VERIFIED → REGISTERED → DONE`; idempotent replay from any state at startup (§17).
5. **Startup sequence:** recover jobs → recover commits → reconcile (only available roots) → clean proven-orphan staging (§17, §25).
6. **Plugin install/update:** `STAGED → HASH/SIG_VERIFIED → MANIFEST_VALID → COMPATIBLE → RECIPES_VALID → STATIC_CHECKED → TESTS_PASSED → [PERMISSION_REVIEW] → ACTIVE`; failure at any step leaves the previous version active; rollback supported (§10).
7. **Source session:** `NOT_CONNECTED ↔ CHECKING ↔ CONNECTED ↔ NEEDS_RECONNECT`; reconnect replaces atomically; disconnect deletes immediately (§13).
8. **Capability health:** per capability, Healthy / Degraded / Unavailable / Rate Limited / Reconnect Required / Catalog Suspicious, with thresholds + hysteresis and trusted-success recovery (§21).
9. **Extraction attempt:** preferred method → Smart Retry (same method) → per mode: Ask / Strict (stop) / Automatic Fallback (user order), never on auth/CAPTCHA/rate-limit/outage; a method switch restarts the unit in fresh staging (§14).
10. **Notification:** `ACTIVE(unseen|seen) → RESOLVED (~1 h visible) → EXPIRED`, keyed by logical dedupe key; retention 30 d / 500 (§30).
11. **Storage root:** `AVAILABLE | LOW (warning ~2× reserve) | AT_RESERVE (pause background writes) | UNAVAILABLE | MIGRATING` (§24).
12. **Root migration:** `PREFLIGHT → PAUSE_WRITES → COPYING → VERIFYING → SWITCHED → RECONCILED → AWAIT_OLD_COPY_DECISION` (resumable; §24.8).
13. **Backup:** `CREATING → VERIFYING → VERIFIED → ROTATED` | `FAILED` (never rotates on failure; §33.8).
14. **Restore:** `PREFLIGHT → STAGED_MIGRATION → REVIEW (plugins/permissions) → {REPLACE (after Safety Snapshot) | MERGE} → RECONCILE → DONE` (§33).
15. **Export job:** `PREFLIGHT → [MISSING_CONTENT_DECISION] → [DOWNLOADING via normal engine] → COPYING → VERIFYING → COMPLETED | COMPLETED_WITH_ISSUES`; resumable (§34).
16. **Remote UI session:** `ACTIVE → EXPIRED | REVOKED`; recovery-code regeneration invalidates the old code; LAN recovery resets passkeys + sessions only (§28).
17. **Follow:** `BASELINE_PENDING → BASELINED → CHECKING → {UP_TO_DATE | NEW_RELEASES}`; source change creates a Source Change Baseline (§20).
18. **Reading progress write:** revisioned compare-and-set; stale revision rejected unless it's explicit Mark Unread / reread intent (§26.23).

## 5. Migration strategy

- Numbered, forward-only schema migrations; each runs in a transaction and records `schema_version`.
- Before migrating, take a consistent snapshot with the SQLite online backup API (never a raw file copy of a live DB; §18). Keep it for recovery.
- The app refuses to open a database or backup whose schema is newer than it supports (§33.5).
- Migration tests run from a fixture of every released schema version and include interrupted-migration recovery.
- Backups older than the running version migrate forward in a staging copy; the original backup file is never modified.
- Data-shape changes that could lose information need an explicit reversible path or a preserved snapshot (Meta Prompt D3).

## 6. Security architecture summary (§48)

| Boundary | Mechanism |
|---|---|
| Inbound UI trust | Access classifier from the real peer address; forwarded headers only from configured trusted proxies; trusted networks per A2; remote requires passkey session; HttpOnly/Secure/SameSite cookies; Origin + CSRF on remote state changes; no tokens in Web Storage |
| Outbound source traffic | Declared domain allowlist (source + CDN), per-hop redirect and DNS revalidation with IP pinning, private/loopback/link-local blocking, same policy for browser via egress proxy (K2); Test Source exception dev-only |
| Plugins | Declarative only; schema + static checks; bounded transforms/regex with resource limits; no paths, no code, no raw secrets; trust labels don't widen access |
| Sessions | Encrypted at rest, key on a separate mount, scoped per source/capability/domain, never logged/backed up/exported |
| Filesystem | Core-generated names; traversal/absolute/symlink-escape blocking; deletes only inside managed roots |
| Documents | Sandboxed opaque-origin rendering + CSP; pdf.js scripting disabled (K3) |
| Diagnostics | Write-time redaction; bounded retention; no matcher-decision telemetry |

## 7. Dependency order

```
C0 ──► C1 foundation ──┬─► C2 UI shell + local readers ─────────────┐
                       └─► C3 plugin runtime, sessions, SSRF, governor ─► C4 catalog/search/mapping ─► C5 downloads/online reader ─► C6 shelf/follow/health/notifications
                                                                                                         │
C1 + C3 + C5 ─► C7 storage mgmt/import/backup/export      C1 + C2 + K4 ─► C8 remote auth/first run      │
all ─► C9 generator, §41 suite, Docker, full verification ◄──────────────────────────────────────────────┘
```

Built earlier than their nominal phase (K4, K5): access classifier + deny-unauthenticated-remote (C1), defaults registry (C1), minimal SSE bus (C1/C2), OneShelf Test Source skeleton (C1/C3), foundation source slices Gutenberg / Hindawi / arXiv (C3/C4).

Each phase's gate is defined in Meta Prompt §C1–C9; no phase is claimed complete until its gate passes (CLAUDE.md).

## 8. Candidate dependencies (to be verified against official docs in C1; not selected yet)

Backend: ASGI framework (FastAPI or Starlette) + uvicorn; stdlib `sqlite3`; HTTP client supporting custom resolution/connection pinning (httpx or aiohttp); Scrapling (non-stealth APIs only, K1); Playwright (Chromium); `cryptography`; a WebAuthn server library; Pillow; a PDF parser for validation; stdlib `zipfile`/XML parsing hardened against XML attacks (defusedxml); YAML safe loader + JSON Schema validator for `.osp`; a linear-time or timeout-bounded regex engine; pytest (+ property testing).
Frontend: React, React Router, TypeScript, Vite, pdf.js, a sandbox-compatible EPUB renderer, an i18n library with RTL support, Vitest, Playwright.
