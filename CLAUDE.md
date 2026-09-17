# OneShelf — Claude Code Project Instructions

## Authoritative specification

Before planning or implementing OneShelf, read:

`docs/OneShelf_Final_Implementation_Meta_Prompt.md`

That document is the authoritative OneShelf product, architecture,
security, UX, testing, and implementation contract.

Priority order:

1. Explicit current user instructions
2. `docs/OneShelf_Final_Implementation_Meta_Prompt.md`
3. This `CLAUDE.md`
4. Existing repository conventions
5. ECC / Superpowers skills, rules, agents, and workflow recommendations

ECC and Superpowers are engineering workflow tools only.
They MUST NOT override, simplify, reinterpret, or expand the OneShelf specification.

If an ECC or Superpowers recommendation conflicts with the OneShelf specification,
the OneShelf specification wins.

## Development workflow

Use ECC and Superpowers where useful for:

- planning
- TDD
- debugging
- code review
- security review
- verification
- context/session management

Do not add features merely because a plugin, skill, agent, or template recommends them.

Do not claim a phase complete until its verification gate passes.

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
