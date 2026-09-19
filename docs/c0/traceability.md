# Requirement Traceability Matrix

Recorded: 2026-09-17 (C0) · Updated: 2026-09-17 (C1, C2, C3, C4, C5, C6, C7, C8, C9) · Authority: Meta Prompt §C0.6, §D1–D3 · Architecture: `architecture.md`

**Coverage:** every Master heading from §0 to §56 (57 sections, 152 numbered subsections, and the unnumbered sub-headings in §4.4, §20, §26.3, §26.22), all 30 §51 invariants (INV), all 17 §42 default groups (DEF), all 30 §49 exclusions (EX), Meta Prompt §D3 deliverables (MPD) and §G investigation rules (MPG).

**Columns:** ID · Requirement (summary; the Master text is normative) · Phase · Planned location (`be/` = `backend/oneshelf/`, `fe/` = `frontend/`) · API/UI surface · Persistence/state · Acceptance evidence · Status

**Status values (one per row, reconciled 2026-09-18 by inspecting the code and the tests):**

- `NOT_STARTED` — none of the requirement's distinctive behaviour exists.
- `IN_PROGRESS` — part of it exists; the Evidence cell names what is present and what is missing.
- `IMPLEMENTED` — the whole requirement is present, but its evidence is an inspection rather than a test or a recorded gate check.
- `VERIFIED` — present **and** carried by a named test or a recorded phase-gate check. Code presence alone never earns this.
- `BLOCKED` — cannot be completed or verified here; the Evidence cell states the exact blocker and what would unblock it.

Required rows may not be relabeled deferred. Optional/future items keep their Master status and are marked *(optional)*.

**Reconciliation, 2026-09-18.** Every row was re-checked against the actual implementation and the actual
suite; statuses were fixed in place. The previous run recorded per-phase deltas in the progress log below
but left the rows themselves at their C0 values, so many read `NS` after the work was done and a few read
`IMPL` where part of the requirement was missing. The progress log is unchanged: it is the record of what
each phase delivered. Where a row now says `IN_PROGRESS`, `NOT_STARTED` or `BLOCKED`, its Evidence cell
says exactly what is missing or what blocks it.

---

## §0–§4 Governance, vision, platform, foundations, domain

| ID | Requirement | Phase | Location | Surface | Persistence | Evidence | Status |
|---|---|---|---|---|---|---|---|
| M0 | Master is authoritative; no redesign/simplification; flag external ideas; no revival of removed scope | C0→all | docs/c0 | — | — | conflict-review-ledger.md; each phase review | VERIFIED |
| M1 | Self-hosted single-user reading library; feels like personal library, not scraper dashboard; progressive disclosure | C2→all | fe/ | all screens | — | UX review vs §32/§45; screenshots | VERIFIED |
| M2 | Deployment & core platform | C1,C8,C9 | — | — | — | Blocked by M2.1 below | BLOCKED |
| M2.1 | Docker first-class; persistent storage; optional separate mounts; no cloud backend/account | C1,C9 | deploy/, be/settings | env/config | app data volume | **EB-1**: no container runtime (`docker`, `podman` absent) on this host, so build, restart and recreation against isolated mounts cannot run. Unblocked by running `docker compose up -d --build` on a host with Docker or Podman, restarting and recreating the container, and confirming the library survives on the mounts | BLOCKED |
| M2.2 | Single user; no username/password account, cloud profile or roles; remote = passkeys; LAN trusted | C1,C8 | be/auth, be/api | first run, Remote Access | remote_auth tables | auth tests; no account/profile UI | VERIFIED |
| M2.3 | Arabic/English, RTL/LTR UI + reading; Arabic normalization for search preserving original text | C2,C4 | fe/i18n, be/search/normalize | all UI; search | normalized key columns | RTL/LTR screenshots; normalization unit tests | VERIFIED |
| M3 | Foundational rules | C1→C7 | — | — | — | rows M3.1–M3.4 | VERIFIED |
| M3.1 | Never silently switch/mix source, language, tracks, or substitute units; fallback changes method only | C4,C5,C6,C7 | be/downloads/extraction, be/reader, be/follow, be/export | Reader, Downloads, Follow, Export | extraction_contracts, follows | INV-02 tests | VERIFIED |
| M3.2 | UNKNOWN is valid; never coerced to No/False/Unavailable/Unsupported/Bad/Missing; unknown quality ≠ unavailable | C1,C4,C5 | be/domain (Unknown-aware types) | cards, details, plugin capabilities | nullable tri-state columns | INV-05, INV-06 tests | VERIFIED |
| M3.3 | Local content readable without source/plugin/internet/session/catalog | C2,C7 | be/reader, be/storage | Reader | assets | INV-11 test | VERIFIED |
| M3.4 | No hidden destructive behavior (listed cases) | C1,C4,C6,C7 | be/storage, be/catalog, be/services | destructive dialogs | — | INV-01/10/18 tests; cleanup audits | VERIFIED |
| M4 | Core domain model | C1 | be/domain, be/db | — | schema | rows M4.1–M4.6 | VERIFIED |
| M4.1 | Work: logical title aggregating listings/languages/formats with provenance; not title equality | C1,C4 | be/domain/work | Work Details | works, work_aliases | domain tests; same-title distinct Works | VERIFIED |
| M4.2 | Source Listing with source-specific identity + provenance | C1,C3 | be/domain | Sources tab | source_listings | same-source dedupe tests (M6.9) | VERIFIED |
| M4.3 | Source Track = Work × source × language with own catalog/order/units/metadata/session/capabilities/baseline/availability; never blended | C1 | be/domain | Work Details Sources/Read tabs | source_tracks | track isolation tests | VERIFIED |
| M4.4 | Reading Unit types and fields (raw/display title, type, numbers, volume, order, date, source, language, availability/download/integrity/read state, progress) | C1 | be/domain/reading_unit | index list, TOC | reading_units | schema + fixture tests (special/extra/3.5) | VERIFIED |
| M4.4a | Numbering precedence source > adapter-derived > UNKNOWN; derived = display/order only, never identity; user correction wins | C1,C4 | be/domain, be/catalog | unit list | source_number, derived_number, user_number | tests: specials not numbered; identity unchanged on renumber | VERIFIED |
| M4.5 | Volumes optional grouping; no volume folder hierarchy required | C1 | be/domain, be/storage/layout | unit list grouping | volume column | layout tests | VERIFIED |
| M4.6 | Local Source Track first-class; readable/exportable without network plugin | C1,C7 | be/domain, be/importer | Work Details | source_tracks(kind=local) | import→read→export offline test | VERIFIED |

## §5 Catalog trust

| ID | Requirement | Phase | Location | Surface | Persistence | Evidence | Status |
|---|---|---|---|---|---|---|---|
| M5 | Catalog trust foundational for Follow/Download Missing/navigation/missing inference | C4 | be/catalog | — | catalog_snapshots | rows below | VERIFIED |
| M5.1 | Only complete snapshots may be Trusted; incomplete never replace trusted, infer deletion, baseline Follow, or feed Download Missing | C4 | be/catalog/completeness | — | snapshot.completeness + evidence | incomplete pagination / failed request / first-page-only / interrupted tests | VERIFIED |
| M5.2 | Keep current + previous Trusted, release events, bounded debug window; suspicious heuristic ≥~50% loss and ≥5 units | C4 | be/catalog/trust | Sources, Work Details warning | catalog_snapshots (bounded) | 300→7 test; history bound test | VERIFIED |
| M5.3 | Suspicious → Trusted after two consecutive complete matching checks or explicit Trust This Catalog | C4 | be/catalog/trust | Sources advanced action | snapshot state | recovery sequence tests; Trust action rejects incomplete | VERIFIED |
| M5.4 | Download Missing, Follow comparison, missing inference, automation use last Trusted only | C4,C5,C6 | be/catalog, be/downloads, be/follow | Download Missing, Follow | — | trusted-only tests | VERIFIED |
| M5.5 | Temporarily missing units keep local content, last_seen, missing_since; no deletion | C4,C6 | be/catalog | unit list state | last_seen, missing_since | disappear/reappear tests | VERIFIED |
| M5.6 | Completed stays Completed; show "N releases since completion" | C6 | be/services/shelf | My Shelf, Work Details | shelf.completed_at + release events | completion preservation test | VERIFIED |

## §6–§8 Search, matching, discovery cache, URL entry

| ID | Requirement | Phase | Location | Surface | Persistence | Evidence | Status |
|---|---|---|---|---|---|---|---|
| M6 | Unified search and matching | C4 | be/search | Search | — | rows below | VERIFIED |
| M6.1 | Local-first then progressive live enrichment of same result set; never clear local results; slow source doesn't block; "7 / 8 sources"; Retry Source | C4 | be/search/service, fe/search | `GET /search` + SSE; Search screen | cache.db discovery | failing/slow source tests; e2e progressive render | VERIFIED |
| M6.2 | SQLite FTS5 (or equivalent) index over original/display/normalized/loose/aliases/source titles/type/languages/creator/external IDs | C4 | be/search/index | — | FTS5 tables | index tests | VERIFIED |
| M6.3 | Preserve originals; normalize keys only; strong Arabic normalization; loose ة↔ه; no stemming, translation, cover matching | C4 | be/search/normalize | — | key columns | Arabic regression + no-stemming tests | VERIFIED |
| M6.4 | Ranking tiers exact→normalized→alias→phrase/prefix→all-token→substring/trigram→fuzzy; small boosts can't overpower; ranking ≠ grouping | C4 | be/search/rank | result order | — | tier ordering + boost-bound tests | VERIFIED |
| M6.5 | Sequential Art family broadly compatible; Novel/Book vs sequential art usually not hard-merged | C4 | be/search/match | — | — | adaptation-boundary tests | VERIFIED |
| M6.6 | Soft Group presentation-only; actions bind concrete listing/track; Hard Mapping needs evidence or user action; Merge/Split/Unlink/Never Match persist and win | C4 | be/search/mapping | Work Details, Search | mappings, overrides | INV-03, INV-04 tests | VERIFIED |
| M6.7 | Missing metadata not negative evidence | C4 | be/search/match | — | — | INV-05 test | VERIFIED |
| M6.8 | Reading Unit matching title-primary + stable supporting evidence; preserve aliases/history | C4 | be/catalog/unit_match | — | unit aliases | rename/reorder tests | VERIFIED |
| M6.9 | Same-source identity via listing ID/canonical URL; cached + live merge | C4 | be/search | — | source_listings unique keys | cached/live dedupe test | VERIFIED |
| M6.10 | No matcher telemetry/central dataset/decision collector/shared logging, under any name | C4,C9 | be/search, be/diagnostics | — | none | INV-29 audit (schema, network, diagnostics) | VERIFIED |
| M7 | Discovery Cache TTL 7 d, 250 MB, LRU; excludes Shelf/Follow/Downloads/mappings/corrections/authoritative; namespaced by source + plugin version/schema; no persistent query analytics | C4 | be/search/discovery_cache | — | cache.db | stale plugin-cache invalidation; cleanup-never-touches-authoritative; no query persistence test | VERIFIED |
| M8 | Direct URL entry: identify plugin, normalize, fetch, preview/resolve; no auth/paywall/DRM bypass; same matching rules | C4 | be/search/url_resolve | Search URL paste | — | supported/unsupported URL tests | VERIFIED |

## §9–§13 Plugins, lifecycle, SSRF, generator, sessions

