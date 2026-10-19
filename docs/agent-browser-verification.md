# Agent browser verification

This is the shared procedure for Claude Code, Codex, and other agents. `AGENTS.md` makes it a completion gate for pushed changes. The target is the real OneShelf deployment at `http://192.168.8.32:8420/`, a private LAN address. Run the browser from the agent's actual runtime, including the `ai-box` Podman container when that is where the agent runs. A successful HTTP probe or local test does not count as visual verification.

## One-time runtime setup

The repository configures the same project-scoped `playwright` MCP server for Claude Code (`.mcp.json`) and Codex (`.codex/config.toml`). Both launch `@playwright/mcp@0.0.83` through `npx` in headless, isolated mode. Its `chromium` channel runs **Google Chrome for Testing**; `chrome --version` from the Playwright browser cache should identify it as such. This channel works without a system-wide Chrome RPM and keeps the project config portable between Fedora hosts and `ai-box` containers. Use a system Google Chrome channel if this runtime explicitly requires it, after verifying the actual executable and updating both project configs together. No remote debugging port is needed or configured.

From the repository root in **each** agent runtime:

1. Check `node --version` and `npx --version`. Install Node.js if missing.
2. Install the matching browser if necessary: `npx -y playwright@1.64.0-alpha-1790635538000 install chromium` (the Playwright version required by the pinned MCP package). Confirm the browser executable reports `Google Chrome for Testing` and launches. Linux may need browser system libraries; follow Playwright's installation error and install only the missing packages.
3. Check `claude mcp get playwright` and `codex mcp get playwright` from the project root. Claude Code may request approval for the checked-in `.mcp.json` in an interactive session; for a noninteractive `claude -p` QA run, explicitly allow the needed `mcp__playwright__...` tools with `--allowedTools`. Codex loads `.codex/config.toml` only for a trusted project; mark the checkout trusted in your local Codex settings if prompted. The Codex config pre-approves only the listed browser QA tools and omits script execution and file upload tools. Restart an already-running agent session after pulling these files, and check that the `playwright` tools appear. An unavailable or unapproved server is a blocker; do not silently switch to HTML-only checks.
4. Use `browser_navigate` on the real URL, `browser_snapshot`, `browser_take_screenshot`, one harmless `browser_click` or `browser_type` on the app, `browser_console_messages`, and `browser_network_requests`. This proves browser launch, access, interaction, rendering, and diagnostics. Save screenshots in ignored `qa-artifacts/` or outside the repository.

The `--isolated` browser profile prevents saved cookies from carrying between sessions. Treat screenshots and diagnostic output as private anyway. Never commit tokens, browser profiles, or sensitive screenshots. Never bind an MCP or Chrome debugging endpoint to a public interface; use the configured local stdio server. If a remote agent lacks a route to the private IP, run verification from an authorized LAN runtime or report **BLOCKED — BROWSER CANNOT REACH PRIVATE LAN**. Do not expose OneShelf publicly to satisfy this check.

## User-managed deployment and evidence

