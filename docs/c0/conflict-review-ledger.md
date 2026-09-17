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

---

## 8. Engineering decisions recorded during C3 (2026-09-17)

| ID | Decision | Rationale / Master refs | Disposition |
|---|---|---|---|
| D-C3-01 | Phase order: C3 before C2, by user decision ("commit C1 and start C3"); C2 still waits for the visual reference (EB-2). | C3 depends only on C1 (architecture.md §7) | Resolved (user decision) |
| D-C3-02 | `.osp` format: zip with `manifest.yaml`, `source.yaml`, `recipes/**/*.yaml`, mandatory `tests/tests.yaml` + fixtures, optional icon. Allowed file types are data only; strict schemas forbid unknown keys; restricted YAML (no tags/anchors/aliases, depth/node limits, no duplicate keys). | §9.3, §10 steps 3–7, INV-13 | Adopted |
| D-C3-03 | Recipe DSL: request templates limited to declared inputs + `{base_url}` with `url`/`path` encoders; CSS (Scrapling translator) / XPath (lxml) / JSON-path subset selectors; capability-specific field sets; pagination modes none/page_number/offset/next_link with explicit completion rules. Core-owned headers (Cookie, Authorization, Host, Proxy-*, X-Forwarded-*, Sec-*) are rejected. | §9.1–9.4, Meta Prompt G2–G4 | Adopted |
| D-C3-04 | Permission set = allowlisted source domains, CDN domains, `network:http`, `browser:<capability>`, `session:required|optional:<capability>`. Every permission must be approved before activation; updates adding permissions wait in `pending_review` while the current version stays active. | §10 "update requesting new permissions requires explicit approval" | Adopted |
| D-C3-05 | Trust labels: uploads are always `local`. Registry `official` / `verified_community` need an ed25519 signature over the package SHA-256 by a locally configured key; unsigned or unknown-key claims downgrade to `community`; signatures that fail with a known key reject the install. | §9.5 labels ≠ access; A1 | Adopted |
| D-C3-06 | Regex engine is RE2 (`google-re2`): linear time, no backreferences or lookaround, pattern ≤ 512 chars, 8 MiB memory. | §9.4 "bounded/safe regex" | Adopted |
| D-C3-07 | Outbound HTTP uses aiohttp with a validating resolver (whole DNS answer must be public; connection uses the validated address), manual redirects re-checked per hop, `trust_env=False`, no cookie jar, bounded bodies, IP-literal hosts and non-default ports refused. | §11, INV-15 | Adopted |
| D-C3-08 | Browser traffic goes through a per-context Core egress proxy with random credentials; Chromium launched with `--proxy-bypass-list=<-loopback>`, `--host-resolver-rules=MAP * ~NOTFOUND , EXCLUDE 127.0.0.1`, QUIC and non-proxied WebRTC UDP disabled, service workers blocked, downloads off, non-http(s) requests aborted. Verified against a control run. | §11 browser path, K2 | Adopted |
| D-C3-09 | Governor: per-request leases; background priorities (read-ahead, Follow, Health) cannot take the last HTTP slot; background browser leases are preempted (task cancelled) for Reader/interactive/manual work; downloads (manual) are not preempted, so Reader waits at most one request. | §15, §16.2, INV-26 | Adopted |
| D-C3-10 | Session store: separate `secrets.db` (rollback journal + `secure_delete`), AES-256-GCM with the source id as authenticated data, key file 0600 in its own 0700 directory. Unreadable sessions become `needs_reconnect`. | §13, §33.3 | Adopted |
| D-C3-11 | Session key default path `<data_dir>/keys/session.key` (separate file and directory, configurable via `ONESHELF_SESSION_KEY_FILE`). Deployment must mount it on separate storage; Docker docs (C9) will make that the default. | §13 "encryption key stored separately" | **Review** |
| D-C3-12 | "User logs in themselves" is implemented as a Core-owned, policy-bound Chromium context streamed to the UI as a JPEG screencast with forwarded input events. Form values are never read; captured state is scoped to session domains, validated with `check_session`, then atomically replaces the stored session. | §13, §12.3 "Use My Session scoped to current source; no raw passwords" | **Review** |
| D-C3-13 | Request guard for every client: `Host` header must be an IP literal, `localhost` or a configured name (DNS-rebinding defence); browser state-changing requests must be same-origin (`Origin` / `Sec-Fetch-Site`). No authentication is added; LAN trust is unchanged. | §28.1 trusts genuine LAN devices, not arbitrary websites in their browsers; §48 | **Review** |
| D-C3-14 | OneShelf Test Source lives in `backend/testsource/` (not packaged with the app). Its loopback exception requires both `ONESHELF_DEV_TEST_SOURCE` and plugin id `oneshelf.test-source`, is loopback-only (never private LAN), and uses a development host map. | §11, §41.2 | Adopted |
| D-C3-15 | List results are complete only with positive evidence (empty page, total reached, last link, single response). Page cap, repeated page, pagination loop, failed/blocked page, parse failure or a catalog item without identity ⇒ incomplete. HTTP 404/410 is categorised `not_found` and recorded as `content_missing`, not a source failure. | §5.1, §21, Meta Prompt G3 | Adopted |
| D-C3-16 | Registry sources: `file://` local mirror or `https://` static index (client allowlisted to that host only). Configured by `ONESHELF_REGISTRY_URL`; no default registry. | A1 | Adopted |
| D-C3-17 | Scrapling is used as a parser only; its `fetchers` extra (patchright, browserforge, curl_cffi, fingerprint data) must never be installed. A guard test fails if stealth packages or fetcher imports appear. | §12.1, §49, K1 | Adopted |
| D-C3-18 | Adaptive selector fallback deferred to C9 (generator/repair), which owns selector fingerprints and validation. | §12.1, §12.3 | Adopted (carried forward) |