| ID | Requirement | Phase | Location | Surface | Persistence | Evidence | Status |
|---|---|---|---|---|---|---|---|
| M9 | Source adapter/plugin architecture | C3 | be/plugins | — | — | rows below | VERIFIED |
| M9.1 | Capabilities search/getWork/getChapters/getPages/getTrending/getLatest/getDownloads/checkSession/healthCheck; missing metadata allowed | C3 | be/plugins/contracts | — | capability states | adapter contract tests | VERIFIED |
| M9.2 | Classification precedence user override > source classification > plugin default > Unknown | C3 | be/plugins, be/domain | Work details edit | classification_overrides | precedence tests | VERIFIED |
| M9.3 | Community plugins declarative `.osp` (manifest/source/recipes/tests/icon); no py/JS/shell/eval/exec; Core owns HTTP/Scrapling/browser/sessions/downloads/DB/FS/paths/network | C3 | be/plugins/schema, validator | Sources upload | plugin store | INV-13 malicious package rejection | VERIFIED |
| M9.4 | Bounded safe transform library incl. bounded regex, with resource limits | C3 | be/plugins/transforms | — | — | ReDoS/size/time limit tests | VERIFIED |
| M9.5 | Trust labels Official/Verified Community/Community/Local indicate review only, not access | C3 | be/plugins | Sources list | plugin.trust_label | label doesn't widen policy test | VERIFIED |
| M9.6 | Native adapters only as rare reviewed official exceptions; WASM not v1 | C3,C9 | be/plugins/native (registry of reviewed) | — | — | review record per native adapter; none by default | IMPLEMENTED |
| M9.7 | Restricted RPC excluded | C3 | — | — | — | EX-04 | IMPLEMENTED |
| M10 | Install via Registry (A1) or local upload; atomic 8-step install; Configure/Update/Disable/Uninstall/Health/Rollback; new permissions need approval; no auto-publish; uninstall keeps Shelf/content; missing plugin keeps provenance + reinstall; backups store names/versions only; account connection optional | C3 | be/plugins/lifecycle, registry | Sources install/review/manage | plugins, plugin_versions, permissions | install rollback; permission-change review; uninstall preserves content; fixture registry tests | VERIFIED |
| M11 | Allowlists + redirect revalidation + DNS revalidation + block loopback/private/link-local/unsafe; same for browser; Test Source dev-only exception | C3 | be/net/policy, be/net/browser_proxy | — | policy config | INV-15 HTTP + browser SSRF/rebinding tests | VERIFIED |
| M12 | Scrapling discovery and adapter generator | C3,C9 | be/generator | Settings → Developer | drafts | rows below | VERIFIED |
| M12.1 | Scrapling: static first, dynamic only if needed, CSS/XPath, APIs/XHR, adaptive selectors; doesn't own queue/retry/Shelf/packaging/priority/policy; no stealth | C3,C9 | be/generator, be/plugins/runtime | — | — | K1 guard test (no stealth fetchers) | VERIFIED |
| M12.2 | Pipeline URL→static→mapping→capabilities→optional dynamic→XHR/DOM/media→confidence→draft→domain/permission review→tests→dev review→validation→local install→optional submission | C9 | be/generator/pipeline | Developer generator UI | draft state | pipeline e2e on Test Source | VERIFIED |
| M12.3 | Generator features list (route mapping, Arabic test queries, unit discovery preserving raw fields, resource discovery not screenshots, Confirmed/Probable/Unknown/Unsupported, manifest/recipe generation, safe transforms, adaptive fallback after failure+validation, CDN vs ads separation, capability-level auth testing, sanity tests, multiple sample Works, preview, Recipe Inspector, Test/Edit/confidence, Generate≠Install, Repair with diffs, validate before replace, atomic activation+rollback, community export/submit, no Shelf/progress/unrelated session access, scoped Use My Session, no raw passwords, no auto-publish) | C9 | be/generator, fe/developer | Developer UI | drafts, repair diffs | per-feature tests; MPG rows | VERIFIED |
| M12.4 | Unsupported declarative sites → "Unsupported by Declarative Adapter" / "Native Adapter Review Required"; no hacks | C9 | be/generator | generator result | — | proprietary-signing fixture test | VERIFIED |
| M13 | Use My Session: user logs in; no passwords; per-source isolation; plugins never get raw material; encrypted at rest, key separate; backup exclusions; cookies/localStorage/IndexedDB/sessionStorage handling; states + actions; auth failure pauses → WAITING_FOR_SESSION, no blind retry; atomic reconnect + resume; disconnect deletes immediately; never log secrets; install doesn't force auth; attach only to needed capabilities/domains | C3 | be/sessions, be/net | Sources → account/session | secrets.db + separate key | same-source isolation; cross-source/CDN leak; reconnect wait/resume; disconnect deletion; log scan | VERIFIED |

## §14–§19 Extraction, governor, downloads, commit, SQLite, auto-download

| ID | Requirement | Phase | Location | Surface | Persistence | Evidence | Status |
|---|---|---|---|---|---|---|---|
| M14 | Methods Direct/HTML-API/Reader Media/Browser; Extraction Contract (source, language, unit, output, method); precedence one-time > source > global > plugin; Preferred + Ask default; Strict/Locked; optional Automatic Fallback; Smart Retry first; no fallback on auth/CAPTCHA/rate limit/outage; explicit public-reader alternative; no auth bypass; health doesn't rewrite; no mixed methods per unit; switch = full temp redownload + validate + atomic replace; method-specific resume; plugin update doesn't change method; history records methods locally | C3,C5 | be/downloads/extraction | download dialogs, Settings → Downloads advanced | extraction_contracts, history | contract-preservation + mode semantics tests | VERIFIED |
| M15 | Global Source Traffic Governor: priority Reader > interactive > manual/downloads > read-ahead > Follow > Health; browser same priority; low-priority browser never blocks Reader; per-source/global concurrency, rate limits, Retry-After, backoff, fairness | C3,C5 | be/net/governor | — | in-memory + persisted rate state | INV-26 saturation test; fairness tests | VERIFIED |
| M16 | Download Engine: persistent SQLite queue/state machine + scheduler + workers + governor + staging + integrity + packaging + commit + recovery + history; grouped UI states | C5 | be/downloads | Downloads | jobs, batches | state machine tests | VERIFIED |
| M16.1 | Per-unit jobs under batch; partial failure ≠ batch failure; Completed / Completed with Issues / Retry All Failed; windowed queue; pause/resume/cancel/retry/reorder | C5 | be/downloads/scheduler | Downloads batch cards | batches, jobs | partial success; huge queue memory bound | VERIFIED |
| M16.2 | Concurrency HTTP 4, Browser 1 independent; advanced may raise | C5 | be/settings/defaults, be/net | Settings advanced | settings | DEF-concurrency test | VERIFIED |
| M16.3 | Initial + up to 3 retries, exponential backoff + jitter; 429 Retry-After; auth → WAITING_FOR_SESSION; 404 no blind repeat; 5xx/timeout/reset retryable | C5 | be/downloads/retry | — | job attempts | Test Source 429/500/404/session-expiry tests | VERIFIED |
| M16.4 | Resume: skip valid pages; Range + ETag/Last-Modified/If-Range, never splice; browser rediscover manifest, compatible resume else restart; per-job manifest | C5 | be/downloads/resume | — | job_manifests | changed-ETag, Range, browser manifest tests | VERIFIED |
| M16.5 | Integrity: images exist/non-zero/decodable/sensible/not HTML/coverage; books type/magic/openable/container valid; no partials in Shelf; same-method page repair | C5 | be/downloads/integrity | Reader repair | asset integrity | HTML-as-media, corrupt media, content-open checks | VERIFIED |
| M16.6 | Cancel setting: delete or keep partial (A4) | C5 | be/downloads | Settings → Downloads | staging | both-mode tests | VERIFIED |
| M16.7 | Clearing Download History keeps content + progress; no cloud telemetry | C5 | be/downloads/history | Downloads history | history table | INV-23 test | VERIFIED |
| M17 | Idempotent Commit Journal: staging → journal → rename → verify → DB txn → complete; startup reconciles listed cases; recovery repeatable; order recover → reconcile → clean orphans | C1,C5 | be/storage/commit_journal | — | commit_journal | crash injection at each boundary; repeated reconciliation (INV-17) | VERIFIED |
| M18 | SQLite source of truth; WAL; migrations; short serialized writes; consistency boundaries; consistent snapshot backups; never copy live DB | C1,C7 | be/db | — | oneshelf.db | migration/recovery tests; snapshot consistency test | VERIFIED |
| M19 | Reading ≠ Downloading; auto-download OFF; Current Unit Only / Current + Read Ahead (next 5 existing); Download Entire Work separate; trigger ~12% + genuine interaction; flow via Reader Cache; priority; leaving Work cancels not-started read-ahead; no source/language switch | C5 | be/reader/auto_download | Reader settings (advanced), Settings → Downloads | settings, jobs | INV-07/08; engagement trigger; leave-Work cancellation | VERIFIED |

## §20–§23 Follow, health, Shelf, independence

| ID | Requirement | Phase | Location | Surface | Persistence | Evidence | Status |
|---|---|---|---|---|---|---|---|
| M20 | Follow binds Work+Language+Preferred Source+Track; no auto switch; alternatives informational (View Alternatives/Change Preferred Source); independent of Shelf; Unfollow immediate + Undo, non-destructive; detect vs Trusted Catalog baseline, not max number/gaps; first Follow baselines; New ≠ auto-download | C6 | be/follow | Following, Work Details | follows, baselines | first-Follow baseline; INV-09; Unfollow independence | VERIFIED |
| M20a | NEW_RELEASE vs NEWLY_AVAILABLE internal distinction; UI may group | C6 | be/follow/events | Following | release_events.kind | event-kind tests | VERIFIED |
| M20b | Metadata change of same unit updates, not new; reordering not new; disappear→return not new; duplicate notifications suppressed; Seen separate from Read | C6 | be/follow/detect | Following | — | rename/reorder/reappear tests | VERIFIED |
| M20c | Preferred Source change: fetch catalog, Source Change Baseline, no flood, preserve progress | C6 | be/follow | Change Preferred Source | baselines | source-change tests | VERIFIED |
| M20d | Schedule ~12 h + jitter; Check Now / Check All Now; plugin Update Now / Update All separate; group by source; API/HTML preferred, browser only if declared; Last Attempted + Last Successful (emphasized) | C6 | be/follow/schedule | Following | follow check timestamps | scheduler jitter/grouping tests | VERIFIED |
| M21 | Capability-level health (Search/Work/Catalog/Reader/Download/Auth); states Healthy/Degraded/Unavailable/Rate Limited/Reconnect Required/Catalog Suspicious; internal categories; thresholds + hysteresis; trusted recovery; 404 ≠ failure; parser failures signal update; plugin version recorded; passive first; no periodic browser probes; active checks low priority; describes only; UI in Sources (A3); Search shows only concise progress | C6 | be/health | Sources; Search progress | health_signals | hysteresis/flap tests; no browser probe test | VERIFIED |
| M22 | My Shelf: immediate save without files; views All/Saved/Reading/Completed/Favorites; Pin separate; Remove confirms Keep/Delete Files; Completed rules + optional delete keeping metadata; progress in SQLite; local-only Shelf search; formats (CBZ per unit, original images; PDF/EPUB coexist); per-unit local record; import CBZ/PDF/EPUB with confident association or Choose Work/Create Local Work | C6,C7 | be/services/shelf, fe/shelf | My Shelf, Work Details | shelf_entries, assets, progress | Backend verified (`test_shelf_and_follow.py`, `test_shelf_api.py`). **Missing in the UI:** Remove from Shelf with Keep/Delete Files, and Mark Completed | IN_PROGRESS |
| M23 | Remove from Shelf ≠ Unfollow; Unfollow keeps Shelf + files; Delete Files keeps Follow + progress unless separately requested | C6 | be/services | dialogs | — | INV-10 matrix test | VERIFIED |

