# Requirement Traceability Matrix

Recorded: 2026-09-17 (C0) · Updated: 2026-09-17 (C1, C3) · Authority: Meta Prompt §C0.6, §D1–D3 · Architecture: `architecture.md`

**Coverage:** every Master heading from §0 to §56 (57 sections, 152 numbered subsections, and the unnumbered sub-headings in §4.4, §20, §26.3, §26.22), all 30 §51 invariants (INV), all 17 §42 default groups (DEF), all 30 §49 exclusions (EX), Meta Prompt §D3 deliverables (MPD) and §G investigation rules (MPG).

**Columns:** ID · Requirement (summary; the Master text is normative) · Phase · Planned location (`be/` = `backend/oneshelf/`, `fe/` = `frontend/`) · API/UI surface · Persistence/state · Acceptance evidence · Status

**Status values:** `NS` Not started · `IMPL` Implemented · `VER` Verified (gate evidence recorded) · `BLK` Blocked (with blocker ID) · `C0` Verified by C0 records · `UP` Satisfied upstream by the Meta Prompt itself.
Required rows may not be relabeled deferred. Optional/future items keep their Master status and are marked *(optional)*.

---

## §0–§4 Governance, vision, platform, foundations, domain

| ID | Requirement | Phase | Location | Surface | Persistence | Evidence | Status |
|---|---|---|---|---|---|---|---|
| M0 | Master is authoritative; no redesign/simplification; flag external ideas; no revival of removed scope | C0→all | docs/c0 | — | — | conflict-review-ledger.md; each phase review | C0 |
| M1 | Self-hosted single-user reading library; feels like personal library, not scraper dashboard; progressive disclosure | C2→all | fe/ | all screens | — | UX review vs §32/§45; screenshots | NS |
| M2 | Deployment & core platform | C1,C8,C9 | — | — | — | rows M2.1–M2.3 | NS |
| M2.1 | Docker first-class; persistent storage; optional separate mounts; no cloud backend/account | C1,C9 | deploy/, be/settings | env/config | app data volume | Docker restart/recreate test on isolated mounts (EB-1) | NS |
| M2.2 | Single user; no username/password account, cloud profile or roles; remote = passkeys; LAN trusted | C1,C8 | be/auth, be/api | first run, Remote Access | remote_auth tables | auth tests; no account/profile UI | NS |
| M2.3 | Arabic/English, RTL/LTR UI + reading; Arabic normalization for search preserving original text | C2,C4 | fe/i18n, be/search/normalize | all UI; search | normalized key columns | RTL/LTR screenshots; normalization unit tests | NS |
| M3 | Foundational rules | C1→C7 | — | — | — | rows M3.1–M3.4 | NS |
| M3.1 | Never silently switch/mix source, language, tracks, or substitute units; fallback changes method only | C4,C5,C6,C7 | be/downloads/extraction, be/reader, be/follow, be/export | Reader, Downloads, Follow, Export | extraction_contracts, follows | INV-02 tests | NS |
| M3.2 | UNKNOWN is valid; never coerced to No/False/Unavailable/Unsupported/Bad/Missing; unknown quality ≠ unavailable | C1,C4,C5 | be/domain (Unknown-aware types) | cards, details, plugin capabilities | nullable tri-state columns | INV-05, INV-06 tests | NS |
| M3.3 | Local content readable without source/plugin/internet/session/catalog | C2,C7 | be/reader, be/storage | Reader | assets | INV-11 test | NS |
| M3.4 | No hidden destructive behavior (listed cases) | C1,C4,C6,C7 | be/storage, be/catalog, be/services | destructive dialogs | — | INV-01/10/18 tests; cleanup audits | NS |
| M4 | Core domain model | C1 | be/domain, be/db | — | schema | rows M4.1–M4.6 | IMPL |
| M4.1 | Work: logical title aggregating listings/languages/formats with provenance; not title equality | C1,C4 | be/domain/work | Work Details | works, work_aliases | domain tests; same-title distinct Works | IMPL |
| M4.2 | Source Listing with source-specific identity + provenance | C1,C3 | be/domain | Sources tab | source_listings | same-source dedupe tests (M6.9) | IMPL |
| M4.3 | Source Track = Work × source × language with own catalog/order/units/metadata/session/capabilities/baseline/availability; never blended | C1 | be/domain | Work Details Sources/Read tabs | source_tracks | track isolation tests | IMPL |
| M4.4 | Reading Unit types and fields (raw/display title, type, numbers, volume, order, date, source, language, availability/download/integrity/read state, progress) | C1 | be/domain/reading_unit | index list, TOC | reading_units | schema + fixture tests (special/extra/3.5) | IMPL |
| M4.4a | Numbering precedence source > adapter-derived > UNKNOWN; derived = display/order only, never identity; user correction wins | C1,C4 | be/domain, be/catalog | unit list | source_number, derived_number, user_number | tests: specials not numbered; identity unchanged on renumber | IMPL |
| M4.5 | Volumes optional grouping; no volume folder hierarchy required | C1 | be/domain, be/storage/layout | unit list grouping | volume column | layout tests | IMPL |
| M4.6 | Local Source Track first-class; readable/exportable without network plugin | C1,C7 | be/domain, be/importer | Work Details | source_tracks(kind=local) | import→read→export offline test | IMPL |

## §5 Catalog trust

| ID | Requirement | Phase | Location | Surface | Persistence | Evidence | Status |
|---|---|---|---|---|---|---|---|
| M5 | Catalog trust foundational for Follow/Download Missing/navigation/missing inference | C4 | be/catalog | — | catalog_snapshots | rows below | NS |
| M5.1 | Only complete snapshots may be Trusted; incomplete never replace trusted, infer deletion, baseline Follow, or feed Download Missing | C4 | be/catalog/completeness | — | snapshot.completeness + evidence | incomplete pagination / failed request / first-page-only / interrupted tests | NS |
| M5.2 | Keep current + previous Trusted, release events, bounded debug window; suspicious heuristic ≥~50% loss and ≥5 units | C4 | be/catalog/trust | Sources, Work Details warning | catalog_snapshots (bounded) | 300→7 test; history bound test | NS |
| M5.3 | Suspicious → Trusted after two consecutive complete matching checks or explicit Trust This Catalog | C4 | be/catalog/trust | Sources advanced action | snapshot state | recovery sequence tests; Trust action rejects incomplete | NS |
| M5.4 | Download Missing, Follow comparison, missing inference, automation use last Trusted only | C4,C5,C6 | be/catalog, be/downloads, be/follow | Download Missing, Follow | — | trusted-only tests | NS |
| M5.5 | Temporarily missing units keep local content, last_seen, missing_since; no deletion | C4,C6 | be/catalog | unit list state | last_seen, missing_since | disappear/reappear tests | NS |
| M5.6 | Completed stays Completed; show "N releases since completion" | C6 | be/services/shelf | My Shelf, Work Details | shelf.completed_at + release events | completion preservation test | NS |

## §6–§8 Search, matching, discovery cache, URL entry

