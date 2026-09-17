# C0 — Conflict & Review Ledger

Recorded: 2026-09-17 · Authority: Meta Prompt §C0.2, §B2–B5, §D3
Rule: the Master (Meta Prompt §F) wins over any older material. Conflicts the Master already resolves are not reopened. Items held for review stay outside mandatory v1 scope unless a later explicit user decision adopts them.

Dispositions: **Resolved (Master)** · **Resolved (user decision)** · **Approved resolution** (C0 proposal approved by the user, UD-4) · **Held for review** (not in v1 scope) · **Constraint** (binding design consequence of the Master)

---

## 1. Resolved by the Meta Prompt (accepted as-is)

| ID | Summary | Master authority | Disposition |
|---|---|---|---|
| C01 | Reader is core v1, not optional | §§26–27, 54, 56 | Resolved (Master) |
| C02 | Keep the approved forest-green/cream/olive/wood identity; no redesign | §§32, 54, 56 | Resolved (Master) |
| C03 | No application-wide light/dark/system theme switcher; reader backgrounds and EPUB theme remain | §§26, 32, 56 | Resolved (Master) |
| C04 | Nav: Home, Search, My Shelf, Following, Downloads, Sources, Settings | §32 | Resolved (Master) |
| C05 | No profile/avatar; Notifications + Needs Attention (hidden at zero) | §§2.2, 32.2, 44 | Resolved (Master) |
| C06 | Use My Session supported; no access-control bypass | §§9–14, 41, 48 | Resolved (Master) |
| C07 | Remote passkey subsystem is mandatory; LAN trusted | §§28–29 | Resolved (Master) |
| C08 | Community plugins are declarative `.osp`; no executable adapters | §§9–12, 48–49 | Resolved (Master) |
| C09 | No title stemming (incl. Arabic article stripping); loose `ة ↔ ه` | §§6.3, 49 | Resolved (Master) |
| C10 | Numbers are never Reading Unit identity | §§4–6, 20, 26.13 | Resolved (Master) |
| C11 | No stealth / CAPTCHA bypass | §§12, 14, 49 | Resolved (Master) |
| C12 | Backups exclude sessions, keys, browser profiles; consistent DB snapshot | §§13, 18, 33 | Resolved (Master) |
| C13 | Defaults: HTTP 4, Browser 1, global governor | §§15–16, 42 | Resolved (Master) |
| C14 | Ranking tiers: exact → normalized → alias → phrase/prefix → all-token → substring/trigram → fuzzy | §6.4 | Resolved (Master) |
| C15 | No automatic persistent recent searches | §7 | Resolved (Master) |
| B2-note | Matcher telemetry and browser notifications excluded | §§0, 6.10, 49, 56 | Resolved (Master) |

Historical implementation gaps (Meta Prompt §B3: in-memory queue, download-based Shelf membership, plaintext cookies, pagination completeness) are **not requirements**. There's no legacy code in this repository, so the corresponding Master requirements are simply built as specified and traced in `traceability.md`.

## 2. Resolved by user decision during C0

| ID | Topic | Source | Decision |
|---|---|---|---|
| UD-1 | Framework/stack (Meta Prompt §B4, first bullet, held for review) | Meta Prompt L84; `/workspace/Oneshelf/oneshelf-ui/server/*.ts` (Node stub) | **Python core** backend; React + TypeScript + Vite frontend. Rationale: Master §§9.3, 12 put Scrapling (Python) inside Core, so one runtime keeps one enforcement point for network/filesystem/session policy. |
| UD-2 | Treatment of `/workspace/Oneshelf` | external directory | Historical reference only; nothing ported |
| UD-3 | Visual reference V missing | Meta Prompt §B1 row V | User supplies it under `docs/reference/` before C2 |

## 3. Newly found conflicts — older UI/UX brief

Source: `/workspace/Oneshelf/OneShelf-UIUX-Master-Prompt.md` (306 lines; not tracked in this repo).