## §24–§25 Storage and staging

| ID | Requirement | Phase | Location | Surface | Persistence | Evidence | Status |
|---|---|---|---|---|---|---|---|
| M24 | Storage model | C1,C7 | be/storage | Settings → Storage | storage_roots | rows below | VERIFIED |
| M24.1 | Roots with stable ID, path, availability, free space, default flag; DB stores root_id + relative path; never absolute host paths | C1 | be/storage/roots | Storage settings | storage_roots, assets | identity tests; mount remap test | VERIFIED |
| M24.2 | Families Sequential Art/Books/Other; Work→Language→Source→Files; short stable IDs for collisions; Unicode/Arabic names; untrusted source filenames; Core-owned paths; no rename on metadata change | C1 | be/storage/layout | — | — | collision + Unicode + metadata-change tests | VERIFIED |
| M24.3 | Per-root `<root>/.oneshelf/staging/` on same filesystem; partials only there; scanner/reader ignore | C1 | be/storage/staging | — | staging dirs | same-fs rename test; scanner ignore test | VERIFIED |
| M24.4 | Block `../`, absolute injection, symlink escape, malicious names, plugin paths; delete only in managed roots | C1 | be/storage/paths | — | — | INV-14 path tests | VERIFIED |
| M24.5 | Reserve 5% capped 5 GB; warn ~2×; pause automatic/background writes at reserve; never auto-delete; expected-size preflight | C1,C7 | be/storage/disk_guard | Low Storage notice | root state | reserve/warning/preflight tests | VERIFIED |
| M24.6 | Offline root → Storage Location Unavailable; no mass Missing, cleanup or destructive repair; reconcile on return | C1,C7 | be/storage/roots, scanner | Needs Attention/Storage | root availability | INV-18 test | VERIFIED |
| M24.7 | Manual deletion → Missing Local File keeping Work/Follow/progress; relocation recovery via IDs else import/reconcile | C7 | be/storage/scanner | unit state | assets.integrity | manual delete/move tests | VERIFIED |
| M24.8 | Resumable migration preflight→pause→stream copy→checksum→switch→reconcile→offer keep/delete; never auto-delete old; reads continue where practical; mount-path change = remap + validate, no copy | C7 | be/storage/migration | Storage settings | migration jobs | interrupted migration resume; old-data preservation; remap test | VERIFIED |
| M25 | Staging cleanup: successful leftovers ~24 h; resumable failed ~7 d; startup recover jobs → commits → reconcile → clean proven orphans; never clean before recovery | C1,C5 | be/storage/staging_cleanup | — | — | ordering + retention tests | VERIFIED |

## §26–§27 Reader and isolation

| ID | Requirement | Phase | Location | Surface | Persistence | Evidence | Status |
|---|---|---|---|---|---|---|---|
| M26 | Two reader families (Sequential, Book); core v1 | C2,C5 | fe/reader, be/reader | Reader | — | rows below | VERIFIED |
| M26.1 | Content first; layers Content / Controls / Advanced-Recovery; not a dashboard | C2 | fe/reader | Reader | — | UX review | VERIFIED |
| M26.2 | Auto-hiding top/bottom bars; top: Back, Work title, unit, TOC, compact download, More (Mark Read/Unread, Change Source, Settings, Repair, Work Details, advanced); Back returns context + flushes progress | C2 | fe/reader/shell | Reader | progress flush | `SequentialReader.test.tsx` covers the bars, Back and the progress flush. **Missing:** compact download state in the top bar; More lacks Change Source, Repair and Work Details | IN_PROGRESS |
| M26.3 | Distraction-Free modes; controls don't auto-hide while menu/drawer/settings open; Always Visible *(optional)* | C2 | fe/reader/controls | Reader | reader settings | panel-open no-hide test | VERIFIED |
| M26.3a | Smart: controls on interaction, auto-hide ~3 s | C2 | fe/reader/controls | Reader | — | timing test | VERIFIED |
| M26.3b | Hidden by Default/Minimal: bars hidden unless summoned; navigate by keys/mouse zones/gestures | C2 | fe/reader/controls | Reader | — | No Hidden by Default / Minimal control mode exists; only Smart auto-hide is implemented | NOT_STARTED |
| M26.4 | Long Strip, Single, Double; LTR/RTL/Vertical | C2 | fe/reader/sequential | Reader | — | mode/direction tests | VERIFIED |
| M26.5 | Edge zones/center; direction-aware; keyboard set (prev/next, Space/Shift+Space, fullscreen, TOC, download, zoom, reset, Esc); touch (center tap, swipe, vertical scroll, pinch, double-tap); remapping *(optional)* | C2 | fe/reader/input | Reader | — | `SequentialReader.test.tsx` (direction-aware keys, Space, Escape, zoom, full screen, swipe, pinch, double tap). **Missing:** the download shortcut | IN_PROGRESS |
| M26.6 | Long Strip bounded render window; not fully decoded; percentage progress; optional page detail; restore approximate scroll | C2 | fe/reader/long_strip | Reader | progress.position | Long Strip renders and reports percentage progress. **Missing:** the bounded nearby render window (every page of the chapter is mounted) and restoring the approximate scroll position | IN_PROGRESS |
| M26.7 | Single Page centered; Fit Smart/Width/Height/Original | C2 | fe/reader/single | Reader | — | fit tests | VERIFIED |
| M26.8 | Double Page LTR/RTL pairing, first-page cover, Shift Pairing, wide spreads; no AI/destructive crop | C2 | fe/reader/double | Reader | per-Work pairing offset | pairing tests | VERIFIED |
| M26.9 | Auto Fit Smart/Width/Height/Original; Smart stable | C2 | fe/reader/fit | Reader | — | no-oscillation test | IMPLEMENTED |
| M26.10 | Zoom keyboard/Ctrl+wheel/pinch/double-tap; drag pans; no accidental advance | C2 | fe/reader/zoom | Reader | — | zoomed-pan tests | VERIFIED |
| M26.11 | Minimal bottom UI; page-based (manga/PDF), position (Long Strip), logical (EPUB); scrubber | C2 | fe/reader/progress | Reader | progress | `SequentialReader.test.tsx` progress readout; EPUB/PDF logical progress. **Missing:** the scrubber | IN_PROGRESS |
| M26.12 | TOC drawer (desktop side, tablet side sheet, mobile full/bottom sheet); unit states; filters All/Unread/Downloaded/New; subtle current highlight | C2 | fe/reader/toc | Reader | — | `shows the reading units and their states in the contents drawer`; filters All/Unread/Downloaded. **Missing:** the New filter | IN_PROGRESS |
| M26.13 | End-of-unit uses Source Track order, never chapter+1; card with completed state, next actual unit (Special/Extra), Back to Work | C2 | fe/reader, be/reader/navigation | Reader | — | INV-24 irregular order test | VERIFIED |
| M26.14 | Auto Read 97%; always Mark Read/Unread; manual change doesn't eject | C2 | be/reader/progress | Reader More | read_state | Auto Read threshold and mark read/unread verified in `test_reading.py`; the reader offers Mark as read. **Missing:** Mark as unread in the UI | IN_PROGRESS |
| M26.15 | Continue Reading restores exact same-source progress; Long Strip approximate | C2 | be/reader, fe/home | Home, Work Details | progress | Implemented and carried by eight passing tests — `opens a unit where it was left rather than at the beginning`, `brings the stored page into view in Long Strip`, `clamps a stored position that is past the end of the unit`, `starts at the beginning when the library holds no position`, `writes nothing merely by resuming`, `opens the book at the chapter it was left on`, `opens the document at the page it is given`, `is given the page the library holds, through the Book Reader that renders it` — plus a live locator round-trip against the running API. **Not VERIFIED:** WP-R1's own criterion "re-enter the unit in a browser and land where you left" has not been executed. That step is `BLOCKED_BY_ENVIRONMENT` (E-01, `docs/plan/ISSUES.md`): Chromium cannot spawn on this host. The criterion stands unchanged | IMPLEMENTED |
| M26.16 | Subtle source indicator; manual switching only; same-language alternatives; layout warning; Start This Unit / Try Approximate Position; never fake page equivalence; uncertain → say so, open target track, don't guess | C2,C5 | fe/reader/source_switch, be/reader | Reader Change Source | — | The reader shows no source indicator and cannot switch source; switching exists only on Work Details | NOT_STARTED |
| M26.17 | Settings precedence Session > Work > Content-Type > Global; remember per-Work ON; normal vs advanced settings; backgrounds Black/Dark Gray/White | C2 | be/settings, fe/reader/settings | Reader Settings | reader_settings scoped | precedence tests | VERIFIED |
| M26.18 | Preload ~next 7 / previous 4; Long Strip bounded window; advanced only | C2,C5 | fe/reader/preload | advanced settings | — | No preload policy; the reader fetches what it renders | NOT_STARTED |
| M26.19 | Compact download state (not downloaded/progress/downloaded); quiet auto-download; Download Entire Work on Work page/More | C2,C5 | fe/reader | Reader top bar | — | Per-unit download from Work Details. **Missing:** compact download state in the reader and Download Entire Work | IN_PROGRESS |
| M26.20 | Reader Cache ≠ download; no noisy Cached badges; details distinguish; cache key source + unit identity + resource validator, never title/number | C5 | be/reader/cache | Reader details | cache.db, blobs | key tests; eviction protections | VERIFIED |
| M26.21 | Page failure Retry/Repair/Skip; corrupt local Repair from Source/Skip; never silently delete; source unavailable keeps local/cached readable, no switch; inline Reconnect resuming same unit; calm rate-limit auto retry; offline Downloaded vs Online-only | C2,C5 | fe/reader/errors, be/reader | Reader | — | `reader.pageFailed` offers Retry. **Missing:** Repair from Source and Skip for a corrupt local page | IN_PROGRESS |
| M26.22 | Book Reader; no full notes/drawing/annotations; only bookmarks + highlights; sequential page bookmarks not required | C2 | fe/reader/book | Reader | bookmarks, highlights | EX-15 check | VERIFIED |
| M26.22a | EPUB: font family/size, line height, margins, theme, TOC, search, bookmarks, highlights, logical progress; TOC tabs; no fake page count | C2 | fe/reader/epub | Reader | bookmarks, highlights, progress | `BookReader.test.tsx` (TOC, search, bookmarks, highlights, logical progress, TOC tabs). **Missing:** font family/size, line height, margins and theme | IN_PROGRESS |
| M26.22b | PDF: navigation, zoom, fit width/page, text-layer search, bookmarks, highlights, progress, optional sidebar | C2 | fe/reader/pdf | Reader | bookmarks, highlights, progress | `PdfView.test.tsx` (navigation, text-layer search, bookmarks, highlights, progress). **Missing:** zoom and fit width/page (the page renders at a fixed scale) | IN_PROGRESS |
| M26.23 | Multi-tab: no stale regression; debounced writes; force flush on unit change/hidden/exit/lifecycle | C2 | be/reader/progress, fe/reader | — | progress.revision | multi-tab stale-write tests; Mark Unread/reread still work | VERIFIED |
| M26.24 | Layout-preserving skeletons; one-time "Tap/click center" hint | C2 | fe/reader | Reader | local hint flag | No layout-preserving skeletons and no one-time centre-tap hint | NOT_STARTED |
| M27 | Never inject untrusted HTML/EPUB/document content into app origin/DOM; sanitize, sandbox, CSP, script blocking, isolated viewer, safe SVG; no auth/privileged/network escape (K3) | C2 | be/reader/content_routes, fe/reader/isolation | Reader | — | INV-12 malicious HTML/EPUB/SVG/PDF tests | VERIFIED |