---

## 9. Engineering decisions recorded during C4 (2026-09-17)

| ID | Decision | Rationale / Master refs | Disposition |
|---|---|---|---|
| D-C4-01 | Relevance tiers: exact title → exact normalized → **exact loose** → exact alias → prefix → all-token → substring → fuzzy. The loose tier makes the intentional Arabic ة↔ه equivalence explicit without weakening stronger matches. | §6.3, §6.4 | Adopted |
| D-C4-02 | Boosts (user mapping, verified mapping, Shelf presence, language alias, agreeing sources) only reorder within one tier; they can never cross tiers. | §6.4 "boosts must not overpower strong textual relevance" | Adopted |
| D-C4-03 | Search results are never persisted. Listings and tracks are written only by an explicit durable action (`persist_listing` / `POST /api/listings/bind`). | §6.6, INV-03 | Adopted |
| D-C4-04 | Discovery Cache lives in its own `cache.db`, namespaced `source@plugin_version`, stores **hashed** keys, TTL 7 d, 250 MB LRU. | §7, C15 (no query history) | Adopted |
| D-C4-05 | `source_listings.mapping_decided_by` records who linked a listing to a Work; automatic evidence never overrides a user decision, and Unlink/Never Match/Split block re-association for that pair. | §6.6, INV-04 | Adopted |
| D-C4-06 | Merge refuses two Works that both have a track for the same source and language; the user unlinks or splits first. | §6.6 has no rule for this collision; refusing is non-destructive | **Review** |
| D-C4-07 | When a source renames a listing, the previous raw title is kept as a `source_title` alias so the old title still finds the Work. | §6.8 "preserve title aliases/history" | Adopted |
| D-C4-08 | A complete refresh whose unit set matches the trusted catalog updates that snapshot in place (state `unchanged`) instead of rotating the previous trusted catalog; metadata and order changes still apply. | §5.2 keeps current + previous trusted; §20 reordering ≠ new | Adopted |
| D-C4-09 | Suspicion is computed only between complete snapshots using the §42 heuristic; recovery needs two consecutive complete checks with the same unit set; candidates are cleared when the source returns to the trusted reality, so an old candidate cannot recover later. | §5.2, §5.3 | Adopted |
| D-C4-10 | Reading Units are materialized from the trusted catalog only. Units that disappear are marked unavailable with `missing_since`, never deleted, and their local files stay. | §5.5, §3.4 | Adopted |
| D-C4-11 | Home Hero: Continue Reading → pinned Work → cached discovery, never a network request. The §31.4 "new-release Work" step is added with Follow in C6. | §31.4 | Adopted |
| D-C4-12 | A Home feed that fails simply stays hidden for that source (no error placeholder, no invented data). | §31.1 | Adopted |
| D-C4-13 | Direct URL entry previews through normal capabilities and persists nothing until the user acts. | §8 | Adopted |