| ID | Brief says (line) | Master resolution | Disposition |
|---|---|---|---|
| U01 | Primary nav "Home, Search/Discover, My Shelf, Following, Downloads, Sources, Notifications, Settings" (L40) | 7 destinations; Notifications/Needs Attention top-right, not primary nav (§32.1, §32.2, §44). Mobile "More" includes Notifications (§32.21). | Resolved (Master) |
| U02 | Wooden shelf is Home only; all other screens "wireframe-neutral"; "Do NOT choose the visual theme" (L91, L300–302) | Approved identity applies to the whole app; shelves on Home, My Shelf and selected Discover/Collection; system screens use warm paper/card language (§32, §32.5, §54) | Resolved (Master) |
| U03 | Home is a full shelf wall with rows Continue Reading, New Releases, Recently Added, **Recently Downloaded**, Pinned, Favorites, plus conditional **Active Downloads / Downloads With Issues / Reconnect Required / Storage Warning** shelves; no Hero (L61–84) | Home hierarchy: welcome heading, subtitle, large Hero, Continue Reading, Trending (if available), Latest Releases (if available), Recently Added, other library sections only when useful (§32.3–32.4, §31). Operational problems go to Needs Attention (§32.2, §44). Home must not become a technical dashboard. | Resolved (Master) |
| U04 | Books/novels/papers as standing spines with cover on hover; leaning/overlapping items (L66–67, L81) | Cover remains dominant on Work cards (§32.6). Not specified by Master. | Held for review |
| U05 | Auto-download engagement "~10–15% … may be finalized/configurable" (L122) | ~12% plus genuine reading interaction (§19, §42) | Resolved (Master) |
| U06 | Reader Cache assets "may be reused for a later download after validation" (L121, L222) | Not adopted. Reader Cache ≠ permanent download (§26.20); no hidden temporary download behavior (§34.3). Any reuse would need to preserve Extraction Contract and integrity rules. | Held for review |
| U07 | Matching labels "Verified Match / Possible Match / Distinct Work" (L48) | Compatible presentation of Hard Mapping / Soft Group (§6.6); Master doesn't name these labels | Held for review |
| U08 | Notification classes Critical / Important / Info (L178) | Important / Informational / non-notifying background events (§30.1) | Resolved (Master) |
| U09 | Storage: "Never auto-switch when one is full — offer the user a choice" (L186) | Master: reserve pauses new automatic/background writes, never auto-deletes (§24.5); no hidden behavior (§3.4). Automatic root switching isn't specified, so it's not implemented. The explicit "offer a choice" UI isn't required. | Held for review |
| U10 | Downloads "optional priority" control (L144) | Master controls: pause, resume, cancel, retry, reorder (§16.1) | Held for review |
| U11 | Following state "Check Delayed" (L138) | Master: Last Attempted / Last Successful, health states (§20, §21) | Held for review |
| P-UI | `oneshelf-ui/src/library.ts`: hard-coded demo Works; library state in `localStorage` | C2 forbids fictitious books/statistics; progress/Shelf state lives in SQLite (§22, §26.23); no auth tokens in Web Storage (§28.6) | Resolved (user decision UD-2): not ported |

`CLAUDE.md` vs Meta Prompt: no conflict. CLAUDE.md's precedence (current user instructions > Meta Prompt > CLAUDE.md > conventions > ECC/Superpowers) matches Meta Prompt §A.
ECC/Superpowers: no conflict found. Their recommendations (e.g. coverage targets, extra agents/features) never add product scope.

## 4. Gaps and ambiguities not settled by the Master — approved resolutions (UD-4)

| ID | Gap | Master refs | Approved resolution |
|---|---|---|---|
| A1 | Plugin Registry is the "primary" install path, but no registry endpoint, index protocol, signing authority or submission target exists. The Master also forbids cloud dependence and publishing plugins during verification. | §10, §12.2–12.3, §2.1; Meta Prompt C9 | Registry client for a **static index at a configurable URL**; **no public registry URL shipped by default**. Hash always verified; signature verified when the index publishes publisher keys. Tests use a local fixture registry. "Registry submission" produces a validated submission bundle plus instructions; no network publish. Local `.osp` upload works without any registry. |
| A2 | "LAN auth OFF by default" plus "LAN derived from actual connection + explicit configuration", with no default trusted set defined. Risk: NAT/port forwarding/rootless-container networking can make internet clients look like private-address LAN clients. | §28.1–28.2, §29, §48 | Trusted networks = loopback + **explicitly configured CIDRs**. First Run Access Mode sets them: Local → loopback only; LAN → detected private subnets pre-filled for user confirmation; Remote → adds canonical HTTPS hostname + passkey. Trusted proxies empty by default. Before first run completes: loopback plus an optional env-configured bootstrap network. Startup/Settings warning when all clients arrive from a single gateway address. Remote-classified requests without a valid session are denied from C1 on. |
| A3 | Health UI location is "Settings → Sources" (§21) while Sources is also a primary destination (§32.1, §32.12) and a Settings category (§32.14) | §21, §32.1, §32.12, §32.14 | One Sources management surface (list, status, capabilities, sessions, health, plugin actions). Settings → Sources holds source preferences (extraction defaults, per-source overrides) and deep-links to Sources. No duplicated state or second implementation. |
| A4 | "Keep partial" on cancel has no stated retention | §16.6, §25, §42 Staging | Kept partials use the resumable-failed-partial class: staging only, ~7 days, never visible in My Shelf, cleaned only after recovery/reconciliation proves them orphaned or expired. |
| A5 | "Safahat / Hindawi" canonical domain/identity isn't stated | §41.1, §41.3 | Settled during the G1 source investigation and recorded in the source-capability evidence ledger. Research item, not a blocker. |

## 5. Constraints implied by the Master (binding)

