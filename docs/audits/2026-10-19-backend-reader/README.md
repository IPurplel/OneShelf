# OneShelf backend, adapter and Reader audit — 2026-10-19

**Auditor:** Claude Code (Lead Backend, Adapter, and Reading Systems Engineer).
**Type:** audit and plan only. No application code was changed, and nothing was deployed or restarted.
**Audited revision:** `origin/main` `b9932e1`, on branch `audit/backend-reader-20261019` (this branch adds
only these documents and the role sections in `AGENTS.md`/`CLAUDE.md`).
**Authority:** `docs/OneShelf_Final_Implementation_Meta_Prompt.md` (Master §0–§56, stages C0–C9, INV-1…30).

| Document | Contents |
|---|---|
| [`findings.md`](findings.md) | BE-001…BE-019 (ledger IDs I-91…I-109 in `docs/plan/ISSUES.md`): reproduction, expected vs actual, evidence, root cause, impact, fix, tests |
| [`coverage-matrix.md`](coverage-matrix.md) | Every Master section, the 30 invariants and the C0–C9 gates, with PASS/FAIL/BLOCKED/NOT TESTED/FE and evidence |
| [`adapter-inventory.md`](adapter-inventory.md) | 112 Registry packages (static and packaged tests), the 8 official adapters live, drift |
| [`reader-matrix.md`](reader-matrix.md) | Formats × operations and Reader workflows |
| [`resolution.md`](resolution.md) | **Current state:** how each of the 19 findings was fixed, its regression tests, and its branch/PR |
| [`implementation-log.md`](implementation-log.md) | Phase-by-phase implementation record, merge order, owner actions after deploying |
| [`handoffs-codex.md`](handoffs-codex.md) | Frontend handoffs H-1…H-9 with API contracts, states, tests and acceptance |
| [`repair-plan.md`](repair-plan.md) | Owner actions, 14 work packages in dependency order, regression tests, Codex handoffs, residual risks |

## 1. Executive summary

OneShelf's backend is broad and, in most areas, carefully engineered. The suite is large (1,485 tests pass,
with 90% line coverage). The plugin sandbox and SSRF controls are strong. The catalog-trust, crash-journal,
and event designs are sound. All 112 Registry adapters validate and pass their packaged tests.

The audit nonetheless found **19 reproducible defects**, several of which break core user flows **in
production today**:

1. **Manga, webtoon and comic downloads fail end to end** (BE-002 → BE-003, P1). Search and URL entry never
   apply the adapter's declared defaults, so Works from MangaDex, 3asq, Tapas and WEBTOON are stored as
   `unknown`. The engine then picks a single-file download for an image chapter and fails. On production,
   the 3asq Berserk Work shows **"unknown · Unknown language"**. With the type supplied, the same chapters
   download as valid CBZs. The product path and the live-test path differ, which is why the suite stayed
   green.
2. **Jobs hang forever** (BE-005, P1). Production has **no storage location configured**. A download there
   has been stuck in `PREPARING` because an unexpected exception (here, `RuntimeError: no storage location
   configured`) escapes the engine's handled-error list. Oversized resources and redirect loops strand jobs
   the same way.
3. **A remote session can permanently widen the LAN trust boundary** (BE-001, P1 security), in a way that
   survives LAN Recovery. The exact reproduction is kept out of this public repository until it is fixed. Production has no remote
   access enabled, so this is not exploitable there today. It must be fixed before remote access is turned
   on.
4. **Long operations freeze the whole server** (BE-006, P1). Backup, restore, export, scan and file serving
   run on the event loop. An 82 MB backup stalled every request for 1.06 s, and that scales linearly with
   library size.
5. Data-safety and contract issues follow (P2):
   - Repair deletes the old copy before the new one exists (BE-009).
   - Re-downloading a missing file wedges the commit journal (BE-008).
   - Resume asks for an unsatisfiable byte range (BE-007).
   - Follow can flood "new releases" (BE-010).
   - Downloads and file serving buffer whole resources in RAM (BE-011).
   - Users cannot correct metadata at all (BE-012); a traceability row claims this was verified.
   - There is no format selection (BE-013).
   - Two bundled adapters fail live (BE-014).
6. Minor (P3): backups carry remote-session hashes (BE-015), plus misleading storage and reader errors, an
   unbounded descriptor cache, a preflight that ignores known sizes, and a socket leak on timeout
   (BE-016…019).

**Coverage (computed from the matrix):** 83 section rows give 51 PASS, 23 FAIL, 1 BLOCKED, 3 FE
(frontend-owned) and 5 N/A. The invariants give **26 PASS, 4 FAIL** (INV-4, 17, 19, 30). Stage gates C1 and
C4–C9 have open blocking findings.

