# Noor Book Core milestone — execution report

Date: 2026-10-24. Branch: `codex/noorbook-reader`. Baseline: `8aaff477a334b6851934e9ddbc079d4d46363502`.

## Scope and outcome

Implemented the independently approved Core milestone: reject nonempty incomplete reader results before descriptor caching, and normalize the supported static SVG subset to PNG before existing image validation and page caching. Raster reading, page response headers, frontend behavior and permanent-download preferences retain their existing contracts. No source adapter was added.

The bounded Linux subprocess uses pinned `resvg_py==0.5.0`, 256 MiB address space, 5 seconds CPU, 8 seconds wall time, at most two workers and 8M output pixels. It rejects active content, external references, DTD/entities and unsupported markup. Embedded JPEG/PNG images are validated. A narrow static paint style subset is converted to presentation attributes; no CSS reaches the renderer. SVG input fails closed on unsupported platforms.

Ownership coordination and two addenda are recorded in `../coordination/2026-10-24-noorbook-backend-review.md`. The final Core reviewer found no critical/important issues in the initial implementation and identified platform test guards and stale docs; both were corrected. Subsequent actual-sample rejection led to the owner-approved static style/overflow addendum and synthetic red/green coverage.

## Verification

- Focused reader, image integrity, SVG and endpoint-guard tests: **90 passed** on Linux.
- Windows portability check: **2 passed, 35 skipped**; raster pass-through and unsupported-platform rejection verified.
- Actual saved source page: PNG output **970 × 1474**, **2,112,226 bytes**; existing integrity validator passed; output visually inspected including its vector overlay.
- Full backend suite: **1644 passed, 1 skipped (shellcheck unavailable), 12 live tests deselected**, in 185.63 seconds. Native Linux verification used the same seven implementation/test files, normalizing only CRLF to LF. The pinned renderer also has a verified Python 3.13 Linux binary wheel matching the Docker runtime; a production image was not built or deployed.
- Initial mixed Windows/WSL run: 55 failures, 1577 passes. Failures identified missing child `python`, CRLF shell shebangs, Windows worktree Git metadata paths, and the endpoint guard mistaking XML namespace identifiers for fetched destinations. Verification uses a native Linux checkout with LF files and the venv on PATH. Only the three exact namespace strings are exempted by the guard.

Evidence directory (ignored): `G:/work/OneShelf/qa-artifacts/noorbook-2026-10-24/`. Logs: `core-red.log`, `style-red.log`, `core-final.log`, `core-windows.log`, `backend-full.log`, `backend-native-linux.log`, `normalization-result.json`. Visual evidence: `normalized-page-111.png`; source investigation: `reader-last-page.png`, `scrapling-result.json`, `core-browser-linux.log`. Actual source markup and session-bearing URLs are not committed.

## Remaining source gate

**BLOCKED — controlled source replay.** Standard Core browser navigation ends with `net::ERR_CONNECTION_CLOSED`; HTTP attempts failed before HTML. A saved browser DOM was successfully parsed with Scrapling, but contained only 8 populated URLs among 11 final-group slots. Neither all 111 descriptors nor the 100→101 request sequence is proven. No request bodies, tokens or page URLs were guessed. A second title, preview state, expiry behavior and declarative recipe feasibility remain unverified. Noor Book cannot yet be opened as a supported OneShelf source.

## Deployment/browser evidence

- Commit and remote SHA: to be recorded in the final handoff after commit/push.
- User deployment confirmation: none for this revision.
- Deployment checkout SHA: no evidence supplied.
- Running image revision: unverified.
- Production browser accessibility: not tested; awaiting user-managed deployment.
- Production pages/interactions: none tested for this change.
- Desktop/mobile results: not tested for this change.
- Console, network and JavaScript exceptions: no production observations for this change.
- Source-site observations and saved-page rendering above are not production QA.

No server deployment, rebuild or restart was performed. This milestone is intended for review on its feature branch; merging Core changes without an adapter is a separate integration decision. Production PASS is not claimed.

## Merge verification — 2026-10-24

The user explicitly approved merging PR #11. Integrating main at `8415d81613300d5d504aff6d6b228b2bb0c7b0fa` exposed seven existing readiness/auth test failures, reproduced unchanged on main (7 failed, 32 passed in those modules). The backend owner approved test-only repairs: assert the redacted `database_ok` readiness contract and reset module-level rate-limiter state per independent test application while preserving production budgets. A new HTTP regression verifies that the eleventh sign-in-options request returns 429 with Retry-After. No production authentication behavior was changed.

Final merged-candidate backend result: **1645 passed, 1 shellcheck-dependent skip, 12 live tests deselected**, in 183.60 seconds. Evidence: `main-baseline-auth-tests.log`, `merge-candidate-tests.log`, `merge-fixed-tests.log`, and the owner decision in `../coordination/2026-10-24-merge-test-repairs.md`. Deployment confirmation, deployment checkout/image revision, and production browser QA remain pending. The source transport blocker remains unresolved; this merge does not establish Noor Book source support.
