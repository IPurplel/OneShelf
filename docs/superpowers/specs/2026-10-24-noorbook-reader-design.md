# Noor Book reader investigation and proposed design

Date: 2026-10-24. Status: user approved implementation after reviewing the plan. The [backend owner contract](../coordination/2026-10-24-noorbook-backend-review.md) permits independent Core normalization/completeness work. Source integration remains blocked on controlled transport replay; no Noor Book adapter exists yet.

## Intended result

Open a Noor Book title's available **Read** content inside OneShelf, using Scrapling for discovery and parsing, with OneShelf navigation, progress and Reader Cache. The first milestone is opening a supplied book URL. Search, catalog browsing, downloads and registry publication are separate capabilities, not assumed from a successful reader.

Authority: `docs/OneShelf_Final_Implementation_Meta_Prompt.md`, especially §§12, 19, 26–27 and final section G; user-supplied AGENTS ownership and deployment instructions.

## Evidence from the supplied title

Sample: [White Nights / الليالي البيضاء](https://www.noor-book.com/en/ebook-%D8%A7%D9%84%D9%84%D9%8A%D8%A7%D9%84%D9%8A-%D8%A7%D9%84%D8%A8%D9%8A%D8%B6%D8%A7%D8%A1-%D8%AF%D9%88%D8%B3%D8%AA%D9%88%D9%8A%D9%81%D8%B3%D9%83%D9%8A-pdf).

The earlier browser session provided the following evidence, while subsequent fresh sessions and Core transport still failed:

- The in-app browser opened the supplied page. Its metadata says Arabic, PDF, 111 pages, 5.41 MB. These are source claims, not a downloaded PDF inspection.
- Clicking the actual Read control opened `#readModal` on the same page. No sign-in or challenge interaction was needed in this browser session; this does not prove a cookie-free request works.
- The reader displayed groups **1–100** and **101–111**. Selecting the latter changed the page slots to 101–111. Selecting 111 loaded and visibly displayed the last page.
- Observed DOM: `a.read-btn[data-target="#readModal"]`; `.pages_from_to` attributes `start`, `end`, `file_num`; `.page_img` attributes `page_number`, `has_image`; loaded page `img[src]` elements.
- Source page images use same-origin `/book/read_book_image/.../<page-number>/...svg` URLs. Identifiers are opaque and must be discovered anew, not copied from this session or guessed.
- Exported page 111 was **503,115 bytes**, `image/svg+xml`, SVG dimensions 485.12 × 736.64, viewBox `0 0 363.84 552.48`. It contains an embedded JPEG plus paths, symbols, clipping and text-shaped vector uses. Extracting only the JPEG can lose displayed content.
- Scrapling parsed a saved fragment of this live DOM: both page groups, 11 ordered slots in the last group, **8 populated image URLs**, and the page-111 URL. This directly demonstrates that visible/lazy-loaded image URLs alone are incomplete.
- Asset inventory observed `/en/book/read_book` and `/en/book/read_modal_load_pages_from_to` resources. Request methods, bodies, response schema, token lifecycle and Core replay remain **unverified**. Observing a URL is not a reproducible extraction contract.
- Direct requests through Core `HttpClient` failed with connection errors before HTML could be parsed, on Windows and Ubuntu. The supplied book request also failed on Windows. Browser success does not establish Core transport success.

The earlier web text fetch was a cached snapshot. The findings above are from actual interaction, DOM inspection and a source asset. Only one title was inspected; all 111 page bodies were not fetched or checked.

## Existing OneShelf constraints

| Area | Verified behavior / consequence |
| --- | --- |
| `backend/oneshelf/plugins/runtime.py` | Already uses Scrapling; retain declarative parsing. |
| `backend/oneshelf/plugins/results.py` | `ResourceDescriptor(url, index, page_label, html, title)` represents ordered images or sanitized text. |
| `backend/oneshelf/sources/browser_fetcher.py` | GET navigation and DOM retrieval only; it has no declared click/select workflow. Setting `fetch: browser` alone does not reproduce this investigation. |
| `backend/oneshelf/reader/service.py` | Fetches source resources through Core, validates and caches page bytes. Existing retry can refresh descriptors for expired URLs. |
| `ReaderService._online_descriptors()` / reader pages route | Currently accepts nonempty entries without checking `ListResult.complete`; the route returns a page list without completeness evidence. Adapter evidence alone cannot prevent a partial book from appearing complete. |
| `backend/oneshelf/integrity/validators.py` | Pillow-based `_validate_image` rejects the actual SVG sample with `undecodable image (UnidentifiedImageError)`. An adapter-only change cannot display this sample through the existing path. |
| `backend/oneshelf/api/library.py` | Reader page route serves bytes with content isolation headers. Do not weaken these to admit active SVG. |
| `frontend/src/features/reader/ReadRoute.tsx` | Existing image reader is the intended presentation. Remote PDF reading is not needed for this observed source flow. |

## Recommended design and alternatives

**Recommended:** discover the source's real Read request flow, parse its responses with Scrapling, and produce a complete ordered image descriptor list. Core retrieves original SVG resources, validates them and converts an approved safe subset to raster page bytes in an isolated, bounded process. Cache the derived pages temporarily and use the existing image reader. The conversion operates on the source document, not browser screenshots. Preserve provenance and avoid changing the original source asset into a permanent Download automatically.

**Alternative:** serve sanitized SVG as an image through an explicitly isolated content route. This preserves vector zoom, but expands SVG sanitization, MIME and browser isolation responsibilities. It is a separate Core design decision requiring owner review and hostile-input tests; do not simply bypass `_validate_image`.

Embedding the entire Noor website does not provide OneShelf page descriptors, cache or progress. Extracting only an embedded JPEG can omit SVG overlays. A PDF download is a different source capability and is not the requested first milestone.

## Written ownership handoff (proposal, not approval)

Claude Code owns the adapter, transport, integrity and Reader Core implementation. Codex owns any needed frontend states and rendered verification. This document records the required boundary; it does not imply Claude has reviewed or approved it and no message has been sent to another chat.

Required contract:

1. One source listing produces one book Reading Unit; pages and 100-page display groups are not chapters or separate Works. Preserve source identity and language without auto-merging editions from metadata alone.
2. Reader extraction returns ordered, one-based `ResourceDescriptor` entries with original source page labels and explicit completeness evidence. Session-specific URL tokens never become unit identity.
3. All transport, cookies, redirects, DNS validation, retries, rate limits and cache limits remain Core-owned. Only proven required source/CDN domains are allowed; advertising and analytics are excluded.
4. Core normalizes supported SVG page content into validated raster bytes before returning it through the existing page route. Keep the public reader contract unchanged if this approach is accepted. Exact renderer, dependency/version and resource budgets require a bounded feasibility decision before production code.
5. Loading, incomplete extraction, expired source session, unavailable reader and unsupported format remain distinguishable. For this first milestone, reject an incomplete reader result before caching descriptors or returning a page list; report a clear source extraction failure. Do not introduce partial-book presentation as an implicit frontend feature. Test a second-group failure after the first group returned 100 entries, and compatibility with existing complete sources.
6. Reading alone creates no permanent asset or download job under default settings. Existing explicitly enabled reading-download preferences retain their semantics.

If the real request sequence cannot be expressed in the current declarative recipe language, record **Native Adapter Review Required**. Any bounded Core capability extension needs an explicit owner-reviewed contract; do not embed scripts or implement an unbounded click engine inside a package.

## Acceptance and open gates

- Reproduce Read discovery and page resource fetch through the controlled OneShelf transport, including expiry behavior. The in-app browser investigation is not the production transport.
- Demonstrate complete ordered descriptors for both sample groups, including the 100→101 boundary and page 111; then verify more than one representative title and an unavailable/preview case before claiming source-wide support.
- Use synthetic SVG fixtures for security and rendering tests. Reject external fetches, scripts, event handlers, foreign content, XML entities and resource exhaustion; preserve valid transforms, clipping and overlays. Fail closed on content outside the approved subset.
- Exercise OneShelf page navigation, zoom, RTL controls, resume, cache eviction and interruption with isolated data. No fabricated success or complete state on network failure.
- Search/download support and metadata edition accuracy remain unverified and are outside this first milestone.

## Original investigation evidence

Baseline: branch `main`, commit `8aaff477a334b6851934e9ddbc079d4d46363502`. No application changes, commits or pushes were made for this investigation. Status initially matched the local `origin/main` tracking reference; no new remote verification was performed for this plan.

Other backend edits appeared concurrently during the investigation. They were not made, staged, committed, or tested as part of this task. The two documents and ignored research evidence are this task's deliverables.

Ignored local evidence in `qa-artifacts/noorbook-2026-10-24/`:

- `reader-dom.html`, `parse_reader.py`, `scrapling-result.json`: actual browser DOM and successful Scrapling parse.
- `reader-last-page.png`: visually inspected last page.
- `page-111.svg`, `inspect_svg.py`, `svg-result.json`: source resource and actual Core validation failure.
- `http-probe.log`, `white-nights-probe.log`: transport failures. These logs precede/separately describe the successful browser access.

Browser: in-app browser reached Noor Book; Read, group switch and page 111 were tested in its narrow viewport. Full desktop/mobile QA was not performed. Captured browser warn/error logs were empty at the final check; a complete request-failure/exception audit was unavailable. Project Playwright launch failed (`spawn UNKNOWN`), and Chrome via CUA was unavailable. No OneShelf production browser QA was attempted.

Deployment confirmation: none for this work. Deployment checkout SHA: not inspected. Running image revision: unverified. Production accessibility: not tested in this investigation. Integration gaps confirmed: SVG is rejected by the current image validator, browser retrieval does not provide click/select actions, and descriptor loading discards completeness evidence. No fixes implemented.

## Implementation update — 2026-10-24

The user approved implementation and external Claude Code coordination. The written backend-owner contract authorizes an independent Core milestone while source replay remains blocked. That milestone now includes bounded SVG-to-PNG normalization and rejection of incomplete descriptor lists before caching. The existing image validator, public page headers and frontend remain unchanged.

The saved source page passes the new normalization and existing integrity checks: PNG, 970 × 1474, 2,112,226 bytes. The output was visually inspected, including the vector overlay. Static inline paint declarations are converted to validated presentation attributes and removed before rendering; active/external content remains rejected. This proves rendering of one saved page, not live Noor Book integration.

Current source replay: Core HTTP fails before receiving HTML, and the standard Core browser launches but navigation ends with `net::ERR_CONNECTION_CLOSED`. The project Playwright tool also remains unavailable (`spawn UNKNOWN`). No proven request/body/session contract, second-title test, or full 111-page extraction exists, so no adapter is implemented or advertised. Tasks 1, 3 and source-specific Task 4 remain blocked.

See the execution report for current test results and handoff evidence. No production deployment or production browser verification has been performed.
