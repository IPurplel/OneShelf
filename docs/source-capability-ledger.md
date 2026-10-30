# Source Capability Evidence Ledger

Recorded: 2026-09-18 · **Revised: 2026-09-21** · Authority: Meta Prompt §D3, Master §41 · Environment: this development host, direct outbound HTTPS

**States:** `verified` / **Confirmed** (exercised against the live source through the OneShelf runtime, and where
content is involved the bytes were opened) · `unverified` / **Probable** (plausible from the markup but not
exercised) · **Unknown** (not investigated) · `unavailable` (the source cannot be reached from here) ·
`unsupported` (deliberately not provided, with the reason).

A capability is never Confirmed because a page loaded or a request returned 200.

Nothing in this table is inferred from a homepage loading or a 200 response. "Verified" means the capability
ran through the OneShelf runtime and, where content is involved, the bytes were opened and parsed.

Live checks are opt-in: `ONESHELF_LIVE_SOURCES=1 .venv/bin/pytest tests/live -m live` (8 passed, 2026-09-21).
The default suite never touches the network: each shipped package carries its own fixtures captured from
these same responses, and its packaged tests run offline.

## 1. Shipped packages

| Source | Package | search | work | catalog | reader / downloads | Evidence |
|---|---|---|---|---|---|---|---|
| MangaDex | `oneshelf.mangadex` | verified | verified | verified | reader: verified (at-home server) | `api.mangadex.org` JSON API; live search and work on 2026-09-18; packaged fixtures captured from the same responses. Chapter pages are composed from `baseUrl` + hash + filename with a declarative template. |
| Project Gutenberg | `oneshelf.gutenberg` | verified | verified | verified (one unit per book) | downloads: **verified — EPUB opened** | Gutendex API for the catalogue, `www.gutenberg.org` for files. The live test opens the EPUB and finds `META-INF/container.xml`. gutenberg.org's own `/ebooks/search` is disallowed by its robots.txt, which is why the API is used. |
| arXiv | `oneshelf.arxiv` | verified | verified | verified (one unit per paper) | downloads: **verified — PDF header checked** | `export.arxiv.org` Atom API; the live test fetches the PDF and asserts `%PDF-`. |
| Standard Ebooks | `oneshelf.standard-ebooks` | verified | verified | verified | downloads: **verified — EPUB opened** | OPDS feeds. One work, several formats: the package exposes EPUB, and the feed's other acquisition links stay formats of the same Work rather than separate Works (§41.3 format stress). |
| WEBTOON | `oneshelf.webtoon` | **unsupported (robots)** | verified | verified | reader: **verified — images fetched and packaged** | `webtoons.com/robots.txt` disallows `/*/search` for every agent, so search is not implemented. Episodes come from WEBTOON's own episode API (`m.webtoons.com/api/v1/webtoon/{titleNo}/episodes`), in reading order with a numeric cursor — the HTML list page cannot paginate (I-21). **The viewer needs no browser:** it carries every image as `data-url` on `img._images` and its script only moves that into `src` on scroll. Its CDN refuses an image without a `Referer`, which the recipe declares. Live 2026-09-20: >300 episodes complete and correctly numbered (I-22), three real images fetched, validated by the download path's own checks and packaged into a CBZ the integrity validator accepts. |
| Tapas | `oneshelf.tapas` | **unsupported (robots)** | verified | verified | reader: **verified — image validated** | `tapas.io/robots.txt` disallows `/search` for every agent. The episode list is the site's own XHR, which answers with its list markup inside a JSON envelope (`response.markup_at`), and an episode carries its images as `data-src` before any script runs — so neither needed a browser. Live 2026-09-20: 721 episodes paginated to completion in the source's own order and numbering, and an episode image passed the download path's validator. Episodes a series does not offer anonymously are simply not listed; nothing attempts to reach them. |
| Safahat (Hindawi) | `oneshelf.hindawi` | verified | verified | verified (one unit per book) | downloads: **verified — EPUB opened** | **A5 settled:** `www.hindawi.org` redirects to `www.safahat.org`, which is the canonical domain; the files are served from `downloads.hindawi.org`. Everything is markup: search results, the book page with its author and synopsis, and direct EPUB and PDF links. The search form POSTs but redirects to a canonical GET address, which is the one the recipe asks for. Live 2026-09-20: five results with authors, both formats, and a 2.3 MB EPUB opened as an EPUB. |
| 3asq (Al-Aasheq) | `oneshelf.3asq` | verified | verified | verified | reader: **verified — pages validated and packaged** | **At `3asq.online`.** WordPress/Madara, in Arabic. The chapter list is not in the series page: the site fetches it from its own endpoint under the same series path, which robots.txt allows, so that is the request the adapter makes. Chapter images are plain `src` on the page. `latest` is also offered. Live 2026-09-21: 21 search results complete with no issues, 567 chapters of One Piece in reading order, 23 images in a chapter, 104 latest entries, and three real pages through the download path's validators into a CBZ the integrity validator accepts. Per §41.4 a public catalogue and parser stress source, never an assumed official or licensed default. |
## 1a. Correction to the 2026-09-18 record

Three capabilities were recorded then as needing browser escalation. All three were wrong, and none of
them needed a browser:

- **The WEBTOON viewer** was said to "build the page images with JavaScript". It does not: every image
  URL is in the HTML as `data-url`, and the script only moves it into `src` while scrolling.
- **Tapas** was said to keep "its episode data in script state". It does not: the episode list is the
  site's own XHR, which answers with the list as markup inside a JSON envelope.
