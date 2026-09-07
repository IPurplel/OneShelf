# Handoff — manga/comic downloader

Everything a fresh session needs. The "Findings" section is the expensive part:
each line cost a debugging cycle, and re-deriving them is the main risk.

## What this is

Self-hosted downloader with a web UI at `http://127.0.0.1:8080`. Paste a series
URL or search by name; it clears bot checks in a real browser, downloads pages
over parallel HTTP, and writes one lossless CBZ per chapter. Book sites work the
same way — paste a book page and each linked EPUB/PDF/MOBI becomes a selectable
download, stored as the file itself rather than an archive.

```
E:\projects\manga downloader
  app/        adapters/ · session.py · fetcher.py · queue.py · packager.py · main.py
  web/        index.html · app.js · style.css   (no build step)
  tools/      optimize_cbz.py  (standalone; see note below)
  downloads/  the library (~229 Berserk chapters, ~1.6 GB)
```

Run: `./.venv/Scripts/python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8080`
Test: `./.venv/Scripts/python.exe -m pytest -q` → **499 pass**
Lint: `./.venv/Scripts/python.exe -m pyflakes app/ tests/` → clean

**The UI has no test runner.** `web/` is three static files with no build step,
so nothing under `tests/` touches it — it is checked by driving a real browser
with patchright against a server on an isolated `MD_CONFIG_DIR`/`MD_OUTPUT_DIR`
and `MD_DESYNC_PORT=0` (port 8081 is held by the user's own instance). Keep
those scripts in `scratchpad/`, and prefer a real download over a stubbed
`/api/*` route wherever the assertion is about what the *server* did — a stubbed
preview once made "previewing adds nothing to the Library" pass without ever
reaching the database.

The venv installs from `requirements.txt` only; `pytest`/`pyflakes` come from
`requirements-dev.txt` and have to be installed before either command works.

Console output must use `PYTHONIOENCODING=utf-8` or Arabic titles crash cp1252.

## State

| Adapter | Status |
| --- | --- |
| `madara` | **Verified end-to-end.** manga-starz 391 ch, 3asq 68 ch |
| `mangathemesia` | Preview + search only (TS theme; rizzfables) |
| `vcomics` | **Verified end-to-end.** azoramoon c1, 29 pp. Search + locked-chapter handling live-checked |
| `mangadex` | **Verified end-to-end.** Berserk ar: c0.01 47 pp, c1 38 pp, full-size originals, no browser |
| `comix` | Preview 463 ch; never downloaded |
| `blogger` | Preview 21 issues; never downloaded |
| `books` | **Verified end-to-end.** planetebook, 8ghrb, bettergutenberg, arabic-book (URL only). Search live-checked |
| `gutenberg` | **Verified end-to-end.** 77k books; search + one-per-format downloads, Frankenstein EPUB 0.47 MB |
| `generic` | Heuristic fallback |

**Search asks for one kind at a time.** The UI requires Book / Manga / Comics
before the box is usable, `/api/search` requires `?type=` (400 otherwise), and
only sites whose adapter declares that `content_type` are queried at all. Every
adapter declares one — `manga` for mangadex/vcomics/mangathemesia/madara/generic,
`comics` for comix/blogger, `book` for books — and a test fails if a new adapter
forgets, because a missing type makes it unreachable from search.

Configured: 8 manga sites (3asq, manga-starz, arabtoons, azoramoon, mangadex,
mangaread, manhuaplus, rizzfables), 4 book sites (8ghrb, planetebook,
bettergutenberg, gutenberg) and **no comics site** — comix/blogger have no search at all, so the Comics chip
says so rather than looking broken.

**Ranking is ours; matching is still the site's.** These engines match
descriptions and word stems, so their raw answer to `berserk` buries the real
series among things merely containing the letters. `/api/search` scores each hit
with `base.relevance()`, drops what is judged irrelevant, and orders the rest by
band — except across scripts, where an Arabic query legitimately returns a
series shown under a romanised name and text can settle nothing. See Findings.

`mangathemesia`, `comix` and `blogger` are still unproven at the step that
matters: none has produced a CBZ.

## Findings — do not re-derive

**Cloudflare.** patchright's requirement is "Chrome without fingerprint
injection". Passing `viewport`, `locale`, `user_agent` or `ignore_https_errors`
to `launch_persistent_context` applies CDP overrides that are detectable;
`viewport` alone makes `window.outerWidth`/`screen` disagree and damns the
session permanently. Use `no_viewport=True` and nothing else. Tests assert their
absence — do not "tidy" them back. Chromium version matters independently: 131
never passed, 149 passes in ~6s.

**Two network paths, deliberately different.** The desync proxy (TLS handshake
fragmentation, beats the ISP's SNI filter) applies to the **HTTP downloader
only**. The browser has ECH/DoH and reaches sites unaided; routing it through a
fragmented handshake makes Cloudflare re-challenge forever — an unescapable
verify loop. `desync_browser` exists and defaults false.

**Never synthesise a click when a person can make one.** Turnstile marks
programmatic clicks untrusted and loops that session permanently; a real click
afterwards cannot rescue it. Headless (LXC) still clicks — measured, it is the
only thing that ever produced clearance there.

**Browser lifecycle.** A persistent context quits when its last window closes,
and every operation opens/closes a page — so a "keeper" page is held open. A
dead context was previously cached forever; it now self-heals once, except in
attach mode (`browser_cdp`), where relaunching would contradict the config.

**Chapter numbers.** `extract_number` (in `adapters/base.py`): explicit
"Chapter N" → leading number → trailing. Percent-encoded slugs must be decoded
first — `%d8%a7` is hex, so scanning raw slugs reads chapter numbers out of
escape sequences (chapter 372 became chapter 1). Blogger's numbers live in the
link text only; its slugs (`16_16`, `19_02077140790`) are junk.

**Image quality.** WordPress `name-WxH.ext` → `name.ext`; Blogger `/s1600/` →
`/s0/`. The site URL always stays as the last candidate so a failed upgrade
degrades rather than fails.

**Adapters are chosen by DOM fingerprint, not hostname.** That is why 3asq,
arabtoons and rizzfables needed no code. `registry.resolve()` pre-fetches the
page and caches it as `_last_html` — that copy is **unrendered**, so adapters
needing JS content keep their own `_rendered_cache`.

**comix.to** returns `{"e": "<encrypted>"}` from its API and `{"message":
"Missing token."}` without a token; it is read from the rendered DOM instead.
Wait on a *link* selector, never a container — the container ships empty.

**A 403 or 503 is not by itself a bot check.** Image CDNs use both for their own
reasons — a MangaDex@Home node answers 403/503/404 while it pulls the chapter
from upstream. `Fetcher._is_bot_check` decides on evidence instead: the body
carries a Cloudflare marker (`session.is_challenge`), or we already hold cookies
for that host, which only happens once it has challenged us. Anything else is
retried like a 5xx. Treating the status alone as a challenge is what sent a
browser to solve Cloudflare *against an image node*, ten times a chapter.

**Never solve a challenge just to build a request.** `_headers` uses
`sessions.peek_session` (passive) — `get_session` solves when nothing is
cached, so calling it there pointed the browser at every image host a series
touched, and MangaDex hands out a fresh node per chapter. A challenge is
something a *response* tells you about.

**Some page URLs expire.** MangaDex's name one node and carry a short-lived
token, so a failed page means a dead URL, not a missing page. `Adapter.pages_expire`
opts into `refresh_pages`, and the queue re-lists and retries only the casualties,
up to `PAGE_REFRESH_ROUNDS`. Off for everyone else: re-listing a site with stable
paths returns the same dead URL.

**A 200 from `?s=` is not proof that a search happened.** rizzfables keeps the
TS theme's markup but wires its search box to `POST /Index/live_search`
(`search_value=…` → JSON), leaving `?s=` to serve the **homepage**. Its grid
parses perfectly, so every query returned the same seven front-page series —
noise in every multi-site search, and an answer that looks real. The adapter now
detects the marker `Index/live_search` in the page it was given and calls that
endpoint instead. The endpoint returns no URL: links are `/series/<prefix>-<slug>`
with a site-wide prefix scraped from the same markup, and a slug rebuilt exactly
as the site's own script does (`_live_slug`, including its two contraction
fix-ups). Verified live: "leveling" → 1 real hit whose page has 146 chapters.

**Sites match on names you cannot see.** MangaDex indexes every alternative
title, so an Arabic query hits series whose displayed name is romanised —
`الغريب` matches JoJo through `مغامرة جوجو الغريبة`. Showing only the romanised
title makes a correct hit look like the query was ignored, which is exactly how
"search is broken" gets reported. `SearchResult.alt_title` carries the name that
actually matched and the UI shows it under the title.

**azoramoon serves everything, but not as links.** The platform (Astro, marker
`/_vcomics/`, API `PUBLIC_API_URL` → `api.azorafly.com`) server-renders its
hydration state: an `astro-island`'s `props` attribute holds the series record
*and the entire chapter list* — 165 of them on a page that shows 21 anchors.
Counting `<a href*="/chapter-">` finds only the newest twenty, the "more"
control fires no request, and no wait or scroll adds any. Look in the island.
Props are HTML-escaped JSON where every value is wrapped in Astro's
`[type, payload]` pair (0 = value, 1 = array) — decode recursively or the list
reads as pairs. No browser is needed anywhere: series, reader and search are
plain HTTP, which also matters because **the ISP resets connections to this
host** and the browser (no desync by design) cannot reach it at all. Hence
`SessionManager.fetch_text_direct`.

**Chapters can be for sale.** azoramoon sells early access; the chapter record
says `isAccessible: false` and its reader page is replaced by a `lockedChapter`
island. Locked chapters are dropped from the listing, and a locked reader is
reported as locked rather than as a parse failure.

**azoramoon's search only indexes Latin titles — and hides it.** A query it
cannot match is not rejected but *ignored*: `/api/query?searchTerm=الغريب`
answers with the whole 2329-series catalogue, newest first, which is
indistinguishable from real results. `_relevant()` requires every word of the
query to appear in the returned title, turning that back into "nothing found".
The same failure mode as rizzfables, from a different direction.

**The environment did not actually beat `config.yaml`.** This file, the module
docstring, `config.example.yaml` and the README all promised it did. It did not:
`load_settings()` hands the YAML to `Settings(**…)` as keyword arguments, and
pydantic-settings ranks constructor arguments *above* the environment by
default. So `MD_OUTPUT_DIR` worked only for keys the YAML never mentioned. Every
shipped deployment depends on the documented order — `deploy/Dockerfile`,
`docker-compose.yml` and the systemd unit set `MD_OUTPUT_DIR`, `MD_CONFIG_DIR`
and `MD_PORT` while pointing `MD_CONFIG_FILE` at a copy of
`config.example.yaml`, which sets all three itself — so a container would have
written to the path in the file and ignored the volume it was mounted, and
`MD_PORT` would have been dead. Fixed by overriding
`settings_customise_sources` to rank `env_settings` first; `tests/test_config.py`
holds the order. Related to item 5 below: this is the sort of thing that only
surfaces the first time it is deployed.

**A rule that only loses on `:hover` looks like a rule that does not work.**
`button:hover:not(:disabled)` scores (0,2,1); `.tab.is-active` and
`.kind.is-active` score (0,2,0) and `button.primary` only (0,1,1). Source order
cannot save the loser, and the cursor is by definition sitting on the control
that was just clicked — so the selected tab turned grey the instant it was
selected, and **the Fetch button went blank**: hovering replaced its accent fill
with `--surface-2` while the text stayed `--accent-text`, i.e. white on
near-white. `button.primary:hover` had only ever set `filter`, which does not
restore a background. Three separate instances of one trap in one file; each now
repeats its own background under `:hover`. Check specificity before believing a
state class is being ignored.

**Native form controls do not read the palette.** A `<select>` kept the
platform's light chrome inside a dark panel, because the shared input rule
listed only `input[type=…]`. `color-scheme` on `:root` (and again in both dark
blocks) is what steers everything CSS cannot reach — the list a `<select>` pops
open, scrollbars, spinners — and the `select` element itself now shares the
input styling.

**`hidden` did not hide anything in this UI.** The browser's
`[hidden] { display: none }` loses to any author rule that sets `display`, and
several components set one (`.search-results` is a grid, `.loading` a flex row).
So `el.hidden = true` set the property, the element stayed on screen, and search
results survived both picking one and changing the search type. Fixed once,
globally, with `[hidden] { display: none !important }` — check that before
believing a "hidden" element is gone. Related: `button:hover:not(:disabled)` is
more specific than `.kind.is-active`, and the cursor sits on a chip the instant
it becomes active, which rendered the selected chip white-on-white until the
active rule repeated itself for `:hover`.

**Books go through the same pipeline, packaged differently.** `Adapter.packaging`
is `"cbz"` for everything except the `books` adapter, which sets `"file"`: the
site links a finished EPUB/PDF, so `queue._process_file` writes the bytes
through instead of building an archive. The mapping is series = book page,
chapter = one linked file, page = its URL, so a book with three formats is three
selectable items and a 72-volume collection is 72. Chapter identity is
`<book page>#<position>` — the page, not the file, so it survives a restart and
carries the referer the file host wants.

**Both book sites search fine over `?s=` — they are WordPress.** (An earlier
note here said otherwise; it was never tested.) planetebook wraps each result in
`<article>`, 8ghrb's theme in `<li class="post">`, so `_result_nodes` takes the
first wrapper that matches — combining them would list every book twice. Both
return nothing for a query they do not have, which is what makes them safe in a
multi-site search. Roughly **4 in 10 8ghrb posts link no file at all** — they
point at a Facebook group instead — so a "no book files" error there is the
honest answer, not a parsing bug.

**Book filenames come from the page, not the URL.** These sites name files by
database id (`2463.pdf`), which is useless in a library. When a page offers one
book in a few formats — all extensions distinct — each download is named after
the *book* (`رواية الغريب.pdf`, `Agnes Grey.epub`). A page of same-extension
files is a collection, where the site's own numbering is the only thing keeping
volumes apart, so those names are kept.

**`urlparse().path` silently truncates a filename at `;`.** It still implements
RFC 2396 `;params`, so bettergutenberg's
`/library/007_Frankenstein; or, the modern prometheus_pg84.epub` parses to a
path of `…/007_Frankenstein` with the extension filed under `params` — every
book on the site looked like no book at all. Use `urlsplit` for anything that
inspects a path (`books._path_of`). The same names then need `_encoded()` before
the request, because spaces and semicolons are legal in a filename and illegal
in a request line.

**Three sites now, in three different ways, have answered an unanswerable query
with something that merely looks like results** — rizzfables' front-page grid,
azoramoon's whole catalogue newest-first, arabic-book's "latest posts" widget.
Nothing structural separates any of them from a real hit, so the test is the
text: `base.query_matches()` requires every word of the query to appear in the
hit, and is applied by `books` and `vcomics`. Assume the next site does it too.

**A file URL can be base64 in a `data-` attribute.** arabic-book.net puts its
PDF in `<span data-href="aHR0cHM6…">` with no anchor anywhere, so the page looks
like it offers nothing. `books._encoded_links` decodes `data-*` values and
accepts only those that decode to a URL ending in a known book format.

**Gutenberg needs its own adapter, and the reason is the download list.** Search
(`/ebooks/search/?query=`, `li.booklink`) is the easy half. The list offers the
same text as EPUB3 / legacy EPUB / no-images EPUB plus a "send to Dropbox,
Drive, OneDrive" link per format — an OAuth flow, not a file — and every URL
ends `.epub3.images`, an extension no reader opens. `_downloads()` ranks the
variants, keeps the best of each real format, drops `/ebooks/send/`, and names
each download after the book.

**Some sites build sections and books identically.** bettergutenberg's "Novels"
and its copy of Frankenstein are both WordPress pages with `rel="bookmark"`;
only URL depth separates them, so `_MIN_PATH_DEPTH` holds that per host. It has
to stay per-host: planetebook's books sit at the root (`/agnes-grey/`).

**What breaks book downloads**, all confirmed live: match on the **path's
extension**, never the word "download" (that matched an Adobe help page in a
footer); the file host is often not the site (8ghrb → bookleaks.com, plus a 301
to https), so send the book page as `Referer`; and a file host that dislikes you
answers **200 with HTML**, which `looks_like_document` rejects rather than
storing an unreadable "book". `LIBRARY_EXTENSIONS` deliberately excludes `.txt`:
that set is also the delete path's allow-list, and a user's own notes.txt in the
output directory must never be ours to delete.

**Adapter choice normally costs a page render** (`registry.resolve` fingerprints
the DOM). `owns_its_host = True` skips it for an adapter that owns its hostname
outright — only MangaDex, which otherwise needed a browser to render a JS site
purely to conclude "this is mangadex.org", and failed with the browser.

**The queue view merged instead of rebuilding, so nothing ever left it.**
`refreshJobs()` wrote each job from `/api/jobs` into `state.jobs` and never
removed anything, while `renderJobs()` drew the whole map. The server forgot a
cleared or removed job correctly; the browser did not. "Clear finished"
therefore reported success over a list that had not changed, and only a reload
emptied it. It now rebuilds the map from the server's list every time, fetches
the per-job details concurrently, and lets a job that 404s mid-refresh fall back
to its summary rather than rejecting the refresh and freezing the view.

**A search hit is not ranked by the site that returned it.** These engines match
descriptions and word stems, and the API used to interleave sites round-robin
with no ordering at all. Measured live on `berserk` across the eight configured
manga sites: 26 hits, the real Berserk at positions **1, 7 and 20**, with `Magic
Emperor` and `The Hero Becomes Duke's Eldest Son` — not one word shared with the
query — ranked above two of them. `base.relevance()` now scores every hit
(exact → title prefix → whole word → word prefix → substring), `/api/search`
drops the irrelevant and sorts by band, still interleaving sites *within* a
band so the top of the list is everyone's exact match. Same query now: the three
real Berserks at 1–3, the noise gone.

**The one thing relevance must not do is judge across scripts.** Requiring the
query to appear in the hit is right for `berserk` vs `Magic Emperor` and wrong
for `berserk` vs an Arabic title: these sites index names in several writing
systems and display one, so the site matched on a name the page never shows.
`relevance()` therefore only returns *irrelevant* when the query and the hit
share a script; otherwise the hit is kept and ranked last. Verified live —
`الغريب` still returns the JoJo entries this file documents (via their Arabic
alt titles, ranked top), with the unjudgeable Latin-titled hits below them.

**Previewing is not owning.** `preview_series` writes a series row *and* the
whole chapter list — that is how the Add view shows what you already hold — so
`list_series()` returning every row meant clicking a search result filed the
series in your Library. The Library is now `series.first_download_at IS NOT
NULL`, stamped in `Database.set_chapter_status` when a chapter reaches `done`
(one place, so a new download path cannot forget to join). Deleting every file
leaves it set, which is what keeps the documented "files go, series stays"
behaviour; "Remove from library" still drops the row outright. Schema 2, with an
`ALTER` + backfill in `Database._migrate` — `CREATE TABLE IF NOT EXISTS` does
nothing to an existing table, so without the migration every install predating
the column would read as never downloaded and the Library would empty itself.
Verified live: a real MangaDex preview writing 108 chapters left the Library
empty; one real chapter downloaded put it there with `chapter_count` still 108.

**Three sources are live on self-written fixtures.** `ktobati.com`,
`noor-book.com` and `kitaboka.com`/`norkitab.com` were added to `KNOWN_HOSTS`
(and the last two to `search_sites`) with tests built entirely from hand-written
HTML, which this file warns about at the bottom for exactly this reason. The
Noor filter in particular decides a book is catalog-only by finding the word
"unavailable" in the page — a convention nothing has confirmed Noor uses, and one
the fixture was written to satisfy. It at least no longer matches raw markup:
`_visible_text()` strips scripts, styles and attributes first, so a CSS class
called `unavailable` cannot condemn a page. **None of the three has produced a
downloaded file.** Treat them as item 1 below, not as working sources.

**Noor now has live evidence, and it is bad.** A real session searching
`الغريب` for books: three `HTTP 403 on www.noor-book.com - refreshing session`
in a row, the PDF-link selector timing out after 10s, a
`net::ERR_ABORTED; maybe frame was detached?` on the search navigation, and the
preview ending in the hand-written message *"Noor Book lists this title for
reference, but download is unavailable because the file is not licensed for
distribution."* That message is the fixture-driven `_noor_unavailable` guess
firing on a page that had actually just 403'd — so the user is told the book is
unlicensed when the truth is the site blocked us. Either make the adapter tell
403 apart from genuinely-catalog-only, or drop `noor-book.com` from
`search_sites` until someone downloads a file from it.

**Cancel had no status guard.** `JobQueue.cancel` checked that the job and its
task existed and nothing else, so a Cancel clicked a moment after the last
chapter landed rewrote a `done` job as `cancelled` and answered 200 — a download
that fully succeeded, reported to the user as one they stopped. The button is
only rendered while the job is active, but a render is a snapshot and the job
finishes on its own schedule. `remove()` already had the guard; `cancel()` now
matches it, and the API's existing 409 does the rest.

**A progress bar that counts chapters cannot show a chapter.** `done/total` left
a one-chapter job reading 0% from the first byte to the last, while the rows
underneath it counted "12/40 pages" — flat for the whole download, which is
indistinguishable from stuck. `jobProgress()` weights a running chapter by
`pages_done/pages_total`. Two rules fall out of it: the fraction is **clamped**,
because a progress event can arrive for a chapter the summary does not list yet,
and **100% is reserved for `done >= total`** — a running job caps at 99%, since
rounding up to 100 while a file is still being written is the one number a
progress bar must never show. Verified against a real Berserk chapter: 44
intermediate steps where the old code produced 0 then 100.

**Red on the bar means the job failed, not that a chapter did.** One 403 among
forty painted the whole bar red while thirty-nine chapters were still downloading
normally. The summary line already says "1 failed" in red; the bar answers "how
much is done".

**The queue view rebuilt itself from `innerHTML` several times a second.**
Progress arrives per page, and `.chapter-rows` is a 320px scroller — so scrolling
down to watch a chapter was impossible during the download it was showing.
Scroll offsets are now captured per job id and restored after the rebuild, and
the rebuild is skipped entirely while the Queue view is hidden (a `jobsDirty`
flag redraws it on the way back in). The badge, the toolbar and the tab title
live outside that guard, because they have to stay true from any tab.

**Progress goes in the tab title.** A long download spends its life in a
background tab, which is the one place the percentage is guaranteed to be
readable. Restored to the exact original title when nothing is active, rather
than left showing a stale number.

**The chapter filter changes what "Select all" means, so the count says so.**
Filtering is presentational — a chapter selected before the filter was typed
stays selected while hidden, because silently dropping it would be worse — but
the select buttons act on the *shown* set, so "filter to Vol. 3, Select all"
does what it looks like. The consequence is a selection the user cannot see, so
`#selection-count` spells out "36 hidden by the filter". `None` is the exception
and clears everything: it is the escape hatch, and invisible selections are what
it gets reached for.

**An abandoned search keeps running, and that is why search feels slow.**
Found in a real session log, not by reading code: typing `الغريب` fired **ten**
`/api/search` calls — `ال`, `الغ`, `الغري`, `الغريب` and retypes — each waking
all six book sites. The UI's `searchToken` only stopped the stale *responses*
from rendering; **ASGI does not cancel a handler when the caller hangs up**, so
every superseded search ran to its full 20s `search_timeout`. Everything shares
one rate limiter (`requests_per_second: 2.0`), so that time came straight out of
the query the user was still waiting for — and `books` makes it worse by fetching
each candidate's page serially to check it has a real file, ~1s per result.

Measured against the live server: a request killed at 4s went on to fetch **16
more book pages** over the next 20s. Fixed in both halves — the browser aborts
the superseded request (`AbortController` in `runSearch`), and
`_gather_while_connected` races the site fan-out against a disconnect poll and
cancels it. Re-measured: **16 → 1**, the one already in flight.

Beware `grep -c` in a verification pipeline: it exits 1 on zero matches, which
silently truncated an `&&` chain and made the first run of this test look clean.
An earlier reading of the same symptom was also wrong — post-response fetches
that looked like orphaned work turned out to be the user searching in parallel.
Count something only the code under test touches (here: `8ghrb.com` page fetches,
which a manga search never makes).

**Search by author needed a field, not a cleverer matcher.** `relevance()`
scored the title only, so asking for a person returned nothing they wrote — the
one book you want is called *Berserk*, which shares no word with "Kentaro
Miura" and was judged, and dropped, as noise. `SearchResult` now carries
`author`; `relevance()` takes it; Gutenberg stopped appending it to `title`
(which had made every displayed title wrong to fake exactly this); and MangaDex
gained a real author lookup, since `/manga?title=` matches titles only —
`/author?name=` for ids, then `/manga?authors[]=`, run concurrently with the
title search and merged by manga id. Measured on the live app: "Kentaro Miura"
went from 2 hits (a memorial anthology and Berserk Gaiden, no Berserk) to 8,
with his whole bibliography at the top.

**The author band is flat, and that is the point.** The first attempt graded
the author like a title and it did not work: MangaDex stores Berserk's author as
"Miura Kentarou" against a query of "Kentaro Miura" — reordered *and*
transliterated differently — which scores one band below an identical string, so
Berserk still did not appear. `SCORE_AUTHOR = 90` for any author match at
word-*prefix* level or better: above a title that merely starts with the name
(80), below a title that *is* the query (100). The prefix floor is what absorbs
Kentaro/Kentarou while still rejecting a fragment buried inside a name.

**Noor: read, do not download.** The Download control is account-gated and on a
live book produced *no PDF anchor at all*, which is what the old adapter waited
for. The reader is not gated. Clicking Read runs a viewer that serves each page
as an SVG wrapping a base64 PNG at 2144×3024:

    POST /en/book/read_book?o=<token>                    opens the reader
    GET  /book/read_book_image/0/<book>/<n>/<token>.svg   page n

`curr_reading_pages`, `book_hash` and the session token are all in the DOM once
the reader is open, so the pages are minted and handed to the ordinary fetcher —
rate limiting, retries and resume come free. Three new pieces carry it:
`Adapter.packaging_for(chapter)` (books serves both shapes, so packaging cannot
be a class attribute), `Adapter.transform_page(bytes)` (unwrap the SVG before
validation, because a page does not always arrive as an image), and
`packager.write_pdf` — a book belongs in a document, not a comic archive.

**Noor is not finished: it throttles past ~90 pages.** On the 124-page test
title the pages download, unwrap and order correctly, but the run ends short —
90/124, then 108/124 once a retry for "200 with HTML" was added. Page 91 answers
**114 bytes of `text/html`**, and the *same URL fetched by hand seconds later
returns the real 142 KB SVG* — so it is throttling, not a paywall and not a
read quota (pages 91, 92 and 124 were each fetched successfully on their own).
The reader token is also **stable across processes**, so re-opening the reader
does not mint a new one and `refresh_pages` cannot rescue it that way.

What is left is tuning against a hostile source: `requests_per_second: 2.0` with
`image_concurrency: 4` is evidently too fast for a sustained 124-page read.
Try a per-host rate limit for noor-book.com, or more `PAGE_REFRESH_ROUNDS`,
before concluding anything about the adapter. **The mechanism is proven; a
complete book is not.** Do not mark Noor verified until one lands.

**Two Noor traps, both measured.** The Read click is regularly swallowed by a
Google vignette ad — the page comes back with `#google_vignette` appended and no
reader — so the open is retried, and a mid-navigation `ERR_CONNECTION_RESET` is
retried with it. And the old "not licensed for distribution" message was
nonsense: it fired on finding the word "unavailable" anywhere in the page, but
every Noor book page carries a sidebar of *other* titles each labelled
Unavailable. That message is gone; the adapter now says only that the reader did
not open, which is the only thing actually known.

**`/api/search?limit=` was unclamped.** The number goes straight to every
adapter's `search()`, several of which page to reach it — one query string could
send each site, each behind a browser that may have to clear a bot check, off to
walk its catalogue. Capped at `MAX_SEARCH_RESULTS` (50) per site.

## Findings — 2026-09-07 source survey (66 sites)

**`selectolax`'s `css("h2, p")` does not return document order.** It groups
matches *by selector*: a container holding `p, h2, p` comes back as `h2, p, p`.
Building a chapter from that moves every heading to the top and leaves the prose
in one undifferentiated run — wrong, and completely plausible-looking in the
finished EPUB. `prose.blocks_from()` uses `Node.traverse()`, which is real
depth-first document order. Caught by a test, not by reading the output.

**Never key a "seen this node" set on `id()` of a selectolax node.** The parser
hands out a fresh wrapper per traversal step, and CPython reuses the `id()` of
one that has been collected — so an identity set reports unrelated nodes as
already seen. Measured: it silently dropped every block after the first.
`prose._inside_a_block()` asks about ancestor *tags* instead.

**An HTTP/2 handshake can be the whole problem.** `downloads.hindawi.org`
answers **403 to every header combination over h2** and **200 with the full
2.45 MB EPUB over HTTP/1.1** — same URL, same headers, same IP. It is not the
UA, not the referer, not cookies. `Fetcher._retry_over_http1()` now downgrades
once on any `CHALLENGE_STATUS`, before deciding whether the response is even a
bot check, and pins the host afterwards. It has to run *before* the browser
fallback, because the browser cannot rescue a document at all: `page.goto()` on
an EPUB aborts the navigation.

**Sunovels' chapter listing is zero-based.** `page=1` is the *second* fifty.
Measured: bare URL → 1-50, `page=1` → 51-100, `page=2` → 101-150. Reading it as
one-based silently skips 51-100 — a hole that survives a preview.

**WEBTOON's `src` is a shared transparent spacer; the page is in `data-url`.**
Reading `src` yields a chapter of identical 1×1 images that validates as real
and packs into a real CBZ, so nothing downstream can tell it is wrong. The image
host also answers **403 without the chapter as `Referer`** (200 with it).

**Scribble Hub's `order` attribute and its chapter labels disagree** — `order`
289 is the row labelled "Chapter 288", because the count includes a prologue the
numbering does not. Sort on `order`, number from the label: each is right for a
different job.

**AO3 does not need scraping.** Every public work links official EPUB / MOBI /
PDF / AZW3 downloads to anonymous visitors. Chapter identity must exclude the
`updated_at` stamp on those URLs, or every author edit looks like a new chapter.

**A fourth site now answers an unanswerable query with noise.** Sunovels'
`/library` accepts `search=`, `q=`, `keyword=` and `title=` and ignores all
four, returning the same 24 catalogue cards. `base.query_matches()` caught it;
the adapter ships with **no** `search()` at all rather than one that can never
answer. Assume the next site does this too.

**Hindawi/Safahat's `<h1>` is "الكتب" ("Books") on every book page.** Preferring
the h1 — right on every other book site here — named every book the same and
made each download collide with the last. Per-host exception, like
`_MIN_PATH_DEPTH`.

**This container cannot clear an interactive Turnstile.** starzmanga/sparkmanga/
mangalik (Madara) and Scribble Hub were all confirmed to serve their readers
anonymously, and their parsing is verified against real captured markup — but no
CBZ/EPUB was produced through the app's own browser here. The bundled Chromium
131 never clears (this file already says so), and attaching Chromium 151 over
`browser_cdp` did not either, headless. Not an adapter problem; re-test on a
machine with a real browser.

**Eight of the 66 hosts are unreachable from this network entirely** —
`ERR_CONNECTION_RESET` before any HTTP response, in both curl and a real
browser: 3asq.org, noor-book.com, novbook.net, manta.net, toomics.com,
webcomicsapp.com, mangaplaza.com, mangaswat.com's real host. That is the
ISP-level SNI filtering this file documents; `desync_enabled` is the remedy and
could not be exercised in this session.

## Open work, in priority order

**1. Download one file from `ktobati`, `noor-book`, `kitaboka`, and one chapter
from `mangathemesia`, `comix`, `blogger`, `generic`.**
Preview proves the chapter list parses and nothing else. Every serious bug this
project has had — scrambled ordering, thumbnail images, an interstitial parsed
as content — passed preview and died here. `scratchpad/verify_dl.py <url>
[--chapter N]` runs preview → real queue → CBZ inspection (decodes every page,
flags anything under 600px) against a throwaway output dir.

**2. `olympustaff.com` → the 5-Arabic target.** Now the only one left: it does
**not** share azoramoon's platform (no `astro-island`, no `/_vcomics/`, no
`PUBLIC_API_URL` — it is "teamxmanga"), so the old plan of one adapter for both
is dead. azoramoon is covered by `vcomics`; olympustaff needs its own reading.