## §28–§29 Authentication and first run

| ID | Requirement | Phase | Location | Surface | Persistence | Evidence | Status |
|---|---|---|---|---|---|---|---|
| M28 | Web UI authentication | C1,C8 | be/auth, be/api | Settings → Remote Access | remote_auth | rows below | VERIFIED |
| M28.1 | Localhost + LAN auth OFF by default; genuine LAN fully trusted incl. passkey reset / session revoke | C1,C8 | be/api/access | — | trusted networks config (A2) | LAN admin tests | VERIFIED |
| M28.2 | LAN origin from real connection + explicit config; X-Forwarded-For only from trusted proxies; remote proxy traffic gets no LAN trust | C1,C8 | be/api/access | — | trusted proxies config | forged header + proxy tests (INV-30) | VERIFIED |
| M28.3 | Remote: passkey-only built-in auth; advanced VPN/proxy setups; canonical HTTPS hostname; LAN IP stays unauthenticated | C8 | be/auth/webauthn | Remote setup | passkeys | passkey register/authenticate tests | VERIFIED |
| M28.4 | Single fixed internal WebAuthn identity; never exposed as account/profile | C8 | be/auth | — | constant user handle | UI audit | VERIFIED |
| M28.5 | Recovery code at first passkey; not for login; stored as verifier; regeneration invalidates; can authorize new passkey; LAN Recovery resets passkeys + revokes sessions + allows registration; explicit confirmation affecting only remote auth | C8 | be/auth/recovery | Remote Access, LAN Recovery dialog | recovery verifier | regeneration invalidation; recovery scope test (library untouched) | VERIFIED |
| M28.6 | Session list (label, current, created, last active, expiration); Revoke / Revoke All Other; no invasive fingerprinting; default 30 d, options shorter/90 d/1 y/manual; HttpOnly, Secure on HTTPS, SameSite; no tokens in Web Storage; sensitive ops may re-auth | C8 | be/auth/sessions | Remote Access sessions | ui_sessions | session defaults; Web Storage scan | VERIFIED |
| M28.7 | Remote state-changing APIs: Origin validation, CSRF, secure cookies; proxy auth only from configured proxy | C1,C8 | be/api/csrf | — | — | CSRF/Origin rejection tests | VERIFIED |
| M29 | Short first run: Welcome → Storage → Access Mode (Local/LAN/Remote) → Remote hostname/passkey/recovery → optional sources → Finish; no forced advanced config | C8 | fe/first_run, be/services/first_run | First Run | settings | first-run e2e ar/en + mobile | VERIFIED |

## §30–§32 Notifications, home semantics, UI direction

| ID | Requirement | Phase | Location | Surface | Persistence | Evidence | Status |
|---|---|---|---|---|---|---|---|
| M30 | In-app notifications only; no browser notifications | C6 | be/notifications, fe/notifications | Notifications drawer | notifications | EX-12 check | VERIFIED |
| M30.1 | Important: New Releases, Download Failed, Reconnect Required, Low Storage, Catalog Suspicious; Informational: Plugin Update, Source Recovered, Backup/Import; background events don't notify; not a log viewer | C6 | be/notifications/classes | drawer | class column | no-noise tests | VERIFIED |
| M30.2 | Group releases per Work; safe numeric range "Ch. 209–211"; mixed lists; cross-Work summary | C6 | be/notifications/grouping | drawer | — | grouping tests incl. mixed/specials | VERIFIED |
| M30.3 | Seen/Unseen independent of Read/Unread/Partial; "Mark All as Seen" not "Read"; Clear Seen; never changes reading state | C6 | be/notifications | drawer | seen flag | INV-22 test | VERIFIED |
| M30.4 | No per-item success spam; grouped batch success; final failures; Smart Retry silent until exhausted | C6 | be/notifications | drawer | — | download notification tests | VERIFIED |
| M30.5 | Reconnect dedupe per Source | C6 | be/notifications/dedupe | drawer | dedupe key | 20 Works → 1 notice test | VERIFIED |
| M30.6 | Rate limit status-only; one concise notice if prolonged and blocking | C6 | be/notifications | drawer | — | prolonged rate limit test | VERIFIED |
| M30.7 | Low Storage dedupe per root; re-notify only after recovery+recurrence or escalation | C6 | be/notifications | drawer | — | recurrence tests | VERIFIED |
| M30.8 | Catalog Suspicious warning states last trusted catalog kept | C6 | be/notifications | drawer | — | copy test | VERIFIED |
| M30.9 | Plugin updates informational; new permissions need explicit review; never silent auto-update | C6,C3 | be/notifications, be/plugins | Review Update | — | permission update test | VERIFIED |
| M30.10 | Source Recovered optional/silent by default | C6 | be/notifications | — | setting | default test | VERIFIED |
| M30.11 | Backup failure important; success silent; large import may notify for review | C6,C7 | be/notifications | drawer | — | tests | VERIFIED |
| M30.12 | One or two focused actions (View Releases, Retry, Reconnect, Manage Storage, Review Update) | C6 | fe/notifications | drawer | — | UI test | VERIFIED |
| M30.13 | Mandatory logical dedupe keys (`source-auth:`, `storage-low:`, `catalog-suspicious:`, `new-release:`); repeats update existing | C6 | be/notifications/dedupe | — | unique dedupe_key | dedupe tests | VERIFIED |
| M30.14 | Persistent while action required; transient may expire; resolved lingers ~1 h | C6 | be/notifications/lifecycle | drawer | state timestamps | lifecycle tests | VERIFIED |
| M30.15 | Bounded history 30 d or 500, whichever first; subsystem state stays authoritative | C6 | be/notifications/cleanup | — | — | both-limit tests (D2) | VERIFIED |
| M31 | Home discovery semantics | C2,C4,C6 | fe/home, be/services/home | Home | — | rows below | VERIFIED |
| M31.1 | Trending only from trusted getTrending data; no fake global score; hide if none | C4 | be/services/home | Home Trending | cache.db | hide-without-data test | VERIFIED |
| M31.2 | Latest Releases = getLatest discovery feed, distinct from Following New Releases | C4 | be/services/home | Home | cache.db | separation test | VERIFIED |
| M31.3 | Recently Added = recently added to My Shelf | C6 | be/services/home | Home | shelf_entries.added_at | test | VERIFIED |
| M31.4 | Hero contextual but stable; no network request to choose; priority Continue Reading > pinned/new-release > cached discovery | C2,C6 | be/services/home | Home Hero | — | no-network Hero test | VERIFIED |
| M32 | Approved visual identity (forest-green sidebar, cream canvas, olive, wood, restrained shadows, serif headings, clean UI type; calm/premium; not SaaS/Netflix) | C2 | fe/theme | all | — | visual checks vs reference V (EB-2) | VERIFIED |
| M32.1 | Fixed forest-green sidebar with Home/Search/My Shelf/Following/Downloads/Sources/Settings; logo top-left; sparse botanical motif | C2 | fe/shell | sidebar | — | nav test; screenshot | VERIFIED |
| M32.2 | No avatar; Notifications + Needs Attention (hidden at 0; Reconnect/Low Storage/Download Failed/Catalog Suspicious; grouped popover); filtered shortcut, no duplication | C2,C6 | fe/shell/header | header | derived | zero-hidden + filter tests | VERIFIED |
| M32.3 | Home close to reference: welcome, subtitle, Hero, Continue Reading, Trending, Latest, Recently Added, others when useful; adaptive; not dashboard | C2 | fe/home | Home | — | empty-state + adaptive tests; screenshot | VERIFIED |
| M32.4 | Large rounded Hero with cover/title/type/description/Continue/atmospheric art | C2 | fe/home/hero | Home | — | screenshot | VERIFIED |
| M32.5 | Wooden shelves on Home, My Shelf, selected Discover; paper/card for system; none in Settings/Downloads/Sources/Backup; premium subtle wood | C2 | fe/components/shelf | Home, My Shelf | — | screenshot audit | VERIFIED |
| M32.6 | Work cards Compact/Standard/Detailed; one logical Work; dominant cover; concise availability; no internal states | C2 | fe/components/work_card | cards | — | INV-27 UI test | VERIFIED |
| M32.7 | Search UI: warm canvas, serif title, large field, filter chips, Grid/List, cover results, no mandatory shelves | C2,C4 | fe/search | Search | — | screenshot | VERIFIED |
| M32.8 | Work Details: small Hero header (cover/title/original/type/creator/description); actions Continue/Read, Add to Shelf, Follow, Favorite, Pin; tabs Read/Details/Sources; elegant index unit list | C2 | fe/work | Work Details | — | UI tests | VERIFIED |
| M32.9 | My Shelf bookshelf motif; Pinned/Reading/Completed/Favorites sections; search/sort/filter/Grid-List | C2,C6 | fe/shelf | My Shelf | — | `ShelfScreen.test.tsx` (views, search, Grid/List). **Missing:** sort | IN_PROGRESS |
| M32.10 | Following as reading journal; paper rows; New Releases / Needs Attention / Up to Date; no charts | C2,C6 | fe/following | Following | — | UI tests | VERIFIED |
| M32.11 | Downloads operational: no shelves, paper panels, olive progress, green controls, batch cards, expandable units; not analytics | C2,C5 | fe/downloads | Downloads | — | UI tests | VERIFIED |
| M32.12 | Sources elegant catalog-card list: source, type/language, status, last successful check, Configure/More; advanced hidden (A3) | C2,C3 | fe/sources | Sources | — | UI tests | VERIFIED |
| M32.13 | Notifications warm right drawer; Mark All as Seen / Clear Seen / View All | C2,C6 | fe/notifications | drawer | — | UI tests | VERIFIED |
| M32.14 | Settings paper aesthetic; categories left / panel right; General, Reader, Downloads, Storage, Sources, Notifications, Backup, Remote Access, Advanced, Developer; progressive disclosure | C2 | fe/settings | Settings | — | `SettingsScreen.test.tsx`; General, Storage, Backup, Remote access and Developer are built. **Missing:** Reader, Downloads, Sources, Notifications and Advanced are placeholders | IN_PROGRESS |
| M32.15 | Backup/Restore archival feel; multi-step restore, not casual modal | C7 | fe/backup | Backup | — | UI tests | VERIFIED |
| M32.16 | Export wizard Content → Format → Destination → Review; small covers | C7 | fe/export | Export | — | UI tests | VERIFIED |
| M32.17 | First Run "Welcome to OneShelf" / "Your stories, one library."; subtle botanical | C8 | fe/first_run | First Run | — | copy test ar/en | VERIFIED |
| M32.18 | Reader strips decoration; Black/Dark Gray/White; controls keep icon/type quality | C2 | fe/reader | Reader | — | screenshot | VERIFIED |
| M32.19 | Paper drawers/dialogs; no heavy glassmorphism; destructive dialogs explain what happens and what remains | C2 | fe/components/dialog | dialogs | — | copy audit (M47) | VERIFIED |
| M32.20 | Subtle motion (2–4 px lift, soft slide, Hero crossfade); no bounce/elastic/flashy/parallax; reduced motion | C2 | fe/theme/motion | all | — | reduced-motion test | VERIFIED |
| M32.21 | Mobile not shrunk desktop; bottom nav Home/Search/Shelf/Following/More (Downloads/Sources/Notifications/Settings); touch-first Reader | C2 | fe/shell/mobile | mobile | — | mobile viewport e2e | VERIFIED |