| ID | Requirement | Phase | Location | Surface | Persistence | Evidence | Status |
|---|---|---|---|---|---|---|---|
| M6 | Unified search and matching | C4 | be/search | Search | — | rows below | NS |
| M6.1 | Local-first then progressive live enrichment of same result set; never clear local results; slow source doesn't block; "7 / 8 sources"; Retry Source | C4 | be/search/service, fe/search | `GET /search` + SSE; Search screen | cache.db discovery | failing/slow source tests; e2e progressive render | NS |
| M6.2 | SQLite FTS5 (or equivalent) index over original/display/normalized/loose/aliases/source titles/type/languages/creator/external IDs | C4 | be/search/index | — | FTS5 tables | index tests | NS |
| M6.3 | Preserve originals; normalize keys only; strong Arabic normalization; loose ة↔ه; no stemming, translation, cover matching | C4 | be/search/normalize | — | key columns | Arabic regression + no-stemming tests | NS |
| M6.4 | Ranking tiers exact→normalized→alias→phrase/prefix→all-token→substring/trigram→fuzzy; small boosts can't overpower; ranking ≠ grouping | C4 | be/search/rank | result order | — | tier ordering + boost-bound tests | NS |
| M6.5 | Sequential Art family broadly compatible; Novel/Book vs sequential art usually not hard-merged | C4 | be/search/match | — | — | adaptation-boundary tests | NS |
| M6.6 | Soft Group presentation-only; actions bind concrete listing/track; Hard Mapping needs evidence or user action; Merge/Split/Unlink/Never Match persist and win | C4 | be/search/mapping | Work Details, Search | mappings, overrides | INV-03, INV-04 tests | NS |
| M6.7 | Missing metadata not negative evidence | C4 | be/search/match | — | — | INV-05 test | NS |
| M6.8 | Reading Unit matching title-primary + stable supporting evidence; preserve aliases/history | C4 | be/catalog/unit_match | — | unit aliases | rename/reorder tests | NS |
| M6.9 | Same-source identity via listing ID/canonical URL; cached + live merge | C4 | be/search | — | source_listings unique keys | cached/live dedupe test | NS |
| M6.10 | No matcher telemetry/central dataset/decision collector/shared logging, under any name | C4,C9 | be/search, be/diagnostics | — | none | INV-29 audit (schema, network, diagnostics) | NS |
| M7 | Discovery Cache TTL 7 d, 250 MB, LRU; excludes Shelf/Follow/Downloads/mappings/corrections/authoritative; namespaced by source + plugin version/schema; no persistent query analytics | C4 | be/search/discovery_cache | — | cache.db | stale plugin-cache invalidation; cleanup-never-touches-authoritative; no query persistence test | NS |
| M8 | Direct URL entry: identify plugin, normalize, fetch, preview/resolve; no auth/paywall/DRM bypass; same matching rules | C4 | be/search/url_resolve | Search URL paste | — | supported/unsupported URL tests | NS |

## §9–§13 Plugins, lifecycle, SSRF, generator, sessions

| ID | Requirement | Phase | Location | Surface | Persistence | Evidence | Status |
|---|---|---|---|---|---|---|---|
| M9 | Source adapter/plugin architecture | C3 | be/plugins | — | — | rows below | IMPL |
| M9.1 | Capabilities search/getWork/getChapters/getPages/getTrending/getLatest/getDownloads/checkSession/healthCheck; missing metadata allowed | C3 | be/plugins/contracts | — | capability states | adapter contract tests | IMPL |
| M9.2 | Classification precedence user override > source classification > plugin default > Unknown | C3 | be/plugins, be/domain | Work details edit | classification_overrides | precedence tests | IMPL |
| M9.3 | Community plugins declarative `.osp` (manifest/source/recipes/tests/icon); no py/JS/shell/eval/exec; Core owns HTTP/Scrapling/browser/sessions/downloads/DB/FS/paths/network | C3 | be/plugins/schema, validator | Sources upload | plugin store | INV-13 malicious package rejection | IMPL |
| M9.4 | Bounded safe transform library incl. bounded regex, with resource limits | C3 | be/plugins/transforms | — | — | ReDoS/size/time limit tests | IMPL |
| M9.5 | Trust labels Official/Verified Community/Community/Local indicate review only, not access | C3 | be/plugins | Sources list | plugin.trust_label | label doesn't widen policy test | IMPL |
| M9.6 | Native adapters only as rare reviewed official exceptions; WASM not v1 | C3,C9 | be/plugins/native (registry of reviewed) | — | — | review record per native adapter; none by default | IMPL |
| M9.7 | Restricted RPC excluded | C3 | — | — | — | EX-04 | NS |
| M10 | Install via Registry (A1) or local upload; atomic 8-step install; Configure/Update/Disable/Uninstall/Health/Rollback; new permissions need approval; no auto-publish; uninstall keeps Shelf/content; missing plugin keeps provenance + reinstall; backups store names/versions only; account connection optional | C3 | be/plugins/lifecycle, registry | Sources install/review/manage | plugins, plugin_versions, permissions | install rollback; permission-change review; uninstall preserves content; fixture registry tests | IMPL |
| M11 | Allowlists + redirect revalidation + DNS revalidation + block loopback/private/link-local/unsafe; same for browser; Test Source dev-only exception | C3 | be/net/policy, be/net/browser_proxy | — | policy config | INV-15 HTTP + browser SSRF/rebinding tests | IMPL |
| M12 | Scrapling discovery and adapter generator | C3,C9 | be/generator | Settings → Developer | drafts | rows below | NS |
| M12.1 | Scrapling: static first, dynamic only if needed, CSS/XPath, APIs/XHR, adaptive selectors; doesn't own queue/retry/Shelf/packaging/priority/policy; no stealth | C3,C9 | be/generator, be/plugins/runtime | — | — | K1 guard test (no stealth fetchers) | IMPL |
| M12.2 | Pipeline URL→static→mapping→capabilities→optional dynamic→XHR/DOM/media→confidence→draft→domain/permission review→tests→dev review→validation→local install→optional submission | C9 | be/generator/pipeline | Developer generator UI | draft state | pipeline e2e on Test Source | NS |
| M12.3 | Generator features list (route mapping, Arabic test queries, unit discovery preserving raw fields, resource discovery not screenshots, Confirmed/Probable/Unknown/Unsupported, manifest/recipe generation, safe transforms, adaptive fallback after failure+validation, CDN vs ads separation, capability-level auth testing, sanity tests, multiple sample Works, preview, Recipe Inspector, Test/Edit/confidence, Generate≠Install, Repair with diffs, validate before replace, atomic activation+rollback, community export/submit, no Shelf/progress/unrelated session access, scoped Use My Session, no raw passwords, no auto-publish) | C9 | be/generator, fe/developer | Developer UI | drafts, repair diffs | per-feature tests; MPG rows | NS |
| M12.4 | Unsupported declarative sites → "Unsupported by Declarative Adapter" / "Native Adapter Review Required"; no hacks | C9 | be/generator | generator result | — | proprietary-signing fixture test | NS |
| M13 | Use My Session: user logs in; no passwords; per-source isolation; plugins never get raw material; encrypted at rest, key separate; backup exclusions; cookies/localStorage/IndexedDB/sessionStorage handling; states + actions; auth failure pauses → WAITING_FOR_SESSION, no blind retry; atomic reconnect + resume; disconnect deletes immediately; never log secrets; install doesn't force auth; attach only to needed capabilities/domains | C3 | be/sessions, be/net | Sources → account/session | secrets.db + separate key | same-source isolation; cross-source/CDN leak; reconnect wait/resume; disconnect deletion; log scan | IMPL |

## §14–§19 Extraction, governor, downloads, commit, SQLite, auto-download

