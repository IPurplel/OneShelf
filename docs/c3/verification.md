# C3 — Verification Report: Declarative Source Runtime, Sessions, Secure Network Policy

Recorded: 2026-09-17 · Branch: `c3/source-runtime` (from `c1/foundation` @ `2dc014f`) · Authority: Meta Prompt §C3
Status: **C3 gate passed** for the backend described below. User-facing Sources/login screens belong to C2; health states, Needs Attention and notifications to C6; download use of these services to C5; generator/repair to C9.

C2 was skipped for now by user decision (the visual reference V is still missing, EB-2). C3 only depends on C1.

## Environment

| Item | Value |
|---|---|
| Python / SQLite | 3.14.7 / 3.51.2 |
| New runtime deps | aiohttp 3.14.3, cryptography 50.0.1, google-re2 1.1.20251105, playwright 1.63.0 (Chromium 153, Ubuntu fallback build on this Fedora host), PyYAML 6.0.3, scrapling 0.4.15 (parser only; no `fetchers` extra) |
| Pinned set | `backend/requirements.lock` (48 packages) |
| Browser install | `.venv/bin/python -m playwright install chromium` |
| Test policy | warnings are errors; two targeted third-party ignores (anyio alias in `starlette.testclient`; scrapling's no-op lxml `strip_cdata` option) |

## Commands and results

```sh
cd backend
.venv/bin/pytest                 # → 437 passed (C1 158 + C3 279), 0 failed, no warnings
.venv/bin/pytest -m browser      # real Chromium tests (also part of the full run)
```

Stability: the governor tests passed 5 runs in a row and the browser tests 3 runs in a row.

Real-process smoke test (scratch data dir, dev Test Source on 127.0.0.1:18421, OneShelf on 18420):

| Step | Result |
|---|---|
| `POST /api/sources/uploads` (Test Source .osp) | review: id, version 1.0.0, packaged tests passed, 5 permissions |
| `POST /api/sources/install` with approvals | `active`, last step `activated` |
| `GET /api/sources` | `trust_label: local`, `channel: upload`, `session_state: not_connected`, 6 capabilities |
| `POST /api/sources/oneshelf.test-source/login` → `GET /api/logins/{id}/frame` | Chromium started lazily; 200 `image/jpeg`, 7.8 KB; frame shows the Test Source sign-in form |
| `DELETE /api/logins/{id}` | `cancelled` |
| Cross-origin `POST` (Origin: evil.example) | 403 `CROSS_ORIGIN_REQUEST` |
| Foreign `Host: attacker.example` | 421 `HOST_NOT_ALLOWED` |
| Server log | no tracebacks |

## Gate checklist (Meta Prompt §C3)

| Gate item | Evidence | Result |
|---|---|---|
| Malformed / executable plugin rejection | `tests/unit/plugins/test_package_validation.py` (code files, symlinks, zip-slip, non-zip, YAML tags, alias bombs, unknown keys, unsafe domain rules incl. IP literals/localhost/internal suffixes/ports, forbidden headers, template injection, invalid selectors/JSON paths, undeclared capabilities/browser/auth, un-allowlisted fixture URLs; each rejection reason checked) · `test_lifecycle.py::test_malformed_package_is_rejected_without_side_effects` | Pass |
| Bounded transform / regex | `tests/unit/plugins/test_transforms.py` (RE2 linear time on `^(a+)+$` × 50k, backreference/lookaround rejection, pattern/step/value size caps, unknown transforms, URL scheme/credential rejection, Arabic digits, no stemming) | Pass |
| Installation rollback | `test_lifecycle.py` (failed packaged tests reject, crash after store move reconciled, same-version immutability, downgrade refused, rollback to previous) | Pass |
| New-permission review | `test_lifecycle.py` (fresh install without approval → pending_review; update adding a CDN domain → pending_review while old version stays active; approve activates) · `test_sources_api.py::test_upload_review_then_install` | Pass |
| Same-source session isolation; cross-source / CDN secret-leak | `tests/unit/sessions/test_sessions.py` (AES-GCM at rest, AAD binding to source, wrong key, secure delete, redacted repr, scoping by capability/recipe auth/session domain/CDN/secure/path/expiry, isolation between sources, refresh only from session domains) · `test_test_source_pipeline.py::test_use_my_session_flow_with_scoped_cookies` (real server logs: CDN host never received the session cookie) · `test_browser.py::test_browser_contexts_are_isolated` | Pass |
| Reconnect waits | `test_sessions.py::test_reconnect_replaces_atomically_and_resumes_waiters` · pipeline session flow (expire → needs_reconnect → waiter blocked → reconnect → resumes) | Pass |
| DNS / redirect / browser SSRF | `tests/unit/net/test_policy.py` (address classification incl. mapped/6to4/NAT64/CGNAT/metadata; loopback-resolving allowlisted names blocked with a single lookup and zero server hits; mixed answers rejected; per-hop redirect revalidation; env proxies ignored; no cookie jar) · `tests/unit/net/test_egress_proxy.py` (CONNECT/absolute-form policy, IP literals, credentials, pipelined smuggling, header limits) · `tests/integration/browser/test_browser.py` (control run proves an unprotected browser reaches a local service; protected contexts: fetch/img/iframe/navigation/redirect probes to loopback, `localhost`, `[::1]`, link-local metadata and a hostname rebound to loopback → 0 hits) | Pass |
| Priority / fairness | `tests/unit/net/test_governor.py` (priority order, background can't take the last HTTP slot, independent browser capacity, background browser preemption for Reader, downloads not preempted but bounded wait, per-source concurrency, cross-source fairness, rate-limit spacing, Retry-After isolation, cancellation leaks) · pipeline `test_rate_limit_feeds_the_governor` | Pass |
| Uninstall preserves local content and Shelf provenance | `test_lifecycle.py::test_uninstall_preserves_library_and_provenance_and_allows_reinstall` | Pass |

## What C3 delivers (backend)

| Area | Modules |
|---|---|
| Declarative `.osp` format + static validation | `plugins/package.py`, `plugins/schema.py`, `plugins/yamlsafe.py`, `plugins/templates.py`, `plugins/jsonpath.py`, `net/domains.py` |
| Safe transforms, Arabic normalization | `plugins/transforms.py`, `text/arabic.py` |
| Recipe runtime, typed results, completeness evidence, packaged tests | `plugins/runtime.py`, `plugins/results.py` |
| Install / review / update / disable / uninstall / rollback / reconcile / submission bundle | `plugins/manager.py`, migration `0002_plugins.sql` |
| Registry (static index; local mirror or HTTPS; ed25519 locally trusted keys) | `plugins/registry.py` |
| Egress policy, HTTP client, governor | `net/policy.py`, `net/http.py`, `net/governor.py` |
| Browser egress proxy, Chromium contexts, browser fetch | `net/egress_proxy.py`, `net/browser.py`, `net/lazy_browser.py`, `sources/browser_fetcher.py` |
| Use My Session (encrypted store, scoping, login screencast) | `sessions/store.py`, `sessions/manager.py`, `sessions/login.py` |
| Source service, passive health signals | `sources/service.py`, `sources/fetcher.py`, `sources/health.py`, migration `0003_source_health.sql` |
| Diagnostics redaction | `diagnostics/redact.py` |
| API | `api/sources.py` (sources, uploads, install, approve, lifecycle, session, validate, disconnect, health, login, registry), `api/guard.py` |
| OneShelf Test Source (dev/test only, not packaged) | `testsource/server.py`, `testsource/package/`, `testsource/build.py`, `python -m testsource` |

## Known limitations / carried forward (not gate failures)

- **Adaptive selector fallback** (§12.1, §12.3) is not in the runtime yet. It needs stored element signatures and validation, and belongs with the generator and repair workflow (C9).
- **Browser resource discovery** returns the rendered DOM for declarative extraction. Capturing XHR/media resources for downloads comes with the download engine (C5) and generator (C9).
- **Health** records passive signals with plugin version and bounded retention. Thresholds, hysteresis, user-facing states and active checks are C6.
- **Diagnostics:** redaction exists; a persistent rotating diagnostics store (7 d / 100 MB) is not yet written (C6/C9).
- **Extraction Contracts** (§14 modes, fallback) are C5. C3 provides the fetch kinds and error categories they depend on.
- **Live sources** (§41.1) are not yet integrated or checked from this environment (EB-3). Foundation-source packages start in C4.
- **Session key location:** defaults to `<data_dir>/keys/session.key` (a separate file with 0600 permissions). Docker docs (C9) must mount it separately; flagged in the ledger (D-C3-11).
- **Login UI** (the screencast viewer that sends input events) is part of C2 screens; the API is ready.
- **Container verification** is still blocked on this host (EB-1).
