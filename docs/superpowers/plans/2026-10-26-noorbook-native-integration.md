# Noor Book native reader — approved implementation addendum

2026-10-26. Supersedes the transport-blocked state in the 2026-10-24 plan.

## Evidence and ownership

The same unchanged Core EgressProxy failed without ECH and returned HTTP 200 with an explicit public HTTPS-record ECH configuration. Normal Core headless Chromium routed through that transport opened Read successfully. Scrapling parsed all 111/309 ordered slots on two books. Cookie-free boundary resources 1/100/101/111 returned SVG and normalized successfully; 100/101 are actual chapter/blank pages, not a challenge. These are local prototype observations, not deployed OneShelf support.

Claude Code approved the native official exception and expressly delegated implementation to Codex on 2026-10-25. Its follow-up corrected the initial suggestion to bypass EgressProxy: retain the proven CONNECT tunnel and all existing DNS/address policy. Reviews and sensitive captures remain ignored under qa-artifacts/noorbook-2026-10-25.

## Contract

- `net/ech.py`: fixed Noor HTTPS host; fixed dns.google HTTPS-record resolver via existing HttpClient. Validate DNS status/question/answer/type/config/TTL. One bounded in-memory config, no disk/session state. curl_cffi 0.16.3, TLS verification, trust_env=False, manual policy-checked redirects, no auto cookies, decoded-byte cap during receipt, total deadline and cancellation cleanup. Every source request uses unchanged EgressProxy. No cleartext fallback, arbitrary proxy/resolver, or direct network path. ECH is experimental upstream; availability is not guaranteed.
- `plugins/native/noorbook.py`: fixed reviewed provider, Scrapling metadata parsing, one stable book-hash/copy-zero unit, fresh normal Core browser for Read, all source traffic routed through ECH. Ignore ads/other domains. Source scripts execute in the ordinary browser; only fixed Core state extraction and group requests. Source-issued CSRF values never enter persistent configuration or logs.
- Read all file_num=1 groups; validate contiguous bounded ranges, every slot identity and number, total count, and source-populated image URL pattern. Produce complete ListResult[ResourceDescriptor] only after every group succeeds. Max 1000 pages, 20 groups, 30 seconds/group, 300 seconds/reader. NoRead/preview/auth/challenge/rate failure is explicit, never a successful empty or partial book.
- API1.3 `native_profile: noorbook` only for oneshelf.noorbook, exact source host, work/catalog/reader only, browser reader, no auth or recipes. Visible native and fixed-resolver permissions. No executable plugin code or general browser action language.
- SourceService native dispatch preserves health, availability, governor, cancellation and ReaderService cache/expiry behavior. Manifest capabilities drive native discovery and URL preview. Normal recipes unchanged. Browser lease plus HTTP leases must not deadlock: the fixed profile requires at least two source slots, leaving one for child HTTP requests.
- Bundled native package and offline fixture tests; no search/download claim. Install into existing library through normal source installation/update review, without resetting bootstrap or re-enabling disabled sources. Existing adapter repository inclusion remains authorized.

## Execution checklist

- [ ] Red/green transport tests: allowlist, proxy isolation, redirects, bounded decoded body, cookies, cancellation, ECH validation/refresh. Pin dependency.
- [ ] Red/green native parsing and complete-reader tests: 111/309, wrong identity, missing/repeated groups, cap, noRead, stable unit, invalid URLs.
- [ ] Red/green schema/packaged tests and source lifecycle/URL dispatch. Bundle only proven capabilities.
- [ ] Real local OneShelf URL import/read, pages1/100/101/111, cache/resume; second title. Isolated data only. Inspect screenshot/console/network desktop/mobile.
- [ ] Full backend checks, relevant frontend checks, fresh review, commit/push and verify remote SHA.
- [ ] READY — AWAITING USER-MANAGED DEPLOYMENT; no agent deployment. After user confirms, inspect real LAN app through project Chrome Playwright, recording checkout/image provenance separately. Goal remains incomplete until actual integration is verified.


## Browser QA follow-up, 2026-10-27

Actual local Chrome opened the supplied book through Search URL preview, Work Details and Reader (111 slots). Pages1/111 displayed. Some other pages failed unsupported SVG style: source uses static stroke-linecap, stroke-linejoin and stroke-miterlimit already allowed as attributes. Expired source URLs return small HTML200 loading_read messages. Slot count is not proof of complete rendering.