| ID | Requirement | Phase | Location | Surface | Persistence | Evidence | Status |
|---|---|---|---|---|---|---|---|
| M14 | Methods Direct/HTML-API/Reader Media/Browser; Extraction Contract (source, language, unit, output, method); precedence one-time > source > global > plugin; Preferred + Ask default; Strict/Locked; optional Automatic Fallback; Smart Retry first; no fallback on auth/CAPTCHA/rate limit/outage; explicit public-reader alternative; no auth bypass; health doesn't rewrite; no mixed methods per unit; switch = full temp redownload + validate + atomic replace; method-specific resume; plugin update doesn't change method; history records methods locally | C3,C5 | be/downloads/extraction | download dialogs, Settings → Downloads advanced | extraction_contracts, history | contract-preservation + mode semantics tests | NS |
| M15 | Global Source Traffic Governor: priority Reader > interactive > manual/downloads > read-ahead > Follow > Health; browser same priority; low-priority browser never blocks Reader; per-source/global concurrency, rate limits, Retry-After, backoff, fairness | C3,C5 | be/net/governor | — | in-memory + persisted rate state | INV-26 saturation test; fairness tests | IMPL |
| M16 | Download Engine: persistent SQLite queue/state machine + scheduler + workers + governor + staging + integrity + packaging + commit + recovery + history; grouped UI states | C5 | be/downloads | Downloads | jobs, batches | state machine tests | NS |
| M16.1 | Per-unit jobs under batch; partial failure ≠ batch failure; Completed / Completed with Issues / Retry All Failed; windowed queue; pause/resume/cancel/retry/reorder | C5 | be/downloads/scheduler | Downloads batch cards | batches, jobs | partial success; huge queue memory bound | NS |
| M16.2 | Concurrency HTTP 4, Browser 1 independent; advanced may raise | C5 | be/settings/defaults, be/net | Settings advanced | settings | DEF-concurrency test | NS |
| M16.3 | Initial + up to 3 retries, exponential backoff + jitter; 429 Retry-After; auth → WAITING_FOR_SESSION; 404 no blind repeat; 5xx/timeout/reset retryable | C5 | be/downloads/retry | — | job attempts | Test Source 429/500/404/session-expiry tests | NS |
| M16.4 | Resume: skip valid pages; Range + ETag/Last-Modified/If-Range, never splice; browser rediscover manifest, compatible resume else restart; per-job manifest | C5 | be/downloads/resume | — | job_manifests | changed-ETag, Range, browser manifest tests | NS |
| M16.5 | Integrity: images exist/non-zero/decodable/sensible/not HTML/coverage; books type/magic/openable/container valid; no partials in Shelf; same-method page repair | C5 | be/downloads/integrity | Reader repair | asset integrity | HTML-as-media, corrupt media, content-open checks | NS |
| M16.6 | Cancel setting: delete or keep partial (A4) | C5 | be/downloads | Settings → Downloads | staging | both-mode tests | NS |
| M16.7 | Clearing Download History keeps content + progress; no cloud telemetry | C5 | be/downloads/history | Downloads history | history table | INV-23 test | NS |
| M17 | Idempotent Commit Journal: staging → journal → rename → verify → DB txn → complete; startup reconciles listed cases; recovery repeatable; order recover → reconcile → clean orphans | C1,C5 | be/storage/commit_journal | — | commit_journal | crash injection at each boundary; repeated reconciliation (INV-17) | IMPL |
| M18 | SQLite source of truth; WAL; migrations; short serialized writes; consistency boundaries; consistent snapshot backups; never copy live DB | C1,C7 | be/db | — | oneshelf.db | migration/recovery tests; snapshot consistency test | IMPL |
| M19 | Reading ≠ Downloading; auto-download OFF; Current Unit Only / Current + Read Ahead (next 5 existing); Download Entire Work separate; trigger ~12% + genuine interaction; flow via Reader Cache; priority; leaving Work cancels not-started read-ahead; no source/language switch | C5 | be/reader/auto_download | Reader settings (advanced), Settings → Downloads | settings, jobs | INV-07/08; engagement trigger; leave-Work cancellation | NS |

## §20–§23 Follow, health, Shelf, independence

| ID | Requirement | Phase | Location | Surface | Persistence | Evidence | Status |
|---|---|---|---|---|---|---|---|
| M20 | Follow binds Work+Language+Preferred Source+Track; no auto switch; alternatives informational (View Alternatives/Change Preferred Source); independent of Shelf; Unfollow immediate + Undo, non-destructive; detect vs Trusted Catalog baseline, not max number/gaps; first Follow baselines; New ≠ auto-download | C6 | be/follow | Following, Work Details | follows, baselines | first-Follow baseline; INV-09; Unfollow independence | NS |
| M20a | NEW_RELEASE vs NEWLY_AVAILABLE internal distinction; UI may group | C6 | be/follow/events | Following | release_events.kind | event-kind tests | NS |
| M20b | Metadata change of same unit updates, not new; reordering not new; disappear→return not new; duplicate notifications suppressed; Seen separate from Read | C6 | be/follow/detect | Following | — | rename/reorder/reappear tests | NS |
| M20c | Preferred Source change: fetch catalog, Source Change Baseline, no flood, preserve progress | C6 | be/follow | Change Preferred Source | baselines | source-change tests | NS |
| M20d | Schedule ~12 h + jitter; Check Now / Check All Now; plugin Update Now / Update All separate; group by source; API/HTML preferred, browser only if declared; Last Attempted + Last Successful (emphasized) | C6 | be/follow/schedule | Following | follow check timestamps | scheduler jitter/grouping tests | NS |
| M21 | Capability-level health (Search/Work/Catalog/Reader/Download/Auth); states Healthy/Degraded/Unavailable/Rate Limited/Reconnect Required/Catalog Suspicious; internal categories; thresholds + hysteresis; trusted recovery; 404 ≠ failure; parser failures signal update; plugin version recorded; passive first; no periodic browser probes; active checks low priority; describes only; UI in Sources (A3); Search shows only concise progress | C6 | be/health | Sources; Search progress | health_signals | hysteresis/flap tests; no browser probe test | IMPL |
| M22 | My Shelf: immediate save without files; views All/Saved/Reading/Completed/Favorites; Pin separate; Remove confirms Keep/Delete Files; Completed rules + optional delete keeping metadata; progress in SQLite; local-only Shelf search; formats (CBZ per unit, original images; PDF/EPUB coexist); per-unit local record; import CBZ/PDF/EPUB with confident association or Choose Work/Create Local Work | C6,C7 | be/services/shelf, fe/shelf | My Shelf, Work Details | shelf_entries, assets, progress | Shelf state tests; local-only search (no network) | NS |
| M23 | Remove from Shelf ≠ Unfollow; Unfollow keeps Shelf + files; Delete Files keeps Follow + progress unless separately requested | C6 | be/services | dialogs | — | INV-10 matrix test | NS |

## §24–§25 Storage and staging

| ID | Requirement | Phase | Location | Surface | Persistence | Evidence | Status |
|---|---|---|---|---|---|---|---|
| M24 | Storage model | C1,C7 | be/storage | Settings → Storage | storage_roots | rows below | NS |
| M24.1 | Roots with stable ID, path, availability, free space, default flag; DB stores root_id + relative path; never absolute host paths | C1 | be/storage/roots | Storage settings | storage_roots, assets | identity tests; mount remap test | IMPL |
| M24.2 | Families Sequential Art/Books/Other; Work→Language→Source→Files; short stable IDs for collisions; Unicode/Arabic names; untrusted source filenames; Core-owned paths; no rename on metadata change | C1 | be/storage/layout | — | — | collision + Unicode + metadata-change tests | IMPL |
| M24.3 | Per-root `<root>/.oneshelf/staging/` on same filesystem; partials only there; scanner/reader ignore | C1 | be/storage/staging | — | staging dirs | same-fs rename test; scanner ignore test | IMPL |
| M24.4 | Block `../`, absolute injection, symlink escape, malicious names, plugin paths; delete only in managed roots | C1 | be/storage/paths | — | — | INV-14 path tests | IMPL |
| M24.5 | Reserve 5% capped 5 GB; warn ~2×; pause automatic/background writes at reserve; never auto-delete; expected-size preflight | C1,C7 | be/storage/disk_guard | Low Storage notice | root state | reserve/warning/preflight tests | IMPL |
| M24.6 | Offline root → Storage Location Unavailable; no mass Missing, cleanup or destructive repair; reconcile on return | C1,C7 | be/storage/roots, scanner | Needs Attention/Storage | root availability | INV-18 test | IMPL |
| M24.7 | Manual deletion → Missing Local File keeping Work/Follow/progress; relocation recovery via IDs else import/reconcile | C7 | be/storage/scanner | unit state | assets.integrity | manual delete/move tests | IMPL |
| M24.8 | Resumable migration preflight→pause→stream copy→checksum→switch→reconcile→offer keep/delete; never auto-delete old; reads continue where practical; mount-path change = remap + validate, no copy | C7 | be/storage/migration | Storage settings | migration jobs | interrupted migration resume; old-data preservation; remap test | NS |
| M25 | Staging cleanup: successful leftovers ~24 h; resumable failed ~7 d; startup recover jobs → commits → reconcile → clean proven orphans; never clean before recovery | C1,C5 | be/storage/staging_cleanup | — | — | ordering + retention tests | IMPL |