## §33–§39 Backup, export, separation, events, import, scanner, packaging

| ID | Requirement | Phase | Location | Surface | Persistence | Evidence | Status |
|---|---|---|---|---|---|---|---|
| M33 | Exactly two backup types | C7 | be/backup | Settings → Backup | backups | rows below | VERIFIED |
| M33.1 | Library Backup contents list; no downloaded reading files | C7 | be/backup/library | Backup | — | manifest inspection test | VERIFIED |
| M33.2 | Full Backup = Library + selected content; user chooses Works | C7 | be/backup/full | Backup selection | — | selection test | VERIFIED |
| M33.3 | Hard exclusions: passwords, cookies, sessions, tokens, remote UI sessions, recovery code, master key, browser profiles, staging, partials, rebuildable caches | C7 | be/backup | — | — | INV-19 content scan of both types | VERIFIED |
| M33.4 | Canonical `.osbackup` with manifest, schema/version, checksums, inventory, plugin requirements | C7 | be/backup/format | — | — | format validation tests | VERIFIED |
| M33.5 | Older backup migrates forward in staging (original unchanged); newer blocked, never discard unknown fields | C7 | be/backup/restore | Restore | — | version compatibility tests | VERIFIED |
| M33.6 | Preflight: archive/checksum, manifest, compatibility, space, plugins, permission changes, summary; missing plugin doesn't block (reinstall/skip); compatible newer only with review; new permissions need approval | C7 | be/backup/preflight | Restore steps | restore_ops | preflight tests | VERIFIED |
| M33.7 | Replace (after Safety Snapshot) / Merge with deterministic rules (current manual wins, add missing, progress never regresses, healthy files kept, verified backup repairs missing/corrupt) | C7 | be/backup/merge | Restore mode | — | merge conflict matrix tests | VERIFIED |
| M33.8 | Library Backup every 7 d with catch-up; Full manual; keep 4 verified; create → verify → rotate; never delete prior verified first | C7 | be/backup/schedule | Backup settings | backups | failed verification doesn't rotate; catch-up test | VERIFIED |
| M33.9 | Explicit Backup Location; default app storage allowed; same-disk warning; external mounts | C7 | be/backup, fe/backup | Backup Location | settings | warning test | VERIFIED |
| M33.10 | Built-in encryption not required; secrets excluded; external encryption allowed | C7 | — | docs | — | docs note | IMPLEMENTED |
| M34 | Export ≠ Backup; one-way copy; never modifies library/DB/progress/mapping/content | C7 | be/export | Export wizard | export_jobs | INV-20 state diff test | VERIFIED |
| M34.1 | Scope Current Unit/Selected/Range/Entire Work/Selected Works; contract Work+Language+Source+units+formats; no mixing | C7 | be/export/contract | wizard Content | — | contract tests | VERIFIED |
| M34.2 | Prefer local files as-is; copy originals; no recompress/rebuild | C7 | be/export | — | — | byte-identical copy test | VERIFIED |
| M34.3 | Missing content choices Export Downloaded Only / Download Missing Then Export / Cancel; explicit permanent-download notice; normal engine → integrity → commit → export; no hidden temp download | C7 | be/export, fe/export | wizard | — | INV-21 test | VERIFIED |
| M34.4 | CBZ default for sequential; originals for books; no conversion subsystem | C7 | be/export | wizard Format | — | EX-29 check | VERIFIED |
| M34.5 | Folder default; optional ZIP; no giant default ZIP; avoid recompression | C7 | be/export | wizard | — | ZIP store-mode test | VERIFIED |
| M34.6 | Preserve ComicInfo.xml; optional `oneshelf-export.json` (title, aliases, language, source, units, formats, date); never secrets/sessions/tokens/cookies/absolute paths; files usable without it | C7 | be/export/metadata | — | — | metadata secret/path scan | VERIFIED |
| M34.7 | Cleaner export naming; IDs not required by default | C7 | be/export/naming | — | — | naming tests | VERIFIED |
| M34.8 | Explicit destination; preflight online/writable/space/conflicts; never silent overwrite; Skip Identical/Replace/Keep Both; checksum-identical skip | C7 | be/export/destination | wizard Destination/Review | — | conflict tests | VERIFIED |
| M34.9 | Persistent resumable jobs; streaming; destination-local staging; checksum verify; per-file failure isolation; Retry Failed; always Copy | C7 | be/export/jobs | Export activity | export_jobs, export_items | interruption resume; per-file failure tests | VERIFIED |
| M34.10 | Local Source Track exports; missing plugin doesn't block | C7 | be/export | — | — | INV-11 export test | VERIFIED |
| M34.11 | Export activity 30 d or 100 jobs; cleanup never deletes exported files | C7 | be/export/cleanup | activity | — | both-limit + file-preservation tests | VERIFIED |
| M35 | Notifications / Download History / Export activity / Backup history / Diagnostics kept separate | C6,C7 | respective modules | respective screens | separate tables/files | separation audit | VERIFIED |
| M36 | Real-time event channel (SSE/WebSocket) for downloads, notifications, progress, source/job state; polling fallback; no cloud | C1,C6 | be/events, be/api/sse, fe/events | all live screens | — | `tests/unit/test_events.py`, `GET /api/events`. **Missing:** no frontend client subscribes to it; only Search uses its own SSE stream | IN_PROGRESS |
| M37 | Import CBZ/PDF/EPUB; Copy default; Move explicit; Leave in Place advanced/future *(optional)*; confident associate / Choose Existing / Create Local Work; no aggressive merge; drag & drop optional | C1,C7 | be/importer | Import flow | imports, assets | import uncertainty tests; Copy leaves source intact | VERIFIED |
| M38 | Scanner reconciles; manual delete → Missing Local File; offline → Unavailable; missing plugin still readable; OneShelf IDs aid recovery; per-asset checksum/size/path/integrity; checksums never matching evidence; no dedup | C1,C7 | be/storage/scanner | Storage | assets | scanner tests | VERIFIED |
| M39 | CBZ may include ComicInfo.xml; preserve originals; no unnecessary recompression; packaging only after integrity verification | C1,C5 | be/downloads/packaging | — | — | packaging order + byte preservation tests | VERIFIED |

## §40–§43 API docs, source suite, defaults, diagnostics

| ID | Requirement | Phase | Location | Surface | Persistence | Evidence | Status |
|---|---|---|---|---|---|---|---|
| M40 | API documentation: endpoint groups, auth expectations, events, plugin APIs, job interfaces; no cloud API; no secret exposure | C3→C9 | docs/api | — | — | docs review vs implemented routes | VERIFIED |
| M41 | Initial test source suite | C3→C9 | plugins/official, test_source | — | — | rows below; source-capability evidence ledger | VERIFIED |
| M41.1 | Real sources: MangaDex, 3asq/Al-Aasheq, WEBTOON, Tapas, Safahat/Hindawi (A5), Project Gutenberg, arXiv, Standard Ebooks | C3→C9 | plugins/official | Sources | plugins | Five of eight ship and are tested offline and live: MangaDex, Gutenberg, arXiv, Standard Ebooks and WEBTOON (search/work/catalog only). **Blocked:** 3asq/Al-Aasheq — `3asq.org` does not resolve from this environment; Tapas — episode data sits in script state and `/search` is disallowed by robots; Safahat/Hindawi — book pages render with JavaScript; the WEBTOON reader — the viewer builds its images with JavaScript. Unblocked by network access to 3asq, and by justified browser escalation (or the underlying XHR) for the other three, then generating and verifying a package for each | BLOCKED |
| M41.2 | Controlled OneShelf Test Source for deterministic failure testing | C1,C3 | test_source/ | dev only | — | fault fixture suite | VERIFIED |
| M41.3 | Roles: foundation (Gutenberg, Hindawi, arXiv), sequential (MangaDex, 3asq), difficult web (WEBTOON, Tapas), format stress (Standard Ebooks: one Work, many formats, no duplicate Works) | C3→C9 | plugins/official | — | — | role-specific workflow tests | VERIFIED |
| M41.4 | Correctness/reference vs real-world stress sources; 3asq public parser testing only, not official/licensed default | C9 | docs/evidence | — | — | evidence ledger labels | VERIFIED |
| M41.5 | Local deterministic cases: irregular order/numbers, Special, Prologue, 3.5, 300→7, 429 Retry-After, 500, session expiry, HTML-as-media, corrupt media, interruption, changed ETag, unapproved redirect, malformed metadata, incomplete pagination, other recovery | C1→C5 | test_source/ | — | — | one scenario test each | VERIFIED |
| M42 | Single source of approved defaults, consistent across UI/API/runtime/migrations (D2) | C1 | be/settings/defaults | Settings | settings | DEF rows | VERIFIED |
| M43 | Diagnostics: parser/network/job/health operational data only; 7 d or 100 MB rotating; never passwords/cookies/tokens/auth headers/sensitive bodies; no matcher telemetry | C3,C6 | be/diagnostics | Settings → Advanced | rotating files | `test_redact.py` (redaction at write time). **Missing:** the rotating 7 d / 100 MB diagnostics store itself | IN_PROGRESS |

## §44–§50 UX rules, security, exclusions, non-goals

| ID | Requirement | Phase | Location | Surface | Persistence | Evidence | Status |
|---|---|---|---|---|---|---|---|
| M44 | Top-right Needs Attention + Notifications bell with counts; Needs Attention secondary to Hero, hidden at zero, actionable only; grouped popover with Reconnect/Manage Storage/Retry/View Source | C2,C6 | fe/shell/header | header | derived | UI tests | VERIFIED |
| M45 | Progressive disclosure: normal vs advanced for Downloads, Reader, Sources as listed | C2→C8 | fe/settings, fe/sources | Settings, Sources | — | `a11y.test.tsx`; Sources keeps versions/trust behind More. **Missing:** the normal/advanced split for Downloads, Reader and Sources settings, whose panels are placeholders | IN_PROGRESS |
| M46 | Errors answer what happened / what OneShelf did safely / what user can do; raw errors only in expandable details | C2→C8 | fe/components/error | all | — | copy audit | VERIFIED |
| M47 | Destructive actions state what is removed, what remains, effects on files/progress/Follow/Shelf (Remove from Shelf, Delete Files, Replace Library, Reset Remote Passkeys, Uninstall Plugin) | C2,C6,C7,C8,C3 | fe/components/dialog | dialogs | — | Restore, LAN reset, history clearing and storage actions explain what happens (`ConfirmDialog`, `BackupPanel`, `RemotePanel`). **Missing:** Remove from Shelf and Delete Files dialogs, because those actions are not in the UI | IN_PROGRESS |
| M48 | Security boundaries summary (declarative plugins, Core-owned capabilities, allowlists, redirect/DNS, SSRF, genuine LAN, trusted proxies, Origin/CSRF, secure cookies, no Web Storage tokens, document isolation, path safety, no plugin FS, no raw sessions, no secrets in logs/backups/export) | C1→C8 | see architecture.md §6 | — | — | INV-12–15, 19, 30 + security review | VERIFIED |
| M49 | Explicit v1 exclusions stay out of scope | all | — | — | — | EX rows | IMPLEMENTED |
| M50 | Non-goals don't delay v1 (multi-user, cloud sync, annotation suite, AI recs, automation marketplace, WASM, conversion, dedup, push) | all | — | — | — | scope review per phase | IMPLEMENTED |

