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
- `SUPERSEDED` — replaced by a later explicit owner decision. The row keeps what it required and what was done, and names the requirement that replaced it. It counts neither as verified nor as blocking.

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
| M9.6 | Native adapters only as rare reviewed official exceptions; WASM not v1 | C3,C9 | be/plugins/native (registry of reviewed) | — | — | `test_boundaries_and_native_adapters.py::test_there_are_no_native_adapters_by_default` (no native package, no loader) and `::test_no_wasm_runtime_is_installed` | VERIFIED |
| M9.7 | Restricted RPC excluded | C3 | — | — | — | `test_no_executable_plugins_or_rpc.py::test_there_is_no_rpc_channel_to_a_plugin` (EX-04's guard) | VERIFIED |
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
| M22 | My Shelf: immediate save without files; views All/Saved/Reading/Completed/Favorites; Pin separate; Remove confirms Keep/Delete Files; Completed rules + optional delete keeping metadata; progress in SQLite; local-only Shelf search; formats (CBZ per unit, original images; PDF/EPUB coexist); per-unit local record; import CBZ/PDF/EPUB with confident association or Choose Work/Create Local Work | C6,C7 | be/services/shelf, fe/shelf | My Shelf, Work Details | shelf_entries, assets, progress | Backend: `test_remove_from_shelf_offers_file_choices_and_keeps_other_state` (Keep Files removes the entry, leaves the file, keeps Follow and progress), `test_delete_files_keeps_follow_shelf_and_progress`, `test_delete_files_touches_only_this_works_files`, `test_a_symlink_standing_in_for_a_managed_file_is_refused_and_never_counted`, `test_completed_survives_new_releases_and_counts_them`. UI: the eight WP-L1 tests in `WorkScreen.test.tsx` and `ShelfScreen.test.tsx`, including Arabic and the honest deletion count. **Live criterion executed 2026-09-19 (BV-02)**: the removal dialog read correctly in English and Arabic, mirrored, with zero axe violations and zero console errors | VERIFIED |
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
| M26.2 | Auto-hiding top/bottom bars; top: Back, Work title, unit, TOC, compact download, More (Mark Read/Unread, Change Source, Settings, Repair, Work Details, advanced); Back returns context + flushes progress | C2 | fe/reader/shell | Reader | progress flush | `says whether this unit is on the device, and can fetch the whole work`, `marks a unit unread as readily as read`, `keeps the reading controls to three layers, with the rest behind More`, plus the existing bar and flush tests. **Live 2026-09-19**: More holds mark read, mark unread, download the whole work and work details | VERIFIED |
| M26.3 | Distraction-Free modes; controls don't auto-hide while menu/drawer/settings open; Always Visible *(optional)* | C2 | fe/reader/controls | Reader | reader settings | panel-open no-hide test | VERIFIED |
| M26.3a | Smart: controls on interaction, auto-hide ~3 s | C2 | fe/reader/controls | Reader | — | timing test | VERIFIED |
| M26.3b | Hidden by Default/Minimal: bars hidden unless summoned; navigate by keys/mouse zones/gestures | C2 | fe/reader/controls | Reader | reader settings (per work) | `SourceSwitch.test.tsx::hides the bars until they are summoned, in the minimal control mode` (a drifting mouse does not summon); live 2026-09-20: bars `data-hidden=true` on entry, mouse move left them hidden, the centre button summoned them, axe clean | VERIFIED |
| M26.4 | Long Strip, Single, Double; LTR/RTL/Vertical | C2 | fe/reader/sequential | Reader | — | mode/direction tests | VERIFIED |
| M26.5 | Edge zones/center; direction-aware; keyboard set (prev/next, Space/Shift+Space, fullscreen, TOC, download, zoom, reset, Esc); touch (center tap, swipe, vertical scroll, pinch, double-tap); remapping *(optional)* | C2 | fe/reader/input | Reader | — | `SequentialReader.test.tsx` (direction-aware keys, Space, Escape, zoom, full screen, swipe, pinch, double tap, and `downloads this unit from the keyboard, like every other reading action`); live 2026-09-20: pressing `d` in the reader enqueued a real batch. Remapping stays optional (§26.5) | VERIFIED |
| M26.6 | Long Strip bounded render window; not fully decoded; percentage progress; optional page detail; restore approximate scroll | C2 | fe/reader/long_strip | Reader | progress.position | `holds only a bounded window of a long chapter, not the whole of it`, `moves the window as the reader scrolls, and keeps the scroll height steady`, `reads its position from the pages themselves, not from an estimated height`, `reserves each page's space before it loads`, `resumes inside the window, so virtualization does not lose the position`, `writes progress as the reader scrolls, with the revision it last saw`; **live 2026-09-19**: a 120-page unit mounted 12, the window followed the scroll, the library held page 34 and re-entry restored 34/120 with no console errors | VERIFIED |
| M26.7 | Single Page centered; Fit Smart/Width/Height/Original | C2 | fe/reader/single | Reader | — | fit tests | VERIFIED |
| M26.8 | Double Page LTR/RTL pairing, first-page cover, Shift Pairing, wide spreads; no AI/destructive crop | C2 | fe/reader/double | Reader | per-Work pairing offset | pairing tests | VERIFIED |
| M26.9 | Auto Fit Smart/Width/Height/Original; Smart stable | C2 | fe/reader/fit | Reader | — | `SequentialReader.test.tsx::keeps Smart fit steady across pages instead of deciding per page` — checked by mutation 2026-09-20: giving alternate pages their own class makes it fail | VERIFIED |
| M26.10 | Zoom keyboard/Ctrl+wheel/pinch/double-tap; drag pans; no accidental advance | C2 | fe/reader/zoom | Reader | — | zoomed-pan tests | VERIFIED |
| M26.11 | Minimal bottom UI; page-based (manga/PDF), position (Long Strip), logical (EPUB); scrubber | C2 | fe/reader/progress | Reader | progress | `moves through the unit with a scrubber that respects reading direction`; live: the scrubber moved the reader to 3 / 3 and carried the work's own direction | VERIFIED |
| M26.12 | TOC drawer (desktop side, tablet side sheet, mobile full/bottom sheet); unit states; filters All/Unread/Downloaded/New; subtle current highlight | C2 | fe/reader/toc | Reader | — | `filters the contents by what is new, as well as unread and downloaded`; `is_new` comes from Follow's own release record (`test_units_say_which_of_them_are_new`) and is cleared by `POST /api/follows/{id}/seen` | VERIFIED |
| M26.13 | End-of-unit uses Source Track order, never chapter+1; card with completed state, next actual unit (Special/Extra), Back to Work | C2 | fe/reader, be/reader/navigation | Reader | — | INV-24 irregular order test | VERIFIED |
| M26.14 | Auto Read 97%; always Mark Read/Unread; manual change doesn't eject | C2 | be/reader/progress | Reader More | read_state | Auto Read threshold and mark read/unread in `test_reading.py`; `marks a unit unread as readily as read` puts both in the reader | VERIFIED |
| M26.15 | Continue Reading restores exact same-source progress; Long Strip approximate | C2 | be/reader, fe/home | Home, Work Details | progress | Eight tests — `opens a unit where it was left rather than at the beginning`, `brings the stored page into view in Long Strip`, `clamps a stored position that is past the end of the unit`, `starts at the beginning when the library holds no position`, `writes nothing merely by resuming`, `opens the book at the chapter it was left on`, `opens the document at the page it is given`, `is given the page the library holds, through the Book Reader that renders it` — **and the declared live criterion, executed 2026-09-19 (BV-01)**: read to page 2, left the reader, re-entered; opened on page 2, the rendered element was page 2, the library held `{page: 2}`, zero console errors | VERIFIED |
| M26.16 | Subtle source indicator; manual switching only; same-language alternatives; layout warning; Start This Unit / Try Approximate Position; never fake page equivalence; uncertain → say so, open target track, don't guess | C2,C5 | fe/reader/source_switch, be/reader | Reader Change Source | — | `tests/unit/reader/test_alternatives.py` (7: confident match, other language never offered, no match, ambiguous, unnumbered never matched by position, chapter≠special, local track), `test_work_api.py::test_the_reader_can_ask_what_another_source_offers_for_this_unit` and `::...plain_404`, `SourceSwitch.test.tsx` (indicator, offer without claiming the same page, plain refusal + track link, approximate seek); live 2026-09-20 (`wpr5.py` PASS): indicator "English · local", panel warned about layout, offered Start this unit / Try approximate position for the confident source and "could not find this unit on source-c" with its track link, which landed on that track | VERIFIED |
| M26.17 | Settings precedence Session > Work > Content-Type > Global; remember per-Work ON; normal vs advanced settings; backgrounds Black/Dark Gray/White | C2 | be/settings, fe/reader/settings | Reader Settings | reader_settings scoped | precedence tests | VERIFIED |
| M26.18 | Preload ~next 7 / previous 4; Long Strip bounded window; advanced only | C2,C5 | fe/reader/preload | advanced settings | — | `preloads the next seven and the previous four, and no further` (Long Strip window), `prefetches the band around a single page without putting it on screen` (Single/Double). The numbers come from the §42 registry through `GET /api/reader/settings` — `test_reader_settings_come_from_the_one_defaults_registry` — not from literals in the component | VERIFIED |
| M26.19 | Compact download state (not downloaded/progress/downloaded); quiet auto-download; Download Entire Work on Work page/More | C2,C5 | fe/reader | Reader top bar | — | `says whether this unit is on the device, and can fetch the whole work`; units carry `integrity` (`test_units_say_whether_their_local_copy_is_sound`) so the state is honest about a copy that is there but unreadable | VERIFIED |
| M26.20 | Reader Cache ≠ download; no noisy Cached badges; details distinguish; cache key source + unit identity + resource validator, never title/number | C5 | be/reader/cache | Reader details | cache.db, blobs | key tests; eviction protections | VERIFIED |
| M26.21 | Page failure Retry/Repair/Skip; corrupt local Repair from Source/Skip; never silently delete; source unavailable keeps local/cached readable, no switch; inline Reconnect resuming same unit; calm rate-limit auto retry; offline Downloaded vs Online-only | C2,C5 | fe/reader/errors, be/reader | Reader | — | `offers Retry, Repair from Source and Skip when a page will not load`; repair goes through the normal pipeline (`test_repair_downloads_a_broken_copy_again_through_the_normal_pipeline`) and is refused for a local work with no source (`test_a_local_work_has_no_source_to_repair_from`) | VERIFIED |
| M26.22 | Book Reader; no full notes/drawing/annotations; only bookmarks + highlights; sequential page bookmarks not required | C2 | fe/reader/book | Reader | bookmarks, highlights | EX-15 check | VERIFIED |
| M26.22a | EPUB: font family/size, line height, margins, theme, TOC, search, bookmarks, highlights, logical progress; TOC tabs; no fake page count | C2 | fe/reader/epub | Reader | bookmarks, highlights, progress | `lets the reader set type, spacing, margins and theme, without loosening the frame`, `remembers the reading comfort for this book`, plus the existing TOC/search/bookmarks/highlights/progress tests. **Live 2026-09-19**: the rendered document measured 18px → 24px, line height 30.6 → 48, the sepia page, wider margins, all surviving re-entry, with `sandbox=""` and the frame's own CSP still in place and 0 axe violations | VERIFIED |
| M26.22b | PDF: navigation, zoom, fit width/page, text-layer search, bookmarks, highlights, progress, optional sidebar | C2 | fe/reader/pdf | Reader | bookmarks, highlights, progress | `zooms in, out and back to the fit`, `fits the whole page when asked, and remembers the choice`, `lets the keyboard reach the page area, which scrolls once it is zoomed`, plus the existing navigation, text-search, bookmark and highlight tests. **Live 2026-09-19**: fit width 1440 wide, fit page 514×772, zoom 643×965, re-entry unchanged with the fit still pressed, 0 axe violations | VERIFIED |
| M26.23 | Multi-tab: no stale regression; debounced writes; force flush on unit change/hidden/exit/lifecycle | C2 | be/reader/progress, fe/reader | — | progress.revision | multi-tab stale-write tests; Mark Unread/reread still work | VERIFIED |
| M26.24 | Layout-preserving skeletons; one-time "Tap/click center" hint | C2 | fe/reader | Reader | local hint flag | `SourceSwitch.test.tsx::shows the centre-tap hint once, and never again` and `::holds each page's place while it loads`; `SequentialReader.test.tsx::reserves each page's space before it loads`; live 2026-09-20: hint shown once, absent on the next visit, pages held their place | VERIFIED |
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
| M30.10 | Source Recovered optional/silent by default | C6 | be/notifications | — | setting | `test_source_recovered_is_silent_unless_it_is_turned_on` — the notice is optional and silent by default (§30.10), with `GET/POST /api/notifications/settings` and its Settings control | VERIFIED |
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
| M32.6 | Work cards Compact/Standard/Detailed; one logical Work; dominant cover; concise availability; no internal states | C2 | fe/components/work_card | cards | — | INV-27 UI test; **Defect found 2026-09-21 on the real UI (I-47, I-48):** the earlier evidence never exercised an unbound live result or a real cover — every result card of a real search was an inert span, and no cover reached any screen. Fixed (`1d6b11d`, `5d5b83f`, `19fa935`) and re-verified in a real browser against real sources (`docs/c9/verification.md` §6); `test_open_and_covers.py` (32), `ResultCard.test.tsx` (10) | VERIFIED |
| M32.7 | Search UI: warm canvas, serif title, large field, filter chips, Grid/List, cover results, no mandatory shelves | C2,C4 | fe/search | Search | — | screenshot; **Defect found 2026-09-21 on the real UI (I-47, I-48):** the earlier evidence never exercised an unbound live result or a real cover — every result card of a real search was an inert span, and no cover reached any screen. Fixed (`1d6b11d`, `5d5b83f`, `19fa935`) and re-verified in a real browser against real sources (`docs/c9/verification.md` §6); `test_open_and_covers.py` (32), `ResultCard.test.tsx` (10) | VERIFIED |
| M32.8 | Work Details: small Hero header (cover/title/original/type/creator/description); actions Continue/Read, Add to Shelf, Follow, Favorite, Pin; tabs Read/Details/Sources; elegant index unit list | C2 | fe/work | Work Details | — | UI tests | VERIFIED |
| M32.9 | My Shelf bookshelf motif; Pinned/Reading/Completed/Favorites sections; search/sort/filter/Grid-List | C2,C6 | fe/shelf | My Shelf | — | `ShelfScreen.test.tsx` (views, search, Grid/List, and `sorts the shelf by title or by when a work arrived, without asking the library again`); live 2026-09-20: eight works reordered by title, locale-aware, axe clean | VERIFIED |
| M32.10 | Following as reading journal; paper rows; New Releases / Needs Attention / Up to Date; no charts | C2,C6 | fe/following | Following | — | UI tests | VERIFIED |
| M32.11 | Downloads operational: no shelves, paper panels, olive progress, green controls, batch cards, expandable units; not analytics | C2,C5 | fe/downloads | Downloads | — | UI tests | VERIFIED |
| M32.12 | Sources elegant catalog-card list: source, type/language, status, last successful check, Configure/More; advanced hidden (A3) | C2,C3 | fe/sources | Sources | — | UI tests | VERIFIED |
| M32.13 | Notifications warm right drawer; Mark All as Seen / Clear Seen / View All | C2,C6 | fe/notifications | drawer | — | UI tests | VERIFIED |
| M32.14 | Settings paper aesthetic; categories left / panel right; General, Reader, Downloads, Storage, Sources, Notifications, Backup, Remote Access, Advanced, Developer; progressive disclosure | C2 | fe/settings | Settings | — | `SettingsScreen.test.tsx`: `has no category left saying it is coming later`, `keeps the technical knobs behind disclosure, and writes what the reader chooses`, `offers auto-download as the Master defines it: off, and with its own reach`, `turns the Source Recovered notice on, which is off until asked for`, plus the category list and storage tests. **Live 2026-09-19**: all ten categories in both languages hold real controls, no placeholders, 0 axe violations | VERIFIED |
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
| M33.10 | Built-in encryption not required; secrets excluded; external encryption allowed | C7 | — | docs | — | `test_backup.py::test_backup_excludes_every_secret_and_rebuildable_store` (no session, key or staging byte reaches an archive) and `docs/operations.md` §5, which states that no archive is encrypted by OneShelf, that none needs to be, and how to encrypt the volume yourself | VERIFIED |
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
| M36 | Real-time event channel (SSE/WebSocket) for downloads, notifications, progress, source/job state; polling fallback; no cloud | C1,C6 | be/events, be/api/sse, fe/events | all live screens | — | `tests/unit/test_events.py` (bus, ordering, drop-with-resync, SSE encoding) and `src/app/live.test.tsx` (`tells a screen to re-read when the library says something changed`, `falls back to polling while the stream is down, and stops once it is back`, `re-opens the stream after an error…`, `re-reads on a resync rather than guessing what it missed`), plus `follows the library live, re-reading only what changed`. **Live 2026-09-19**: two tabs, one `/api/events` stream — following a work in one moved the other's list 8 → 9 with no navigation or refresh | VERIFIED |
| M37 | Import CBZ/PDF/EPUB; Copy default; Move explicit; Leave in Place advanced/future *(optional)*; confident associate / Choose Existing / Create Local Work; no aggressive merge; drag & drop optional | C1,C7 | be/importer | Import flow | imports, assets | import uncertainty tests; Copy leaves source intact | VERIFIED |
| M38 | Scanner reconciles; manual delete → Missing Local File; offline → Unavailable; missing plugin still readable; OneShelf IDs aid recovery; per-asset checksum/size/path/integrity; checksums never matching evidence; no dedup | C1,C7 | be/storage/scanner | Storage | assets | scanner tests | VERIFIED |
| M39 | CBZ may include ComicInfo.xml; preserve originals; no unnecessary recompression; packaging only after integrity verification | C1,C5 | be/downloads/packaging | — | — | packaging order + byte preservation tests | VERIFIED |

## §40–§43 API docs, source suite, defaults, diagnostics

| ID | Requirement | Phase | Location | Surface | Persistence | Evidence | Status |
|---|---|---|---|---|---|---|---|
| M40 | API documentation: endpoint groups, auth expectations, events, plugin APIs, job interfaces; no cloud API; no secret exposure | C3→C9 | docs/api | — | — | docs review vs implemented routes | VERIFIED |
| M41 | Initial test source suite | C3→C9 | plugins/official, test_source | — | — | rows below; source-capability evidence ledger | VERIFIED |
| M41.1 | Real sources: MangaDex, 3asq/Al-Aasheq, WEBTOON, Tapas, Safahat/Hindawi (A5), Project Gutenberg, arXiv, Standard Ebooks | C3→C9 | plugins/official | Sources | plugins | **All eight ship**, each passing the tests it packages (`test_official_packages.py`) and verified live (`tests/live/test_source_suite.py`, `ONESHELF_LIVE_SOURCES=1`): MangaDex, Gutenberg, arXiv, Standard Ebooks, WEBTOON, Tapas, Safahat/Hindawi (2026-09-20) and **3asq/Al-Aasheq at 3asq.online** (2026-09-21 — search 21 results complete, One Piece 567 chapters in reading order, 23 images in a chapter, 104 latest entries, three pages validated and packaged into a CBZ the integrity validator accepts). None needed a browser. Search is `Unsupported` for WEBTOON and Tapas because both robots.txt files disallow it; every other capability of every source is exercised. `3asq.org` was a stale domain, never an implementation — see `docs/c9/source-capability-ledger.md` §1c | VERIFIED |
| M41.2 | Controlled OneShelf Test Source for deterministic failure testing | C1,C3 | test_source/ | dev only | — | fault fixture suite | VERIFIED |
| M41.3 | Roles: foundation (Gutenberg, Hindawi, arXiv), sequential (MangaDex, 3asq), difficult web (WEBTOON, Tapas), format stress (Standard Ebooks: one Work, many formats, no duplicate Works) | C3→C9 | plugins/official | — | — | role-specific workflow tests | VERIFIED |
| M41.4 | Correctness/reference vs real-world stress sources; 3asq public parser testing only, not official/licensed default | C9 | docs/evidence | — | — | evidence ledger labels. 3asq ships as a public catalogue and parser stress source only, never an assumed official or licensed default: its manifest asks for one domain permission, declares no auth and no browser, and the package tests hold that (`test_3asq_package.py`) | VERIFIED |
| M41.5 | Local deterministic cases: irregular order/numbers, Special, Prologue, 3.5, 300→7, 429 Retry-After, 500, session expiry, HTML-as-media, corrupt media, interruption, changed ETag, unapproved redirect, malformed metadata, incomplete pagination, other recovery | C1→C5 | test_source/ | — | — | one scenario test each | VERIFIED |
| M42 | Single source of approved defaults, consistent across UI/API/runtime/migrations (D2) | C1 | be/settings/defaults | Settings | settings | DEF rows | VERIFIED |
| M43 | Diagnostics: parser/network/job/health operational data only; 7 d or 100 MB rotating; never passwords/cookies/tokens/auth headers/sensitive bodies; no matcher telemetry | C3,C6 | be/diagnostics | Settings → Advanced | rotating files | `tests/unit/diagnostics/test_store.py` (rotation by age then size, bounds, clearing), `test_redact.py` (redaction at write time, incl. I-18 regression), `test_no_matcher_telemetry.py::test_the_diagnostics_store_takes_operational_records_only` and `::test_a_matching_pass_writes_nothing_to_the_diagnostics_store` (INV-29), `test_app.py::test_diagnostics_are_local_bounded_and_clearable`, `test_test_source_pipeline.py::test_a_source_failure_becomes_a_local_diagnostic`, `test_shelf_and_follow.py::test_a_check_that_fails_leaves_a_diagnostic_saying_why`, `SettingsScreen.test.tsx::shows what the local diagnostics hold, and can clear them`; live 2026-09-20 (`wpd1.py` PASS): real Check Now failures filled the store (3 records, 582 B), panel read "3 records / 582 B of 100 MB / Kept for 7 days, then dropped", nothing sensitive on disk, clearing emptied it, axe clean, no console errors | VERIFIED |

## §44–§50 UX rules, security, exclusions, non-goals

| ID | Requirement | Phase | Location | Surface | Persistence | Evidence | Status |
|---|---|---|---|---|---|---|---|
| M44 | Top-right Needs Attention + Notifications bell with counts; Needs Attention secondary to Hero, hidden at zero, actionable only; grouped popover with Reconnect/Manage Storage/Retry/View Source | C2,C6 | fe/shell/header | header | derived | UI tests | VERIFIED |
| M45 | Progressive disclosure: normal vs advanced for Downloads, Reader, Sources as listed | C2→C8 | fe/settings, fe/sources | Settings, Sources | — | Advanced disclosure in Reader, Downloads and Sources — `keeps the technical knobs behind disclosure…`; live check confirmed the advanced controls are absent until disclosed and present after. Sources keeps versions, trust labels and channels behind Advanced; the reader's own drawer keeps its advanced settings the same way | VERIFIED |
| M46 | Errors answer what happened / what OneShelf did safely / what user can do; raw errors only in expandable details | C2→C8 | fe/components/error | all | — | copy audit | VERIFIED |
| M47 | Destructive actions state what is removed, what remains, effects on files/progress/Follow/Shelf (Remove from Shelf, Delete Files, Replace Library, Reset Remote Passkeys, Uninstall Plugin) | C2,C6,C7,C8,C3 | fe/components/dialog | dialogs | — | Restore, LAN reset, history clearing and storage actions already explained themselves; Remove from Shelf and Delete Files now do too — what is removed and what stays in separate sections, Keep and Delete as two named actions, and the count reported afterwards is the library's, not a forecast. Tests as for M22; **live bilingual check executed 2026-09-19 (BV-02)** | VERIFIED |
| M48 | Security boundaries summary (declarative plugins, Core-owned capabilities, allowlists, redirect/DNS, SSRF, genuine LAN, trusted proxies, Origin/CSRF, secure cookies, no Web Storage tokens, document isolation, path safety, no plugin FS, no raw sessions, no secrets in logs/backups/export) | C1→C8 | see architecture.md §6 | — | — | INV-12–15, 19, 30 + security review | VERIFIED |
| M49 | v1 exclusions enforced; none silently revived | all | tests/unit/exclusions | — | — | `test_every_exclusion_is_guarded.py`: §49 is read out of the Master and every one of its 30 items names a guard that exists. Each guard was checked by introducing its violation and watching it fail (2026-09-20, 8 of 8 caught; two guards strengthened when they did not) | VERIFIED |
| M50 | Non-goals don't delay v1 (multi-user, cloud sync, annotation suite, AI recs, automation marketplace, WASM, conversion, dedup, push) | all | — | — | — | `test_every_exclusion_is_guarded.py::test_the_non_goal_list_still_matches_the_masters_own_list` and `::test_no_non_goal_arrived_early` — §50 is read out of the Master and each of its nine items names a guard that exists | VERIFIED |

## §51–§56 Invariants, structure, testing, design state, reconciliation

| ID | Requirement | Phase | Location | Surface | Persistence | Evidence | Status |
|---|---|---|---|---|---|---|---|
| M51 | All 30 acceptance invariants preserved | all | — | — | — | All 30 invariants verified; INV-25 closed with its Start This Unit / Try Approximate Position affordances (2026-09-20) | VERIFIED |
| M52 | Subsystem separation as listed; source-specific logic out of generic queue/storage; small testable units | C0→all | architecture.md §2 | — | — | `test_boundaries_and_native_adapters.py::test_the_generic_machinery_never_names_a_source` and `::test_the_schema_never_names_a_source_either` (downloads, storage, db, reader, library, follow, backup, export) | VERIFIED |
| M53 | Test categories: unit, integration, deterministic source failures, adapter contract, migration, crash/recovery, queue restart, storage offline, catalog trust, session reconnect, rate limits, resume/validators, corrupt repair, path safety, SSRF, EPUB/HTML isolation, CSRF/Origin, backup compatibility, restore merge, export resume/conflicts, Arabic normalization, RTL/LTR, manual overrides, multi-tab progress, events, accessibility-critical; isolated data only | C1→C9 | tests/ | — | isolated fixtures | C9 final verification report | VERIFIED |
| M54 | Architecture fully specified; visual refinement only within approved language; no semantic changes | C0→all | — | — | — | ledger | VERIFIED |
| M55 | Instructions to the Meta Prompt generating model | — | — | — | — | Meta Prompt §A | VERIFIED |
| M56 | Retained older requirements (Docker, ar/en, RTL/LTR, persistent jobs, concurrency control, stable IDs, atomic commit, URL entry, realtime, API docs, bounded memory, display/matching/identity separation) and superseded ideas | all | — | — | — | Retained requirements hold except Docker verification (EB-1). Bounded memory closed with M26.6's window (live: 12 of 120 pages mounted); realtime closed with M36's client | IN_PROGRESS |

## §51 Acceptance invariants

| ID | Invariant | Gate phase(s) | Minimum evidence (Meta Prompt §D1) | Status |
|---|---|---|---|---|
| INV-01 | Suspicious/incomplete catalog never erases trusted state | C4 | incomplete pagination + 300→7 preserve Trusted and derived state; recovery obeys completeness | VERIFIED |
| INV-02 | Source/language never switch silently | C4,C5,C6,C7 | search, Follow, Reader, retries, fallback, downloads, exports preserve source/language | VERIFIED |
| INV-03 | Soft Group never becomes permanent identity | C4 | Soft Group cannot create mappings; actions persist concrete track | VERIFIED |
| INV-04 | User overrides never silently overwritten | C4,C7 | refresh, plugin update, restore merge preserve overrides | VERIFIED |
| INV-05 | Unknown metadata never negative evidence | C4 | missing creator/date/volume/classification stays Unknown, not a mismatch | VERIFIED |
| INV-06 | Unknown quality never blocks content | C4,C5 | `test_boundaries_and_native_adapters.py::test_unknown_is_never_treated_as_unavailable` — an unknown unit is listed beside an available one, stays `unknown` rather than becoming `unavailable`, and nothing downloaded is not bad quality | VERIFIED |
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
| INV-25 | Cross-source progress approximate/manual | C2,C5 | Nothing maps positions across sources: `alternatives()` matches on the unit's own number and type or refuses, and Try Approximate Position carries a *fraction* applied to the target unit's own length, announced as approximate on screen (`SourceSwitch.test.tsx::opens an approximate position as approximate, and says so` — it fails without the parameter, confirmed 2026-09-20) | VERIFIED |
| INV-26 | Browser background work can't starve Reader/direct work | C3,C5 | saturated low-priority work; bounded Reader responsiveness | VERIFIED |
| INV-27 | Search results represent Works | C4 | Work-level results with selectable provenance, no duplicated source cards | VERIFIED |
| INV-28 | Covers never identity evidence | C4 | matching ignores covers; test with identical/different covers; **Defect found 2026-09-21 on the real UI (I-47, I-48):** the earlier evidence never exercised an unbound live result or a real cover — every result card of a real search was an inert span, and no cover reached any screen. Fixed (`1d6b11d`, `5d5b83f`, `19fa935`) and re-verified in a real browser against real sources (`docs/c9/verification.md` §6); `test_open_and_covers.py` (32), `ResultCard.test.tsx` (10) | VERIFIED |
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
| DEF-diagnostics | 7 d or 100 MB | C3 | `DiagnosticsStore` reads both bounds from the registry and `rotate()` applies age first, then size, oldest segment first; `test_store.py` covers both, and the live panel showed "of 100 MB" and "Kept for 7 days" from the same defaults (2026-09-20) | VERIFIED |
| DEF-retry | initial + up to 3 retries | C5 | retry count test | VERIFIED |
| DEF-remote-session | 30 d (options shorter/90 d/1 y/manual) | C8 | session expiry test | VERIFIED |
| DEF-storage-reserve | 5% capped 5 GB; warning ~2× reserve | C1 | guard tests | VERIFIED |
| DEF-catalog-suspicious | ≥~50% loss and ≥5 units; complete snapshots only; not sole truth | C4 | heuristic boundary tests | VERIFIED |
| DEF-staging | successful leftovers ~24 h; resumable failed ~7 d | C1,C5 | retention tests | VERIFIED |
| DEF-other | Preferred + Ask; settings precedence; classification precedence; remember per-Work Reader settings ON; preload ~7/4; folder export default; Copy import default; local/LAN auth OFF; metadata/format identity behavior (Meta Prompt D2) | C1→C8 | `test_defaults_reach_every_layer.py` — the API serves the registry's own values for the reader, auto-download and diagnostics; the reader's fallback constants equal them; and no other module writes an approved default down again | VERIFIED |

## §49 Exclusions (negative verification)

| ID | Excluded | Verification | Status |
|---|---|---|---|
| EX-01 | Cloud OneShelf account | `test_no_accounts_or_multi_user.py` (no account route, no OneShelf service reached, sign-in is passkey or source only) | VERIFIED |
| EX-02 | Multi-user | `test_no_accounts_or_multi_user.py::test_the_schema_never_says_which_user_a_row_belongs_to` (CREATE and ALTER) | VERIFIED |
| EX-03 | Arbitrary executable community plugin code | INV-13 | VERIFIED |
| EX-04 | Restricted-RPC plugin design | `test_no_executable_plugins_or_rpc.py` (no exec/eval/import/subprocess/pickle in the plugin path; no RPC transport; YAML only through the restricted loader) | VERIFIED |
| EX-05 | Matcher telemetry / central collector / shared dataset | INV-29 | VERIFIED |
| EX-06 | Automatic source switching | INV-02 | VERIFIED |
| EX-07 | Automatic cross-language fallback | INV-02 | VERIFIED |
| EX-08 | Automatic translation | `test_no_translation_or_ai_matching.py` (no translation engine installed; nothing names a target language) | VERIFIED |
| EX-09 | Title stemming | no-stemming tests (C09) | VERIFIED |
| EX-10 | Cover/image matching | INV-28 | VERIFIED |
| EX-11 | AI matching requirement | `test_no_translation_or_ai_matching.py` (no model runtime or hosted client installed; binding is `decided_by="evidence"`) | VERIFIED |
| EX-12 | Browser notifications | no Notification API / push usage audit | VERIFIED |
| EX-13 | Automatic new-release downloads | INV-09 | VERIFIED |
| EX-14 | Complex storage deduplication | `test_no_dedup_or_annotation_system.py` (no dedup identifiers, no unique checksum index, `os.link` only as the atomic half of a move) and `test_work_api.py::test_the_same_file_imported_twice_is_stored_twice` (two inodes) | VERIFIED |
| EX-15 | Full note/drawing/annotation system | `test_no_dedup_or_annotation_system.py` (two mark tables and no third; no annotation identifiers) | VERIFIED |
| EX-16 | Social feed | `test_no_social_or_commercial_surfaces.py::test_no_route_opens_a_social_or_commercial_surface` | VERIFIED |
| EX-17 | Comments/reviews | `test_no_social_or_commercial_surfaces.py::test_no_table_stores_comments_followers_or_purchases` | VERIFIED |
| EX-18 | Followers | `test_no_social_or_commercial_surfaces.py::test_no_table_stores_comments_followers_or_purchases` (`follows` is a work, `followers` is a person) | VERIFIED |
| EX-19 | Chat | `test_no_social_or_commercial_surfaces.py::test_nothing_in_the_product_builds_one_of_these` | VERIFIED |
| EX-20 | Ads | `test_no_social_or_commercial_surfaces.py` (no ad identifiers; strings guarded in both languages) | VERIFIED |
| EX-21 | Subscriptions/payments | `test_no_social_or_commercial_surfaces.py::test_no_payment_processor_is_installed` | VERIFIED |
| EX-22 | Gaming/achievement systems | `test_no_social_or_commercial_surfaces.py::test_nothing_in_the_product_builds_one_of_these` | VERIFIED |
| EX-23 | Anti-bot stealth/bypass | K1 guard test; config audit | VERIFIED |
| EX-24 | CAPTCHA bypass | `test_no_bypass_or_screenshot_extraction.py` (no solver installed or called; a blocked source is reported instead) | VERIFIED |
| EX-25 | Paywall bypass | Use My Session scope tests | VERIFIED |
| EX-26 | DRM bypass | `test_no_bypass_or_screenshot_extraction.py::test_nothing_touches_drm` | VERIFIED |
| EX-27 | Screenshot-based normal extraction | `test_no_bypass_or_screenshot_extraction.py` (no screenshot in any extraction path; the one screencast is Use My Session) | VERIFIED |
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
| M36 | `events/bus.py`, `GET /api/events` | `tests/unit/test_events.py` (bus, ordering, drop-with-resync, SSE encoding) and `src/app/live.test.tsx` (`tells a screen to re-read when the library says something changed`, `falls back to polling while the stream is down, and stops once it is back`, `re-opens the stream after an error…`, `re-reads on a resync rather than guessing what it missed`), plus `follows the library live, re-reading only what changed`. **Live 2026-09-19**: two tabs, one `/api/events` stream — following a work in one moved the other's list 8 → 9 with no navigation or refresh | VERIFIED |
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
| M43 | `diagnostics/redact.py`, `diagnostics/store.py`, `api/storage.py` (`/api/diagnostics`) | `test_redact.py`, `test_store.py`, `test_app.py` | — |
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


## Release requirements (explicit user requirements, 2026-09-21)

REL-10 and REL-11 were added by a further explicit requirement: the official adapters must be available on a fresh installation without any manual step.

REL-16…REL-25 were added by the OneShelf-Adapters requirement (2026-09-21): adapter development, contribution and the Registry move to an independent public repository; OneShelf keeps an offline release snapshot and reads the Registry over HTTPS.

REL-12…REL-15 were added by the Official Source Registry requirement (2026-09-21): discover, review, install, update and reinstall the official adapters from the web UI through the existing Registry architecture, alongside the bundled path. That requirement supersedes ledger decision D-C3-16's "no default registry".

Recorded after the C-phase work, as a subsequent explicit user requirement: OneShelf must install from
a clone with one command, and be published as a public GitHub repository named exactly `OneShelf`.
These rows follow the same rule as every other: `VERIFIED` means the criterion was executed, and
IMPLEMENTED is not VERIFIED.

| ID | Requirement | Implementation | Evidence | Status |
|---|---|---|---|---|
| REL-01 | `./install.sh` from a clone: detects a runtime, detects Compose, never installs either, never uses sudo, creates `.env` only when absent, prepares only OneShelf's own directories, builds, starts, waits for readiness, checks health, prints the URL, is safe to repeat | `install.sh`, `deploy/lib.sh` | `tests/deploy/test_install_scripts.py` — expanded deployment suite: 58 passed, 1 ShellCheck skip; covers Docker and Podman detection, an installed-but-dead runtime, no runtime at all, Compose plugin vs standalone, no Compose, first-run `.env` at mode 600, an existing `.env` left byte-for-byte and honoured, a repeated install changing nothing, only its own five directories created, and no secret in the output. **Never executed against a real runtime** | IMPLEMENTED |
| REL-02 | `update.sh`: preserves data and configuration, refuses unsafe automatic updates with an explanation, rebuilds, restarts through the normal migration path, verifies readiness and health, documents rollback | `update.sh` | `test_install_scripts.py` — refuses before an install, refuses with local changes to tracked files (naming the stash command and stating the library is untouched), continues without git, propagates a readiness failure; rollback documented in README → Updating. **Never executed against a real runtime** | IMPLEMENTED |
| REL-03 | `uninstall.sh`: stops and removes the deployment, **keeps persistent data by default**; destruction is separate, named, explicit and strongly confirmed, and touches nothing else | `uninstall.sh` | `test_install_scripts.py` — a library file and a content file both survive the default path byte-for-byte; an unknown option is refused; `--delete-data` with the wrong answer deletes nothing; with the exact sentence it deletes its own directories and leaves a sibling directory untouched. **Never executed against a real runtime** | IMPLEMENTED |
| REL-04 | The interface is served from the API's own origin, behind the same boundaries | `api/app.py::_mount_web_interface`, `deploy/Dockerfile` (web build stage) | `tests/integration/test_web_ui.py` — root, assets, SPA fallback, API still 404s as the API, no path escape, a remote client refused at `/`, `/shelf` and `/assets/...`, and the API still runs with no build present. Live 2026-09-21: the real `vite build` output served at `/`, a hashed asset, a deep link, and the full UI rendered in a browser with no console errors | VERIFIED |
| REL-05 | README quick start, prerequisites, default URL, persistent data, updating, uninstalling, backups, advanced Compose for both runtimes, Fedora + Podman first-class | `README.md` | Quick start is the three commands; both runtimes documented separately; every linked document exists | VERIFIED |
| REL-06 | Release hygiene: clean tree, `main`, reviewed `.gitignore`, no secrets or user data tracked | `.gitignore` | Handoff scan across all 82 reachable baseline commits found no credential keys/tokens or user data; tracked changes reviewed, original untracked reference image preserved and excluded; `.env`, `deploy/volumes/`, `*.osbackup` and local databases are ignored; the only credential present is the Test Source's deliberate fake, which `test_browser.py` asserts never reaches disk | VERIFIED |
| REL-07 | A public GitHub repository named exactly `OneShelf`, `main` pushed, remote HEAD equal to local HEAD | — | **Published 2026-09-21** on the owner's explicit decision to publish independently of the host gate. `IPurplel/OneShelf`, `private: false`, default branch `main`, 84 commits pushed without force and without rewriting history. Local and remote HEAD verified equal through the GitHub API. Remote contains README, all three scripts, `.env.example`, the Compose file and Dockerfile, and `frontend/`, `backend/`, `docs/`, `deploy/`; `.env`, `deploy/volumes`, `backend/var` and `keys` all return 404. Publication is not deployment verification | VERIFIED |
| REL-08 | Fedora-host Podman verification: install from a fresh-clone-style checkout, readiness, health, a storage root, real content, restart, full recreation, schema and migrations, content on persistent storage, non-root, healthy, `update.sh` safe, `uninstall.sh` preserving data | `deploy/`, the three scripts | **Not executed.** No container runtime exists in this environment and none may be installed here. Exact commands: `docs/c9/verification.md` §3a | BLOCKED |
| REL-09 | Clean-clone release test against the published repository | — | **Partly done, 2026-09-21.** The public repository was cloned into an isolated temporary directory and everything short of the container itself was exercised from that clone alone: every file an install needs is present, the executable bits survived, no `.env` or library data came with it, all four scripts parse, `install.sh` with no runtime refuses clearly and exits 1, and with a stub runtime it detects Compose, creates `.env`, creates its five directories, passes `--env-file` and `-p oneshelf` to Compose, and then fails readiness honestly because nothing is running. **The actual install needs a container runtime** | BLOCKED |
| REL-10 | The eight official adapters install automatically on a fresh library, through the normal `PluginManager` pipeline, exactly once; a source the person disabled or removed is never restored; updates keep rollback and never approve new permissions; a broken adapter is contained and raised in Needs Attention without blocking readiness (§3.3) | `plugins/bundled.py`, migration 0014, `api/app.py` startup, `notifications.bundled_source_failed` | `test_bundled_sources.py` (21), `test_bundled_sources_api.py` (6), `test_migration_bundled_channel.py` (4); four safety guards checked by mutation, each caught. Live 2026-09-21 against the real application process from a fresh data directory: all eight active as `official`/`bundled`, `/api/ready` listing all eight installed and none failed, a real search answered by all six search-capable sources with none failed; then WEBTOON disabled and Tapas removed, the process restarted, and both stayed that way with 6 active, 8 plugin rows, 8 version rows and the marker set | VERIFIED |
| REL-11 | The production image carries the bundled adapters and installs them on first start | `deploy/Dockerfile` (`ONESHELF_BUNDLED_PLUGINS_DIR=/app/plugins/official`) | `test_image_contains_bundled_sources.py` — every adapter file survives the real `.dockerignore` (matcher checked against Docker's rules first), `COPY backend/ /app/` places them where the environment points, Compose does not override it, and the builder is inside the installed package. **The image has not been built or started**: the host gate now asserts `/app/plugins/official`, all eight active from a fresh install, and that disabled and removed sources survive restart, recreation and update | BLOCKED |
| REL-12 | The official Registry artifacts are generated, deterministic and verifiable: `registry/index.json` (`oneshelf.registry/1`, sorted, with `api`) and `registry/packages/*.osp` built by the one canonical builder shared with the bundled bootstrap, packaged-tested, hashed from the bytes, never hand-edited; served over HTTPS as the default Registry | `backend/plugins/registry_tool.py` (`build`, `verify`, `public-key`), `registry/`, `deploy/compose.yaml`, `.env.example` | `test_registry_tool.py` (23): all eight with real hashes, byte-identical to bundled, two builds identical, hand-edited hash / replaced package / stray file / stale sources / failing adapter / id mismatch all fail, committed `registry/` verifies; `test_registry_defaults.py` (5). Live 2026-09-21: the real application process, fresh data directory, `ONESHELF_REGISTRY_URL` = the GitHub raw index, read all eight entries over HTTPS through Core's egress policy | VERIFIED |
| REL-13 | Sources screen: Installed Sources, Official Source Registry and Install from file; Registry states Installed / Install / Update / Review update / Disabled · Update available / newer installed (no downgrade) / Requires a newer OneShelf; a review showing name, publisher, version, trust, capabilities, permissions with new ones marked, domains and packaged-test result before any install; the install bound to the reviewed sha256; a calm degraded state; English and Arabic | `frontend/src/features/sources/RegistryPanel.tsx`, `SourcesScreen.tsx`, `api/sources.py` (`GET /api/registry`, `POST /api/registry/review-package`, `POST /api/registry/install`) | `RegistryPanel.test.tsx` (12), `SourcesScreen.test.tsx` (13), `test_registry_api.py` (15, including remote-without-passkey 401 and cross-origin 403); sha binding and no-downgrade checked by mutation, both caught. Live 2026-09-21 in Chromium against the real app and the GitHub Registry: 8 cards, 7 Installed, removed Tapas *Not installed* → review (3 packaged tests passed) → installed; English and Arabic (RTL) screenshots in `docs/c9/`. The live check found one defect (a removed source still listed as installed, untranslated) — fixed with a regression test | VERIFIED |
| REL-14 | Official trust only through Ed25519 signatures from locally configured public keys (multiple, for rotation); index labels and keys never trusted; unsigned/unknown → Community, bad signature → refused; the private key never in Git, the image, `.env.example`, the frontend, tests or fixtures; signing takes an externally supplied key | `oneshelf/plugins/manager.py::_verified_label`, `registry.py::parse_trusted_keys`, `plugins/registry_tool.py` (refuses a key inside the work tree), `.gitignore`/`.dockerignore` (`*.pem`, `*.key`, `*.p8`) | **IMPLEMENTED — BLOCKED ON OWNER SIGNING KEY.** Trust cases in `test_registry_lifecycle.py`; signing with a runtime-generated TEST-ONLY key, env-var key file, wrong key, `--require-signed`, in-repo key refusal and public-key output in `test_registry_tool.py`; `test_no_private_key_ships.py` scans every tracked file for private-key material (checked by a planted marker, caught). No production key exists, so none was generated, and the published Registry is **unsigned**: live, its entries read `effective_trust = community` and a reinstalled source is recorded as Community. Unblocked by the owner running the process in `docs/plugins.md` §7. **2026-09-21:** the owner reported signing the Core Registry, but the public key line was not supplied and `registry/index.json` holds 0 signatures; the Registry has since moved to OneShelf-Adapters, where signed publication is REL-24 **Superseded 2026-09-21 by explicit owner decision (REL-26):** production signatures are no longer required; the first-party Registry is trusted by its repository-controlled tiers. Ed25519 support remains, and is tested, as optional stronger evidence. Cryptographic signing was never verified in production and is not marked so | SUPERSEDED |
| REL-15 | Bundled and Registry are two delivery paths into one lifecycle per plugin id: no duplicate identities; an explicit Registry action transfers ownership (`channel = registry`) persistently, also while an update waits for review; the bundled bootstrap never reclaims or downgrades it; removed sources are never reinstalled automatically; reading the Registry or updating never enables a disabled source; new permissions always need review; library data survives | `manager.py` (`install_from_registry`, `_record`, `install_state`, `review_from_registry`), `bundled.py::_maintain` | `test_registry_lifecycle.py` (47) and `test_registry_api.py`: removed bundled source reinstalled as the same plugin, no bundled downgrade after restart, pending-review ownership claim, disabled preserved through Registry update / approve / upload, installed-newer, rollback, pending update approved from its review bound to its bytes; four guards checked by mutation. Live 2026-09-21 (real process, GitHub Registry): Tapas removed → *available* → reviewed → wrong sha refused (422) → installed as `registry`; WEBTOON disabled and left disabled by listing; after restart Tapas still `registry`/active, WEBTOON disabled, 8 rows, readiness true | VERIFIED |
| REL-16 | A public, independent adapter repository `IPurplel/OneShelf-Adapters`: canonical home of adapter sources, contribution guide, trust tiers, review/deprecation/publishing policy, security policy, templates — no licence or contribution terms chosen for the owner | OneShelf-Adapters `README.md`, `CONTRIBUTING.md`, `SECURITY.md`, `docs/`, `adapters/{official,verified-community,community}/`, `templates/basic-source/` | Created public 2026-09-21 via the GitHub API; `main` and `registry` pushed, remote refs verified. Repository policy tests (31) pass locally and in CI. Legal terms recorded as undecided (`docs/legal-status.md`, REL-25) | VERIFIED |
| REL-17 | Contributor workflow and CI: `bootstrap`, `new-adapter`, `check-adapter`, `check-all`, `fetch-baseline`, `publish-registry`; PR and issue templates; CODEOWNERS on every security-sensitive path; unprivileged fork-safe validation (`pull_request`, `contents: read`, no secrets, no persisted credentials, no signing), advisory latest-Core check, manual live check | OneShelf-Adapters `tools/`, `.github/` | `test_repository.py`: no `pull_request_target`, read-only defaults, no secrets or signing in workflows, CODEOWNERS coverage, `new-adapter` output passes the checks and bad input is refused. **Validate adapters** green on GitHub for `0aa48e9`, `a67bc8a`; advisory workflow dispatched and green. Found and fixed: a fork commit could be pinned as tooling (CI now requires the pin on OneShelf `main`); `pip` silently kept stale tooling (bootstrap now proves the installed commit). Ruleset (no force push/deletion on `main`, `registry`), read-only workflow token and secret scanning with push protection configured via the API. A pull request from an outside account has not been exercised | VERIFIED |
| REL-18 | The eight Official adapters migrated to OneShelf-Adapters with the same ids, versions, recipes, fixtures and permissions, and no unexplained package drift | OneShelf-Adapters `adapters/official/` | Built old Core and new repository sources side by side: all eight byte-identical. `check-all` passes all eight. One explained repackaging followed (REL-20) | VERIFIED |
| REL-19 | Core keeps an offline release snapshot of the allowlisted Official adapters, synced (never hand-edited) with provenance; Registry-only adapters stay out; first run never contacts GitHub | `backend/plugins/sync_snapshot.py`, `backend/plugins/official/UPSTREAM.json`, `oneshelf/plugins/bundled.py` | `test_sync_snapshot.py` (16): copies the eight and records repository/commit/path/allowlist deterministically; refuses a missing, non-Official or duplicate id, symlinks, failing packaged tests and uncommitted upstream changes, changing nothing on failure; removes adapters no longer allowlisted, leaves non-adapter files; Registry-only adapters not copied. Two guards checked by mutation. Real sync from `OneShelf-Adapters@c09ef03` then `@0aa48e9` changed no adapter file. Fresh-install-offline: `test_when_the_registry_is_unreachable_everything_else_still_works` and the live outage run | VERIFIED |
| REL-20 | OneShelf-Adapters publishes a deterministic, reproducible `oneshelf.registry/1` Registry on its `registry` branch, built from accepted sources with trust from the tier, verified before publication, reachable over HTTPS | `oneshelf.plugins.adapter_repo` (`build-registry`, `verify-registry`, `reproducible`), OneShelf-Adapters `tools/publish-registry`, `registry` branch | `test_adapter_repo.py` (49). Published `00873a9`, re-published `a97e5a6`; read over HTTPS through Core's own client and egress policy: 8 entries, every sha verified. **Found by the new CI:** the canonical builder deflated, and zlib vs zlib-ng made packages platform-specific; it now stores entries with fixed headers, and CI rebuilds every published version on GitHub's runner to the exact published bytes (`a67bc8a`: "every published version rebuilds to its published bytes"). The one-time repackaging kept every file identical and is documented | VERIFIED |
| REL-21 | Core's default Registry is OneShelf-Adapters; the exact historical default keeps working without editing `.env`; custom, empty and unset values untouched; the old Core Registry frozen and deprecated | `deploy/compose.yaml`, `.env.example`, `deploy/container_start.py::alias_registry_url`, `registry/README.md` | `test_registry_defaults.py` (16), `test_update_leaves_an_env_with_the_historical_registry_url_byte_for_byte`. The alias lives in deployment because INV-29 forbids an endpoint in the application (the first attempt put one there; the standing guard caught it). Live 2026-09-21: the real app started through `container_start.py` with the old URL read the new Registry; all eight Installed; Standard Ebooks removed → available → reviewed (4 packaged tests) → wrong sha 422 → installed as `registry`; MangaDex disabled stayed disabled; after restart the same; an unreachable Registry gave 502 with readiness true | VERIFIED |
| REL-22 | Mixed trust end to end: Official / Verified Community / Community from the tier; signatures required for signed tiers at publication (made optional by REL-26); OneShelf grants a level only from a trusted key's valid signature; the UI shows each entry's own level and keeps trust apart from delivery channel; 'Source Registry', not 'Official' | `adapter_repo` signing policy, `manager._verified_label`, `RegistryPanel.tsx`, `SourcesScreen.tsx`, `strings.ts` | `test_adapter_repo.py`: labels from tier, Official/Verified publication without a key fails, Community needs none, a community entry relabelled official fails verification, a core install gets trust from the signature alone. `test_registry_api.py`: a Registry-only adapter installs with no Core change; the same signed Registry reads Official/Verified with the key and Community without it; an unsigned preview never reads Official. `RegistryPanel.test.tsx` (14), `SourcesScreen.test.tsx` (14). Live screenshot of 'Source Registry' against the published Registry (`docs/c9/`) | VERIFIED |
| REL-23 | Cross-repository compatibility: OneShelf-Adapters validates with a pinned Core revision (no copied validators, no submodule), a CI contract check against Core's Registry parser, and an advisory latest-main check | OneShelf-Adapters `tooling/oneshelf-core-ref.txt`, `tools/check-all`, `.github/workflows/{validate,core-latest}.yml` | Every CI run installs the pinned Core from GitHub, runs every adapter through it, builds a Registry and verifies it with Core's parser, checks immutability and reproducibility against the published Registry. Pin moved `8a5805f` → `5e01f28` → `afff652`, each in its own commit. Core side: `test_registry_api.py` consumes a Registry built by `adapter_repo` through the running application | VERIFIED |
| REL-24 | Signed publication of Official and Verified Community entries in the OneShelf-Adapters Registry, with the public key configured in OneShelf and in `registry-trust/trusted-keys.txt`; the private key never in either repository, CI, artifacts or logs | `adapter_repo` (`build-registry --signing-key`, key refused inside any Git work tree), `tools/publish-registry`, `registry-trust/trusted-keys.txt`, `ONESHELF_REGISTRY_TRUSTED_KEYS` | **IMPLEMENTED — BLOCKED ON OWNER SIGNING KEY.** Signing, verification and refusal paths tested with TEST-ONLY keys; no private key tracked in either repository (policy tests, secret scanning). The published Registry is an explicit unsigned preview. Unblocked by the owner creating the key and running `./tools/publish-registry --signing-key … --key-id …` (OneShelf-Adapters `docs/publishing.md`) and supplying the public line **Superseded 2026-09-21 by explicit owner decision (REL-26):** signing is optional for the first-party Registry; `build-registry --require-signing` keeps the stricter policy available. Production signing is not claimed as verified and is no longer a release blocker | SUPERSEDED |
| REL-25 | Licence and contribution terms for OneShelf-Adapters (licence, DCO/CLA or similar) | OneShelf-Adapters `docs/legal-status.md` | Owner decision, not taken on the owner's behalf; recorded as UD-5 alongside UD-4 for Core. Technical contribution infrastructure exists; the project does not rely on third-party contributions as redistributable assets until decided | BLOCKED |
| REL-26 | Repository-governed first-party trust (owner decision, 2026-09-21): only when `ONESHELF_REGISTRY_URL` exactly equals the locally configured `ONESHELF_FIRST_PARTY_REGISTRY_URL` (default `https://raw.githubusercontent.com/IPurplel/OneShelf-Adapters/registry/index.json`) do its `official`/`verified_community` tiers become Official/Verified Community without a signature; any other Registry's claims stay Community unless a trusted key signs them; an empty setting trusts no Registry by its tiers; valid signatures remain stronger evidence (shown as Signed), invalid trusted-key signatures are refused; hashes, HTTPS/egress, review and permissions unchanged | `manager._trust` (label + basis), `PluginManager(first_party_registry=…)`, `AppConfig.first_party_registry_url`, `api/sources.py` (`trust_basis`), `RegistryPanel.tsx`, `deploy/compose.yaml`, `.env.example`, `adapter_repo --require-signing` | `test_first_party_trust.py` (15) covering the owner's ten cases; `test_registry_defaults.py`; `RegistryPanel.test.tsx` (Signed only for a verified signature, also in the review). Both guards checked by mutation (first-party location check; invalid-signature refusal). Live 2026-09-21 through `container_start.py` against GitHub: the first-party Registry reads Official by `first_party`, unsigned, and Gutenberg installs as Official after review (wrong sha 422); an old `.env` with the legacy URL lands on the first-party Registry; a different real HTTPS Registry claiming `official` reads and installs as Community | VERIFIED |