**3. More book sources.** Target is 5 Arabic + 5 English; 4 are live. Probed
2026-08-12, so re-check before trusting:

| Site | State |
| --- | --- |
| lib-books.com | **Dead** — HTTP 500 on every URL |
| kutubypdf.com | **Unreachable** from here, even through the bypass |
| librelegacy.org | **Dead** — HTTP 503 on every URL |
| standardebooks.org | Reachable *intermittently* (`/ebooks?query=` works, then "host unreachable" for minutes). Needs a retry story before it can join |
| kutubgate.com | Search fine (`?s=`, `article`+`h2 a`). **Protocol solved, site still not worth it** — see below |
| books.e3raf.co | Search fine, but result links live in `onclick="location.href='…'"`, not `href`. The تحميل link `/down/?id=91739` is **not** a redirect: it serves another 136 KB HTML page, so it needs a second hop parsed |
| arabic-book.net | **Downloads work** (base64 `data-href`, verified 2.77 MB PDF) and it is a known host, so URLs paste in. Kept **out of search**: its result page renders a latest-posts widget in the same `<article>` markup as hits, and a query with no matches still returns ten of them |
| wamdabook.com | Search fine (`/books/?s=`, `.book-item` → `a.book-title`). Download is `<button id="download_book">`, JS-driven — needs the endpoint from the Network tab |
| bkora.online, maktabti.app | Reachable; result markup not yet identified |

