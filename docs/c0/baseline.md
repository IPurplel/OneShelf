# C0 — Current Baseline

Recorded: 2026-09-17 · Phase: C0 (inspection only; no application code, dependencies or scaffold)
Authority: `docs/OneShelf_Final_Implementation_Meta_Prompt.md` §C0.1, §C0.3–C0.5

## 1. Repository

| Item | Finding |
|---|---|
| Path | `/workspace/Oneshelfv1` |
| Branch / HEAD | `main` / `1a7d872` ("chore: normalize docs path and main branch") |
| History | 2 commits (`11a447d` initialize specification, `1a7d872`) |
| Remote | none configured |
| Working tree at C0 start | clean |
| Tracked files | `CLAUDE.md` (70 lines), `.claude/settings.json` (only enables `ecc@ecc`), `docs/OneShelf_Final_Implementation_Meta_Prompt.md` (4,195 lines) |
| AGENTS.md / nested instructions / README | none |
| Manifests, lockfiles, migrations, tests, Docker/deploy config, source code | none |

## 2. Specification integrity

The Master Specification embedded in Meta Prompt §F (file lines 323–4125, between the BEGIN/END markers) hashes to SHA-256
`29954d4c34f32725b900a59823afddb31b576127ffbf028ccfa46389b746d3de`. That **exactly matches** the hash Meta Prompt §B1 records for the original `OneShelf_Master_Spec_v1(2).md` (3,803 lines), so the embedded Master is verbatim.

Reproduce:
```sh
sed -n '323,4125p' docs/OneShelf_Final_Implementation_Meta_Prompt.md | sha256sum
```

## 3. Instructions in force

Priority order (CLAUDE.md, consistent with Meta Prompt §A):
1. Explicit current user decisions (recorded below as UD-n)
2. Meta Prompt, with the Master in §F taking precedence within it
3. `CLAUDE.md`
4. Existing repository conventions (none exist yet)
5. ECC / Superpowers workflow tooling (workflow only; they can't change product scope)

Active workflow hooks: ECC GateGuard (fact-forcing gate before first Bash and first Write per file). Workflow only; it doesn't conflict with anything in the Master.

### User decisions recorded during C0

| ID | Decision |
|---|---|
| UD-1 | Backend is a Python core (single ASGI modular monolith; Scrapling/Playwright in-process under Core control). Frontend is a React + TypeScript + Vite SPA. Resolves the stack question Meta Prompt §B4 held for review. |
| UD-2 | `/workspace/Oneshelf` (older UI/UX brief + `oneshelf-ui` demo) is historical reference only. Nothing is ported; conflicts are recorded in the ledger. |
| UD-3 | The user will add the approved visual reference (V, `oneshelf-library-home.png`) under `docs/reference/` before C2. |
| UD-4 | C0 findings approved, including the proposed resolutions A1–A5 in `conflict-review-ledger.md`. C1 needs separate explicit authorization. |

## 4. Historical / external context

| Location | Status |
|---|---|
| `sandbox:/workspace/scratch/...` (Meta Prompt §B1 evidence paths M, A, R, R1–R6, P, V) | **Not present.** `/workspace/scratch` doesn't exist. They're treated as provenance only, per CLAUDE.md. |
| `/workspace/Oneshelf/OneShelf-UIUX-Master-Prompt.md` | Present (306 lines). Older UI/UX design brief, superseded by Master §32 where they conflict (ledger U01–U11). |
| `/workspace/Oneshelf/oneshelf-ui/` | Present, not a git repo. 811 lines of source: React 19, Vite 8, Tailwind 4, Vitest, Playwright, oxlint, TypeScript 6; hard-coded fictitious works; Favorites/Pins/Completed kept in `localStorage` (`oneshelf-demo-v1`); Node `http` server stub where every service reports `unimplemented`. Has `node_modules/` and `dist/`. Reference only (UD-2); **not modified**. |
| `/workspace/rose-room-sunset` | Unrelated to OneShelf; not inspected. |

## 5. Application state, data, storage and credentials (C0.3)

- No OneShelf database, storage roots, caches, plugin directories, session stores, key files, backups or mounted library volumes exist for this repository.
- No credentials or secrets were found or printed.
- **Nothing to preserve** other than the tracked docs and the sibling reference directory, which is read-only for this project.

## 6. Existing features (C0.4)

None. No implementation exists to check against the Master, and no old branches exist to integrate. The build follows the Master from scratch (not a rewrite forced by an older prompt; there's simply nothing here yet).

## 7. Build / test baseline (C0.5)

| Command | Result |
|---|---|
| Build | none defined |
| Tests | none defined, **0 tests** |
| Lint / typecheck | none defined |

So there are **no pre-existing failures**. From C1 on, any failing test is introduced by new work. Historical pass counts from the legacy checkout (R) are not this baseline.

## 8. Host environment

| Tool | Version / state |
|---|---|
| OS | Linux 7.1.10 (Fedora 44) |
| Python | 3.14.7 (system), pip 26.0.1 |
| Python `sqlite3` | SQLite 3.51.2, **FTS5 available** (verified by creating an fts5 virtual table in memory) |
| Node / npm | 22.23.1 / 10.9.8 |
| git / gh | 2.55.0 / 2.97.0 |
| Absent | docker, podman, sqlite3 CLI, uv, pnpm |

## 9. Environment blockers (recorded; independent work continues)

| ID | Blocker | Affected gate | What would clear it |
|---|---|---|---|
| EB-1 | No container runtime on host | C9 Docker build/restart/recreation verification | A Docker-compatible runtime in the verification environment |
| EB-2 | Visual reference V missing | C2 "responsive Arabic/English visual checks against the reference" | User adds the image under `docs/reference/` (UD-3) |
| EB-3 | Outbound access to live sources not yet checked | Live integration checks in C3/C4/C5/C9 for the §41 sources | Checked at the start of the first live-source slice; results go in the source-capability evidence ledger |
| EB-4 | Host Python 3.14 may be newer than some dependencies support (Scrapling, Playwright, lxml, WebAuthn) | C1 dependency selection | C1 pins a supported Python for dev and the container, based on current official docs |