---

## 10. Engineering decisions recorded during C5 (2026-09-17)

| ID | Decision | Rationale / Master refs | Disposition |
|---|---|---|---|
| D-C5-01 | A `settings` table (scopes global/source/work/content_type) was added in C5; §42 defaults stay in the defaults registry and settings only override them. | §14 precedence, D2 single defaults source | Adopted |
| D-C5-02 | Method → capability mapping: `direct` uses the `downloads` capability (whole files, Range/If-Range resume); `html_api`, `reader_media` and `browser` use the `reader` capability (per-page resources). | §14 methods; recipes declare their own fetch kind | Adopted |
| D-C5-03 | Fallback is considered only after Smart Retry is exhausted, and only for method-specific categories (parser/selector/media/resource/not-found). Auth, CAPTCHA, rate limit, outage, transport and blocked never trigger a method change. | §14 | Adopted |
| D-C5-04 | Preferred + Ask records a pending decision on the failed job (`pending_decision_json`) instead of switching method automatically; the user chooses through retry with a one-time method. | §14 "Preferred + Ask" | Adopted |
| D-C5-05 | A method change restarts the unit in a fresh staging area (manifest cleared), so methods are never mixed inside one unit. | §14 "never mix extraction methods within one Reading Unit" | Adopted |
| D-C5-06 | Enqueue skips units that already have a verified asset or an active job, and reports them as `skipped`. | §16.1, avoids duplicate work and duplicate assets | Adopted |
| D-C5-07 | CBZ packaging stores original page bytes uncompressed (ZIP_STORED) with ComicInfo.xml, and the archive is validated before commit. | §39 preserve originals, no recompression | Adopted |
| D-C5-08 | Reader Cache identity = source + Reading Unit key + hashed resource URL + validator; blobs live outside the library database and never inside a storage root. | §26.20 | Adopted |
| D-C5-09 | Cache protection is explicit: `set_open_units()` marks what the Reader is showing; protected entries are never evicted even when that keeps the cache above its cap. | §42 Reader Cache protections | Adopted |
| D-C5-10 | Progress writes are revision-checked (compare-and-set). Mark Read / Mark Unread and rereading always work; only stale writes are rejected. | §26.23 | Adopted |
| D-C5-11 | Auto-download while reading queues the current unit plus up to 5 existing following units of the same track; leaving the Work cancels only queued jobs other than the unit being read. | §19 | Adopted |
| D-C5-12 | Downloaded content is read from the local archive with no network and no cache entry; the Reader Cache is only for online reading. | §3.3, §26.20 | Adopted |
| D-C5-13 | Reader page bytes are served from a dedicated route with `Content-Security-Policy: sandbox`, `nosniff` and `no-store`, ahead of the C2 isolated viewer. | §27, §48 | Adopted |

---

## 11. Engineering decisions recorded during C6 (2026-09-17)