**kutubgate, in full, so nobody re-derives it.** Its download page hides the
whole flow in a percent-encoded inline script (`unquote()` the HTML to read it).
It is three plain POSTs to `https://dl.kutubgate.com/wp-admin/admin-ajax.php`,
no browser required, verified working:

1. `action=omar_get_nonce` → `data.nonce`
2. `action=omar_get_token&post_id=<id>` → `data.token` (900s expiry)
3. `action=omar_get_download&post_id=<id>&token=…&nonce=…` → `data.url`

`post_id` comes from `const postId = <n>` in that same script. **Do not build on
this yet**: the one page that carries `dl.kutubgate.com/download/…` links was a
72-part series, and its `data.url` is a **264 MB `.zip`** — a container the
library deliberately does not store. Three ordinary single-book pages carry no
such link at all, so single books use some *other* mechanism that still has to
be found. Solve that before writing the adapter, or it will support only the
archives nobody asked for.

**4. Smaller:** search is browser-per-site (HTTP-first would take 6.6s → ~2s);
the queue is lost on restart; preview is silent for ~36s; `/api/cover` takes 4s
because it needlessly goes through rate limiting and quality upgrading.

**5. Never deployed.** `deploy/DEPLOY-LXC.md` and `install.sh` are written and
handle Chrome/Xvfb/patchright but have never been run — the original goal.
Needs `host: 0.0.0.0`; there is **no authentication**, so keep it on the LAN.

## Notes

- `tools/optimize_cbz.py` converts CBZ pages to WebP. Measured on this library
  it saves **~0%** — the source JPEGs are already efficient — so it is not used.
  Useful for PNG-heavy libraries. `--dry-run` first.
- Local `config.yaml` is Windows test config (`headless: false`, desync on for
  HTTP). `config.example.yaml` is the shipped default.
- Fixtures must be captured from real pages. The Madara adapter passed fixtures
  I had written myself while silently mis-ordering chapters and downloading
  thumbnails.