## §26–§27 Reader and isolation

| ID | Requirement | Phase | Location | Surface | Persistence | Evidence | Status |
|---|---|---|---|---|---|---|---|
| M26 | Two reader families (Sequential, Book); core v1 | C2,C5 | fe/reader, be/reader | Reader | — | rows below | NS |
| M26.1 | Content first; layers Content / Controls / Advanced-Recovery; not a dashboard | C2 | fe/reader | Reader | — | UX review | NS |
| M26.2 | Auto-hiding top/bottom bars; top: Back, Work title, unit, TOC, compact download, More (Mark Read/Unread, Change Source, Settings, Repair, Work Details, advanced); Back returns context + flushes progress | C2 | fe/reader/shell | Reader | progress flush | e2e back-context + flush test | NS |
| M26.3 | Distraction-Free modes; controls don't auto-hide while menu/drawer/settings open; Always Visible *(optional)* | C2 | fe/reader/controls | Reader | reader settings | panel-open no-hide test | NS |
| M26.3a | Smart: controls on interaction, auto-hide ~3 s | C2 | fe/reader/controls | Reader | — | timing test | NS |
| M26.3b | Hidden by Default/Minimal: bars hidden unless summoned; navigate by keys/mouse zones/gestures | C2 | fe/reader/controls | Reader | — | e2e navigation test | NS |
| M26.4 | Long Strip, Single, Double; LTR/RTL/Vertical | C2 | fe/reader/sequential | Reader | — | mode/direction tests | NS |
| M26.5 | Edge zones/center; direction-aware; keyboard set (prev/next, Space/Shift+Space, fullscreen, TOC, download, zoom, reset, Esc); touch (center tap, swipe, vertical scroll, pinch, double-tap); remapping *(optional)* | C2 | fe/reader/input | Reader | — | input tests desktop + touch emulation | NS |
| M26.6 | Long Strip bounded render window; not fully decoded; percentage progress; optional page detail; restore approximate scroll | C2 | fe/reader/long_strip | Reader | progress.position | memory-bound + restore tests | NS |
| M26.7 | Single Page centered; Fit Smart/Width/Height/Original | C2 | fe/reader/single | Reader | — | fit tests | NS |
| M26.8 | Double Page LTR/RTL pairing, first-page cover, Shift Pairing, wide spreads; no AI/destructive crop | C2 | fe/reader/double | Reader | per-Work pairing offset | pairing tests | NS |
| M26.9 | Auto Fit Smart/Width/Height/Original; Smart stable | C2 | fe/reader/fit | Reader | — | no-oscillation test | NS |
| M26.10 | Zoom keyboard/Ctrl+wheel/pinch/double-tap; drag pans; no accidental advance | C2 | fe/reader/zoom | Reader | — | zoomed-pan tests | NS |
| M26.11 | Minimal bottom UI; page-based (manga/PDF), position (Long Strip), logical (EPUB); scrubber | C2 | fe/reader/progress | Reader | progress | model tests | NS |
| M26.12 | TOC drawer (desktop side, tablet side sheet, mobile full/bottom sheet); unit states; filters All/Unread/Downloaded/New; subtle current highlight | C2 | fe/reader/toc | Reader | — | responsive TOC tests | NS |
| M26.13 | End-of-unit uses Source Track order, never chapter+1; card with completed state, next actual unit (Special/Extra), Back to Work | C2 | fe/reader, be/reader/navigation | Reader | — | INV-24 irregular order test | NS |
| M26.14 | Auto Read 97%; always Mark Read/Unread; manual change doesn't eject | C2 | be/reader/progress | Reader More | read_state | threshold + manual tests | NS |
| M26.15 | Continue Reading restores exact same-source progress; Long Strip approximate | C2 | be/reader, fe/home | Home, Work Details | progress | restore tests | NS |
| M26.16 | Subtle source indicator; manual switching only; same-language alternatives; layout warning; Start This Unit / Try Approximate Position; never fake page equivalence; uncertain → say so, open target track, don't guess | C2,C5 | fe/reader/source_switch, be/reader | Reader Change Source | — | INV-25 test | NS |
| M26.17 | Settings precedence Session > Work > Content-Type > Global; remember per-Work ON; normal vs advanced settings; backgrounds Black/Dark Gray/White | C2 | be/settings, fe/reader/settings | Reader Settings | reader_settings scoped | precedence tests | NS |
| M26.18 | Preload ~next 7 / previous 4; Long Strip bounded window; advanced only | C2,C5 | fe/reader/preload | advanced settings | — | DEF preload test | NS |
| M26.19 | Compact download state (not downloaded/progress/downloaded); quiet auto-download; Download Entire Work on Work page/More | C2,C5 | fe/reader | Reader top bar | — | UI test | NS |
| M26.20 | Reader Cache ≠ download; no noisy Cached badges; details distinguish; cache key source + unit identity + resource validator, never title/number | C5 | be/reader/cache | Reader details | cache.db, blobs | key tests; eviction protections | NS |
| M26.21 | Page failure Retry/Repair/Skip; corrupt local Repair from Source/Skip; never silently delete; source unavailable keeps local/cached readable, no switch; inline Reconnect resuming same unit; calm rate-limit auto retry; offline Downloaded vs Online-only | C2,C5 | fe/reader/errors, be/reader | Reader | — | error-state tests | NS |
| M26.22 | Book Reader; no full notes/drawing/annotations; only bookmarks + highlights; sequential page bookmarks not required | C2 | fe/reader/book | Reader | bookmarks, highlights | EX-15 check | NS |
| M26.22a | EPUB: font family/size, line height, margins, theme, TOC, search, bookmarks, highlights, logical progress; TOC tabs; no fake page count | C2 | fe/reader/epub | Reader | bookmarks, highlights, progress | EPUB gate tests (isolated renderer) | NS |
| M26.22b | PDF: navigation, zoom, fit width/page, text-layer search, bookmarks, highlights, progress, optional sidebar | C2 | fe/reader/pdf | Reader | bookmarks, highlights, progress | PDF gate tests | NS |
| M26.23 | Multi-tab: no stale regression; debounced writes; force flush on unit change/hidden/exit/lifecycle | C2 | be/reader/progress, fe/reader | — | progress.revision | multi-tab stale-write tests; Mark Unread/reread still work | NS |
| M26.24 | Layout-preserving skeletons; one-time "Tap/click center" hint | C2 | fe/reader | Reader | local hint flag | UI test | NS |
| M27 | Never inject untrusted HTML/EPUB/document content into app origin/DOM; sanitize, sandbox, CSP, script blocking, isolated viewer, safe SVG; no auth/privileged/network escape (K3) | C2 | be/reader/content_routes, fe/reader/isolation | Reader | — | INV-12 malicious HTML/EPUB/SVG/PDF tests | NS |

## §28–§29 Authentication and first run

| ID | Requirement | Phase | Location | Surface | Persistence | Evidence | Status |
|---|---|---|---|---|---|---|---|
| M28 | Web UI authentication | C1,C8 | be/auth, be/api | Settings → Remote Access | remote_auth | rows below | NS |
| M28.1 | Localhost + LAN auth OFF by default; genuine LAN fully trusted incl. passkey reset / session revoke | C1,C8 | be/api/access | — | trusted networks config (A2) | LAN admin tests | IMPL |
| M28.2 | LAN origin from real connection + explicit config; X-Forwarded-For only from trusted proxies; remote proxy traffic gets no LAN trust | C1,C8 | be/api/access | — | trusted proxies config | forged header + proxy tests (INV-30) | IMPL |
| M28.3 | Remote: passkey-only built-in auth; advanced VPN/proxy setups; canonical HTTPS hostname; LAN IP stays unauthenticated | C8 | be/auth/webauthn | Remote setup | passkeys | passkey register/authenticate tests | NS |
| M28.4 | Single fixed internal WebAuthn identity; never exposed as account/profile | C8 | be/auth | — | constant user handle | UI audit | NS |
| M28.5 | Recovery code at first passkey; not for login; stored as verifier; regeneration invalidates; can authorize new passkey; LAN Recovery resets passkeys + revokes sessions + allows registration; explicit confirmation affecting only remote auth | C8 | be/auth/recovery | Remote Access, LAN Recovery dialog | recovery verifier | regeneration invalidation; recovery scope test (library untouched) | NS |
| M28.6 | Session list (label, current, created, last active, expiration); Revoke / Revoke All Other; no invasive fingerprinting; default 30 d, options shorter/90 d/1 y/manual; HttpOnly, Secure on HTTPS, SameSite; no tokens in Web Storage; sensitive ops may re-auth | C8 | be/auth/sessions | Remote Access sessions | ui_sessions | session defaults; Web Storage scan | NS |
| M28.7 | Remote state-changing APIs: Origin validation, CSRF, secure cookies; proxy auth only from configured proxy | C1,C8 | be/api/csrf | — | — | CSRF/Origin rejection tests | NS |
| M29 | Short first run: Welcome → Storage → Access Mode (Local/LAN/Remote) → Remote hostname/passkey/recovery → optional sources → Finish; no forced advanced config | C8 | fe/first_run, be/services/first_run | First Run | settings | first-run e2e ar/en + mobile | NS |

