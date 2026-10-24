# OneShelf — Backend Remediation Plan

**Date:** 2026-10-24  
**Based on:** BACKEND_AUDIT.md (32 findings across ~140 files)  
**Branch:** main @ `65178f7`

---

## Phase 1 — Concurrency & Security (High priority)

Fix the two high-severity concurrency bugs and the auth rate limiting gap.

| # | Issue | Files | Effort | Description |
|---|---|---|---|---|
| 1.1 | BKD-001 SearchService thread safety | `search/service.py` | Medium | Replace `self.limit = limit` with a parameter passed through the search pipeline. Create a `SearchContext` dataclass or thread through method args. |
| 1.2 | BKD-002 EventBus race condition | `events/bus.py` | Low | Catch `Full` in `put_nowait()` instead of pre-checking `qsize()`. The resync-and-drop logic already exists — just make it resilient to the race. |
| 1.3 | BKD-003 Auth rate limiting | `api/auth.py`, new `api/rate_limit.py` | Small | In-memory per-IP rate limiter (sliding window). 10 req/min on sign-in endpoints, 5 req/min on `lan-recovery`. Cleanup stale entries periodically. |

**Verification:**
- Concurrent search test: two simultaneous searches with different limits return correct counts
- SSE stress test: rapid event publishing doesn't lose events
- Auth rate limit test: 11th request within 60s returns 429

---

## Phase 2 — Performance (Medium priority)

Fix N+1 queries and resource management issues that affect responsiveness.

| # | Issue | Files | Effort | Description |
|---|---|---|---|---|
| 2.1 | BKD-004 N+1 batch queries | `api/library.py`, `downloads/` | Medium | Replace per-row `batch()` call with a single JOIN query for `list_batches`. Same for `batch_detail` per-job queries. |
| 2.2 | BKD-004 N+1 unit queries | `api/works.py` | Low | Replace per-unit `SELECT assets` with `WHERE reading_unit_id IN (...)` or a JOIN. |
| 2.3 | BKD-010 CBZ memory | `integrity/validators.py` | Medium | Add per-image size cap (20MB). Consider streaming validation or sampling for large archives. |
| 2.4 | BKD-018 Backoff cap | `downloads/engine.py` | Minimal | `min(delay, 3600)` — cap retry backoff at 1 hour. |
| 2.5 | BKD-020 Sequential follows | `follow/runner.py` | Medium | `asyncio.gather()` with semaphore (3–5 concurrent checks). |

**Verification:**
- `list_batches` with 200 items: query count drops from ~200 to ~2
- `work_units` with 500 chapters: query count drops from ~500 to ~2
- CBZ with 200×5MB pages: peak memory stays under 100MB
- Failed download after 20 retries: backoff capped at 1 hour, not 12 days

---

## Phase 3 — Data Integrity (Medium priority)

Fix storage and migration issues that could cause data loss or orphaned state.

| # | Issue | Files | Effort | Description |
|---|---|---|---|---|
| 3.1 | BKD-005 Migration snapshot leak | `db/migrate.py` | Low | Wrap target connection in `try/finally` or `contextlib.closing()`. |
| 3.2 | BKD-006 Orphan root marker | `storage/roots.py` | Low | Insert DB row first, then write marker. Rollback DB on marker failure. |
| 3.3 | BKD-007 Scanner Windows paths | `storage/scanner.py` | Low | Normalize `os.path.relpath()` output to POSIX separators. |
| 3.4 | BKD-008 Unbounded undo dict | `follow/service.py` | Low | `OrderedDict` with max 100 entries, evict oldest. |
| 3.5 | BKD-009 Restore write lock | `restore/service.py` | Medium | Document limitation, or add "maintenance mode" that returns 503 during restore. |

**Verification:**
- `snapshot()` with simulated backup error: no leaked file handles
- `register_root()` with constraint violation: no orphan markers on disk
- `reconcile()` on Windows: files matched correctly despite path separators
- Unfollow 200+ works: memory stays bounded