The user owns updates of the production server at `192.168.8.32`. Agents must not deploy, rebuild, restart, or update it unless the user explicitly requests that action. The documented [`./update.sh` procedure](../README.md#updating) remains available for the user's manual update; see its preconditions and [upgrade notes](operations.md#7-upgrades). A GitHub push never proves it ran. Lack of agent SSH credentials is not evidence that the server is outdated; do not repeatedly try SSH authentication without authorized credentials.

The user's confirmation that they updated the server starts browser QA. Record these as **separate** facts:

| State | What establishes it |
| --- | --- |
| GitHub push verified | Full expected SHA equals the remote branch SHA from `git ls-remote` |
| User confirmed manual deployment | Explicit user confirmation for this push |
| Deployment checkout SHA verified | Fresh `git rev-parse HEAD` output from the deployment host, supplied by the user or obtained with authorized access |
| Running image revision verified | Build/deployment provenance tying the running container image to the expected commit; a checkout SHA or healthy container alone is insufficient |
| Browser functionality verified | Chrome opened the real URL and the relevant screenshots, interactions, console, and network checks passed |

The user reported on 2026-10-19 that GitHub `main` and the deployment checkout both held `dca1907d838be4dbeb5c0ea0963e67e900118357`, and container `oneshelf-oneshelf-1` was `Up (healthy)`. This is a dated baseline, not standing proof for later pushes or of the image's source revision. The deployment-host command `docker compose ps` returned `no configuration file provided` from the repository root because Compose did not discover `deploy/compose.yaml` there; it does not indicate that OneShelf is broken. The documented invocation supplies `--env-file .env -f deploy/compose.yaml`.

If the running image revision cannot be proven, state **running image revision unverified**. The browser may still be used after user deployment confirmation to report what the currently accessible application does, but do not call it verification of the new Git revision without sufficient provenance. Use **BLOCKED — DEPLOYMENT NOT UPDATED** only when evidence actually establishes a stale deployment. Before user confirmation, use **READY — AWAITING USER-MANAGED DEPLOYMENT**.

## After every committed and pushed change

1. Inspect `git status`, worktrees, and the current branch. Preserve other agents' work. Run tests and checks relevant to the change before committing (`frontend`: `npm test`, `npm run build`; `backend`: the relevant `pytest` subset or full suite as appropriate; docs/config: parse files, check commands, and inspect the diff). Run additional checks for risks the change introduces.
2. Commit and push using the existing branch and the user's authorization. Never force-push. Record `git rev-parse HEAD`, the branch name, and the push result. Verify the remote branch directly, for example `git ls-remote origin refs/heads/main`, and compare its full SHA to the expected SHA. Resolve a mismatch before proceeding. Run the relevant checks against the exact pushed commit.
3. Tell the user the change is ready for their manual server update and report **READY — AWAITING USER-MANAGED DEPLOYMENT**. Do not start production deployment actions. This is a handoff state, not a failed application or failed push.
4. After the user confirms their update, record the distinct deployment evidence above. Use reliable host output the user supplies, such as checkout SHA, update/build output, container health, and image identity. Do not infer an image revision from a healthy `/api/ready`, an unchanged page, or the checkout SHA alone. If image provenance remains unknown, carry that limitation into the browser report.
5. Navigate in Playwright MCP to `http://192.168.8.32:8420/`. Record the page title/URL and inspect an actual desktop screenshot. For relevant UI work, resize or emulate a mobile viewport and inspect its screenshot. Check layout, alignment, spacing, clipping/overflow, visibility, and responsive behavior.
6. Use the accessibility snapshot to select controls, then exercise the changed feature and related flows. Inspect loading, empty, success, and failure states where applicable. Check buttons, menus, forms, navigation, and dialogs. For OneShelf, pay particular attention to discovery/search, work details, source selection and installed adapters, chapter/book navigation, the reader, and downloads. Do not mutate or delete real library data merely to create a QA state; use a safe test account/data or report the state that could not be exercised.
7. Call `browser_console_messages` and `browser_network_requests` after the interactions. Identify JavaScript exceptions, console errors, failed requests, and relevant HTTP errors. For backend-only changes, run API/functional checks as well; use the browser whenever behavior is observable in the app.
8. If a defect appears, save the issue and evidence, find its root cause, correct it within the authorized scope, rerun relevant tests, commit/push and verify the new remote SHA, then return to the user-managed deployment handoff. Reopen the app in Chrome after the user confirms the correction is deployed. Repeat until the relevant blocking defect is resolved. Never call an old screenshot a retest.

For every browser call, use the local MCP tools in this order as needed: `browser_navigate`, `browser_snapshot`, `browser_take_screenshot`, `browser_click`/`browser_type`, `browser_resize`, `browser_console_messages`, and `browser_network_requests`. The last two show what the browser observed; check them after navigation and again after interactions. A screenshot of a browser error page is evidence of an access failure, not a successful OneShelf screenshot.

## Helper scripts and field notes

**Frontend revision from the agent runtime.** After the user confirms the manual update,
`scripts/agent/deployed-revision.sh <sha>` can build the frontend of `<sha>` in a throwaway worktree and
compares Vite's content-hashed entry assets (`/assets/index-*.js|css`) with the ones the live `index.html`
serves. Results are cached in `~/.cache/oneshelf-agent/`. Exit codes: 0 = MATCH, 1 = MISMATCH,
2 = could not check. A MISMATCH means the live frontend assets differ from the local build; investigate
the build conditions and deployment evidence before concluding the server is stale. A MATCH is evidence
for the **frontend assets only**, not proof of the running image's Git revision. A backend-only or
docs-only commit leaves the hashes unchanged, so it still needs the host evidence in step 4 above.
Say in the report which kind of evidence was used. Do not run this check before user deployment
confirmation or describe a pre-deployment mismatch as a failed deployment.

**Scripted evidence.** `backend/.venv/bin/python scripts/agent/browser_check.py --path / --path /sources --click Search`
opens each path in headless Chrome at 1440×900 and 390×844. It saves viewport and full-page screenshots,
and records console errors, page exceptions, failed or ≥400 requests, and horizontal overflow, to
`qa-artifacts/browser/<timestamp>/report.json`. `--click` follows one link or button by accessible name
(navigation only). Exit codes: 0 clean, 1 problems, 2 unreachable. Use it alongside the MCP session for
repeatable before/after evidence, not instead of looking at the page.

Field notes from setting this up in `ai-box`:

- Pages render "Loading…" first, so a screenshot taken straight after `browser_navigate` or `browser_click`
  shows the loading state. Call `browser_wait_for` with text from the loaded page before taking it.
- In full-page screenshots, fixed elements (the desktop sidebar, the mobile tab bar) are drawn where the
  viewport ended, part-way down the page. That is a capture artifact. Judge layout from viewport shots.
- `networkidle` waits can time out because the app keeps a live `/api/events` connection open. Wait for
  content instead.
- Codex loads `.codex/config.toml` only when the **exact** checkout or worktree path is trusted in
  `~/.codex/config.toml`. A trusted parent such as `/workspace` is not enough. `codex mcp list` shows
  "No MCP servers configured" until the path is trusted.
- Claude Code ignores project permissions until the workspace trust dialog has been accepted once
  interactively. `claude mcp list` shows `⏸ Pending approval` until the `.mcp.json` server is approved.
- `claude -p --allowedTools …` is variadic. Pass the prompt on stdin, or it is taken as a tool name.

## Completion report

Report these fields even when a gate is blocked:

| Field | Required result |
| --- | --- |
| Git | Branch, full commit SHA, push result, remote branch SHA |
| Deployment | User confirmation; expected and observed checkout SHA; running image revision evidence, each stated separately |
| Browser | Runtime, Chrome version, URL access result |
| Coverage | Pages and interactions; desktop/mobile screenshots and observations |
| Diagnostics | Console errors, failed network requests, JavaScript exceptions |
| Evidence | Local screenshot/log paths outside version control or in ignored `qa-artifacts/` |
| Outcome | Defects and fixes; **READY — AWAITING USER-MANAGED DEPLOYMENT**, **PASS**, **FAIL**, or **BLOCKED**, with exact reason |

Do not turn a partial check into **PASS** or claim the new revision was visually verified without enough evidence of the running image. An unproven image revision is an explicit limitation, not a confirmed deployment failure. If the deployment is proven stale, write **BLOCKED — DEPLOYMENT NOT UPDATED**. If the LAN is unavailable, say so separately. These instructions run when an agent performs work; they do not install a self-hosted runner or trigger checks after independent GitHub pushes. Such automation requires a separately authorized CI/runner setup.

## Maintainer references

- [Playwright MCP installation and browser selection](https://playwright.dev/docs/getting-started-mcp)
- [Claude Code project MCP scope and approval](https://code.claude.com/docs/en/mcp)
- [Claude Code project instruction imports](https://code.claude.com/docs/en/memory#import-additional-files)
- [Codex project configuration and trust](https://developers.openai.com/codex/config-basic)
- [Codex MCP configuration](https://developers.openai.com/codex/mcp)