## §30–§32 Notifications, home semantics, UI direction

| ID | Requirement | Phase | Location | Surface | Persistence | Evidence | Status |
|---|---|---|---|---|---|---|---|
| M30 | In-app notifications only; no browser notifications | C6 | be/notifications, fe/notifications | Notifications drawer | notifications | EX-12 check | NS |
| M30.1 | Important: New Releases, Download Failed, Reconnect Required, Low Storage, Catalog Suspicious; Informational: Plugin Update, Source Recovered, Backup/Import; background events don't notify; not a log viewer | C6 | be/notifications/classes | drawer | class column | no-noise tests | NS |
| M30.2 | Group releases per Work; safe numeric range "Ch. 209–211"; mixed lists; cross-Work summary | C6 | be/notifications/grouping | drawer | — | grouping tests incl. mixed/specials | NS |
| M30.3 | Seen/Unseen independent of Read/Unread/Partial; "Mark All as Seen" not "Read"; Clear Seen; never changes reading state | C6 | be/notifications | drawer | seen flag | INV-22 test | NS |
| M30.4 | No per-item success spam; grouped batch success; final failures; Smart Retry silent until exhausted | C6 | be/notifications | drawer | — | download notification tests | NS |
| M30.5 | Reconnect dedupe per Source | C6 | be/notifications/dedupe | drawer | dedupe key | 20 Works → 1 notice test | NS |
| M30.6 | Rate limit status-only; one concise notice if prolonged and blocking | C6 | be/notifications | drawer | — | prolonged rate limit test | NS |
| M30.7 | Low Storage dedupe per root; re-notify only after recovery+recurrence or escalation | C6 | be/notifications | drawer | — | recurrence tests | NS |
| M30.8 | Catalog Suspicious warning states last trusted catalog kept | C6 | be/notifications | drawer | — | copy test | NS |
| M30.9 | Plugin updates informational; new permissions need explicit review; never silent auto-update | C6,C3 | be/notifications, be/plugins | Review Update | — | permission update test | NS |
| M30.10 | Source Recovered optional/silent by default | C6 | be/notifications | — | setting | default test | NS |
| M30.11 | Backup failure important; success silent; large import may notify for review | C6,C7 | be/notifications | drawer | — | tests | NS |
| M30.12 | One or two focused actions (View Releases, Retry, Reconnect, Manage Storage, Review Update) | C6 | fe/notifications | drawer | — | UI test | NS |
| M30.13 | Mandatory logical dedupe keys (`source-auth:`, `storage-low:`, `catalog-suspicious:`, `new-release:`); repeats update existing | C6 | be/notifications/dedupe | — | unique dedupe_key | dedupe tests | NS |
| M30.14 | Persistent while action required; transient may expire; resolved lingers ~1 h | C6 | be/notifications/lifecycle | drawer | state timestamps | lifecycle tests | NS |
| M30.15 | Bounded history 30 d or 500, whichever first; subsystem state stays authoritative | C6 | be/notifications/cleanup | — | — | both-limit tests (D2) | NS |
| M31 | Home discovery semantics | C2,C4,C6 | fe/home, be/services/home | Home | — | rows below | NS |
| M31.1 | Trending only from trusted getTrending data; no fake global score; hide if none | C4 | be/services/home | Home Trending | cache.db | hide-without-data test | NS |
| M31.2 | Latest Releases = getLatest discovery feed, distinct from Following New Releases | C4 | be/services/home | Home | cache.db | separation test | NS |
| M31.3 | Recently Added = recently added to My Shelf | C6 | be/services/home | Home | shelf_entries.added_at | test | NS |
| M31.4 | Hero contextual but stable; no network request to choose; priority Continue Reading > pinned/new-release > cached discovery | C2,C6 | be/services/home | Home Hero | — | no-network Hero test | NS |
| M32 | Approved visual identity (forest-green sidebar, cream canvas, olive, wood, restrained shadows, serif headings, clean UI type; calm/premium; not SaaS/Netflix) | C2 | fe/theme | all | — | visual checks vs reference V (EB-2) | NS |
| M32.1 | Fixed forest-green sidebar with Home/Search/My Shelf/Following/Downloads/Sources/Settings; logo top-left; sparse botanical motif | C2 | fe/shell | sidebar | — | nav test; screenshot | NS |
| M32.2 | No avatar; Notifications + Needs Attention (hidden at 0; Reconnect/Low Storage/Download Failed/Catalog Suspicious; grouped popover); filtered shortcut, no duplication | C2,C6 | fe/shell/header | header | derived | zero-hidden + filter tests | NS |
| M32.3 | Home close to reference: welcome, subtitle, Hero, Continue Reading, Trending, Latest, Recently Added, others when useful; adaptive; not dashboard | C2 | fe/home | Home | — | empty-state + adaptive tests; screenshot | NS |
| M32.4 | Large rounded Hero with cover/title/type/description/Continue/atmospheric art | C2 | fe/home/hero | Home | — | screenshot | NS |
| M32.5 | Wooden shelves on Home, My Shelf, selected Discover; paper/card for system; none in Settings/Downloads/Sources/Backup; premium subtle wood | C2 | fe/components/shelf | Home, My Shelf | — | screenshot audit | NS |
| M32.6 | Work cards Compact/Standard/Detailed; one logical Work; dominant cover; concise availability; no internal states | C2 | fe/components/work_card | cards | — | INV-27 UI test | NS |
| M32.7 | Search UI: warm canvas, serif title, large field, filter chips, Grid/List, cover results, no mandatory shelves | C2,C4 | fe/search | Search | — | screenshot | NS |
| M32.8 | Work Details: small Hero header (cover/title/original/type/creator/description); actions Continue/Read, Add to Shelf, Follow, Favorite, Pin; tabs Read/Details/Sources; elegant index unit list | C2 | fe/work | Work Details | — | UI tests | NS |
| M32.9 | My Shelf bookshelf motif; Pinned/Reading/Completed/Favorites sections; search/sort/filter/Grid-List | C2,C6 | fe/shelf | My Shelf | — | UI tests | NS |
| M32.10 | Following as reading journal; paper rows; New Releases / Needs Attention / Up to Date; no charts | C2,C6 | fe/following | Following | — | UI tests | NS |
| M32.11 | Downloads operational: no shelves, paper panels, olive progress, green controls, batch cards, expandable units; not analytics | C2,C5 | fe/downloads | Downloads | — | UI tests | NS |
| M32.12 | Sources elegant catalog-card list: source, type/language, status, last successful check, Configure/More; advanced hidden (A3) | C2,C3 | fe/sources | Sources | — | UI tests | NS |
| M32.13 | Notifications warm right drawer; Mark All as Seen / Clear Seen / View All | C2,C6 | fe/notifications | drawer | — | UI tests | NS |
| M32.14 | Settings paper aesthetic; categories left / panel right; General, Reader, Downloads, Storage, Sources, Notifications, Backup, Remote Access, Advanced, Developer; progressive disclosure | C2 | fe/settings | Settings | — | UI tests | NS |
| M32.15 | Backup/Restore archival feel; multi-step restore, not casual modal | C7 | fe/backup | Backup | — | UI tests | NS |
| M32.16 | Export wizard Content → Format → Destination → Review; small covers | C7 | fe/export | Export | — | UI tests | NS |
| M32.17 | First Run "Welcome to OneShelf" / "Your stories, one library."; subtle botanical | C8 | fe/first_run | First Run | — | copy test ar/en | NS |
| M32.18 | Reader strips decoration; Black/Dark Gray/White; controls keep icon/type quality | C2 | fe/reader | Reader | — | screenshot | NS |
| M32.19 | Paper drawers/dialogs; no heavy glassmorphism; destructive dialogs explain what happens and what remains | C2 | fe/components/dialog | dialogs | — | copy audit (M47) | NS |
| M32.20 | Subtle motion (2–4 px lift, soft slide, Hero crossfade); no bounce/elastic/flashy/parallax; reduced motion | C2 | fe/theme/motion | all | — | reduced-motion test | NS |
| M32.21 | Mobile not shrunk desktop; bottom nav Home/Search/Shelf/Following/More (Downloads/Sources/Notifications/Settings); touch-first Reader | C2 | fe/shell/mobile | mobile | — | mobile viewport e2e | NS |