---

## Phase 4 — Defense in Depth (Low priority)

Hardening and code quality improvements. No functional risk if deferred.

| # | Issue | Files | Effort | Description |
|---|---|---|---|---|
| 4.1 | BKD-011 f-string SQL | 9 files | Medium | Add allowlist assertions before all f-string column/table interpolations. |
| 4.2 | BKD-012 Info leakage | `api/app.py`, `api/storage.py`, `api/sources.py`, `services/tasks.py` | Small | Redact paths from `/api/ready`, backup views, and task errors. |
| 4.3 | BKD-013 getattr dispatch | `api/sources.py` | Minimal | Replace with explicit dispatch map. |
| 4.4 | BKD-014 SSE subscriber cap | `events/bus.py` | Minimal | `MAX_SUBSCRIBERS = 100`, reject with 503. |
| 4.5 | BKD-015 HttpClient eviction | `sources/service.py` | Minimal | Evict on plugin update or use LRU. |
| 4.6 | BKD-016 chmod Windows | `sessions/store.py` | Small | Emit startup warning, optionally use `icacls`. |
| 4.7 | BKD-017 TOCTOU move | `storage/commit.py` | Low | Use `O_EXCL` open in the rename fallback. |
| 4.8 | BKD-019 LIKE escaping | `search/index.py`, `search/cache.py` | Low | Escape `%` and `_` before LIKE patterns. |
| 4.9 | BKD-021 Port normalization | `api/guard.py` | Low | Normalize Origin and Host to `(host, port)` tuples. |
| 4.10 | BKD-022 Dev timeout | `api/generator.py` | Minimal | `aiohttp.ClientTimeout(total=10)`. |

---

## Not Recommended to Fix

| Issue | Reason |
|---|---|
| I-1 Upload cleanup race | Handled correctly by `missing_ok=True` |
| I-2 Hardcoded migration name | Works correctly, comment is sufficient |
| I-3 Missing remote_session on public paths | Public paths don't read it |
| I-4 lru_cache on per-request closure | Harmless overhead |
| I-5 st_dev on Windows | Alternative check not practical |
| I-6 SPA catch-all 200s | Standard SPA behavior |
| I-7 Open action path param | Handled by if/elif with 404 |
| I-8 Generator memory | Bounded by max_fetches |
| I-9 60-bit IDs | Sufficient for single-user |
| I-10 Duplicated error helpers | Consolidation is optional cleanup |

---

## Execution Order

```
Phase 1.2 (EventBus race)        → quick win, low risk
Phase 1.3 (Rate limiting)        → new file, no existing code touched
Phase 1.1 (SearchService)        → needs careful refactor
Phase 2.4 (Backoff cap)          → one-line fix
Phase 2.2 (N+1 unit queries)    → straightforward JOIN
Phase 2.1 (N+1 batch queries)   → needs understanding of batch() internals
Phase 3.1 (Migration leak)       → simple try/finally
Phase 3.2 (Orphan marker)        → reorder two operations
Phase 3.3 (Scanner Windows)      → one-line normalize
Phase 3.4 (Unbounded undo)       → swap dict for OrderedDict
Phase 2.3 (CBZ memory)           → needs streaming approach design
Phase 2.5 (Sequential follows)   → asyncio.gather with semaphore
Phase 3.5 (Restore lock)         → design decision needed
Phase 4.*                        → opportunistic, any order
```

---

## What Was NOT Found

- No SQL injection via user input
- No path traversal vulnerabilities
- No bare `except:` clauses hiding errors
- No hardcoded secrets or credentials
- No CORS misconfiguration
- No missing authentication on protected routes
- No insecure session handling
- No command injection vectors
- No deserialization vulnerabilities
- No timing side-channels in auth (`hmac.compare_digest` used correctly)
- No SSRF — egress policy is comprehensive
- No ReDoS — RE2 regex engine used for plugins
