# Release handoff audit and remaining plan

Audit date: 2026-09-20. Baseline: `b4400cd242e2931909950ac263c9b71fa5bc2b5a`, branch `main`.
The workspace clock/date differs from historical records labelled September 21; those records remain historical evidence.

## Safe handoff

`git status`, the last eight commits, `git diff`, and `git diff --cached` were inspected before edits.
No tracked changes or staged changes existed. The only untracked file was
`image refrence/oneshelf-library-home.png`; it is preserved, outside the release commits.
Claude's scripts, tests, SPA serving and release documentation are already committed in
`8fe7fba`, `dc808ee`, and `b4400cd`. None need to be recreated.
Original requirements remain 305 VERIFIED, M2/M2.1 BLOCKED, M56 IN_PROGRESS.

GitHub's connected identity is IPurplel. `IPurplel/OneShelf` is public and empty (no branches).
No Docker/Podman executable or standard runtime socket is present; no runtime will be installed here.
The latest explicit user instruction authorizes publication independently of the unavailable host gate,
superseding the old REL-07 dependency on REL-08. Publication does not verify deployment.

## Bounded remaining work (WP-REL)

1. Add failing script regressions for missing probe tools, health payload, configuration passed to
   Compose, unsafe paths, directory/ownership failure, unsafe Git states and command failures.
2. Repair only release scripts/helpers, Compose mounts and build exclusions. Preserve configuration
   bytes, user data, existing migrations and application behavior. Default uninstall stays nondestructive.
   Restrict automatic destructive removal to canonical default directories; custom paths need manual removal.
3. Fresh independent review; run script tests, full backend/frontend suites, frontend production build,
   and opt-in live tests. Record skips/failures accurately.
4. Scan tracked files and history for secrets/user data, verify executable modes, reconcile README and
   records, commit focused changes. Configure origin, push main without force, verify remote equality.
5. Clone the actual public repository into an isolated temporary directory and run all feasible checks.
   Provide exact Fedora-host commands for installation, import, restart/recreation persistence, schema,
   uid, container health, update and uninstall/reinstall. M2/M2.1/M56 and final release remain open until
   actual host evidence is supplied.

Files: install.sh, update.sh, uninstall.sh, deploy/lib.sh, deploy/compose.yaml, build ignore files,
backend/tests/deploy/test_install_scripts.py, README.md, and existing release/traceability records.

## Verification checkpoint before publication

- Full backend: `cd backend && .venv/bin/pytest` → **989 passed, 1 skipped, 8 deselected**.
- Deployment subset: **58 passed, 1 skipped**; skip is optional ShellCheck (not installed).
- Frontend: `npm test` → **196 passed**; `npm run build` passed including typecheck.
- Live: initial run **7 passed, 1 failed** (Gutenberg returned bytes that were not a ZIP/EPUB).
  Follow-up retrieval of the same public URL (`https://www.gutenberg.org/ebooks/84.epub3.images`)
  returned HTTP 200, application/epub+zip, 474161 bytes and a valid ZIP. The original malformed body
  was not retained, so its exact cause is not claimed. The unchanged full live suite rerun passed
  **8/8**, with no skips and no test weakening.
- Fresh independent review: no remaining critical/high code defect. A duplicate obsolete host-guide
  block was removed and a backup-volume write check added following review.
- `bash -n` on scripts and all Fedora guide Bash blocks, `git diff --check`, executable Git modes,
  and ignore checks passed. No actual runtime install/update/uninstall has been claimed.
- History hygiene: all 82 reachable baseline commits scanned for credential/key/token shapes and
  local-data filenames. Only deliberate redaction/egress test credential fixtures matched heuristics.
  No tracked .env, session keys, databases, backups or runtime stores were found. The original
  untracked visual reference remains untouched and will not be published.

The code changes are confined to release scripts, container configuration/guards, tests and docs.
Original application requirement statuses remain **305 VERIFIED, 2 BLOCKED, 1 IN_PROGRESS**.