- **Hindawi book pages** were said to "render their content with JavaScript", on the evidence that
  `/books/34691082/` carried no title or file links. That id does not exist — the URL redirects to the
  site's not-found page, which is what was being read. A real book page serves its title, author,
  synopsis and both file links as markup.

The lesson recorded here rather than quietly fixed: *a page that renders nothing is not evidence that
the page renders with JavaScript.* Check a document that exists before concluding anything about how a
site is built.

## 1b. The four sources completed on 2026-09-20 and 2026-09-21, capability by capability

Each capability is stated on its own, in the vocabulary above. Nothing here is Confirmed because a page
loaded: every Confirmed line names a live check that ran through the OneShelf runtime.

| Capability | WEBTOON | Tapas | Safahat (Hindawi) | 3asq (Al-Aasheq) |
|---|---|---|---|
| Search | **Unsupported** — robots.txt disallows `/*/search` for every agent | **Unsupported** — robots.txt disallows `/search` for every agent | **Confirmed** — five results with titles, ids and authors | **Confirmed** — 21 results, complete, no issues |
| Work Details | **Confirmed** — title and cover | **Confirmed** — title, cover and synopsis from `/info` | **Confirmed** — title, author, cover and synopsis | **Confirmed** — title, cover and description |
| Catalog / Reading Units | **Confirmed** — >300 episodes, complete, in the source's own order and numbering | **Confirmed** — 721 episodes paginated to completion | **Confirmed** — one book, one Reading Unit (`one_shot`) | **Confirmed** — 567 chapters, complete, oldest first |
| Reader resources | **Confirmed** — images extracted and fetched | **Confirmed** — images extracted and fetched | **Unsupported** — a book is a file, read by OneShelf's own document reader | **Confirmed** — 23 images in a chapter |
| Download resources | **Confirmed** — three images validated by the download path's own checks and packaged into a CBZ the integrity validator accepts | **Confirmed** — an episode image passed the same validator | **Confirmed** — EPUB and PDF offered; a 2.3 MB EPUB opened as an EPUB | **Confirmed** — three pages (one of 4.9 MB) validated and packaged the same way |
| Latest | **Unknown** — not investigated, and not required by §41 | **Unknown** — not investigated | **Unknown** — not investigated | **Confirmed** — 104 entries; a bounded window, so it reports itself incomplete rather than claiming the whole archive |
| Auth / session | Not applicable — nothing here is behind a login, and nothing attempts one | Not applicable — episodes a series does not offer anonymously are simply not listed | Not applicable — the library is free to read | Not applicable — no login, no session declared |

Browser escalation was considered for each and used for none, because each was reachable statically or
through the site's own request. No screenshots are taken anywhere, and nothing bypasses a paywall, a
CAPTCHA, DRM, anti-bot measures or an authentication restriction.

## 1c. 3asq: a stale domain, not a missing implementation (2026-09-21)

`3asq.org` was recorded as unreachable on 2026-09-18 and again on 2026-09-20, and both readings were
correct — that host does not resolve. What was wrong was the conclusion drawn from it: the domain had
moved. The current site is **`3asq.online`**, and it answers everything.

An inspection before any code was written found there was nothing to migrate: no package, no manifest,
no allowlist entry, no recipe, no fixture, no live test, and no domain-alias or migration logic
anywhere in the codebase. The source had simply never been built, because it had never been reachable.

**Identity across the move.** Source Tracks are keyed on `source_id`, which is the plugin id, never a
domain. The id is `oneshelf.3asq`, and a test holds it free of any domain, so if this site moves again
the change is one line of configuration and nobody's existing mappings are orphaned.

**Policy.** One permission, `network:domain:3asq.online`. HTTPS only, no CDN wildcard, no session, no
browser. `test_3asq_package.py` checks that the old domain, the old scheme, private addresses and
lookalike hosts such as `3asq.online.evil.test` are all refused.

## 2. Investigated, not shipped

| Source | State | Evidence and what would change it |
|---|---|---|
| OneShelf Test Source | verified (local) | Ships with the repository rather than as an `.osp` in `plugins/official`. It is the deterministic failure source: rate limits, 500s, session expiry, HTML-instead-of-image, corrupt media, interrupted downloads, changed validators, redirects to unapproved domains, incomplete pagination, the 300→7 catalogue collapse. |

## 3. What the shipped packages deliberately do not do

- No stealth, fingerprint evasion, CAPTCHA solving or paywall/DRM circumvention anywhere (Master §12.1, §49). Scrapling is used as a parser; every request goes through the Core HTTP client under an egress policy.
- No crawling of paths a source's robots.txt disallows. Where that removes a capability (WEBTOON and Tapas search), the capability is simply absent and is recorded here.
- No screenshot extraction: a reader capability exists only where the underlying resources are available.
- Rate limits in the shipped packages are conservative (20–60 requests per minute, 1–2 concurrent) and the Traffic Governor applies on top.

## 4. Re-checking

```sh
cd backend
.venv/bin/pytest tests/integration/plugins/test_official_packages.py   # offline: packages valid, fixtures pass
ONESHELF_LIVE_SOURCES=1 .venv/bin/pytest tests/live -m live            # live: real sources, artefacts opened
```

A failure in the live run means the source changed: run the generator's **Repair Existing Adapter** flow against
it (`POST /api/generator/repair/{plugin_id}/diagnose`, then `/repair`), review the selector diff, and activate the
new version only after it validates.