| ID | Constraint | Master refs | Design consequence |
|---|---|---|---|
| K1 | Scrapling includes stealth fetchers / challenge-solving modes; Scrapling fetchers do their own networking | §9.3, §11, §12.1, §49 | Stealth/challenge modes are never used or enabled (a guard test asserts it). Core owns all transport. Scrapling is used for parsing, selectors, adaptive fallback and generator analysis over responses fetched by Core's policy-enforced clients. |
| K2 | Browser requests must obey the same SSRF policy, but Chromium resolves DNS itself | §11, §15, Meta Prompt G2/G4 | Browser egress goes through a Core-owned local egress proxy that shares the HTTP policy module (allowlist, per-hop redirect revalidation, resolve → validate → pin, block loopback/private/link-local/unsafe). Request interception is defense in depth, not the only control. |
| K3 | Untrusted documents must be isolated from the app origin with one canonical hostname | §27, §48, INV-12 | EPUB/HTML sanitized and rendered in sandboxed iframes with an opaque origin (no `allow-same-origin`, no scripts), served from a content route with `Content-Security-Policy: sandbox` and restrictive `default-src`; pdf.js with PDF scripting and eval disabled; SVG never inlined into app DOM; no auth cookies reachable from content frames. |
| K4 | "Authentication boundaries needed for earlier phases must already protect those surfaces" | Meta Prompt C8; §28 | Access classifier (loopback / trusted LAN / remote via trusted proxies only) and deny-unauthenticated-remote middleware built in C1 before any API route exists. |
| K5 | Progress/events and deterministic failure testing are needed before their nominal phases | §36, §41.2, §41.5, Meta Prompt C9 ("do not defer all real integration"), D2 | Minimal SSE bus in C1/C2 (finished in C6); OneShelf Test Source skeleton in C1/C3; a single defaults registry from C1. |

## 6. Held-for-review register (not v1 scope unless separately authorized)

- Meta Prompt §B4: legacy 183-source inventory / "92 verified" target / extraction quotas; combined selected-chapter EPUB and scanned-page PDF generation; dedicated author-search expansion; opt-in persistent search-history UI; Stop All command; redacted diagnostics export; fixed synthetic benchmark sizes; legacy proxy/desync/attached-browser controls; old agent/worktree assignments; earlier palettes.
- U04, U06, U07, U09, U10, U11 (above).

New items found during implementation get appended here with source location, Master reference and disposition.

---

## 7. Engineering decisions recorded during C1 (2026-09-17)

Routine choices made under Meta Prompt §C0.7 ("make routine engineering choices autonomously"). None changes product semantics; items marked **Review** are flagged for the user.

| ID | Decision | Rationale / Master refs | Disposition |
|---|---|---|---|
| D-C1-01 | Backend deps: FastAPI/Starlette + uvicorn, Pillow, pypdf, defusedxml; tests with pytest + httpx2. Pinned in `backend/requirements.lock`. | UD-1; image decode validation (§16.5), PDF open check, hardened XML (§27, §48) | Adopted |
| D-C1-02 | uvicorn runs with `proxy_headers=False`; OneShelf alone decides forwarded-header trust. | uvicorn defaults to trusting `X-Forwarded-For` from 127.0.0.1, which would bypass §28.2 | Adopted |
| D-C1-03 | Default trusted networks = loopback only; LAN CIDRs must be configured (`ONESHELF_TRUSTED_NETWORKS`) until First Run sets them. | Approved A2 | Adopted |
| D-C1-04 | Root identity marker `<root>/.oneshelf/root.json`; missing/foreign marker ⇒ Storage Location Unavailable. | §24.1, §24.6, INV-18 (unmounted mount points look empty) | Adopted |
| D-C1-05 | Managed filenames embed short IDs for both Work and Reading Unit: `Family/Title [work-id]/lang/source/Unit [unit-id].ext`. Scanner recovers manual moves only by ID-bearing name **plus** checksum match. | §24.2 collisions/recovery, §24.7; checksums never used as Work identity (§38) | Adopted |
| D-C1-06 | C1 import requires an explicit Choose Work / Create Local Work decision; no automatic association yet. | §22, §37 "never aggressively merge"; confident association needs C4 matching | Adopted |
| D-C1-07 | Importing adds the Work to My Shelf by default (`add_to_shelf=True`, caller can opt out). | §22 places import within My Shelf; not stated explicitly | **Review** |
| D-C1-08 | An interrupted **Move** import keeps the original file (deletion happens only in the live call after the commit completes and the original is unchanged). | §3.4 no hidden destructive behavior | Adopted |
| D-C1-09 | Staging retention: completed owner 24 h; failed non-resumable owner 24 h; resumable partials 7 d; areas without metadata or with unknown owners 7 d; never while a commit or owner is open or root unavailable. | §25, §42 Staging, A4 | Adopted |
| D-C1-10 | Commit recovery isolates per-entry failures (records error on the journal row) so one bad entry cannot block startup. | §17 "recovery must be safe to repeat" | Adopted |
| D-C1-11 | Test config treats warnings as errors, with one targeted ignore for an anyio alias deprecation raised inside `starlette.testclient`. | keep output pristine without hiding OneShelf warnings | Adopted |
| D-C1-12 | CBZ page images: jpg/jpeg/png/webp/gif/bmp, plus avif when Pillow reports codec support; other entries are not treated as pages. | §16.5 decodability must be verifiable | Adopted |
