# OneShelf — Backend Audit Report

**Date:** 2026-10-24  
**Scope:** All core backend Python modules (~140 files, 30 packages under `backend/oneshelf/`)  
**Branch:** main @ `65178f7`

---

## Methodology

Four parallel audits covering every core module: API/auth/sessions, DB/storage/backup, network/plugins/sources, and services/workers/search. Full file reads with focus on security, correctness, performance, and code quality. Pattern scanning for SQL injection, bare exceptions, path traversal, secret handling, CORS, and resource management.

---

## Architecture Strengths

The backend demonstrates strong security-by-design across every layer:

| Area | Design | Assessment |
|---|---|---|
| Path safety | `resolve_within()` checks symlinks + traversal at every FS boundary | Excellent |
| Session encryption | AES-256-GCM with source-id AAD binding, separate key file, `secure_delete` | Excellent |
| Token storage | SHA-256 hash only, raw token never persisted | Excellent |
| Recovery codes | scrypt KDF with random salt, `hmac.compare_digest` | Excellent |
| WebAuthn | Single-use challenges, 5-min TTL, authorization required for registration | Excellent |
| CSRF | `Sec-Fetch-Site` + Origin check in `RequestGuardMiddleware` | Excellent |
| DNS rebinding | Host allowlist; IP literals always allowed; configured names checked | Excellent |
| Egress policy | Per-plugin domain allowlists, IP literal blocking, DNS rebinding prevention, private address validation | Excellent |
| Reader content | Sandbox CSP, nosniff, same-origin resource policy | Excellent |
| Plugin sandbox | RE2 regex (no ReDoS), restricted YAML, bounded transforms, package validation | Excellent |
| SQL | Parameterized queries (?) used for all user-supplied values | Good (see BKD-003) |
| CORS | None configured = same-origin only | Correct |
| DB safety | WAL, `synchronous=FULL`, foreign keys ON, `BEGIN IMMEDIATE` for writes | Excellent |
| Backup | SQLite online backup API, never raw file copy of live DB | Excellent |
| Commit journal | Crash-safe FSM with idempotent replay, per-step persistence | Excellent |
| HTML sanitisation | Double sanitisation (source runtime + nh3), allowlist approach | Excellent |
| Traffic governor | Priority-based leasing with fairness, background preemption, per-source rate limits | Excellent |

---

## Issues Found

### High Severity

#### BKD-001 — SearchService.search() mutates instance state (Thread Safety)

**File:** `search/service.py:249`  
**Risk:** Incorrect result counts for concurrent searches

`self.limit = limit` writes to instance state during a search. If two concurrent searches (e.g., two browser tabs) set different limits, they interfere with each other. The limit affects result trimming downstream.

**Fix:** Pass `limit` as a parameter through the search pipeline instead of storing it on `self`.  
**Effort:** Medium

---

#### BKD-002 — EventBus._deliver() TOCTOU race condition

**File:** `events/bus.py`  
**Risk:** Lost SSE events or exceptions in the publish path

`_deliver()` checks `qsize()` then calls `put_nowait()` without holding the subscriber lock. Two concurrent publishes could both pass the size check and one fail with `Full`, losing the event.

**Fix:** Hold the subscriber lock around the check-and-put, or catch `Full` in `put_nowait()` and handle gracefully (the resync-and-drop logic is already there).  
**Effort:** Low

---

### Medium Severity

#### BKD-003 — No rate limiting on authentication endpoints

**File:** `api/auth.py`  
**Risk:** Challenge exhaustion, brute-force enumeration, `lan-recovery` abuse

Endpoints affected:
- `POST /api/auth/sign-in/options` — generates WebAuthn challenges without limit
- `POST /api/auth/sign-in` — verifies authentication without limit
- `POST /api/auth/passkeys/register/options` — generates registration challenges
- `POST /api/auth/lan-recovery` — resets all remote auth from LAN

An attacker on the LAN could flood challenge generation or repeatedly call `lan-recovery` to disrupt remote access.

**Fix:** Per-IP rate limiter: 10 req/min on sign-in, 5 req/min on `lan-recovery`.  
**Effort:** Small

---

#### BKD-004 — N+1 query patterns in API endpoints

**Files:** `api/library.py:168-170`, `api/works.py:56-59`, `api/library.py:204-219`  
**Risk:** Performance degradation with large libraries

| Endpoint | Pattern | Impact |
|---|---|---|
| `list_batches` | Fetches batch IDs then calls `s.downloads.batch(id)` per row | 200+ queries for limit=200 |
| `work_units` | Per-unit `SELECT assets WHERE reading_unit_id = ?` | 500+ queries for long manga |
| `batch_detail` | Per-job `_job_available_format` + `_bytes_total` queries | 1500+ queries for large batch |

**Fix:** Use JOINs or `WHERE id IN (...)` batch queries.  
**Effort:** Medium

---

#### BKD-005 — migrate.py snapshot() leaks connection on error

