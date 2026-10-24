# Noor Book Reader Implementation Plan — Conditional Draft

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Open Noor Book's available Read content inside OneShelf using the source's real page resources and OneShelf's reader controls and progress.

**Architecture:** Scrapling parses source-provided reader responses into complete ordered image descriptors. Core owns transport and safe SVG-to-raster normalization; existing Reader Cache and image reader present pages. Production implementation depends on proving the request sequence and approving the Core normalization contract.

**Tech Stack:** Existing Python backend, Scrapling, declarative `.osp` recipes, Core HTTP/browser infrastructure, React reader. The owner approved pinned `resvg_py==0.5.0` for the isolated Core normalizer.

**Spec:** [Investigation and proposed design](../specs/2026-10-24-noorbook-reader-design.md), plus `docs/OneShelf_Final_Implementation_Meta_Prompt.md` §§12, 19, 26–27 and final section G.

## Global Constraints

- The user subsequently approved implementation and Claude Code coordination on 2026-10-24. Registry publication remains separate.
- Claude owns backend/adapters/Reader Core; Codex owns frontend. The [written owner contract](../coordination/2026-10-24-noorbook-backend-review.md) authorizes Codex to implement the scoped Core changes in an isolated worktree.
- `No stealth/anti-bot bypass.` Preserve the declarative package boundary and controlled Core transport.
- Discover actual source URLs, selectors and completion evidence; never hardcode this session's opaque tokens or infer all page URLs from one example.
- Reading uses temporary Reader Cache by default; preserve the explicit existing auto-download preference.
- Preserve identity, library data, existing visual design, content isolation and other agents' changes. Use synthetic fixtures in version control; keep actual source pages and screenshots ignored.
- User-managed production deployment only, followed by the repository's browser verification gate.

## Review Focus

- Lazy loading exposes only a subset of image URLs; completion must include the 100→101 boundary and final page.
- Fresh Core sessions can fail while an existing browser session works; transport/session equivalence must be demonstrated.
- SVG is active structured content, and extracting its JPEG can omit overlays; conversion must be isolated and visually faithful.
- Expiring resource URLs and interrupted group requests must not corrupt unit identity, progress or completeness.
- A working title does not imply preview/restricted titles, other formats, search or downloads are supported.

## Execution boundary

Task 1 remains blocked: controlled Core HTTP retrieval failed before a response, and the standard Core browser now launches but reports `net::ERR_CONNECTION_CLOSED` on source navigation. The owner explicitly approved Task 2 independently: `normalize_page_image(data: bytes) -> bytes`, pinned `resvg_py==0.5.0`, a Linux worker limited to 256 MiB, 8 seconds and 8M output pixels, plus rejection of incomplete descriptor results before caching. Tasks 3–4 remain conditional on a proven source request sequence and a second title; no adapter or source-support claim is authorized by synthetic Core tests.

### Task 1: Establish a reproducible extraction and rendering contract

Owner: Claude/backend, with Codex supplying the saved UI evidence. This gates Tasks 3–4; the owner approved Task 2 independently.

Files: read `backend/oneshelf/sources/browser_fetcher.py`, `backend/oneshelf/plugins/schema.py`, `backend/oneshelf/plugins/runtime.py`, `backend/oneshelf/net/http.py`, `backend/oneshelf/integrity/validators.py`; update the design document with verified findings. Keep captured source fixtures under ignored `qa-artifacts/noorbook-2026-10-24/`.

Consumes: supplied title URL and observed DOM selectors/resource paths in the design. Produces: a sanitized request/response trace, declarative feasibility decision, completeness algorithm, session rules and owner-approved SVG normalization design.

- [ ] Capture the ordinary Read interaction and group requests with a working network-inspection browser. Record actual HTTP methods, request fields, response type and the origin/lifetime of required opaque values; remove credentials and live tokens from publishable evidence.
- [ ] Replay the observed flow through Core transport, starting with normal HTTP and using the existing scoped session mechanism only where demonstrated necessary. Verify source resource retrieval separately from HTML retrieval.
- [ ] Parse captured responses using `scrapling.parser.Selector`. Account for both group controls and lazy page slots. Prove all 111 descriptors in order without inventing URLs or downloading every body. Verify representative boundary resources and report any missing slots as incomplete.
- [ ] Reopen the reader with a fresh context and check whether resource URLs remain usable or need refresh. Establish a bounded renewal path, not indefinite retry.
- [ ] Repeat on another available title and an unavailable/preview case. Record capability states separately; do not implement site search as a prerequisite for URL-only reading.
- [ ] Determine whether current recipe extraction/pagination can express the flow. Current `fetch: browser` is GET-only and cannot click Read. If a new Core primitive is required, write its bounded schema, behavior and error contract for owner approval, or report Native Adapter Review Required.
- [ ] Evaluate a safe SVG normalizer using synthetic fixtures with embedded raster, vector overlays and clipping. Reject scripts, external URLs, XML entities, foreign content and oversized input/output. Select a maintained renderer, pin its version, define memory/pixel/time limits and confirm deployment packaging before proposing its addition.
- [ ] Update this plan with exact interfaces, new dependency, request contracts, test names and commands. Stop implementation if controlled transport or safe rendering cannot be demonstrated.

Existing reproducible investigation checks (PowerShell, repository root):

```powershell
& backend/.venv/Scripts/python.exe qa-artifacts/noorbook-2026-10-24/parse_reader.py
$env:PYTHONPATH='G:/work/OneShelf/backend'
& backend/.venv/Scripts/python.exe qa-artifacts/noorbook-2026-10-24/inspect_svg.py
```