## §33–§39 Backup, export, separation, events, import, scanner, packaging

| ID | Requirement | Phase | Location | Surface | Persistence | Evidence | Status |
|---|---|---|---|---|---|---|---|
| M33 | Exactly two backup types | C7 | be/backup | Settings → Backup | backups | rows below | NS |
| M33.1 | Library Backup contents list; no downloaded reading files | C7 | be/backup/library | Backup | — | manifest inspection test | NS |
| M33.2 | Full Backup = Library + selected content; user chooses Works | C7 | be/backup/full | Backup selection | — | selection test | NS |
| M33.3 | Hard exclusions: passwords, cookies, sessions, tokens, remote UI sessions, recovery code, master key, browser profiles, staging, partials, rebuildable caches | C7 | be/backup | — | — | INV-19 content scan of both types | NS |
| M33.4 | Canonical `.osbackup` with manifest, schema/version, checksums, inventory, plugin requirements | C7 | be/backup/format | — | — | format validation tests | NS |
| M33.5 | Older backup migrates forward in staging (original unchanged); newer blocked, never discard unknown fields | C7 | be/backup/restore | Restore | — | version compatibility tests | NS |
| M33.6 | Preflight: archive/checksum, manifest, compatibility, space, plugins, permission changes, summary; missing plugin doesn't block (reinstall/skip); compatible newer only with review; new permissions need approval | C7 | be/backup/preflight | Restore steps | restore_ops | preflight tests | NS |
| M33.7 | Replace (after Safety Snapshot) / Merge with deterministic rules (current manual wins, add missing, progress never regresses, healthy files kept, verified backup repairs missing/corrupt) | C7 | be/backup/merge | Restore mode | — | merge conflict matrix tests | NS |
| M33.8 | Library Backup every 7 d with catch-up; Full manual; keep 4 verified; create → verify → rotate; never delete prior verified first | C7 | be/backup/schedule | Backup settings | backups | failed verification doesn't rotate; catch-up test | NS |
| M33.9 | Explicit Backup Location; default app storage allowed; same-disk warning; external mounts | C7 | be/backup, fe/backup | Backup Location | settings | warning test | NS |
| M33.10 | Built-in encryption not required; secrets excluded; external encryption allowed | C7 | — | docs | — | docs note | NS |
| M34 | Export ≠ Backup; one-way copy; never modifies library/DB/progress/mapping/content | C7 | be/export | Export wizard | export_jobs | INV-20 state diff test | NS |
| M34.1 | Scope Current Unit/Selected/Range/Entire Work/Selected Works; contract Work+Language+Source+units+formats; no mixing | C7 | be/export/contract | wizard Content | — | contract tests | NS |
| M34.2 | Prefer local files as-is; copy originals; no recompress/rebuild | C7 | be/export | — | — | byte-identical copy test | NS |
| M34.3 | Missing content choices Export Downloaded Only / Download Missing Then Export / Cancel; explicit permanent-download notice; normal engine → integrity → commit → export; no hidden temp download | C7 | be/export, fe/export | wizard | — | INV-21 test | NS |
| M34.4 | CBZ default for sequential; originals for books; no conversion subsystem | C7 | be/export | wizard Format | — | EX-29 check | NS |
| M34.5 | Folder default; optional ZIP; no giant default ZIP; avoid recompression | C7 | be/export | wizard | — | ZIP store-mode test | NS |
| M34.6 | Preserve ComicInfo.xml; optional `oneshelf-export.json` (title, aliases, language, source, units, formats, date); never secrets/sessions/tokens/cookies/absolute paths; files usable without it | C7 | be/export/metadata | — | — | metadata secret/path scan | NS |
| M34.7 | Cleaner export naming; IDs not required by default | C7 | be/export/naming | — | — | naming tests | NS |
| M34.8 | Explicit destination; preflight online/writable/space/conflicts; never silent overwrite; Skip Identical/Replace/Keep Both; checksum-identical skip | C7 | be/export/destination | wizard Destination/Review | — | conflict tests | NS |
| M34.9 | Persistent resumable jobs; streaming; destination-local staging; checksum verify; per-file failure isolation; Retry Failed; always Copy | C7 | be/export/jobs | Export activity | export_jobs, export_items | interruption resume; per-file failure tests | NS |
| M34.10 | Local Source Track exports; missing plugin doesn't block | C7 | be/export | — | — | INV-11 export test | NS |
| M34.11 | Export activity 30 d or 100 jobs; cleanup never deletes exported files | C7 | be/export/cleanup | activity | — | both-limit + file-preservation tests | NS |
| M35 | Notifications / Download History / Export activity / Backup history / Diagnostics kept separate | C6,C7 | respective modules | respective screens | separate tables/files | separation audit | NS |
| M36 | Real-time event channel (SSE/WebSocket) for downloads, notifications, progress, source/job state; polling fallback; no cloud | C1,C6 | be/events, be/api/sse, fe/events | all live screens | — | multi-client update + reconnect fallback tests | IMPL |
| M37 | Import CBZ/PDF/EPUB; Copy default; Move explicit; Leave in Place advanced/future *(optional)*; confident associate / Choose Existing / Create Local Work; no aggressive merge; drag & drop optional | C1,C7 | be/importer | Import flow | imports, assets | import uncertainty tests; Copy leaves source intact | IMPL |
| M38 | Scanner reconciles; manual delete → Missing Local File; offline → Unavailable; missing plugin still readable; OneShelf IDs aid recovery; per-asset checksum/size/path/integrity; checksums never matching evidence; no dedup | C1,C7 | be/storage/scanner | Storage | assets | scanner tests | IMPL |
| M39 | CBZ may include ComicInfo.xml; preserve originals; no unnecessary recompression; packaging only after integrity verification | C1,C5 | be/downloads/packaging | — | — | packaging order + byte preservation tests | NS |

## §40–§43 API docs, source suite, defaults, diagnostics