**File:** `db/migrate.py:78-83`  
**Risk:** SQLite file handle leak if `conn.backup(target)` raises

The target connection opens inside `with` but `target.close()` is outside. If `backup()` raises, the handle leaks.

**Fix:** Use `try/finally` or `contextlib.closing()` to ensure the target connection closes.  
**Effort:** Low

---

#### BKD-006 — roots.py marker written before DB insert

**File:** `storage/roots.py:98-121`  
**Risk:** Orphan `.oneshelf/root.json` marker blocks retry

`register_root()` writes the marker file to disk *before* inserting the DB row. If the insert fails (constraint violation), the marker remains with no DB record. A retry then fails with "directory is already a OneShelf storage location". Recovery requires manual marker deletion.

**Fix:** Insert DB row first, write marker after, rollback on marker write failure.  
**Effort:** Low

---

#### BKD-007 — scanner.py `os.path.relpath()` uses `\` on Windows

**File:** `storage/scanner.py:31`  
**Risk:** File relocation completely broken on Windows

`_untracked_files()` uses `os.path.relpath()` which produces `\` separators on Windows. The rest of the system uses POSIX `/` separators. Untracked files would never match tracked paths, breaking reconciliation.

**Fix:** Replace `os.path.relpath()` with `PurePosixPath` or normalize with `.replace("\\", "/")`.  
**Effort:** Low

---

#### BKD-008 — FollowService._undo dict is unbounded

**File:** `follow/service.py`  
**Risk:** Slow memory leak over time

The `_undo` dictionary stores undo state for every unfollow. No cleanup, TTL, or size cap. Each unfollow adds an entry that persists until restart.

**Fix:** Use `OrderedDict` with max size (e.g., 100), evicting oldest entries.  
**Effort:** Low

---

#### BKD-009 — Restore service holds write lock for entire merge

**File:** `restore/service.py:197-331`  
**Risk:** All API requests block during restore

The entire merge runs in a single transaction. For a large library (thousands of works), this holds the SQLite write lock for potentially minutes. All other API requests block or timeout.

**Fix:** Break into batched transactions or accept the limitation with a progress indicator and "maintenance mode" response.  
**Effort:** Medium

---

#### BKD-010 — CBZ validation loads every page into memory

**File:** `integrity/validators.py:165`  
**Risk:** Memory spike during large CBZ validation

`z.read(info)` loads entire image files for every page. A 200-page CBZ with 5MB pages = ~1GB sequential memory allocations. No streaming or per-image size cap beyond archive-level `MAX_ENTRY_BYTES` (256MB).

**Fix:** Add per-image size cap (e.g., 20MB) and validate via streaming if possible.  
**Effort:** Medium

---

### Low Severity

#### BKD-011 — f-string SQL with table/column names

**Files:** `restore/service.py`, `backup/service.py`, `library/shelf.py`, `library/reclassify.py`, `api/firstrun.py`, `reader/service.py`, `library/overrides.py`, `storage/staging_cleanup.py`, `storage/migration.py`  
**Risk:** Latent SQL injection if a future refactor passes user input

All callers pass hardcoded constants — not exploitable today. But inconsistent with the excellent parameterized SQL used everywhere else. Creates a fragile pattern that could be copied with user input.

**Fix:** Add allowlist assertions or use pre-built query maps.  
**Effort:** Medium (many files)

---

#### BKD-012 — Error message information leakage

**Files:** `api/sources.py:314`, `api/app.py:334`, `api/storage.py:254`, `services/tasks.py:61`  
**Risk:** Internal details exposed to API clients

| Location | Leak |
|---|---|
| `api/sources.py:314` | Python exception class names |
| `api/app.py:334` | Absolute filesystem path in `/api/ready` |
| `api/storage.py:254` | Absolute backup file paths |
| `services/tasks.py:61` | Exception details in task status |

Acceptable for self-hosted single-user app, but violates least-disclosure principle.

**Fix:** Redact paths, use generic error messages for unexpected exceptions.  
**Effort:** Small

---

#### BKD-013 — Dynamic dispatch via `getattr`

**File:** `api/sources.py:151`  
**Risk:** Arbitrary method call if action string were user-controlled

Currently safe (hardcoded callers). Replace with explicit dispatch map.  
**Effort:** Minimal

---

#### BKD-014 — No subscriber cap on SSE event bus

**File:** `events/bus.py`  
**Risk:** Memory exhaustion from many concurrent SSE connections

Per-subscriber queue is capped at 256 events, but subscriber count is unlimited.

**Fix:** Cap at 50-100 subscribers; return 503 beyond limit.  
**Effort:** Minimal

---

#### BKD-015 — HttpClient cache unbounded

**File:** `sources/service.py:82-90`  
**Risk:** Memory growth from stale `aiohttp.ClientSession` instances

Cached by `(plugin_id, sha256)`. After many plugin updates, old entries with open connection pools are never evicted.

**Fix:** Evict on plugin update, or use LRU cache.  
**Effort:** Minimal

---

#### BKD-016 — `os.chmod` no-op on Windows

**Files:** `sessions/store.py:89`, `sessions/store.py:33,39`  
**Risk:** Secrets file may have wider permissions than intended

POSIX permissions are silently ignored on Windows. The `secrets.db` and key file may be readable by other users.

**Fix:** Emit startup warning on Windows, or use `icacls`.  
**Effort:** Small

---

#### BKD-017 — commit.py `_move_no_replace` rename fallback TOCTOU

**File:** `storage/commit.py:74-86`  
**Risk:** Silent overwrite on filesystems without hard links

The `os.link` path is atomic and safe. The `os.rename` fallback (FAT32, exFAT, network mounts) has a TOCTOU race: `os.path.lexists(dst)` returns False, another process creates `dst`, then `os.rename` overwrites it. Violates the commit engine's "never overwrite" invariant.

**Fix:** Use `os.link` with a proper fallback that opens with `O_EXCL`.  
**Effort:** Low

---

#### BKD-018 — Download backoff grows without cap

**File:** `downloads/engine.py`  
**Risk:** Jobs that fail many times stall for days

`delay = backoff_base ** attempts` (base=2) — after 20 attempts: 2^20 = ~12 days.

**Fix:** `min(delay, 3600)` — cap at 1 hour.  
**Effort:** Minimal

---

#### BKD-019 — LIKE wildcard escape missing

**Files:** `search/index.py`, `search/cache.py`  
**Risk:** Broader search results than intended

LIKE search uses `%{normalized}%` — if text contains `%` or `_`, they act as wildcards. Also `clear_source` uses `f"{source_id}@%"` — a source_id with `%` could clear more cache entries.

**Fix:** Escape `%` and `_` before LIKE queries.  
**Effort:** Low

---

#### BKD-020 — FollowRunner.check_all() is sequential

**File:** `follow/runner.py`  
**Risk:** Slow new-release detection with many follows and slow sources

Checks follows one at a time. With many follows, a single pass can take very long.

**Fix:** `asyncio.gather()` with a semaphore (3-5 concurrent checks).  
**Effort:** Medium

---

#### BKD-021 — Origin/Host port normalization mismatch

**File:** `api/guard.py:68-70`  
**Risk:** False rejections on non-standard ports

`Origin` header may omit the port while `Host` includes it (`host:8420`). The string comparison would reject valid same-origin requests.

**Fix:** Normalize both to `(host, port)` tuples before comparison.  
**Effort:** Low

---

#### BKD-022 — Dev endpoint calls external service without timeout

**File:** `api/generator.py:171-175`  
**Risk:** Request blocks indefinitely if test source hangs

No `aiohttp.ClientTimeout` is set on the POST to `dev_test_source_address/__control`.

**Fix:** `timeout=aiohttp.ClientTimeout(total=10)`.  
**Effort:** Minimal

---

### Informational

| # | File | Issue |
|---|---|---|
| I-1 | `api/sources.py:39` | Upload cleanup race — handled by `missing_ok=True` |
| I-2 | `db/schema/__init__.py` | `rebuilds_referenced_table` hardcoded to one migration name |
| I-3 | `api/app.py:191` | Public paths don't set `remote_session` in scope state |
| I-4 | `api/discovery.py:33` | `lru_cache` on per-request closure — pointless but harmless |
| I-5 | `storage/staging.py:29` | `st_dev` comparison unreliable on Windows |
| I-6 | `api/app.py:229` | SPA catch-all returns 200 for probe paths (noisier security scanning) |
| I-7 | `api/library.py:257` | Open `{action}` path param — handled but enum would be cleaner |
| I-8 | `generator/discovery.py:98` | Page bodies stored in memory — bounded by `max_fetches=24` |
| I-9 | `domain/ids.py:9` | 60 bits of randomness in IDs — fine for single-user |
| I-10 | Multiple files | Duplicated `error()` helper across 5+ API modules |

---

## Summary

| Severity | Count | Key Items |
|---|---|---|
| **High** | 2 | SearchService thread safety (BKD-001), EventBus race (BKD-002) |
| **Medium** | 8 | Auth rate limit (003), N+1 queries (004), migration leak (005), orphan marker (006), scanner Windows (007), unbounded undo (008), restore lock (009), CBZ memory (010) |
| **Low** | 12 | f-string SQL (011), info leakage (012), getattr (013), SSE cap (014), HttpClient cache (015), chmod Windows (016), TOCTOU (017), backoff (018), LIKE escape (019), sequential follows (020), port normalization (021), dev timeout (022) |
| **Informational** | 10 | Edge cases, code quality notes |

**Overall assessment:** The backend is well-engineered with strong security fundamentals — encryption, path safety, egress policy, and session handling are all excellent. No critical vulnerabilities were found. The most impactful findings are the two high-severity concurrency bugs (BKD-001, BKD-002) and the N+1 query patterns (BKD-004). The authentication rate limiting gap (BKD-003) is the most significant security finding.