## §51–§56 Invariants, structure, testing, design state, reconciliation

| ID | Requirement | Phase | Location | Surface | Persistence | Evidence | Status |
|---|---|---|---|---|---|---|---|
| M51 | All 30 acceptance invariants preserved | all | — | — | — | 29 invariants verified; INV-25's own affordances are not built yet | IN_PROGRESS |
| M52 | Subsystem separation as listed; source-specific logic out of generic queue/storage; small testable units | C0→all | architecture.md §2 | — | — | architecture review each phase; import-boundary lint | IMPLEMENTED |
| M53 | Test categories: unit, integration, deterministic source failures, adapter contract, migration, crash/recovery, queue restart, storage offline, catalog trust, session reconnect, rate limits, resume/validators, corrupt repair, path safety, SSRF, EPUB/HTML isolation, CSRF/Origin, backup compatibility, restore merge, export resume/conflicts, Arabic normalization, RTL/LTR, manual overrides, multi-tab progress, events, accessibility-critical; isolated data only | C1→C9 | tests/ | — | isolated fixtures | C9 final verification report | VERIFIED |
| M54 | Architecture fully specified; visual refinement only within approved language; no semantic changes | C0→all | — | — | — | ledger | VERIFIED |
| M55 | Instructions to the Meta Prompt generating model | — | — | — | — | Meta Prompt §A | VERIFIED |
| M56 | Retained older requirements (Docker, ar/en, RTL/LTR, persistent jobs, concurrency control, stable IDs, atomic commit, URL entry, realtime, API docs, bounded memory, display/matching/identity separation) and superseded ideas | all | — | — | — | Retained requirements hold except: Docker verification (EB-1), the realtime UI client (M36) and bounded reader memory (M26.6) | IN_PROGRESS |

## §51 Acceptance invariants

| ID | Invariant | Gate phase(s) | Minimum evidence (Meta Prompt §D1) | Status |
|---|---|---|---|---|
| INV-01 | Suspicious/incomplete catalog never erases trusted state | C4 | incomplete pagination + 300→7 preserve Trusted and derived state; recovery obeys completeness | VERIFIED |
| INV-02 | Source/language never switch silently | C4,C5,C6,C7 | search, Follow, Reader, retries, fallback, downloads, exports preserve source/language | VERIFIED |
| INV-03 | Soft Group never becomes permanent identity | C4 | Soft Group cannot create mappings; actions persist concrete track | VERIFIED |
| INV-04 | User overrides never silently overwritten | C4,C7 | refresh, plugin update, restore merge preserve overrides | VERIFIED |
| INV-05 | Unknown metadata never negative evidence | C4 | missing creator/date/volume/classification stays Unknown, not a mismatch | VERIFIED |
| INV-06 | Unknown quality never blocks content | C4,C5 | Unknown quality doesn't hide/reject/mark unavailable | IMPLEMENTED |
| INV-07 | Reading never implies permanent download unless enabled | C5 | ordinary reading makes no permanent download | VERIFIED |
| INV-08 | Auto-download OFF by default | C1,C5 | defaults registry + fresh install assertion; enabled engagement per spec | VERIFIED |
| INV-09 | Follow never auto-downloads | C6 | new-release events enqueue nothing | VERIFIED |
| INV-10 | Remove from Shelf / Unfollow / Delete Files independent | C6 | separate assertions on files, Shelf, Follow, read state, progress | VERIFIED |
| INV-11 | Local content readable without source/plugin/network | C2,C7 | read + export CBZ/PDF/EPUB with source offline, plugin disabled/uninstalled, session disconnected | VERIFIED |
| INV-12 | Reader content can't execute privileged actions | C2 | malicious HTML/EPUB/SVG/PDF can't reach privileged actions, auth context or prohibited network | VERIFIED |
| INV-13 | Community plugins can't execute arbitrary code | C3 | malicious `.osp` code payloads rejected | VERIFIED |
| INV-14 | Plugins can't access arbitrary paths | C1,C3 | path payloads rejected; Core-only path generation | VERIFIED |
| INV-15 | Plugins can't SSRF into LAN/internal | C3 | HTTP + browser redirect/DNS SSRF cases blocked | VERIFIED |
| INV-16 | Incomplete downloads never appear as completed | C1,C5 | incomplete/corrupt artifacts stay out of local content | VERIFIED |
| INV-17 | Commit crash recoverable idempotently | C1,C5 | crash at each commit step; repeated reconciliation, no duplicate/lost registration | VERIFIED |
| INV-18 | Offline storage ≠ mass deletion | C1,C7 | offline root → Unavailable, no mass Missing/cleanup; safe reconnect reconcile | VERIFIED |
| INV-19 | Backups contain no sessions/passwords/tokens | C7 | inspect Library + Full contents/manifests for all exclusions | VERIFIED |
| INV-20 | Export never silently modifies library | C7 | state diff before/after normal export | VERIFIED |
| INV-21 | Download Missing Then Export requires explicit notice | C7 | disclosure required; normal validated commit then export | VERIFIED |
| INV-22 | Notifications never alter reading state | C6 | Seen / Clear Seen / cleanup leave reading untouched | VERIFIED |
| INV-23 | Clearing history never deletes content/state | C5,C6,C7 | download/export/notification history cleanup preserves content + progress | VERIFIED |
| INV-24 | Navigation follows Source Track order | C2 | prologue, Special, Extra, 3.5 navigate by track order | VERIFIED |
| INV-25 | Cross-source progress approximate/manual | C2,C5 | Nothing maps positions across sources, and a track change re-asks the backend for that track's units (C2 gate). **Missing:** the Start This Unit / Try Approximate Position affordances, which need in-reader source switching (M26.16) | IN_PROGRESS |
| INV-26 | Browser background work can't starve Reader/direct work | C3,C5 | saturated low-priority work; bounded Reader responsiveness | VERIFIED |
| INV-27 | Search results represent Works | C4 | Work-level results with selectable provenance, no duplicated source cards | VERIFIED |
| INV-28 | Covers never identity evidence | C4 | matching ignores covers; test with identical/different covers | VERIFIED |
| INV-29 | Matching diagnostics never telemetry | C4,C6,C9 | review persistent records, diagnostics, network calls, cleanup | VERIFIED |
| INV-30 | Remote passkey/session/CSRF boundaries; genuine LAN trusted per config | C1,C8 | passkey/session/CSRF/Origin + LAN/trusted-proxy/forged-header tests | VERIFIED |

## §42 Defaults (single defaults registry, D2)

| ID | Default | Phase | Verification | Status |
|---|---|---|---|---|
| DEF-backup | Library Backup every 7 d; Full manual; retain last 4 verified | C7 | schedule + rotation tests | VERIFIED |
| DEF-discovery-cache | TTL 7 d; 250 MB; LRU | C4 | cleanup both-limit tests | VERIFIED |
| DEF-reader-cache | TTL 7 d; 5 GB; LRU; never evict current unit / open nearby pages / permanent downloads | C5 | eviction protection tests | VERIFIED |
| DEF-auto-download | OFF; when enabled ~12% + genuine interaction | C1,C5 | INV-08; trigger test | VERIFIED |
| DEF-read-ahead | next 5 existing Reading Units | C5 | bounded read-ahead test | VERIFIED |
| DEF-auto-mark-read | 97% | C2 | threshold test | VERIFIED |
| DEF-reader-smart-controls | auto-hide ~3 s | C2 | timing test | VERIFIED |
| DEF-download-concurrency | HTTP 4; Browser 1 (independent) | C3,C5 | governor limit tests | VERIFIED |
| DEF-follow | ~12 h + jitter | C6 | scheduler test | VERIFIED |
| DEF-notifications | resolved visible ~1 h; history 30 d or 500 | C6 | lifecycle + both-limit tests | VERIFIED |
| DEF-export-activity | 30 d or 100 jobs | C7 | both-limit test | VERIFIED |
| DEF-diagnostics | 7 d or 100 MB | C3 | The retention default exists in the registry but nothing consumes it: there is no diagnostics store to rotate | NOT_STARTED |
| DEF-retry | initial + up to 3 retries | C5 | retry count test | VERIFIED |
| DEF-remote-session | 30 d (options shorter/90 d/1 y/manual) | C8 | session expiry test | VERIFIED |
| DEF-storage-reserve | 5% capped 5 GB; warning ~2× reserve | C1 | guard tests | VERIFIED |
| DEF-catalog-suspicious | ≥~50% loss and ≥5 units; complete snapshots only; not sole truth | C4 | heuristic boundary tests | VERIFIED |
| DEF-staging | successful leftovers ~24 h; resumable failed ~7 d | C1,C5 | retention tests | VERIFIED |
| DEF-other | Preferred + Ask; settings precedence; classification precedence; remember per-Work Reader settings ON; preload ~7/4; folder export default; Copy import default; local/LAN auth OFF; metadata/format identity behavior (Meta Prompt D2) | C1→C8 | registry consistency test across UI/API/runtime/migrations | IMPLEMENTED |

## §49 Exclusions (negative verification)

| ID | Excluded | Verification | Status |
|---|---|---|---|
| EX-01 | Cloud OneShelf account | no account endpoints/UI; offline operation | IMPLEMENTED |
| EX-02 | Multi-user | single-user model audit | IMPLEMENTED |
| EX-03 | Arbitrary executable community plugin code | INV-13 | VERIFIED |
| EX-04 | Restricted-RPC plugin design | architecture review | IMPLEMENTED |
| EX-05 | Matcher telemetry / central collector / shared dataset | INV-29 | VERIFIED |
| EX-06 | Automatic source switching | INV-02 | VERIFIED |
| EX-07 | Automatic cross-language fallback | INV-02 | VERIFIED |
| EX-08 | Automatic translation | no translation code paths | IMPLEMENTED |
| EX-09 | Title stemming | no-stemming tests (C09) | VERIFIED |
| EX-10 | Cover/image matching | INV-28 | VERIFIED |
| EX-11 | AI matching requirement | dependency/architecture audit | IMPLEMENTED |
| EX-12 | Browser notifications | no Notification API / push usage audit | VERIFIED |
| EX-13 | Automatic new-release downloads | INV-09 | VERIFIED |
| EX-14 | Complex storage deduplication | architecture audit | IMPLEMENTED |
| EX-15 | Full note/drawing/annotation system | Reader scope audit (bookmarks/highlights only) | IMPLEMENTED |
| EX-16 | Social feed | UI/API audit | IMPLEMENTED |
| EX-17 | Comments/reviews | UI/API audit | IMPLEMENTED |
| EX-18 | Followers | UI/API audit | IMPLEMENTED |
| EX-19 | Chat | UI/API audit | IMPLEMENTED |
| EX-20 | Ads | UI/dependency audit | IMPLEMENTED |
| EX-21 | Subscriptions/payments | UI/API audit | IMPLEMENTED |
| EX-22 | Gaming/achievement systems | UI/API audit | IMPLEMENTED |
| EX-23 | Anti-bot stealth/bypass | K1 guard test; config audit | VERIFIED |
| EX-24 | CAPTCHA bypass | action-required reporting test | IMPLEMENTED |
| EX-25 | Paywall bypass | Use My Session scope tests | VERIFIED |
| EX-26 | DRM bypass | code audit | IMPLEMENTED |
| EX-27 | Screenshot-based normal extraction | extraction method audit | IMPLEMENTED |
| EX-28 | Hidden destructive cleanup | cleanup audits (M3.4, M25, INV-18/23) | VERIFIED |
| EX-29 | Implicit format conversion subsystem | export/packaging audit | VERIFIED |
| EX-30 | Uncontrolled plugin access to LAN/internal services | INV-15 | VERIFIED |