Claude backend owner approved the follow-up contract in ignored qa-artifacts/noorbook-2026-10-25/claude-render-followup-review.txt: add only those static stroke style values; detect exact source expiry in native resource retrieval and trigger existing descriptor renewal; expose additive tracks[].can_download from SourceService.supports_download, suppress unsupported permanent downloads at enqueue/auto-download/UI. Codex implements this scoped repair and frontend link entry. No new Noor search/download capability. The review's estimate that110pages fail was unverified and is not adopted.


## Renewal review, 2026-10-28

Claude Code approved and delegated the reproduced concurrent-expiry repair in reader/service.py and its integration tests (ignored claude-renewal-review.txt). Serialize descriptor loads per unit with waiter-counted, cancellation-safe gates; use descriptor-list object identity to reuse a newer generation for late failures, including unchanged URLs. Preserve source checks under the gate and the existing one-retry rule. Cold simultaneous requests coalesce too. No schema/cache-key change. A previously cached page under an older URL can still become unreachable after a later renewal; this pre-existing cache-identity limitation is outside this scoped concurrency repair. The earlier live409 episode remains unexplained; do not attribute it to fan-out without evidence.


2026-10-28 SVG follow-up: observed English pages155–309 use612pt×792pt, equivalent to816px×1056px. Claude owner approved narrow decimal pt conversion96/72 and rewriting root dimensions to px before rendering; output/memory limits unchanged. Synthetic red/green tests cover equivalent output and refusal of oversized/relative/nonfinite dimensions. Authority: https://www.w3.org/TR/css-values-3/#absolute-lengths . Review stored ignored as claude-svg-pt-review.txt.


## Public-page refusal contract, 2026-10-28

The same live page150 URL and same client failed then succeeded352s later without descriptor renewal. The site's expiry notice can represent a temporary refusal; cause/rate threshold is unproven. Claude approved dedicated PublicReaderExpired, one existing renewal, then bounded120s per-unit refusal state if a fresh public link is also refused or renewal fails. Cached pages remain readable; late queued failures cannot start repeated browser flows. Ordinary authentication remains409. API contract:503 SOURCE_TEMPORARILY_UNAVAILABLE with Retry-After seconds and no-store; no account action, automatic retry loop or governor-wide cooldown. Existing image failure UI remains recoverable with Try again; network diagnostics now distinguish temporary source refusal. Rate remains120rpm pending actual browser request-count measurement. Owner approval: ignored claude-refusal-corrected-review.txt; the earlier claude-refusal-contract-review.txt inspected the wrong checkout and is not an authority for this change.


## Final refusal verification and measured request rate

The cooldown also guards initial descriptor loads after TTL expiry or in-memory eviction; held or persisted descriptors keep cached pages readable without a source call. Both regressions passed after reproducing failures. Frontend prefetch respects numeric Retry-After and resumes only on later reader activity. Online-only tracks hide download repair as well as the download shortcut/menu.

The owner measurement condition is fulfilled: at30rpm the supplied Arabic book completed its Read flow in22.009s (12requests including2metadata requests,2groups,111pages); the English title completed in26.032s (14requests including2metadata requests,4groups,309pages). Page resources loaded after the browser context closed. Both stay within60s navigation/300s total limits. The package now uses30rpm with concurrency2. This is a measured pressure reduction, not proof of the site's refusal threshold or guaranteed availability.

Read-only follow-up review found no concrete blocker in these final changes. Full frontend suite:485passed across41files; production build passed with the existing large-chunk advisory. Backend full-suite baseline failures remain separately recorded; no claim of a green full suite or production verification.

## Baseline repair and final local verification, 2026-10-29

The user chose to repair the four pre-existing failures before merge. Claude approved the scoped backend contract in ignored claude-baseline-repair-review.txt. Backup classification and Replace/Merge restore now preserve private tags, collection memberships, notes and ratings, including case-insensitive tag remapping. The exclusion guard permits only the exact private rating title; public review prompts remain forbidden. The migration test targets migration 0021, and the literal shelf batch route precedes the dynamic work route.

A separate long-strip regression reproduced page drift as image heights changed. Instant jumps and preserving the visible page offset prevent it. A real Chromium fixture with309pages stayed on155 on desktop and mobile without progress writes; actual Noor pages154-156 rendered, and155 remained selected after resize. Latest local browser session: no console errors or failed network requests.

Final local checks:1767backend tests passed,1skipped because shellcheck is unavailable;486frontend tests passed across41files; frontend production build passed (existing chunk-size advisory). Backend tests ran from a clean Linux snapshot of7029387 plus the exact current source overlay. These results do not establish a production deployment. Adapter registry publication, remote integration and user-managed deployment verification remain separate gates.