| ID | Requirement | Phase | Location | Surface | Persistence | Evidence | Status |
|---|---|---|---|---|---|---|---|
| M40 | API documentation: endpoint groups, auth expectations, events, plugin APIs, job interfaces; no cloud API; no secret exposure | C3→C9 | docs/api | — | — | docs review vs implemented routes | NS |
| M41 | Initial test source suite | C3→C9 | plugins/official, test_source | — | — | rows below; source-capability evidence ledger | NS |
| M41.1 | Real sources: MangaDex, 3asq/Al-Aasheq, WEBTOON, Tapas, Safahat/Hindawi (A5), Project Gutenberg, arXiv, Standard Ebooks | C3→C9 | plugins/official | Sources | plugins | per-source G5 evidence (EB-3) | NS |
| M41.2 | Controlled OneShelf Test Source for deterministic failure testing | C1,C3 | test_source/ | dev only | — | fault fixture suite | IMPL |
| M41.3 | Roles: foundation (Gutenberg, Hindawi, arXiv), sequential (MangaDex, 3asq), difficult web (WEBTOON, Tapas), format stress (Standard Ebooks: one Work, many formats, no duplicate Works) | C3→C9 | plugins/official | — | — | role-specific workflow tests | NS |
| M41.4 | Correctness/reference vs real-world stress sources; 3asq public parser testing only, not official/licensed default | C9 | docs/evidence | — | — | evidence ledger labels | NS |
| M41.5 | Local deterministic cases: irregular order/numbers, Special, Prologue, 3.5, 300→7, 429 Retry-After, 500, session expiry, HTML-as-media, corrupt media, interruption, changed ETag, unapproved redirect, malformed metadata, incomplete pagination, other recovery | C1→C5 | test_source/ | — | — | one scenario test each | IMPL |
| M42 | Single source of approved defaults, consistent across UI/API/runtime/migrations (D2) | C1 | be/settings/defaults | Settings | settings | DEF rows | IMPL |
| M43 | Diagnostics: parser/network/job/health operational data only; 7 d or 100 MB rotating; never passwords/cookies/tokens/auth headers/sensitive bodies; no matcher telemetry | C3,C6 | be/diagnostics | Settings → Advanced | rotating files | redaction scan; retention both-limit test | IMPL |

## §44–§50 UX rules, security, exclusions, non-goals

| ID | Requirement | Phase | Location | Surface | Persistence | Evidence | Status |
|---|---|---|---|---|---|---|---|
| M44 | Top-right Needs Attention + Notifications bell with counts; Needs Attention secondary to Hero, hidden at zero, actionable only; grouped popover with Reconnect/Manage Storage/Retry/View Source | C2,C6 | fe/shell/header | header | derived | UI tests | NS |
| M45 | Progressive disclosure: normal vs advanced for Downloads, Reader, Sources as listed | C2→C8 | fe/settings, fe/sources | Settings, Sources | — | UI audit per list | NS |
| M46 | Errors answer what happened / what OneShelf did safely / what user can do; raw errors only in expandable details | C2→C8 | fe/components/error | all | — | copy audit | NS |
| M47 | Destructive actions state what is removed, what remains, effects on files/progress/Follow/Shelf (Remove from Shelf, Delete Files, Replace Library, Reset Remote Passkeys, Uninstall Plugin) | C2,C6,C7,C8,C3 | fe/components/dialog | dialogs | — | dialog copy tests | NS |
| M48 | Security boundaries summary (declarative plugins, Core-owned capabilities, allowlists, redirect/DNS, SSRF, genuine LAN, trusted proxies, Origin/CSRF, secure cookies, no Web Storage tokens, document isolation, path safety, no plugin FS, no raw sessions, no secrets in logs/backups/export) | C1→C8 | see architecture.md §6 | — | — | INV-12–15, 19, 30 + security review | IMPL |
| M49 | Explicit v1 exclusions stay out of scope | all | — | — | — | EX rows | NS |
| M50 | Non-goals don't delay v1 (multi-user, cloud sync, annotation suite, AI recs, automation marketplace, WASM, conversion, dedup, push) | all | — | — | — | scope review per phase | NS |

## §51–§56 Invariants, structure, testing, design state, reconciliation

| ID | Requirement | Phase | Location | Surface | Persistence | Evidence | Status |
|---|---|---|---|---|---|---|---|
| M51 | All 30 acceptance invariants preserved | all | — | — | — | INV rows | NS |
| M52 | Subsystem separation as listed; source-specific logic out of generic queue/storage; small testable units | C0→all | architecture.md §2 | — | — | architecture review each phase; import-boundary lint | IMPL |
| M53 | Test categories: unit, integration, deterministic source failures, adapter contract, migration, crash/recovery, queue restart, storage offline, catalog trust, session reconnect, rate limits, resume/validators, corrupt repair, path safety, SSRF, EPUB/HTML isolation, CSRF/Origin, backup compatibility, restore merge, export resume/conflicts, Arabic normalization, RTL/LTR, manual overrides, multi-tab progress, events, accessibility-critical; isolated data only | C1→C9 | tests/ | — | isolated fixtures | C9 final verification report | NS |
| M54 | Architecture fully specified; visual refinement only within approved language; no semantic changes | C0→all | — | — | — | ledger | C0 |
| M55 | Instructions to the Meta Prompt generating model | — | — | — | — | Meta Prompt §A | UP |
| M56 | Retained older requirements (Docker, ar/en, RTL/LTR, persistent jobs, concurrency control, stable IDs, atomic commit, URL entry, realtime, API docs, bounded memory, display/matching/identity separation) and superseded ideas | all | — | — | — | covered by M2, M16, M15, M4, M17, M8, M36, M40, M26.6, M6.3; ledger C01–C03 | C0 |

## §51 Acceptance invariants

| ID | Invariant | Gate phase(s) | Minimum evidence (Meta Prompt §D1) | Status |
|---|---|---|---|---|
| INV-01 | Suspicious/incomplete catalog never erases trusted state | C4 | incomplete pagination + 300→7 preserve Trusted and derived state; recovery obeys completeness | NS |
| INV-02 | Source/language never switch silently | C4,C5,C6,C7 | search, Follow, Reader, retries, fallback, downloads, exports preserve source/language | NS |
| INV-03 | Soft Group never becomes permanent identity | C4 | Soft Group cannot create mappings; actions persist concrete track | NS |
| INV-04 | User overrides never silently overwritten | C4,C7 | refresh, plugin update, restore merge preserve overrides | NS |
| INV-05 | Unknown metadata never negative evidence | C4 | missing creator/date/volume/classification stays Unknown, not a mismatch | NS |
| INV-06 | Unknown quality never blocks content | C4,C5 | Unknown quality doesn't hide/reject/mark unavailable | NS |
| INV-07 | Reading never implies permanent download unless enabled | C5 | ordinary reading makes no permanent download | NS |
| INV-08 | Auto-download OFF by default | C1,C5 | defaults registry + fresh install assertion; enabled engagement per spec | IMPL |
| INV-09 | Follow never auto-downloads | C6 | new-release events enqueue nothing | NS |
| INV-10 | Remove from Shelf / Unfollow / Delete Files independent | C6 | separate assertions on files, Shelf, Follow, read state, progress | NS |
| INV-11 | Local content readable without source/plugin/network | C2,C7 | read + export CBZ/PDF/EPUB with source offline, plugin disabled/uninstalled, session disconnected | NS |
| INV-12 | Reader content can't execute privileged actions | C2 | malicious HTML/EPUB/SVG/PDF can't reach privileged actions, auth context or prohibited network | NS |
| INV-13 | Community plugins can't execute arbitrary code | C3 | malicious `.osp` code payloads rejected | IMPL |
| INV-14 | Plugins can't access arbitrary paths | C1,C3 | path payloads rejected; Core-only path generation | IMPL |
| INV-15 | Plugins can't SSRF into LAN/internal | C3 | HTTP + browser redirect/DNS SSRF cases blocked | IMPL |
| INV-16 | Incomplete downloads never appear as completed | C1,C5 | incomplete/corrupt artifacts stay out of local content | IMPL |
| INV-17 | Commit crash recoverable idempotently | C1,C5 | crash at each commit step; repeated reconciliation, no duplicate/lost registration | IMPL |
| INV-18 | Offline storage ≠ mass deletion | C1,C7 | offline root → Unavailable, no mass Missing/cleanup; safe reconnect reconcile | IMPL |
| INV-19 | Backups contain no sessions/passwords/tokens | C7 | inspect Library + Full contents/manifests for all exclusions | NS |
| INV-20 | Export never silently modifies library | C7 | state diff before/after normal export | NS |
| INV-21 | Download Missing Then Export requires explicit notice | C7 | disclosure required; normal validated commit then export | NS |
| INV-22 | Notifications never alter reading state | C6 | Seen / Clear Seen / cleanup leave reading untouched | NS |
| INV-23 | Clearing history never deletes content/state | C5,C6,C7 | download/export/notification history cleanup preserves content + progress | NS |
| INV-24 | Navigation follows Source Track order | C2 | prologue, Special, Extra, 3.5 navigate by track order | NS |
| INV-25 | Cross-source progress approximate/manual | C2,C5 | Start This Unit / Try Approximate Position; no guessed unit or exact-page claim | NS |
| INV-26 | Browser background work can't starve Reader/direct work | C3,C5 | saturated low-priority work; bounded Reader responsiveness | IMPL |
| INV-27 | Search results represent Works | C4 | Work-level results with selectable provenance, no duplicated source cards | NS |
| INV-28 | Covers never identity evidence | C4 | matching ignores covers; test with identical/different covers | NS |
| INV-29 | Matching diagnostics never telemetry | C4,C6,C9 | review persistent records, diagnostics, network calls, cleanup | NS |
| INV-30 | Remote passkey/session/CSRF boundaries; genuine LAN trusted per config | C1,C8 | passkey/session/CSRF/Origin + LAN/trusted-proxy/forged-header tests | IMPL |