**Recommendation:** approve R0 (owner actions) immediately, then WP-1, WP-2, WP-5/6/7 and WP-8 as the first
implementation tranche. Those close every P1. The order and tests are in `repair-plan.md`.

## 2. Method

| Activity | What was done | Evidence (git-ignored, under `qa-artifacts/be-audit-20261019/`) |
|---|---|---|
| Specification | Read the Meta Prompt A–G and Master §0–§56 in full (§32 visual detail skimmed: Codex scope) | — |
| Baseline suite | `pytest -m "not browser and not live" --cov=oneshelf`, then browser-marked tests | `pytest-main.log` (1,485 passed, 1 skipped, 90% coverage), `pytest-browser.log` (8 passed) |
| Unmerged branch | Full suite on `origin/feature/text-reading-units` `2267bc8` | `pytest-textunits.log` (exit 0). Branch is 9 ahead and 44 behind `main` (risk, see repair plan) |
| Source inspection | Network policy, egress proxy, HTTP client, access boundary and auth, plugin package and runtime, catalog trust, download engine and commit journal, reader, follow, backup and restore, sessions, event bus, migrations | `notes/candidates.md` |
| Probes | 8 targeted reproductions against the project's own fixtures and Test Source | `probes/*.py` |
| Registry sweep | All 112 OneShelf-Adapters packages: hash check, `load_package`, packaged tests | `registry-sweep/sweep-main.json` |
| Live adapters | Isolated local instance on bundled adapters. 3 passes of search, open, catalog, reader page and one download per source, with each artifact opened and validated | `live/live-*.json`, `local-data/`, `library/` |
| Project live suite | `ONESHELF_LIVE_SOURCES=1 pytest tests/live` | `pytest-live.log` (6 passed, 1 skipped, 1 failed: BE-019) |
| Production (read-mostly) | `deployed-revision.sh`, read-only API state, `browser_check.py` over 9 routes × desktop and mobile, then authorized reversible mutations | `browser-live/`, `live-mutations.md` |

### Production verification (http://192.168.8.32:8420/)

- **Frontend revision:** `scripts/agent/deployed-revision.sh origin/main` → **MATCH** with `b9932e1`
  (`index-CkK_OKPZ.js`, `index-DMhz3blq.css`). This is frontend evidence only.
- **Backend:** `/api/ready` reports schema v20, migrations 0 pending, and recovery order
  `recover_jobs → recover_commits → reconcile → clean_staging`. That matches `main`'s schema, but the backend
  image commit is **unproven**, because the app exposes no version.
- **Browser:** Google Chrome 155, 18 page loads (Home, Search, Shelf, Following, Downloads, Sources,
  Settings, a Work and the Reader, at 1440×900 and 390×844). **0 console errors, 0 page exceptions, 0
  failed requests.** The 3asq Reader renders an Arabic page online. The Work page shows "unknown · Unknown
  language" (BE-002). Downloads shows a job "waiting" forever (BE-005).
- **Mutations (all logged in `live-mutations.md`):**
  - Follow Berserk, then check, then Unfollow. Result: baseline 404, `up_to_date`, no flood. Unfollow left
    Shelf, Favorite and Pin intact. State restored.
  - One Library Backup, created and verified `ok: true`. It is not removable via the API, and retention
    covers it.
  - The authorized public-domain download was **not** queued. Production has no storage location, so it
    would only have reproduced BE-005, which is already evidenced by the existing stuck job.

## 3. Expiring-URL check (BE-017 hypothesis)

The MangaDex "Oneshot" unit's page descriptors were fetched at 19:50:04 UTC and kept in the per-process
cache. Pages 2–4 fetched at 20:02 UTC, and pages 5–8 (not fetched before) at 20:27:13 UTC, all returned 200
`origin=online`. Pages 9–10 returned 404 because the unit has 8 pages. **The URLs did not expire within 37
minutes, so expiry is NOT CONFIRMED.** BE-017 rests on its other evidence: the hidden upstream status, the
unbounded cache, and the disabled-source behaviour.

## 4. Environment

Fedora (Linux 7.2), Python 3.14.7, venv built from `backend/requirements.lock`, Playwright Chromium and Google
Chrome 155. No Docker or Podman. Outbound internet is available. The production app is reachable on the LAN.
Audit worktrees: `/tmp/oneshelf-be-audit-20261019` (branch) and `/tmp/oneshelf-be-audit-textunits`
(detached). The primary checkout `Oneshelfv1/` and its uncommitted changes, plus all other worktrees, were
not modified.