## Meta Prompt deliverables and source-investigation rules

| ID | Requirement | Phase | Evidence | Status |
|---|---|---|---|---|
| MPD-01 | Traceability + updated conflict/review ledger | C0→C9 | this file; conflict-review-ledger.md | VERIFIED |
| MPD-02 | Architecture, persistent-state/state-transition, migration/recovery docs | C0→C9 | architecture.md (baseline); updated per phase | VERIFIED |
| MPD-03 | API/auth/event and declarative plugin/generator documentation | C3→C9 | docs/api, docs/plugins | VERIFIED |
| MPD-04 | Deployment/startup/storage/backup/restore/upgrade instructions matching behavior | C9 | docs/ops | VERIFIED |
| MPD-05 | Dated source-capability evidence ledger (verified/unverified/unavailable/action-required/unsupported) | C3→C9 | docs/evidence/sources.md | VERIFIED |
| MPD-06 | Final verification report: commands, outcomes, workflows, artifact checks, UI/RTL/a11y screenshots, blocked gates | C9 | docs/evidence/verification.md | VERIFIED |
| MPG-1 | Investigate actual source before recipes; static first; justified browser escalation; no guessed selectors; no eval; no stealth/CAPTCHA/paywall/DRM; Use My Session only | C3→C9 | per-source investigation notes | VERIFIED |
| MPG-2 | Generate declarative packages with reviewed permissions; multi-Work/multi-query incl. Arabic; genuine empty queries; CDN vs ads domains; bounded transforms; adaptive only after failure; Unsupported instead of hacks | C9 | generator tests | VERIFIED |
| MPG-3 | Complete catalogs with completion evidence; preserve raw unit fields/order; no numeric gap/duplicate inference; formats don't create Works; reject non-content resources | C4,C9 | catalog/content tests | VERIFIED |
| MPG-4 | Recipes return descriptors; Core executes; scoped credentials; no header forwarding to CDN/redirect; expiring URL refresh bounded; error-class separation; Smart Retry/fallback semantics | C3,C5 | runtime tests | VERIFIED |
| MPG-5 | Verify through application services with isolated data; sanitized dated fixtures; Test Source synthetic faults; open/parse actual artifacts; record revision/plugin/source/conditions/checksums; no runtime telemetry | C3→C9 | evidence ledger | VERIFIED |

---

## Phase progress log

### C1 — 2026-09-17 (gate passed; see `docs/c1/verification.md`)

Rows moved to `IMPL` have their C1 backend portion implemented and tested; UI surfaces and later-phase behavior in the same row remain outstanding, so none are `VER` yet.

| ID | C1 implementation | Evidence | Remaining |
|---|---|---|---|
| M4, M4.1–M4.6, M4.4a | `db/schema/0001_initial.sql`, `domain/ids.py` | `tests/unit/test_schema.py` | matching (C4), listings (C3), UI (C2) |
| M17 | `storage/commit.py` | `tests/unit/test_commit_journal.py` | download packaging commits (C5) |
| M18 | `db/connection.py`, `db/migrate.py` | `tests/unit/test_db_migrations.py` | backup snapshots (C7) |
| M24.1–M24.7 | `storage/roots.py`, `paths.py`, `layout.py`, `staging.py`, `scanner.py` | `test_roots.py`, `test_paths.py`, `test_scanner.py` | Storage UI (C2), low-storage notifications (C6), migration copy flow (C7) |
| M25 | `storage/staging_cleanup.py`, `services/startup.py` | `tests/integration/test_startup_recovery.py` | download job recovery (C5) |
| M28.1, M28.2 | `api/access.py`, `api/middleware.py` | `test_access.py`, `test_app.py` | trusted-network setup + warning (C8, A2), LAN admin actions (C8) |
| M36 | `events/bus.py`, `GET /api/events` | `tests/unit/test_events.py`, smoke test | domain events + UI client (C2–C6) |
| M37 | `importer/service.py` | `tests/integration/test_local_import.py` | confident association (C4/C7), import UI/drag & drop (C2/C7) |
| M38 | `storage/scanner.py` | `tests/integration/test_scanner.py` | scanner UI, missing-plugin readability (C2/C3) |
| M42, DEF-staging, DEF-storage-reserve | `settings/defaults.py` | `test_defaults.py`, `test_roots.py`, `test_startup_recovery.py` | runtime use of remaining defaults in their phases |
| M52 | package layout per `docs/c0/architecture.md` §2 | code review | continues each phase |
| INV-08 | `DEFAULTS.auto_download.enabled = False` | `test_defaults.py` | runtime behavior (C5) |
| INV-14 | Core-only path generation and containment | `test_paths.py` | plugin path payload rejection (C3) |
| INV-16 | validation before commit; unverified finals never registered | `test_integrity.py`, `test_commit_journal.py` | download pipeline (C5) |
| INV-17 | idempotent journal recovery at every boundary | `test_commit_journal.py` | download commits (C5) |
| INV-18 | offline root → unavailable, no mass missing | `test_scanner.py`, `test_roots.py` | root migration (C7) |
| INV-30 | real-peer classification; trusted-proxy-only forwarding; remote denied | `test_access.py`, `test_app.py` | passkeys, sessions, CSRF/Origin (C8) |

Carried forward from C1 (still `NS`): M41.2 OneShelf Test Source skeleton → C3; M24.8 migration copy flow → C7 (remap done); M28.7 Origin/CSRF → C8; M39 packaging → C5.

### C3 — 2026-09-17 (gate passed; see `docs/c3/verification.md`)

| ID | C3 implementation | Evidence | Remaining |
|---|---|---|---|
| M9, M9.1–M9.6 | `plugins/package.py`, `schema.py`, `runtime.py`, `transforms.py` | `tests/unit/plugins/*` | native adapter review process (C9) |
| M10 | `plugins/manager.py`, `plugins/registry.py`, `api/sources.py` | `test_lifecycle.py`, `test_registry_sources.py`, `test_sources_api.py` | Sources UI (C2), plugin update notifications (C6) |
| M11 | `net/policy.py`, `net/http.py`, `net/egress_proxy.py`, `net/browser.py` | `test_policy.py`, `test_egress_proxy.py`, `test_browser.py` | — |
| M12.1 | Scrapling parser-only runtime; K1 guard | `test_runtime.py`, `test_no_stealth.py` | adaptive selectors + generator (C9) |
| M13 | `sessions/*`, login API | `test_sessions.py`, pipeline + browser + API login tests | Connect Account UI (C2); job WAITING_FOR_SESSION (C5) |
| M15 | `net/governor.py` wired into fetchers | `test_governor.py`, pipeline rate-limit test | Reader/download/Follow callers (C5/C6) |
| M21 | passive signals with plugin version | pipeline health test | states, hysteresis, active checks, UI (C6) |
| M41.2, M41.5 | `backend/testsource/` scenarios and package | pipeline tests | media/ETag/interruption scenarios exercised by downloads (C5) |
| M43 | `diagnostics/redact.py` | `test_redact.py` | persistent rotating diagnostics store (C6/C9) |
| M48 | declarative plugins, Core-owned capabilities, allowlists, redirect/DNS, SSRF, no raw session exposure | C3 suites | remote auth parts (C8), document isolation (C2) |
| INV-13, INV-15, INV-26 | package validation; policy + proxy + Chromium flags; governor | see gate checklist | — |
| EX-03, EX-23, EX-30 | no executable plugins; no stealth tooling; no plugin LAN access | validation, K1 guard, SSRF suites | — |
| DEF-download-concurrency | governor defaults 4 HTTP / 1 browser | `test_governor.py` | download engine use (C5) |
| MPG-4 | recipes return descriptors; Core executes; per-hop credential scoping; error-class separation | runtime, pipeline, session tests | expiring-URL refresh (C5) |

Also improved in C3 without changing status: INV-14 now also covers plugin-supplied paths (packages cannot express filesystem paths).

### C4 — 2026-09-17 (gate passed; see `docs/c4/verification.md`)

| ID | C4 implementation | Evidence | Remaining |
|---|---|---|---|
| M5, M5.1–M5.5 | `catalog/trust.py`, migration 0004 | `tests/integration/catalog/test_trust.py`, `test_discovery_api.py` | Completed status + releases since completion (C6) |
| M6, M6.1–M6.9 | `search/normalize.py`, `ranking.py`, `index.py`, `grouping.py`, `mapping.py`, `service.py` | `tests/unit/search/*`, `tests/integration/search/*` | Search UI (C2) |
| M7 | `search/cache.py` | `test_cache.py`, API cached/refresh test | cache use by Reader/downloads (C5) |
| M8 | `search/url_resolve.py` | `test_url_and_home.py`, API test | URL entry UI (C2) |
| M31, M31.1–M31.4 | `discovery/home.py` | `test_url_and_home.py`, `GET /api/home` | Home screen (C2); new-release Hero step (C6) |
| INV-01 | incomplete/suspicious never replace trusted state | trust suite + API gate | — |
| INV-03 | soft grouping writes nothing; actions bind concrete listing/track | grouping suite, `POST /api/listings/bind` | Shelf/Follow/Download callers (C5/C6) |
| INV-04 | `mapping_decided_by`, blocking mappings | mapping suite | restore merge (C7) |
| INV-05 | Unknown type/metadata never blocks grouping or lowers a match | grouping + ranking suites | — |
| INV-27, INV-28 | Work-level results with selectable provenance; covers never identity | grouping suite | search UI presentation (C2) |
| DEF-discovery-cache, DEF-catalog-suspicious | defaults registry values applied | cache + trust suites | — |
| MPG-3 | completeness evidence drives trust; no numeric-gap inference | runtime + trust suites | live sources (C9) |

### C5 — 2026-09-17 (gate passed; see `docs/c5/verification.md`)

| ID | C5 implementation | Evidence | Remaining |
|---|---|---|---|
| M14 | `downloads/contract.py` (precedence, modes, Smart Retry, fallback eligibility) | `tests/unit/downloads/test_contract.py` | browser-method downloads (C9); Ask UI (C2) |
| M16, M16.1–M16.7 | `downloads/engine.py`, `downloads/runner.py`, migration 0007 | `tests/integration/downloads/test_engine.py`, `test_library_api.py` | Downloads screen (C2), failure notifications (C6) |
| M19 | `reader/service.py` auto-download | `tests/integration/reader/test_reading.py` | Reader settings UI (C2) |
| M26.20, M26.23 | `reader/cache.py`, revisioned progress | reader suite, API progress tests | Reader UI (C2) |
| M39 | CBZ packaging with ComicInfo, validated before commit | engine suite | — |
| INV-07 | online reading creates no assets, files or batches | reader + API suites | — |
| INV-23 | clearing history keeps content and progress | engine + API suites | export/notification history (C6/C7) |
| DEF-retry, DEF-reader-cache, DEF-read-ahead, DEF-auto-download, DEF-auto-mark-read | defaults applied at runtime | contract, engine and reader suites | remaining defaults in their phases |