## §42 Defaults (single defaults registry, D2)

| ID | Default | Phase | Verification | Status |
|---|---|---|---|---|
| DEF-backup | Library Backup every 7 d; Full manual; retain last 4 verified | C7 | schedule + rotation tests | NS |
| DEF-discovery-cache | TTL 7 d; 250 MB; LRU | C4 | cleanup both-limit tests | NS |
| DEF-reader-cache | TTL 7 d; 5 GB; LRU; never evict current unit / open nearby pages / permanent downloads | C5 | eviction protection tests | NS |
| DEF-auto-download | OFF; when enabled ~12% + genuine interaction | C1,C5 | INV-08; trigger test | NS |
| DEF-read-ahead | next 5 existing Reading Units | C5 | bounded read-ahead test | NS |
| DEF-auto-mark-read | 97% | C2 | threshold test | NS |
| DEF-reader-smart-controls | auto-hide ~3 s | C2 | timing test | NS |
| DEF-download-concurrency | HTTP 4; Browser 1 (independent) | C3,C5 | governor limit tests | IMPL |
| DEF-follow | ~12 h + jitter | C6 | scheduler test | NS |
| DEF-notifications | resolved visible ~1 h; history 30 d or 500 | C6 | lifecycle + both-limit tests | NS |
| DEF-export-activity | 30 d or 100 jobs | C7 | both-limit test | NS |
| DEF-diagnostics | 7 d or 100 MB | C3 | both-limit test | NS |
| DEF-retry | initial + up to 3 retries | C5 | retry count test | NS |
| DEF-remote-session | 30 d (options shorter/90 d/1 y/manual) | C8 | session expiry test | NS |
| DEF-storage-reserve | 5% capped 5 GB; warning ~2× reserve | C1 | guard tests | IMPL |
| DEF-catalog-suspicious | ≥~50% loss and ≥5 units; complete snapshots only; not sole truth | C4 | heuristic boundary tests | NS |
| DEF-staging | successful leftovers ~24 h; resumable failed ~7 d | C1,C5 | retention tests | IMPL |
| DEF-other | Preferred + Ask; settings precedence; classification precedence; remember per-Work Reader settings ON; preload ~7/4; folder export default; Copy import default; local/LAN auth OFF; metadata/format identity behavior (Meta Prompt D2) | C1→C8 | registry consistency test across UI/API/runtime/migrations | NS |

## §49 Exclusions (negative verification)

| ID | Excluded | Verification | Status |
|---|---|---|---|
| EX-01 | Cloud OneShelf account | no account endpoints/UI; offline operation | NS |
| EX-02 | Multi-user | single-user model audit | NS |
| EX-03 | Arbitrary executable community plugin code | INV-13 | IMPL |
| EX-04 | Restricted-RPC plugin design | architecture review | NS |
| EX-05 | Matcher telemetry / central collector / shared dataset | INV-29 | NS |
| EX-06 | Automatic source switching | INV-02 | NS |
| EX-07 | Automatic cross-language fallback | INV-02 | NS |
| EX-08 | Automatic translation | no translation code paths | NS |
| EX-09 | Title stemming | no-stemming tests (C09) | NS |
| EX-10 | Cover/image matching | INV-28 | NS |
| EX-11 | AI matching requirement | dependency/architecture audit | NS |
| EX-12 | Browser notifications | no Notification API / push usage audit | NS |
| EX-13 | Automatic new-release downloads | INV-09 | NS |
| EX-14 | Complex storage deduplication | architecture audit | NS |
| EX-15 | Full note/drawing/annotation system | Reader scope audit (bookmarks/highlights only) | NS |
| EX-16 | Social feed | UI/API audit | NS |
| EX-17 | Comments/reviews | UI/API audit | NS |
| EX-18 | Followers | UI/API audit | NS |
| EX-19 | Chat | UI/API audit | NS |
| EX-20 | Ads | UI/dependency audit | NS |
| EX-21 | Subscriptions/payments | UI/API audit | NS |
| EX-22 | Gaming/achievement systems | UI/API audit | NS |
| EX-23 | Anti-bot stealth/bypass | K1 guard test; config audit | IMPL |
| EX-24 | CAPTCHA bypass | action-required reporting test | NS |
| EX-25 | Paywall bypass | Use My Session scope tests | NS |
| EX-26 | DRM bypass | code audit | NS |
| EX-27 | Screenshot-based normal extraction | extraction method audit | NS |
| EX-28 | Hidden destructive cleanup | cleanup audits (M3.4, M25, INV-18/23) | NS |
| EX-29 | Implicit format conversion subsystem | export/packaging audit | NS |
| EX-30 | Uncontrolled plugin access to LAN/internal services | INV-15 | IMPL |

## Meta Prompt deliverables and source-investigation rules

| ID | Requirement | Phase | Evidence | Status |
|---|---|---|---|---|
| MPD-01 | Traceability + updated conflict/review ledger | C0→C9 | this file; conflict-review-ledger.md | C0 |
| MPD-02 | Architecture, persistent-state/state-transition, migration/recovery docs | C0→C9 | architecture.md (baseline); updated per phase | C0 |
| MPD-03 | API/auth/event and declarative plugin/generator documentation | C3→C9 | docs/api, docs/plugins | NS |
| MPD-04 | Deployment/startup/storage/backup/restore/upgrade instructions matching behavior | C9 | docs/ops | NS |
| MPD-05 | Dated source-capability evidence ledger (verified/unverified/unavailable/action-required/unsupported) | C3→C9 | docs/evidence/sources.md | NS |
| MPD-06 | Final verification report: commands, outcomes, workflows, artifact checks, UI/RTL/a11y screenshots, blocked gates | C9 | docs/evidence/verification.md | NS |
| MPG-1 | Investigate actual source before recipes; static first; justified browser escalation; no guessed selectors; no eval; no stealth/CAPTCHA/paywall/DRM; Use My Session only | C3→C9 | per-source investigation notes | NS |
| MPG-2 | Generate declarative packages with reviewed permissions; multi-Work/multi-query incl. Arabic; genuine empty queries; CDN vs ads domains; bounded transforms; adaptive only after failure; Unsupported instead of hacks | C9 | generator tests | NS |
| MPG-3 | Complete catalogs with completion evidence; preserve raw unit fields/order; no numeric gap/duplicate inference; formats don't create Works; reject non-content resources | C4,C9 | catalog/content tests | NS |
| MPG-4 | Recipes return descriptors; Core executes; scoped credentials; no header forwarding to CDN/redirect; expiring URL refresh bounded; error-class separation; Smart Retry/fallback semantics | C3,C5 | runtime tests | IMPL |
| MPG-5 | Verify through application services with isolated data; sanitized dated fixtures; Test Source synthetic faults; open/parse actual artifacts; record revision/plugin/source/conditions/checksums; no runtime telemetry | C3→C9 | evidence ledger | NS |

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
