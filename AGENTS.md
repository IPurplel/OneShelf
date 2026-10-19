# OneShelf agent instructions

These instructions apply to Codex, Claude Code, and other coding agents working in this repository. Read `docs/OneShelf_Final_Implementation_Meta_Prompt.md` before planning or changing OneShelf behavior; it remains the authoritative product and architecture specification. Follow explicit current user instructions first. Preserve existing data, project conventions, and the current visual identity.

Use Superpowers as the sole general software-development process for planning, implementation, debugging, tests, verification, review, worktrees, and branch completion. Specialist guidance may add domain knowledge without replacing that workflow.

## Shared browser verification gate

Follow [the browser verification procedure](docs/agent-browser-verification.md) for every change committed and pushed to GitHub. Run relevant local checks, commit and push using the repository's existing Git workflow, and verify the expected SHA is on the remote branch. Determine whether the running deployment incorporates that SHA. A push alone does not update the running container. Use the documented deployment procedure only when authorized.

Once the updated deployment is running, open `http://192.168.8.32:8420/` in Google Chrome through the project Playwright MCP server. Capture and inspect screenshots for user-facing changes, interact with affected functionality, and inspect console messages, failed network requests, and JavaScript exceptions. Check mobile layout when relevant. Backend changes that alter observable behavior also require browser verification. Do not treat HTTP probes, source inspection, or unit tests as a substitute for opening the real application.

If the deployed revision is stale, report **BLOCKED — DEPLOYMENT NOT UPDATED**. If the private LAN or browser is inaccessible, report the exact blocker. Never claim visual verification based on an old deployment or an inaccessible browser. Record defects, fix them within the authorized scope, and repeat the test, Git, deployment, and browser cycle until relevant blocking defects are resolved.

Every completion report must state the commit SHA and branch, remote push and revision result, deployment revision status, browser accessibility, pages and interactions tested, desktop/mobile results, console/network findings, evidence paths, defects/fixes, and final **PASS**, **FAIL**, or **BLOCKED** status. Keep screenshots and temporary QA artifacts outside version control or in ignored directories; never commit credentials, session data, private browser profiles, or sensitive screenshots.

## Concurrent work and access

Respect other agents' branches, worktrees, and uncommitted changes. Coordinate edits to shared configuration files; never overwrite another agent's work or force-push without explicit authorization. Browser debugging endpoints must stay private. The OneShelf URL is on a private LAN: when a runtime cannot reach it, report that limitation and never expose the application publicly as a workaround. These repository instructions do not create unattended GitHub event automation.
