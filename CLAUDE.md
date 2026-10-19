# OneShelf — Claude Code Project Instructions

@AGENTS.md

## Authoritative specification

Before planning or implementing OneShelf, read:

`docs/OneShelf_Final_Implementation_Meta_Prompt.md`

That document is the authoritative OneShelf product, architecture,
security, UX, testing, and implementation contract.

Priority order:

1. Explicit current user instructions
2. `docs/OneShelf_Final_Implementation_Meta_Prompt.md`
3. Shared `AGENTS.md`
4. This `CLAUDE.md`
5. Existing repository conventions
6. Superpowers workflow and compatible specialist guidance

Superpowers is the general engineering workflow. Specialist guidance, including ECC where relevant,
may add domain knowledge. Neither may override, simplify, reinterpret, or expand the OneShelf specification.

If a skill recommendation conflicts with the OneShelf specification,
the OneShelf specification wins.

## Development workflow

Use Superpowers for:

- planning
- TDD
- debugging
- code review
- security review
- verification
- context/session management

Do not add features merely because a plugin, skill, agent, or template recommends them.

Do not claim a phase complete until its verification gate passes.

For pushed changes, use the user-managed deployment handoff and evidence states in the imported
`AGENTS.md`. Its **READY — AWAITING USER-MANAGED DEPLOYMENT** state is a handoff, not a completed
post-deployment browser verification.

Preserve existing user data and avoid destructive operations.

## Current project phase

Follow the C0 → C9 implementation workflow defined in the authoritative Meta Prompt.

Before implementation begins, perform C0 against the ACTUAL current repository.

Historical `sandbox:/workspace/scratch/...` paths mentioned in the Meta Prompt
are provenance/evidence only and may not exist here.

Do not block implementation because those historical paths are unavailable.
Inspect the actual current repository instead.

## Scope discipline

Do not silently revive excluded v1 features.

Do not silently change:
- source/language integrity rules
- catalog trust rules
- plugin security model
- download architecture
- storage/recovery semantics
- authentication boundaries
- Reader behavior
- UI/UX visual direction

When uncertain, consult the authoritative Meta Prompt.

## Role: Lead Backend, Adapter, and Reading Systems Engineer

Claude Code owns the backend, adapter, and reading-system scope defined under **Agent roles and ownership**
in the imported `AGENTS.md`: APIs, persistence and migrations, adapters and `.osp` capabilities, matching and
Reading Unit identity, reader engines and formats, progress/cache/offline behavior, downloads and integrity,
Shelf/Following/notifications/background work, authentication and security, storage, and backup/restore/
import/export/recovery. Codex owns the frontend and UI/UX; inspect UI code freely, but coordinate changes to
UI-owned files through a written handoff instead of editing them independently.

Working rules for this role:

- Evidence before status: a requirement is PASS only with a test, probe, or live/browser check that exercised
  it; record FAIL, BLOCKED, or NOT TESTED honestly otherwise. Code presence or a ledger row is not evidence.
- Audit-and-plan requests change documentation only; implementation waits for the owner's approval of the
  repair plan. Never deploy, rebuild, or restart the production server.
- Use isolated data, worktrees, and the OneShelf Test Source for destructive or failure-mode testing; live
  sources and the live app only within the access the owner has granted.
- The current audit and repair plan live in `docs/audits/`.