Expected now: 2 groups, 11 final-group slots, 8 populated URLs in the saved snapshot; actual SVG rejected with `UnidentifiedImageError`. These prove the investigation findings, not working OneShelf support.

### Task 2: Implement the approved Core image normalization boundary

Owner: Claude; scoped implementation delegated to Codex through the written coordination contract. Approved independently of Task 1.

Intended files: new `backend/oneshelf/reader/page_image.py`; integrate through `backend/oneshelf/reader/service.py`; dependency/package changes only where the approved renderer requires them. Avoid broad weakening of `backend/oneshelf/integrity/validators.py` or content headers.

Tests: proposed `backend/tests/unit/reader/test_page_image.py`; extend `backend/tests/integration/reader/test_reading.py` with synthetic source resources.

Consumes: original bytes fetched under the source's Core policy. Produces: validated raster page bytes for the existing reader page/cache contract, or an explicit unsupported/invalid resource result. The final function signature and renderer budgets must be supplied by Task 1 before coding.

- [x] Write failing tests for ordinary raster pass-through, faithful approved SVG rendering, clipped/transformed embedded images and vector overlays.
- [x] Write rejection tests for scripts/event handlers, external references, entities, foreign objects, invalid dimensions and bounded execution. Confirm invalid inputs never enter Reader Cache.
- [x] Implement the approved normalizer and integrate it before page-cache insertion. Keep transport and source sessions outside the renderer.
- [x] Add a regression where reader extraction returns 100 entries with `complete=False` after the second group fails. Assert a clear failure, no descriptor-cache insertion and no successful partial page-list response. Enforce that check in `ReaderService._online_descriptors()`; verify existing complete-source fixtures still succeed. The current implementation ignores this evidence, so adapter tests alone are insufficient.
- [x] Verify cached/reopened pages, page cancellation, expired descriptor refresh and no permanent asset/job creation under default reading settings.
- [x] Run the new tests plus relevant reader and integrity regressions; review and commit only this scoped Core change once tests pass.

### Task 3: Build and validate the Noor Book URL-reader adapter

Owner: Claude. Conditional on a proven declarative flow; otherwise return to Task 1's native review decision.

Repository: `OneShelf-Adapters` (the existing ignored clone is `qa-artifacts/OneShelf-Adapters`; choose an appropriate isolated checkout at implementation time).

Proposed package files under `adapters/community/oneshelf.noorbook/`: `manifest.yaml`, `source.yaml`, `rights.yaml`, `recipes/work.yaml`, `recipes/catalog.yaml`, `recipes/reader.yaml`, and sanitized synthetic fixtures/tests following current repository conventions. Create no unsupported search/download recipe merely to fill a template.

Consumes: proven requests and session rules. Produces: one book `UnitDescriptor` and complete ordered `ResourceDescriptor(url, index, page_label)` entries. Declare only verified capability permissions and required domains.

- [ ] Write failing fixture tests for both observed groups, lazy empty slots, first/last page, duplicate responses, failed second group, wrong-title responses and no Read/preview state.
- [ ] Implement metadata, single-book unit and reader recipes from the verified contract. Keep source page labels and stable book identity separate from expiring URLs.
- [ ] Validate complete/incomplete evidence and scope auth per capability. Reject unrelated cover/ad assets and undeclared redirects.
- [ ] Run adapter tooling (`./tools/check-adapter oneshelf.noorbook` from the adapter repository, matching the inspected CLI contract) and Core integration tests against the approved Core revision. Perform a bounded live check on representative titles.
- [ ] Review package permissions and source status. Commit the package only after verification. Installation, bundling and public registry submission remain distinct decisions.

### Task 4: Verify OneShelf reading and perform the deployment handoff

Owner: Codex for frontend; Claude for any Core defect. Prefer existing UI without redesign.

Files to inspect: `frontend/src/features/reader/ReadRoute.tsx`, `SequentialReader.test.tsx`, `pagePreloads.ts`; `backend/tests/integration/reader/test_reading.py`. Change frontend files only for a demonstrated contract or presentation gap. Keep screenshots/logs ignored.

- [ ] With isolated local data, open the supplied URL through the approved source flow; verify one book unit and one ordered page sequence. Confirm pages 1, 100, 101 and 111, zoom, RTL controls, resume and cache behavior.
- [ ] Test interrupted loads, expired source links/session, partial groups and unavailable titles. Ensure status messages do not claim the book is complete or downloaded when it is not.
- [ ] Run relevant backend/adapter checks and frontend test/build checks if frontend changes. Review exact changes, commit/push only approved work and verify the remote SHA.
- [ ] Report **READY — AWAITING USER-MANAGED DEPLOYMENT**. Do not update or restart the production server.
- [ ] After user deployment confirmation, use project Playwright Chrome at `http://192.168.8.32:8420/`. Inspect desktop/mobile screenshots and affected interactions, console errors, exceptions and failed requests. Record checkout and running-image evidence separately from the remote commit.
- [ ] Resolve blocking defects through the same test/push/manual-deployment/browser cycle. Claim PASS only for behavior and revision actually verified.

## Plan self-review

The plan includes three observed integration gaps (GET-only browser recipes, SVG rejection and discarded completeness evidence), lazy pagination, scoped sessions, stable unit identity, no implicit downloads, ownership and deployment gates. User implementation authorization and owner coordination now permit the independent Core work. Source request bodies and token lifecycle remain unproven, so the adapter and end-to-end source milestone remain blocked.