| ID | Decision | Rationale / Master refs | Disposition |
|---|---|---|---|
| D-C6-01 | Shelf views: `saved` means on the Shelf with no reading progress and not Completed; `reading` means any partial/read progress and not Completed. | §22 lists the views without defining the split | **Review** |
| D-C6-02 | "N releases since completion" counts release events detected after `completed_at`; Completed is never cleared automatically. | §5.6 | Adopted |
| D-C6-03 | Delete Files removes managed files and their asset rows but keeps Shelf, Follow and reading progress; Remove from Shelf offers a removal summary first (files, bytes, progress, followed). | §22, §23, §47 | Adopted |
| D-C6-04 | Follow baselines are stored as unit-key sets (first_follow or source_change). Detection = trusted catalog − baseline − already-reported events, so reappearing units are never "new". | §20 | Adopted |
| D-C6-05 | A suspicious or missing trusted catalog produces no release events and surfaces as the Follow state instead. | §5.4, §20 | Adopted |
| D-C6-06 | Unfollow keeps its undo token in memory for the session only. | §20 "immediate with Undo"; nothing else is touched, so a lost token is harmless | **Review** |
| D-C6-07 | Health thresholds: 3 consecutive failures → Degraded, 6 → Unavailable, 2 consecutive successes → Healthy; rate limit and auth failures map to their own states; `content_missing` never degrades. | §21 thresholds/hysteresis without fixed numbers | **Review** |
| D-C6-08 | Health active checks are an explicit service call at HEALTH priority and refuse capabilities that need the browser. | §21 "do not periodically spin up browser solely for health" | Adopted |
| D-C6-09 | Notification dedupe keys follow the Master's examples (`source-auth:`, `storage-low:`, `catalog-suspicious:`, `new-release:`, plus `download-failed:<unit>`); Needs Attention is a filter over unresolved keys with those prefixes. | §30.13, §32.2, §44 | Adopted |
| D-C6-10 | New-release summaries use a numeric range only when the numbers are contiguous integers ("Ch. 209–211"); otherwise they list labels ("Chapter 209, Special, Extra Story"). | §30.2 | Adopted |
| D-C6-11 | Only final download failures notify; Smart Retry, page repairs, health probes and cache work never do (`should_notify` blocklist). | §30.1, §30.4 | Adopted |
| D-C6-12 | API route ordering is enforced by a test: a literal path may never be registered after a parameterized path that would shadow it (this bug shipped twice during C5/C6). | defensive; no Master rule | Adopted |

---

## 12. Engineering decisions recorded during C7 (2026-09-17)

| ID | Decision | Rationale / Master refs | Disposition |
|---|---|---|---|
| D-C7-01 | Merge restores records that are missing from the current library, including Shelf entries removed after the backup was taken. | §33.7 "missing records may be added"; the Master gives no tombstones | **Review** |
| D-C7-02 | Export output layout is `<Work Title> (<language>)/` per selected work, with the optional `oneshelf-export.json` sidecar inside it; ZIP wraps that same folder. | §34.5–34.7 ask for cleaner naming and a folder default without fixing a layout | **Review** |
| D-C7-03 | Export history retention is 30 days or the 100 most recent jobs, whichever is tighter. | §34.11, DEF-export-activity | Adopted |
| D-C7-04 | Backup retention is four verified archives in a single configured backup location; several simultaneous backup locations are not modelled in v1. | §33.8–33.9 | **Review** |
| D-C7-05 | Excluded-by-construction backup tables: source session refs, commit journal, download jobs and batches, search index, health signals and state, storage-migration bookkeeping. They are cleared from the snapshot copy, which is then vacuumed. | §33.1, §33.3 (rebuildable/transient state is not library state) | Adopted |
| D-C7-06 | A local import writes its search-index rows inside the same commit-journal transaction, so an imported work is immediately findable and can be an association target for later imports. | §6.1, §22, §37 | Adopted |
| D-C7-07 | `/api/import/uploads` accepts a `filename` query parameter used only as a label for the suggested title; the stored path is always the opaque upload id. | §48 path safety; a client-supplied name never influences placement | Adopted |
| D-C7-08 | A storage migration is planned and verified against the destination before any file is copied, and the old copy is deleted only by an explicit later request (`discard_old_copy`). | §24.8 "never auto-delete old" | Adopted |
| D-C7-09 | Export chooses among existing files only: CBZ is preferred for sequential content, books export as they are, and an explicit format list is honoured exactly. Nothing is ever converted. | §34.4, EX-29 | Adopted |
| D-C7-10 | Selected Works export as one job carrying one contract per work (shared destination, output and conflict policy), so sources and languages are never mixed. | §34.1 | Adopted |
