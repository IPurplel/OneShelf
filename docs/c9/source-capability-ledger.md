# Source Capability Evidence Ledger

Recorded: 2026-09-18 · Authority: Meta Prompt §D3, Master §41 · Environment: this development host, direct outbound HTTPS

**States:** `verified` (exercised against the live source and the artefact opened) · `unverified` (plausible but not exercised) · `unavailable` (the source cannot be reached from here) · `action required` (a decision or work item stands in the way) · `unsupported` (deliberately not provided, with the reason).

Nothing in this table is inferred from a homepage loading or a 200 response. "Verified" means the capability
ran through the OneShelf runtime and, where content is involved, the bytes were opened and parsed.

Live checks are opt-in: `ONESHELF_LIVE_SOURCES=1 .venv/bin/pytest tests/live -m live` (4 passed, 2026-09-18).
The default suite never touches the network: each shipped package carries its own fixtures captured from
these same responses, and its packaged tests run offline.

## 1. Shipped packages

| Source | Package | search | work | catalog | reader / downloads | Evidence |
|---|---|---|---|---|---|---|
| MangaDex | `oneshelf.mangadex` | verified | verified | verified | reader: verified (at-home server) | `api.mangadex.org` JSON API; live search and work on 2026-09-18; packaged fixtures captured from the same responses. Chapter pages are composed from `baseUrl` + hash + filename with a declarative template. |
| Project Gutenberg | `oneshelf.gutenberg` | verified | verified | verified (one unit per book) | downloads: **verified — EPUB opened** | Gutendex API for the catalogue, `www.gutenberg.org` for files. The live test opens the EPUB and finds `META-INF/container.xml`. gutenberg.org's own `/ebooks/search` is disallowed by its robots.txt, which is why the API is used. |
| arXiv | `oneshelf.arxiv` | verified | verified | verified (one unit per paper) | downloads: **verified — PDF header checked** | `export.arxiv.org` Atom API; the live test fetches the PDF and asserts `%PDF-`. |
| Standard Ebooks | `oneshelf.standard-ebooks` | verified | verified | verified | downloads: **verified — EPUB opened** | OPDS feeds. One work, several formats: the package exposes EPUB, and the feed's other acquisition links stay formats of the same Work rather than separate Works (§41.3 format stress). |
| WEBTOON | `oneshelf.webtoon` | **unsupported (robots)** | verified | verified | reader: **action required** | `webtoons.com/robots.txt` disallows `/*/search` for every crawler, so search is not implemented. Works and episode lists are reached by title number (`/episodeList?titleNo=…`). The viewer ships only thumbnails in its HTML and builds the page images with JavaScript, so reader pages need browser escalation before they can be offered. |

## 2. Investigated, not shipped

| Source | State | Evidence and what would change it |
|---|---|---|
| Tapas | action required | `tapas.io/robots.txt` allows `/series/` and `/episode/` but disallows `/search` for `*`, so the shape would match WEBTOON: direct-URL works plus an episode list. The series page embeds its episode data in script state rather than in list markup, so it needs either the underlying XHR or browser escalation. Not shipped rather than guessed. |
| Safahat / Hindawi | action required | **A5 is resolved:** `www.hindawi.org/robots.txt` points its sitemap at `https://www.safahat.org/sitemap.xml`, and both hosts serve the Hindawi Foundation library, so **safahat.org is the canonical domain**. Book pages render their content with JavaScript: the static HTML of `/books/34691082/` carries no title, EPUB or PDF links. A browser-escalated or API-based adapter is needed. |
| 3asq / Al-Aasheq | **unavailable** | `3asq.org` does not resolve from this environment (`Name or service not known`, 2026-09-18), so no capability could be exercised. Nothing about it is claimed. Per §41.4 it is a public catalogue/parser stress source, never an assumed official or licensed default. |
| OneShelf Test Source | verified (local) | Ships with the repository rather than as an `.osp` in `plugins/official`. It is the deterministic failure source: rate limits, 500s, session expiry, HTML-instead-of-image, corrupt media, interrupted downloads, changed validators, redirects to unapproved domains, incomplete pagination, the 300→7 catalogue collapse. |

## 3. What the shipped packages deliberately do not do

- No stealth, fingerprint evasion, CAPTCHA solving or paywall/DRM circumvention anywhere (Master §12.1, §49). Scrapling is used as a parser; every request goes through the Core HTTP client under an egress policy.
- No crawling of paths a source's robots.txt disallows. Where that removes a capability (WEBTOON search), the capability is simply absent and is recorded here.
- No screenshot extraction: a reader capability exists only where the underlying resources are available.
- Rate limits in the shipped packages are conservative (20–60 requests per minute, 1–2 concurrent) and the Traffic Governor applies on top.

## 4. Re-checking

```sh
cd backend
.venv/bin/pytest tests/integration/sources/test_official_packages.py   # offline: packages valid, fixtures pass
ONESHELF_LIVE_SOURCES=1 .venv/bin/pytest tests/live -m live            # live: real sources, artefacts opened
```

A failure in the live run means the source changed: run the generator's **Repair Existing Adapter** flow against
it (`POST /api/generator/repair/{plugin_id}/diagnose`, then `/repair`), review the selector diff, and activate the
new version only after it validates.
