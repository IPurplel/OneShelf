Now I have the full picture. Here's my analysis of the two proposed repairs.

---

## Repair 1 — Readiness test (`test_app.py:97`)

**Root cause:** The handler at `app.py:345` returns `"database_ok": config.db_path.exists()`, but the test at `test_app.py:97` asserts `"database" in body`. The key was renamed (likely during the recent `aa80dd6` remediation) and the test wasn't updated to match.

**Proposed fix:** Replace `"database" in body` with `body["database_ok"] is True`. Keep `"storage_roots" in body`.

**Assessment: Correct and minimal.** The response shape is `database_ok` (boolean), not `database` (path or object). The assertion should check both presence and value. No production code change.

---

## Repair 2 — Rate limiter test isolation (`test_auth_api.py`)

**Root cause:** `rate_limit.py:45-46` creates `_auth_limiter` and `_recovery_limiter` as **module-level singletons**. Every rate-limited call across the entire test session accumulates in the same counters. I count the following rate-limited hits across `test_auth_api.py`:

| IP | Endpoint hits | Total |
|----|--------------|-------|
| `LAN_PEER` (192.168.1.10) | `register/options` in 8 tests + 4 parametrized `test_i91` | **12** |
| `REMOTE_PEER` (203.0.113.9) | `sign-in/options` + `sign-in` + `register/options` across 6 tests + 4 parametrized | **~21** |

Both IPs exceed the 10-request budget within a single test run. Since tests complete well under 60 seconds, the sliding window never expires entries. Once the 11th hit lands, every subsequent test that touches a rate-limited endpoint from that IP gets an unexpected `429`.

**Proposed fix:** The `app` fixture takes `monkeypatch` and replaces `_auth_limiter` / `_recovery_limiter` with fresh `RateLimiter` instances using the same production budgets (`window_seconds=60, max_requests=10` and `window_seconds=60, max_requests=3`). Add an explicit regression test that calls `sign-in/options` 11 times from the same peer and asserts:
- Requests 1–10 succeed
- Request 11 returns `429` with a `Retry-After` header

**Assessment: Sound and well-scoped.** The `monkeypatch.setattr` pattern is standard pytest for module-level singletons — it's automatically reverted after each test, so every test starts with clean counters. Using identical budgets means each test still exercises the real `RateLimiter.check` code path, just without cross-test contamination. The explicit 429 regression test provides positive evidence that rate limiting works, which is stronger than the previous implicit reliance on the singleton surviving across tests. No production code change.

---

## Summary

Both repairs are **test-only**, **narrowly scoped**, and **preserve production behavior exactly**. The rate limiter regression test actually strengthens coverage over the status quo. I approve the proposed repairs as described.

One minor implementation note: in repair 2, the `monkeypatch.setattr` targets should be the fully qualified module paths (`"oneshelf.api.rate_limit._auth_limiter"` and `"oneshelf.api.rate_limit._recovery_limiter"`) since `auth.py` imports the *functions* `require_auth_rate_limit` / `require_recovery_rate_limit`, which close over the module-level names. Patching at the `rate_limit` module level is correct because the functions reference `_auth_limiter` and `_recovery_limiter` by name at call time, not by captured binding.