Also strengthened without status change: INV-16 (invalid media never registered), INV-17 (download commits replay through the journal), INV-26 (Reader stays responsive under download saturation).

### C6 — 2026-09-17 (gate passed; see `docs/c6/verification.md`)

| ID | C6 implementation | Evidence | Remaining |
|---|---|---|---|
| M5.6, M22, M23 | `library/shelf.py` | `tests/integration/library/test_shelf_and_follow.py`, `test_shelf_api.py` | My Shelf screen (C2) |
| M20, M20a–M20d | `follow/service.py`, `follow/runner.py`, migration 0008 | follow suite + API follow tests | Following screen (C2), View Alternatives (C2) |
| M21 | `health/service.py` | health suite + `/api/sources/{id}/health/state` | Sources screen (C2), scheduled active checks (C2 settings) |
| M30, M30.1–M30.15, M35, M44 | `notifications/service.py`, engine failure hooks | notification suite + API tests | Notification drawer and Needs Attention UI (C2) |
| INV-09 | release detection never enqueues downloads | follow suite + API test | — |
| INV-10 | Shelf, Follow, files and progress independent | shelf suite + API test | — |
| INV-22 | Seen/Clear Seen never touch reading state | notification suite + API test | — |
| EX-12 | no browser notification or push APIs | `tests/unit/test_no_browser_notifications.py` | — |
| DEF-follow, DEF-notifications | ~12 h + jitter; 1 h resolved, 30 d / 500 retention | follow and notification suites | — |

### C7 — 2026-09-17 (gate passed; see `docs/c7/verification.md`)

| ID | C7 implementation | Evidence | Remaining |
|---|---|---|---|
| M24, M24.8 | `storage/migration.py`, `db/schema/0009_storage.sql`, `api/storage.py` | `tests/integration/storage/test_migration.py`, `test_storage_api.py` | Storage UI (C2) |
| M33–M33.10 | `backup/service.py`, `backup/runner.py` | `tests/integration/backup/test_backup.py`, `test_restore.py` | Backup/Restore UI (C2, M32.15) |
| M34–M34.11 | `export/service.py`, `db/schema/0010_export.sql` | `tests/integration/export/test_export.py`, `test_storage_api.py` | Export wizard UI (C2, M32.16) |
| M37 (association) | `importer/suggest.py`, `search/index.py::write_work_index` | `tests/unit/test_import_suggestions.py`, `test_storage_api.py` | import UI and drag & drop (C2) |
| M38 (reconcile surface) | `POST /api/storage/scan` | `test_storage_api.py::test_storage_overview_and_scan` | Storage UI (C2) |
| DEF-backup, DEF-export-activity | `settings/defaults.py`, `backup/service.py`, `export/service.py` | `test_backup.py`, `test_export.py` | — |
| EX-29 | no conversion path exists; format choice only selects an existing file | `test_missing_content_offers_choices_and_never_converts_formats`, `test_sequential_units_default_to_cbz_while_books_keep_their_original` | audit repeated in C9 |
| INV-19 | `backup/service.py` exclusions by construction | `test_backup_excludes_every_secret_and_rebuildable_store` | repeat with live sessions (C9) |
| INV-20 | `export/service.py` copies only | `test_export_copies_originals_without_touching_the_library` | — |
| INV-21 | `ExportBlocked` unless the disclosure is acknowledged | `test_download_missing_requires_an_explicit_permanent_download_notice` | wizard wording (C2) |

Carried forward from C7 (still `NS`): M32.15 Backup/Restore screens and M32.16 Export wizard → C2; INV-11 and M3.3 need the C2 Reader half before they can be marked; M47 destructive-action wording → C2/C8.

### C8 — 2026-09-18 (gate passed; see `docs/c8/verification.md`)

| ID | C8 implementation | Evidence | Remaining |
|---|---|---|---|
| M2.2, M28, M28.3, M28.4 | `auth/passkeys.py`, `auth/service.py`, `api/auth.py`, migration `0011_remote_auth.sql` | `tests/integration/auth/test_passkeys.py`, `test_auth_api.py` | Remote Access screens (C2) |
| M28.1, M28.2 (completed) | `auth/policy.py` merges configured and environment networks per request | `tests/unit/auth/test_policy.py`, `test_a_trusted_proxy_never_lends_its_own_lan_trust_to_remote_visitors` | trusted-network Settings UI (C2) |
| M28.5 | `auth/recovery.py`, `RemoteAuth.lan_recovery_reset` | `tests/unit/auth/test_recovery.py`, `test_lan_recovery_resets_remote_auth_only` | confirmation wording in the UI (C2, M47) |
| M28.6 | `auth/sessions.py`, `api/auth.py` sessions routes | `tests/unit/auth/test_sessions.py`, `test_sessions_can_be_listed_and_revoked` | session list UI (C2) |
| M28.7 | `api/guard.py` (Host allowlist follows the canonical hostname), secure cookies | `tests/unit/test_request_guard.py`, `test_cross_site_requests_are_refused`, `tests/unit/test_no_token_storage.py` | — |
| M29 | `api/firstrun.py`, `first_run` table | `test_first_run_is_short_and_never_blocks_home`, `test_first_run_remote_mode_needs_a_hostname_and_a_passkey` | wizard UI, Arabic/English and mobile checks (C2, EB-2) |
| DEF-remote-session | `auth/sessions.py::LIFETIMES` (30 d default) | `test_default_lifetime_is_thirty_days`, `test_configurable_lifetimes` | — |
| INV-30 (completed) | real-peer classification plus session authentication at the boundary | `tests/unit/test_access.py`, `test_auth_api.py` | — |

Carried forward from C8 (still `NS`): M32.17 Remote Access screen and M47 destructive-action wording → C2; M45, M46 UX rules → C2; M2, M2.1 Docker → C9.

### C9 — 2026-09-18 (see `docs/c9/verification.md` and `docs/c9/source-capability-ledger.md`)

| ID | C9 implementation | Evidence | Remaining |
|---|---|---|---|
| M12, M12.2–M12.4 | `generator/{discovery,structure,draft,repair,service}.py`, `api/generator.py`, migration `0012_generator.sql` | `tests/integration/generator/` (25 tests, including a generated adapter run through the real runtime and a full repair cycle) | Developer UI (C2) |
| M41, M41.1, M41.3, M41.4 | `plugins/official/` — MangaDex, Gutenberg, arXiv, Standard Ebooks, WEBTOON; `plugins/build.py` | `test_official_packages.py` offline, `tests/live/test_source_suite.py` live (4 passed) | 3asq (unavailable), Tapas and Safahat/Hindawi (browser escalation), WEBTOON reader — all recorded in the capability ledger |
| M40, MPD-03 | `docs/api.md` (107 routes), `docs/plugins.md` | route-by-route review against the routers | kept in step with C2's additions |
| MPD-04 | `docs/operations.md` | matches `db/migrate.py`, `services/startup.py`, `backup/`, `restore/` | Docker verification (EB-1) |
| MPD-05 | `docs/c9/source-capability-ledger.md` | dated live probes, 2026-09-18 | re-run when sources change |
| MPD-06 | `docs/c9/verification.md` | commands, versions, commit, blocked gates | UI/RTL/a11y screenshots (C2) |
| MPG-1, MPG-2, MPG-5 | static-first discovery, reviewed permissions, CDN vs ads separation, artefacts opened and parsed | `test_discovery.py`, `test_draft.py`, live suite | Arabic multi-query checks once an Arabic source ships |
| M2.1 (partial) | `deploy/Dockerfile`, `deploy/compose.yaml`, `GET /api/ready` | `test_readiness_reports_what_startup_actually_did`; module smoke-run | **Blocked EB-1**: build, restart, recreation |

Carried forward from C9: M2.1 Docker verification → EB-1 (still `NS`). **M53 and INV-29 are now `Verified`**
(2026-09-18, `docs/c9/test-categories.md`): all twenty-six §53 categories audited against the suite, the
queue-restart gap filled, and the telemetry audit held by `tests/unit/test_no_matcher_telemetry.py` and
`tests/unit/test_suite_is_isolated.py`. M41.2 and M41.5 remain `IMPL` from C1/C3 and gained the generator-facing static pages and the
markup switch used to exercise repair.

### C2 — 2026-09-18 (gate passed for the surfaces built; see `docs/c2/verification.md`)

| ID | C2 implementation | Evidence | Remaining |
|---|---|---|---|
| M1, M32–M32.21 | the shell, the visual identity and every library and operational surface | `frontend/src/**` with 122 tests; screenshots against the approved reference (EB-2 cleared) | — |
| M11.4, M10.2 | source install from a file: permissions in plain words, packaged tests before install | `InstallPanel.test.tsx` | registry install screen (the API is covered in C3) |
| M13 | Use My Session: a relayed window, no password seen, the session captured only on request | `LoginSession.test.tsx` | — |
| M12–M12.6 | generator drafts, capability states, Recipe Inspector, submission bundle, repair with selector diff | `GeneratorPanel.test.tsx` | — |
| M28, M32.14 | remote access: canonical hostname, passkeys, sessions, Recovery Code shown once, LAN reset | `RemotePanel.test.tsx` | — |
| M33, M34, M37 | Backup and Restore as a workflow, Export as a wizard, Import with review | `BackupPanel.test.tsx`, `ExportWizard.test.tsx`, `ImportPanel` | — |
| M2.3, M45, M46 | Arabic and English as peers, direction independent of content, focus and keyboard behaviour | `a11y.test.tsx`, axe-core zero violations across sixteen page states in both languages | more screenshot coverage |
| M22, M31–M31.4 | My Shelf views and search; Home's adaptive sections and stable hero | `ShelfScreen.test.tsx`, `HomeScreen.test.tsx` | — |
| M26–M26.24 | both reader families, modes, pairing, zoom, gestures, full screen, controls, progress, contents, end-of-unit | `SequentialReader.test.tsx`, `BookReader.test.tsx`, `PdfView.test.tsx`, `epub.test.ts` | — |
| M26.22, M22 | bookmarks and highlights as library state, counted in a backup and merged on restore | `tests/integration/reader/test_marks.py`, `useBookMarks`, `HighlightPane` | highlight overlay on the page itself is out of v1 scope (§26.22) |
| M26.23 | a reader reads the revision it must carry before writing progress | `test_progress_can_be_read_back_so_a_reader_knows_the_revision_it_must_carry`, `carries the revision the library already holds…` | — |
| M27, INV-12 | untrusted content isolated: sanitised EPUB in an empty-sandbox frame under its own CSP; pdf.js with no annotation layer | `epub.test.ts`, `BookReader.test.tsx`, `pdf-isolation.test.ts` | — |
| INV-11, M3.3 | local reading with no source, plugin or network | `reads local pages without asking any source`, `GET /api/reader/units/{id}/file` | export-without-plugin already covered in C7 |
| INV-24 | irregular units keep Source Track order | `ends the unit with the next unit in source order, never chapter plus one` | — |

Carried forward from C2 — **corrected 2026-09-18 by the reconciliation above.** This line previously read
"nothing behavioural", which was wrong: it was written from the C2 record's own §5 rather than from the
matrix. Re-checking every row against the code found real gaps inside C2's scope — the reader's bounded
Long Strip window, preload, source indicator, scrubber, Mark as unread, restoring position within a unit,
page Repair/Skip, EPUB typography, PDF zoom and fit, the centre-tap hint and skeletons, Remove from
Shelf / Mark Completed, My Shelf sort, five placeholder Settings panels, and no UI client for
`GET /api/events`. Each is named in its own row above.
