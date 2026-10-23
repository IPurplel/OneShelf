# OneShelf agent instructions

These instructions apply to Codex, Claude Code, and other coding agents working in this repository. Read `docs/OneShelf_Final_Implementation_Meta_Prompt.md` before planning or changing OneShelf behavior; it remains the authoritative product and architecture specification. Follow explicit current user instructions first. Preserve existing data, project conventions, and the current visual identity.

Use Superpowers as the sole general software-development process for planning, implementation, debugging, tests, verification, review, worktrees, and branch completion. Specialist guidance may add domain knowledge without replacing that workflow.

## User-managed production deployment

The user manually updates the OneShelf server at `192.168.8.32` after GitHub pushes. Neither Codex nor Claude Code may deploy, rebuild, restart, or update that production server unless the user explicitly requests it. A push does not prove a deployment. After pushing and verifying the remote SHA, report **READY — AWAITING USER-MANAGED DEPLOYMENT** and tell the user the change is ready for their update. Do not treat an ordinary pending manual deployment as an application or push failure.

The user's confirmation that they updated the server is sufficient to start browser QA. Track GitHub SHA, user deployment confirmation, deployment checkout SHA, running image revision, and browser findings as separate evidence. A matching checkout SHA and healthy container do not independently prove the running image revision. If image revision remains unproven, say so without calling the deployment failed; do not claim that the new revision was visually verified unless its presence in the running app is sufficiently established. Use deployment-host evidence the user provides. Do not repeatedly attempt SSH when authorized credentials are unavailable.

## Shared browser verification gate

Follow [the browser verification procedure](docs/agent-browser-verification.md) for every change committed and pushed to GitHub. Run relevant local checks, commit and push using the repository's existing Git workflow, and verify the expected SHA is on the remote branch. Wait for the user's manual deployment confirmation before treating browser checks as post-change verification.

After the user confirms deployment, open `http://192.168.8.32:8420/` in Google Chrome through the project Playwright MCP server. Capture and inspect screenshots for user-facing changes, interact with affected functionality, and inspect console messages, failed network requests, and JavaScript exceptions. Check mobile layout when relevant. Backend changes that alter observable behavior also require browser verification. Do not treat HTTP probes, source inspection, or unit tests as a substitute for opening the real application.

Report **BLOCKED — DEPLOYMENT NOT UPDATED** only when evidence establishes a stale deployment, not merely because the user has not yet performed the manual update or image provenance is unknown. If the private LAN or browser is inaccessible, report the exact blocker. Browser checks of an accessible app may be reported as such, but never label them verification of a new revision without sufficient deployment evidence. Record defects, fix them within the authorized scope, and repeat the test, push, user deployment handoff, and browser cycle until relevant blocking defects are resolved.

Every completion report must state the commit SHA and branch, remote push result, user deployment confirmation, checkout SHA evidence, running image revision evidence, browser accessibility, pages and interactions tested, desktop/mobile results, console/network findings, evidence paths, defects/fixes, and final **READY**, **PASS**, **FAIL**, or **BLOCKED** status as appropriate. Keep screenshots and temporary QA artifacts outside version control or in ignored directories; never commit credentials, session data, private browser profiles, or sensitive screenshots.

## Concurrent work and access

Respect other agents' branches, worktrees, and uncommitted changes. Coordinate edits to shared configuration files; never overwrite another agent's work or force-push without explicit authorization. Browser debugging endpoints must stay private. The OneShelf URL is on a private LAN: when a runtime cannot reach it, report that limitation and never expose the application publicly as a workaround. These repository instructions do not create unattended GitHub event automation.

## Agent roles and ownership

Ownership decides who changes a file first; it never overrides the authoritative specification, the
user-managed deployment handoff, or the concurrency rules above.

- **Claude Code — Lead Backend, Adapter, and Reading Systems Engineer.** Owns backend architecture and APIs;
  the database, schema, migrations, persistence and transactions; every source adapter and `.osp` plugin
  capability (search, parsing, catalogs, language support, pagination, downloads); Work matching, Source
  Tracks and Reading Unit identity; the reader engines and formats (PDF, EPUB, CBZ, text units; sequential,
  RTL, LTR and vertical where supported) on the backend side; reading progress, history, Reader Cache, offline
  behavior and resume; download queues, retries, cancellation and file integrity; Shelf, Following,
  notifications and background processes; authentication, access control, security and storage; backups,
  restore, import, export and recovery.
- **Codex — Frontend and UI/UX.** Owns `frontend/` and the visual and interaction design. Backend owners may
  read UI code, and propose or hand off UI changes, but coordinate before editing UI-owned files.
- Cross-boundary work (an API change that a screen depends on, or a screen that needs new backend data) is
  agreed through a written handoff in `docs/` or the relevant audit, naming the contract both sides
  implement. Audits and repair plans are owner-approved before code changes begin.
## Frontend ownership and audit boundary

Codex is the lead frontend engineer and UI/UX auditor. Codex owns frontend architecture and components; visual identity, typography, layout, responsiveness, and browser performance; navigation, forms, menus, dialogs, and feedback states; keyboard, touch, and rendered accessibility; the Home, Search, My Shelf, Following, Downloads, Sources, Settings, first-run, notifications, and Needs Attention interfaces; and Reader presentation and controls. Preserve the approved OneShelf visual reference and authoritative specification rather than applying a generic redesign.

Use UI/UX Pro Max for product UI direction, frontend-design-codex for frontend implementation and browser polish, and frontend-a11y for rendered accessibility. Superpowers remains the sole general software-development process.

Claude Code owns backend APIs and services, adapters, download and database internals, and the core Reader engine. Codex may inspect those files to diagnose a UI symptom, but must coordinate any proposed backend or Reader-engine change with Claude Code and must not edit Claude-owned implementation files without that coordination. Record cross-boundary findings with a reproducible UI symptom, relevant API or Reader evidence, and the required contract or behavior.

For an audit-only request, report confirmed defects, limitations, and a repair plan without changing application behavior. Use real browser interactions and isolated fixtures for state-changing scenarios; never alter the owner's real library to create an audit state. Keep screenshots and browser artifacts in ignored directories, and distinguish the live deployment's observed behavior from any unverified source or running-image revision.
