> Historical development notes. For current deployment, use [README.md](README.md).
> **Latest continuation: [CLAUDE_CONTINUATION.md](CLAUDE_CONTINUATION.md),
> 2026-09-08.** Read it first for Codex's changes, fresh verification, and the
> ranked remaining work. Dated findings below preserve earlier observations.

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
Test on Linux: `.venv-linux/bin/python -m pytest -q` → **859 passed**
(2026-09-08, after Codex's continuation; baseline was 853).
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

**Superseded by [SOURCES.md](SOURCES.md), 2026-09-08.** That file is the
evidence ledger: one row per source, one tier, and for every T4 an absolute
path, a byte size and a page or chapter count. The table below is kept only as
a summary of where each *adapter* stands.

| Adapter | Status |
| --- | --- |
| `madara` | **T4** on four sites: 3asq, mangaread, manhuaplus, arabtoons |
| `mangathemesia` | **T4 for prose** on kolnovel. Its image path remains unproven: rizzfables' CDN fails. See SOURCES.md |
| `vcomics` | **T4.** azoramoon/azorafly, 46 pp. Search + locked-chapter handling live-checked |
| `mangadex` | **T4.** 37 pp, full-size originals, no browser |
| `comix` | **T4** — 12 pp, but only after `scroll_for`; it read 3 before |
| `blogger` | **T4** — 52 pp, unblocked by the stylesheet-fingerprint fix |
| `books` | **T4** on planetebook, 8ghrb, bettergutenberg, kitaboka, noor. `ktobati` excluded (account) |
| `gutenberg` | **T4.** 77k books; search + one-per-format downloads |
| `royalroad` / `ao3` / `webtoons` / `sunovels` | **T4**, one artifact each |
| `aco` | **T4**, 524-page PDF from the IIIF manifest's rendering link |
| `wuxiabox` / `rewayat` / `riwayatarab` | **T4**, one EPUB chapter each; full listing counts recorded in SOURCES.md |
| `scribblehub` | **TB** — Turnstile this container cannot clear |
| `generic` | Heuristic fallback; no source of its own to verify |

**Search asks for one kind at a time.** The UI requires Book / Manga / Comics
before the box is usable, `/api/search` requires `?type=` (400 otherwise), and
only sites whose adapter declares that `content_type` are queried at all. Every
adapter declares one — `manga` for mangadex/vcomics/mangathemesia/madara/generic,
`comics` for comix/blogger, `book` for books — and a test fails if a new adapter
forgets, because a missing type makes it unreachable from search.

Default configuration as of 2026-09-08: **21 search URLs, all with T4 evidence**
— **7 Manga, 13 Books, 1 Comics**. User configuration can override this list.
The reconciled ledger contains 26 T4 hostnames including redirect aliases;
10 match the supplied inventory exactly after removing `www.`.
`manga-starz` (SNI-filtered here) and `rizzfables` (its CDN answers 526 to
everything) were removed by WP-2. comix and blogger still have no search, so
they remain paste-by-URL — but both now download.

**Ranking is ours; matching is still the site's.** These engines match
descriptions and word stems, so their raw answer to `berserk` buries the real
series among things merely containing the letters. `/api/search` scores each hit
with `base.relevance()`, drops what is judged irrelevant, and orders the rest by
band — except across scripts, where an Arabic query legitimately returns a
series shown under a romanised name and text can settle nothing. See Findings.

`comix` and `blogger` have since produced real CBZs (WP-2, 2026-09-08).
`mangathemesia` later produced a prose EPUB from kolnovel; its image download
path still needs an artifact from a working site.

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

## Historical open work (superseded)

**Do not use this list as the current task queue.** WP-5 and several source
additions below were completed later in this file. The current queue is in
[CLAUDE_CONTINUATION.md](CLAUDE_CONTINUATION.md#remaining-work-in-order).

**1. ~~Download one file from every unproven adapter.~~ Done 2026-09-08 (WP-2).**
`noor-book`, `kitaboka`, `comix` and `blogger` all produced files; `ktobati` is
excluded as account-gated; `mangathemesia` is blocked by its site's own CDN;
`generic` is a fallback with no source of its own. Evidence in
[SOURCES.md](SOURCES.md). What remains is WP-5: triage the 183 supplied URLs in
`docs/source-inventory.md` — auth check first, then reachability, then
fingerprint, then platform cluster — before WP-6 adds anything to
`search_sites`. Note that the meta prompt's Group D is a hypothesis list: a
spot check found no live MangaThemesia site among its candidates.

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


## Notes

- `tools/optimize_cbz.py` converts CBZ pages to WebP. Measured on this library
  it saves **~0%** — the source JPEGs are already efficient — so it is not used.
  Useful for PNG-heavy libraries. `--dry-run` first.
- Local `config.yaml` is Windows test config (`headless: false`, desync on for
  HTTP). `config.example.yaml` is the shipped default.
- Fixtures must be captured from real pages. The Madara adapter passed fixtures
  I had written myself while silently mis-ordering chapters and downloading
  thumbnails.

## Findings — 2026-09-07 WP-0 verification baseline

**The handoff and meta prompt lag the checkout.** The isolated Linux baseline
ran **691 tests**, not 499 or 552. `desync_browser` is already a declared Settings
field and `SessionManager` uses its proxy selection; HTTP limiters are already
per-host, although all use the same configured rate. These are read from code,
not proposed fixes. WP-1 must measure the existing route before replacing it.

**The verification tool could delete the directory it was given and write into
the real database.** It reassigned only `settings.output_dir`, recursively
removed that directory on entry, and used the unchanged `settings.db_path` and
browser profile. `--keep` saved the archive but did not isolate anything else.
Each invocation now copies settings and assigns all storage paths to a fresh
child directory, clears attached-browser and runtime-proxy state, uses an
ephemeral desync port, and retains evidence on both success and failure.
The regression test supplies conflicting MD_* storage variables and a sentinel
user file: the isolated paths stay separate and the existing file survives.

**A signature is not an openable book.** The old verifier accepted both a fake
PDF made from `%PDF`, padding and `%%EOF`, and an arbitrary ZIP named `.epub`.
Both failures were reproduced before the fix. The audit now renders PDF pages,
follows EPUB container/OPF/spine references and renders the document, and still
fully decodes CBZ images with a 600px width floor. A real Gutenberg EPUB does
not contain `OEBPS/chapter.xhtml`, which the app's generated-EPUB verifier
assumes; audit source EPUBs by their own spine instead of applying that layout.
Missing spine members, empty prose, truncated images, and page-count mismatches
are regression cases. EPUB spine items include front matter, and rendered page
counts depend on layout; neither should be mislabeled as literary chapters.

**A finished queue job can still fail its audit.** The first WP-0 Frankenstein
file was written successfully but the new reporting path imported `by_id` from
`app.adapters`, which does not export it. It is in `app.adapters.registry`.
The audit correctly kept the file and recorded a failed run; after correcting
the import, a fresh real run passed. A job marked done is not the report's pass
condition: artifact inspection must also succeed.

**Historical SNI failures are not current TB evidence.** All 18 configured URLs
answered HTTP 200 via the local desync proxy during WP-0, including Noor and
`3asq.online`. That says nothing about Noor's browser reader route or whether
desync was necessary. The configured `3asq.online` is also not `3asq.org`.
Supplemental probes captured `manga-starz.net` -> `starzmanga.com` and
`azoramoon.com` -> `azorafly.com`; URL-only selection called several theme sites
`generic`, while their fetched DOM correctly selected Madara or MangaThemesia.
Keep route, exact hostname and fingerprint evidence separate from support.

**One current T4 artifact is retained.** Anonymous Gutenberg Frankenstein EPUB:
`/workspace/manga downloader/.state/verification/run-arxyf3k8/downloads/Frankenstein; or, the modern prometheus/Frankenstein; or, the modern prometheus.epub`,
474161 bytes, 32 spine items and 239 rendered pages (PyMuPDF 1.26.4). A prose
page was visually inspected; blank pagination pages also occur and are not
missing chapters. Source, SHA-256, queue result and verifier details are in
`docs/evidence/wp0/download.json`; a byte-identical real-file fixture is in
`tests/fixtures/books/gutenberg_frankenstein.epub`. SOURCES.md assigns the other
17 configured URLs T1 pending their own artifacts; it does not turn historical
claims into current T4 evidence. TU is the user-approved tier for unavailable
or insufficient evidence that fits none of T0–T4 or TB.

**An audit must survive the failure it is measuring.** Review found that one
POST timeout or invalid JSON response aborted the entire connectivity batch
before any report was saved, and the fixed output filename erased the previous
run. Endpoint failures now become per-site `audit_error` records, other hosts
continue, and each unique run checkpoints its own JSON after every response.
A timeout/invalid-JSON regression test confirms that completed results survive.

**The original URL inventory has now arrived.** `docs/source-inventory.md`
preserves all 183 supplied entries (86 Arabic, 97 English), including names,
categories, `www` prefixes and path-specific entry points. Every supplied host
appears in Section 5 of the meta prompt; its additional references are
`3asq.online`, `azoramoon.com` and `olympustaff.com`. Only four supplied hosts
overlap the 18 configured search hosts. This is inventory reconciliation, not
live triage. A first domain scan falsely reported three omissions because it
missed `.edu`, `.info`, and a domain immediately followed by `->`; compare
complete domain tokens before claiming an inventory is missing entries.

## Findings — 2026-09-08 coverage program, WP-1

**Noor does not need a browser to open its anonymous reader.** A live White
Nights page provides `csrf_token`, `crypto_token`, `b_h` and `book_hash`; its
script posts to `/en/Verification/check_user`, then `/en/book/read_book`.
The former explicitly reports `is_logged: 0`. Replaying these requests through
one initially empty HTTP session produced all 111 reader pages. Clearing the
session cookies between POSTs changed the reader response to 403. The SVG URLs
then worked in a separate client, so the ordinary page fetcher remains the
correct download path. `SessionManager.direct_http_client` provides the scoped
cookie-preserving transport; no account or Download endpoint is involved.
Real HTML/JSON and search captures are in `tests/fixtures/noor`.

**An Arabic URL is valid request input and an invalid raw HTTP header.** The
reader opened, but its pages failed before any request reached the server:
httpx raises UnicodeEncodeError on an Arabic slug placed in `Referer`. A test
reproduced it while constructing the request. `Fetcher._headers` now encodes the
URL through `httpx.URL` first. This applies to every adapter, not just Noor.

**Noor's complete-book run crossed the old failure point.** At 0.5 requests per
second and image concurrency 1, all 111 pages downloaded, bound into a PDF and
rendered successfully: 33679155 bytes. The exact path and SHA-256 are in
`docs/evidence/wp1/noor.json`. `host_requests_per_second` now supplies a
Noor-specific 0.5 ceiling, with bare and www names sharing the limiter; a lower
user-wide cap still wins. Other hosts keep their usual cap. The first attempt,
before the Referer fix, was interrupted and remains failed evidence. The
successful PDF is scanned Arabic; its page 12 was visually inspected.

**A redirected GET hides the failure of the following POST.** 3asq.org redirects
to 3asq.online. Reading the series over desync worked, but posting the chapter
list to the old hostname was redirected with 301, became a GET, and returned no
chapters. Madara now follows the series' canonical link when deciding the AJAX
origin. Direct static HTML and form requests use the existing HTTP bypass;
complete-markup checks preserve browser fallback for JS readers. This is a
platform behavior, not a hardcoded 3asq exception.

**A readable chapter list can still name missing pages.** Hunter X Hunter
chapter 1 parsed 33 images but six returned 404, and the queue correctly failed
at 27/33. Chapter 420 completed: 16 pages, 47861046 bytes, every image decoded
and at least 600 pixels wide. Both runs are preserved under
`docs/evidence/wp1`; the failed first chapter is a source-content limitation,
not evidence that retrying stable URLs will restore missing files.

## Findings — 2026-09-08 coverage program, WP-2 / WP-3 / WP-4

**A WordPress AJAX endpoint says no with `0`, and an exception-only fallback
never hears it.** `Adapter.post_form` fell back to the browser when the direct
HTTP POST *raised*, and kept the answer when it succeeded. `admin-ajax` returns
`0` for an action it does not recognise and `-1` for a failed nonce, both as
**HTTP 200 with a one-character body**, and a redirected POST produces the same
`0` — the redirect is followed as a GET and the action never runs. So Madara
held `0`, reported "no chapters found", and never tried the browser that would
have answered. `EMPTY_FORM_REPLIES` now treats an empty reply as a failure of
the direct path, not as an answer. The test for this was already in the tree,
failing, before this session began.

**A stylesheet decided the adapter.** A real Blogger comics blog has a
MangaThemesia theme's CSS pasted into its template, so its markup carries the
marker `bixbox` twice — inside an `@media` block, styling a class the page
never uses. Every fingerprint here is a substring test over raw HTML,
MangaThemesia outranks Blogger (110 vs 90), so it claimed the page and every
blogspot series failed with *"No chapter list … open the series page on the
site"* against a URL that **was** the series page. `registry.fingerprint_html`
now strips `<style>` blocks before matching. `<script>` deliberately stays:
`ts_reader` is a real marker and lives in one. Only the copy used for matching
is stripped; the adapter still parses the untouched page. Blogger produced its
first CBZ — 52 pages — the moment this was fixed.

**The Kitaboka alias pointed at the empty side.** The adapter mapped
`kitaboka.com` → `norkitab.com`, described in its own docstring as "the active
Norkitab backend". Live, `norkitab.com` answers **976 bytes of HTML 4
frameset** whose only content is `<frame src="…kitaboka.com/books">`;
`kitaboka.com` answers **227 KB with 37 book links**. So every Kitaboka search
fetched an empty document and returned nothing, for every query, and had done
since it was added. Nothing caught it because the tests were built from
hand-written markup that agreed with the mistake — the exact failure the bottom
of this file warns about. Fixtures are now real captures
(`tests/fixtures/kitaboka/`), the alias resolves towards `kitaboka.com`, and
the site went from *never produced a file* to a 246-page, 4.8 MB PDF.

**Kitaboka is the sixth site to answer an unanswerable query with its
catalogue.** The sentinel `zzqvoneshelfnonexistent987654321` returns **27 real
book links**, overlapping the ones a genuine query returns. `query_matches`
turns it back into "nothing found". Six now, in six different shapes. Assume
the next one does it too.

**A lazily-mounted reader hands back only what is on screen, and the result is
a perfectly good archive of a quarter of the chapter.** comix.to mounts pages
as they scroll into view. `wait_for` plus `wait_ms=2500` saw **3 images**;
scrolling to the end saw **12**. The three were real, full-size, 785×1200 —
they passed the 600px floor, passed the decode, packed into a valid CBZ, and
nothing downstream could tell. Measured against the same chapter twice.
`SessionManager.fetch_html(scroll_for=…)` now scrolls until a round adds no
new matches; a page that was already complete pays one scroll. This is general,
not a comix hack: any infinite-scroll reader needs it.

**A verifier that opens the file still cannot tell you the chapter is short.**
The comix CBZ passed `verify_cbz` completely. What caught it was knowing that
Attack on Titan chapter 1 is not three pages. Artifact inspection proves the
file is real; only the *source* can say whether it is complete.

**`fold` folds ؤ and ئ, and said for a long time that it did not.** The comment
above `_ARABIC_FOLD` presented Lucene's omission of ؤ→و and ئ→ي as this
module's behaviour. It is not: NFKD decomposes U+0624 to waw + U+0654 and
U+0626 to yeh + U+0654, and the combining-mark strip that removes harakat
removes the hamza with them. The table omits them; the pass before it does not.
Behaviour left alone, comment corrected, and the real behaviour is now pinned
by a test rather than by prose.

**A pasted bidi mark is not whitespace, and `.strip()` does not remove it.**
`/api/search` sent `q.strip()` straight to every site. Measured live: the
pasted string `‏الغريب‎` returns **0 hits on 8ghrb and 0 on 3asq**;
the same query cleaned returns **12 and 10**. Inside `fold()` the same
characters reached the `\W+` rule and became a *space* — harmless at the edge of
a query, but in the middle of a word it split one token into two and every gate
downstream then looked for both halves. `textmatch.clean_query` deletes them,
and `main.search` cleans before fan-out.

**Folding rescues a hit the site returned; it cannot rescue one the site never
returned.** That was the whole of GAP A. A site with an unnormalised index
answers `رواية` and `روايه` as different words, so the hit never arrives and
there is nothing to re-rank. `textmatch.query_variants` offers the spellings a
reader might have typed instead, and `main.search` sends them **only to a site
that found nothing**, stopping at the first that answers — so a site whose
index already normalises (Noor) pays nothing at all. Measured across the five
Arabic sites: **276 → 447 hits, +62%**, table in
`docs/evidence/wp3/before-after.md`.

The single most valuable variant is the least interesting one: strip harakat
and tatweel and map the Persian letter forms. `رِوايَة`, `روايـــة` and `کتاب`
each returned **0 hits on every site** as typed. Nobody types tatweel into a
search box on purpose — it arrives by copy-paste from a justified heading.
`undecorate` is deliberately *not* `fold`: it changes only what is decorative,
so the string being sent is still the word the reader meant.

**The reverse letter substitutions have to be anchored to the end of a word.**
Teh marbuta and alef maqsura occur nowhere else, so substituting every heh in
`شهرزاد` produces a string that is not Arabic — and costs a real variant its
turn in a list that is deliberately capped.

**Two `'/'` handlers, and the loser was registered first.** `web/app.js` bound
the shortcut twice; the later registration ran second and won, and it
re-targeted `#chapter-filter` whenever `#preview` was visible — which is
exactly when someone wants to search again. So the keyboard route back to
search was dead from the first result click until a page reload. One handler
now, one rule: `'/'` goes to the view's search box, never to the chapter
filter. Its comment about the search input "staying disabled until a kind is
chosen" described behaviour that had already been removed.

**`clearResults()` leaves the text in the box, and search only fires on
`input`.** So after opening a result the box still read `berserk`, retyping the
same query changed nothing and fired nothing, Enter needed a cursor that
`clearResults` had just set to `-1`, and `renderRecents()` no-ops above two
characters. The text is now deliberately kept — someone who clicked a result
usually wants the same list back — and Enter, Escape and a visible **Back to
results** control all restore it from `lastSearch`, held before it is nulled.
Nothing re-queries the network to go back.

**The result-click handler skipped the reset trio.** The kind chips and the
clear button all run `clearTimeout(searchTimer); searchToken++;
abandonSearch();`. Clicking a result ran none of them, so a pending debounce or
an in-flight fetch survived and its late render could reopen the result list on
top of the preview just loaded. It now runs the same three.

**`pgrep -f <pattern>` matches the shell that is waiting on it.** A
`while pgrep -f wp2_artifacts.sh; do sleep 10; done` never exits: the waiting
command's own command line contains the pattern. The batch had already
finished. `pkill -f` on the same pattern then killed the shell issuing it.
Same family as the `grep -c` trap below — match on something only the thing
under test produces.

**A positive search query has to name something the site actually holds.** The
first search audit scored `bettergutenberg.org` at zero for *Agnes Grey*, which
is planetebook's copy, not theirs. It also showed WordPress `?s=` matching
stems and body text: `?s=agnes` returns "Experiments upon **Magnes**ia Alba".
A zero from this audit means "no gated, relevant hit", never "the site is
broken" — check the query before the adapter.

**URL-only adapter selection is a filter, not a verdict — including in your own
tooling.** The first run of the search audit used `adapters.select(url)` and
reported six sites returning nothing, because every Madara and MangaThemesia
site resolves to `generic` by URL alone and `GenericAdapter` has no `search()`.
`app.main` gets this right (`resolve`, which fingerprints the fetched DOM); the
audit did not. Fingerprint in the tool the same way the app does, or measure
the tool instead of the app.

**This repo has mixed line endings, and a Python `write_text` silently
normalises them.** `app/session.py` and `tests/test_books.py` are CRLF for most
of their lines and LF for the rest — a Windows history showing through. Editing
either with `pathlib.Path.write_text()` rewrote every line as LF and turned a
40-line change into a **2,719-line diff** that would have buried the actual
edit in review. Converting the whole file back to CRLF was no better: it
rewrote the ~58 lines that were legitimately LF. The repair is to align the new
content against `git show HEAD:<file>` and re-emit each *unchanged* line with
its original bytes. Check `git diff --stat` against the size of the edit you
actually made — a number far larger than expected is this, not your change.

## Findings — 2026-09-08 coverage program, WP-5 (triage of the 183 supplied sites)

**Group D was a hypothesis and it did not survive contact.** The meta prompt
lists ~32 sites as "likely zero-code coverage" — 20 Madara, 12 MangaThemesia —
on the strength of their names and reputations. Fingerprinted live: **one**.
`kolnovel.com`, and it fingerprints as MangaThemesia, not the Madara it was
filed under. Of the other 31, most no longer exist; the ones that answer serve
Next.js or plain WordPress. Treat every hypothesis list in that prompt the same
way: it is a place to start looking, never a verdict, and the whole WP-6 "add
the host and run verify_dl" shortcut is worth about four sites, not thirty-two.

**A 200 is not content, and this list is full of counter-examples.**
`mangak.com` answers 200 with a HugeDomains **for-sale page**. `mangarose.com`
and `ozulscans.com` answer 200 and redirect into ad networks
(`p.asdfix.com`, `avq.one`). `mangapro.com` answers 200 with a **114-byte**
body. A reachability check that reads only the status code calls all of these
healthy. `triage_pass2.verdict_for` classifies on the *final* URL and the body
size: below ~12 KB nothing in this inventory was ever real content, while live
sites came back 40 KB–1.1 MB.

**Separate "blocked here" from "gone" with a second pass, not a guess.** Of 94
hosts that failed or answered too small, only **7** came back with content
through the desync proxy — and four of those are account-gated anyway. The
other 67 are unreachable through the bypass too, so the ISP filter is not what
is wrong with them. Historical SNI hypotheses do not survive as current
evidence; re-probe before filing anything TB.

**Arabic web-novel sites run manga platforms' themes, and both adapters assume
images.** `kolnovel.com` fingerprints as MangaThemesia and lists **13,406
chapters correctly**, then dies with "No page images found". `cenele.com`
fingerprints as Madara and finds no chapter list at all. A kolnovel chapter
page carries **180 `<p>` and 0 `<img>`** — it is prose. The theme matched; the
content type did not.

This is the highest-leverage finding in the pass, because the supplied
inventory holds ~15 Arabic novel sites and ~20 English web-novel sites and the
fix is not one adapter each: it is deciding a chapter's *kind* from the chapter
rather than from the adapter class. The machinery already exists and is proven
— `prose.py`, `packaging = "text"`, `packager.write_epub`, `Adapter.fetch_text`,
`packaging_for(chapter)` — and Sunovels and Royal Road ship on it today.

**The remaining sites do not cluster into adapters.** Among live, unclaimed
hosts the commonest signatures are Next.js (12), WordPress (10) and Laravel
(8). None of those is an adapter-sized cluster: they describe how a site is
*built*, not how its chapters are laid out, and a scraper cannot be shared on
that basis. Only `vcomics/astro` (asuracomic.net) names real markup. Plan the
rest as one adapter per site or per small family.

**The 92-site target is not reachable from this list.** At most 74 of the 183
supplied sites are live and not excluded, so even a perfect run tops out at 74
— and each one costs adapter work, not a config line. Said here rather than
discovered at the end.

## Findings — 2026-09-08 coverage program, prose routing (WP-6/WP-7 first cut)

**A platform's theme says how to find a chapter and cannot say what is in it.**
`kolnovel.com` fingerprints as MangaThemesia and `cenele.com` as Madara, and
both serve Arabic *novels*. Read as comics they failed outright. The fix is not
per-site: `Adapter.packaging_for(chapter)` may now answer **asynchronously**
(`JobQueue._packaging_for` awaits an awaitable and calls a plain hook plainly),
so an adapter can open the chapter and decide. `prose.looks_like_prose` is the
decision, and both adapters cache the chapter page so classifying it and
reading it cost one fetch.

`looks_like_prose` is deliberately "no images **and** real text", not a ratio.
A chapter with images is a comic chapter however long its translator's note,
and calling one prose would silently drop every page — the worst outcome
available here. The character floor (1,500) only stops an empty or failed page
becoming an EPUB.

**Chasing those two sites turned up three bugs that had nothing to do with
novels**, all of which would have hit comics too:

*MangaThemesia counted every anchor in a chapter row as a chapter.* kolnovel
puts a second, unlabelled `<a>` beside each chapter pointing at
`<chapter-url>/pdf/`, so a 6,703-chapter novel listed **13,406** — exactly
double, which is the shape to recognise. Worse, the `/pdf/` copy sorted equal
to the real chapter and could win, so the download opened a page with no reader
on it. Rows are walked now, not anchors, and an anchor with no text is
furniture.

*MangaThemesia harvested images from the whole document.* `_images_from_dom`
fell back to `tree` when neither `#readerarea` nor `div.reader-area` was
present. On kolnovel that produced **8 "pages", every one an analytics tracking
pixel** (`pixel.quantserve.com/pixel/….gif`). They are not decorative by name,
not 1×1 by URL, and they answer 200 — the only thing separating them from a
comic page is that they were never inside the reader. No reader now means no
pages, and the caller's "no page images found" is the correct answer.

*Madara required `/manga/` in every chapter path.* The post-type slug is
configurable and cenele uses `/cont/`, so all eight marked chapters were
discarded and the series reported "could not read the chapter list" against a
page whose list had parsed perfectly. That guard exists for the **fallback**
scan, where "every `<li>` holding a link" really is a guess; a link the site
marked `li.wp-manga-chapter` needs no such check. Same shape as the search fix
below: be suspicious of what you inferred, not of what the site declared.

**A generic wrapper is a last resort and has to be gated.** kolnovel answers
`?s=` with real results in `<article>` and uses no `div.bs` at all, so search
returned nothing for a series it plainly holds. `article` is WordPress's
generic wrapper and also wraps navigation and category pages, so the sweep is
gated with `query_matches` — but the theme's own `div.bs` cards are **not**,
because ranking near misses is `/api/search`'s job and gating them here would
drop exactly what it exists to rank. An existing test caught the first,
over-broad version of this change.

**Re-verify what already worked after a change like this.** 3asq, mangaread and
manhuaplus were re-run and produced **byte-identical** artifacts (47,861,046 /
13,572,089 / 10,168,699 bytes). A shared-path change that improves two sites is
worth nothing if it quietly costs three.

**`content_type` is per-adapter, and these two sites need it per-site.**
kolnovel and cenele are filed under *Manga* in the search UI because they share
an adapter class with real manga sites. A Books search cannot reach them. Known
and recorded rather than papered over; the fix is to make the kind a property
of the site.

**`git checkout <file>` discards uncommitted work, and this tree is entirely
uncommitted.** Reverting `tests/test_textmatch.py` to clean up a stray edit
threw away 38 WP-3 tests written earlier in the same session. Nothing warned;
the suite simply went from 765 to 727. In a tree with no commits behind it,
`git checkout` is not an undo — it is a delete.

**The content kind belongs to the site, not to the adapter — and the map has to
be reachable without fingerprinting.** kolnovel and cenele are novels on manga
themes, so reading `content_type` off the adapter class filed them under Manga:
a Books search could never reach them and a Manga search returned novels.

The first fix put a per-adapter `CONTENT_TYPE_BY_HOST` on MangaThemesia and
Madara, and it did nothing for the one place the user sees. `/api/sources`
groups every configured site on every page load, so it must not fetch — and
without a fetch those two hosts fingerprint as **`generic`**, which has no such
map. The override therefore lives in `adapters.base.SITE_CONTENT_TYPES`, keyed
by bare hostname and consulted by `Adapter.content_type_for` whatever adapter
is asking. A test pins the case that caught it: `select()` really does return
`GenericAdapter` for kolnovel, and the kind is still `book`.

Note the division: `SITE_CONTENT_TYPES` is a *declaration*, used where nothing
may be fetched; `packaging_for` is a *detection*, made from the chapter itself.
They answer different questions and must not be collapsed.

**A test double has to carry the whole interface it doubles.** Adding
`content_type_for` broke **20 tests** in `test_search_api.py`, none of them
about content types: four hand-rolled stub adapters lacked the new method, each
raised `AttributeError` inside the endpoint's broad per-site handler, and the
endpoint duly reported every site as `"error"`. It read like a routing bug.
They now share one `AdapterInterface` base, so the next hook breaks them
visibly and in one place.

## Findings — 2026-09-08, Arabic Collections Online (WP-6)

**Look for the API before scraping the HTML.** ACO's book page is a **6.5 KB
JavaScript shell**: no title, no author, no file, nothing to parse. Capturing
what the reader actually fetches took one browser run and found a **IIIF
Presentation 3.0 manifest** carrying the entire record — title in English and
Arabic, metadata, `viewingDirection: right-to-left`, 524 page canvases, and a
`rendering` array offering **the whole book as a single PDF** in two
resolutions. The adapter reads one JSON document and never touches the page.

It takes the bound PDF rather than assembling pages from the IIIF Image API,
which also works (`…/full/full/0/default.jpg` returns a 2739x3935 JPEG). The
site has already bound the book; rebuilding it from 524 JPEGs would be slower,
larger and worse. Verified: 262,256,337 bytes, **524 rendered pages**, matching
the manifest's canvas count exactly — which is the check worth doing, because
a short download is the failure mode a PDF verifier cannot see.

**The extension has to be the last thing in a filename.** The two renderings
are distinguished by the manifest's own labels, and appending one after the
extension produced `…v.3.pdf (High-resolution PDF rendering (262.26 MB))` —
which the queue refused as "not a file type this library stores". The size also
stays out of the name: it changes when the site re-scans, and a filename that
encodes it goes stale. `(high resolution)` before `.pdf` is what ships.

**A result card holds more links than the one you want.** ACO's search page
gives each hit a title link, a "Read Online" control pointing at the same book,
and two PDF links on `mc.dlib.nyu.edu/files/books/<id>/…`. All three match the
book-id pattern, so sweeping every anchor read the title off whichever came
last and named every result
`تحميل دِقّة منخفضةLow-resolution PDF(34.…)`. Restricted to reader links on
the collection's own host, and the first title per book wins.

**A search that returns each hit twice is not returning two books.** ACO lists
every result under its romanised title and again with `?lang=ar` under its
Arabic one. Merged on the book id, with the Arabic name kept as `alt_title` —
which is also what makes an Arabic query visibly land on a record displayed
under a romanised name. Measured live: `المتنبي` → 10 hits, `mutanabbi` → 10,
sentinel → **0**. An honest search, unlike six others in this file.

**`curl` could not verify NYU's certificate chain from this container**
(`unable to get local issuer certificate`), while httpx through the app was
fine. A probe script's TLS failure is not the site's problem, and not the
app's — check which client is complaining before recording a site as broken.

## Findings — 2026-09-08, WuxiaBox and the novel-site sweep (WP-7)

**The same chapter can be published under two URLs.** WuxiaBox lists some
chapters both unpadded and zero-padded — `…_46.html` and `…_0046.html` are one
chapter. De-duplicating on the URL is the obvious choice and is enough for the
overlapping pages below, but it left both: measured on `absolute-resonance`,
**1,333 listed links for 1,216 chapters, so 117 would have been downloaded and
packaged twice**. Chapters are keyed on their *number* instead. Worth checking
for anywhere: a chapter list whose length exceeds its highest chapter number is
the symptom.

**A paginated listing can be zero-based *and* overlapping.** `page=1` returns
chapters **91-190**, not 101-200: 100 rows at a stride of 90. Sunovels was
zero-based with no overlap, so "zero-based" is not one bug with one shape —
measure the first row of the second page rather than assuming either.

**Ranking a chapter list by `int()` hid a real defect and invented a fake one.**
Comparing numbers as strings said the list was clean; comparing them as
integers said 117 collided. Both were true, and the integer view was the one
that mattered — `"46"` and `"0046"` are different strings and the same chapter.
When two measurements of the same list disagree, the disagreement *is* the
finding.

**Probing a site hard enough gets you throttled, and throttling looks like
absence.** After a few dozen requests wuxiabox began answering **2,009 bytes**
to everything, including a chapter already downloaded successfully. `curl` had
the same problem across the English novel sites — `novelfull`, `novelfire` and
`freewebnovel` all returned ~5 KB Cloudflare pages to a rapid loop, having
returned 39-105 KB of real content to the triage hours earlier. Route probes
through the app's own session (desync, rate limits, browser fallback) before
recording a site as blocked, and treat a uniform small response as a rate limit
until proven otherwise.

**Framework is not platform, confirmed again.** Of the 25 live novel sites,
the triage's framework labels (Next.js, Laravel, WordPress) predicted nothing:
`novelfull` and `readnovelfull` share a URL shape and neither shares markup
with `wuxiabox`, while `wanderinginn.com` is WordPress built with **Elementor**
and has no `.entry-content` at all — its prose sits in an `.elementor-*`
container. Cluster novel sites by the selectors an adapter would use, not by
what built them. `scratchpad/probe_novels.py` asks that question directly.

**An inventory category is a user's label, not a fact.** `ruya.com` is listed
in the supplied inventory under *Novels*. It is a WordPress site serving
**Turkish dream interpretation** (`/ruyada-yumurta-sarisi-gormek`, `/harf/…`).
Check what a site actually serves before building for the category it was filed
under — and expect a share of any supplied list to be mislabelled, not merely
dead.

**Not every hydration payload holds what you want.** rewayat.club is a Nuxt app
and its `__NUXT__` blob carries the novel record — Arabic title, English title,
description — but **not** its chapters, only the newest 24 of a novel numbered
past 950. There is no pagination control on the page and three guessed
`api.rewayat.club` endpoints answered 404. Recorded as unsolved rather than
half-built: azoramoon's payload held the whole list, and the lesson from that
was "look in the payload", not "the payload always has it".

## Findings — 2026-09-08, Rewayat Club

**A site's chapter list can live on the chapter, not on the novel.** Rewayat's
novel page shows the newest 24 of a 955-chapter serial, has no pagination
control and no "all chapters" link, and three guessed `api.rewayat.club`
endpoints answer 404 — so it was recorded as unsolved. Every *chapter* page's
Nuxt payload carries an `allChapters` array covering the whole serial. When the
index page does not have the list, open a leaf and look there.

**A hydration payload is not necessarily JSON.** Rewayat's is minified
JavaScript: `allChapters` entries read `{value:j,text:"الفصل 2"}` where `j` is
a single-letter variable assigned earlier in the same function. `value` cannot
be read at all without evaluating the script; the chapter number comes from the
literal `text`. azoramoon's payload was HTML-escaped JSON in an attribute, and
this one is executable code — "look in the payload" does not imply "parse it as
JSON".

**The record for the page you are on is often the one that is missing.**
Rewayat builds the current chapter's entry by assignment (`i.text=e`) instead
of writing it as a literal, so a regex over `text:"…"` returns 954 of 955 — and
*which* one is absent depends on which chapter was fetched. Off-by-one at the
end of a 955-chapter list is invisible in a preview, so both ends are pinned by
real fixtures: chapter 1's payload omits 1, chapter 955's omits 955. The
adapter adds the fetched chapter back explicitly.

**Scope a regex to the array it belongs to.** The same `text:"…"` shape appears
elsewhere in the hydration state — menus, footers — so an unscoped match
invents chapters out of navigation labels. `_all_chapter_numbers` finds
`allChapters:[`, walks to its matching bracket, and searches only inside.

**One anchor can hold the title and everything filed under it.** Rewayat's
search cards wrap the name *and* its genre tags in a single `<a>`, so the
anchor's text reads `ساطور الخطيئة مترجمة أكشن فانتازيا`. Vuetify's
`div.v-list-item__title` holds just the name. Same family as ACO's result cards
and kolnovel's `/pdf/` anchors: **a card is not a link, and the link you want is
rarely the whole card.**

**Two search endpoints, one of which lies.** `/search?q=` returns 36 KB that
mentions the query and links nothing; `/library?search=` returns the matches.
A page that contains the query string is not a page that answered it.

## Findings — 2026-09-08, RiwayatArab

**A cross-check that returns `None` has not passed — it has been skipped.**
`_advertised_count` was written to read the site's chapter total out of its
"عرض جميع الفصول (1344)" link. React's server rendering splits that number from
its own parentheses — the markup is literally `(<!-- -->1344<!-- -->)` — so the
regex matched nothing and the function returned `None` on every real page. The
live run logged no mismatch, and I briefly read that as the counts agreeing.
It meant the comparison never ran. The count now comes from the page's
schema.org JSON-LD (`"numberOfPages":1344`), which is meant for machines and
survives React's markers, and a test pins both the broken shape and the working
one.

**React SSR puts `<!-- -->` between adjacent text nodes.** Any string match
that spans two of them fails, and it fails silently. Match inside a single text
node, or use structured data.

**A 200 can mean "not found".** A missing RiwayatArab novel answers 200 with a
16 KB shell titled *"رواية غير موجودة"* and zero anchors — which looks exactly
like a client-rendered page that has not finished. Two hours were nearly spent
concluding "this site needs a browser" from a slug that was simply dead. The
adapter distinguishes them by looking for a title.

**Server-rendered does not mean server-rendered everywhere.** On this site the
novel page, the chapter list and the chapter are all in the HTML; the *search*
results are mounted client-side, and over plain HTTP that page returns 25 KB
that names the query and links nothing. One page needing a browser does not
make a site a browser site, and vice versa — check the page you actually need.

**Pagination shapes seen so far, all different:** sunovels zero-based;
wuxiabox zero-based *and* overlapping by ten; riwayatarab one-based and clean.
There is no house style. Measure the first row of the second page.


## Findings — 2026-09-08, Codex continuation

**A failed listing request is not an end-of-list marker.** RiwayatArab and
WuxiaBox caught exceptions on subsequent listing pages, logged them, and
returned whatever chapters had already been collected. Thus a timeout after
one page became a successful, incomplete preview. RiwayatArab also replaced a
first-page transport failure with misleading advice to find a different novel
URL. Both now raise `AdapterError` with the failed page URL and collected count,
retain the exception cause, and ask the user to retry. The existing preview
endpoint maps the error to HTTP 502; chapter rows are written only after the
listing succeeds. Six regression cases failed before the fix and pass after it,
including retrying the same adapter after the connection recovers.

**Missing test fixtures were accidentally simulating successful pagination.**
The fake session raises when a page is unregistered. Existing tests relied on
the adapters swallowing that exception to stop their shortened catalogues.
They now explicitly replay their last captured page as an end-of-list response.
This is a controlled test condition, not a claim about the live site's last
page. Actual timeout/connection failures are injected separately. Successful
empty/repeated responses and listing safety caps still need their own future
completeness policy; this fix addresses raised request failures only.

**Count fixture links inside the reader list.** WuxiaBox's provenance said its
first page contained chapters 1–100 plus ten padded duplicates. The captured
`ul.chapter-list` actually holds 100 links total and 90 distinct chapters
(1–90); the second fixture holds 91–190. The prose and a new test expectation
were corrected after counting the saved markup. Whole-page links also include
recommendations and do not establish the listing's count.

Both adapters were re-verified through preview → queue → EPUB inspection after
the fix. RiwayatArab: 1,344 listed chapters; chapter 1 is 6,607 bytes, one spine
item, seven rendered pages. WuxiaBox: 1,216 listed chapters; chapter 1 is 9,390
bytes, one spine item, fifteen rendered pages. Exact paths, hashes, transcripts,
the 859-test result, and ranked next steps are in
[CLAUDE_CONTINUATION.md](CLAUDE_CONTINUATION.md).

## Findings — 2026-09-08, audit of this session's own source work

Five defects, each reproduced before being written down, none caught by the
859 tests passing at the time. That is the point: all five survive a green run
and a preview.

**A classifier calibrated on characters excluded short chapters.**
`prose.looks_like_prose` required 1,500 characters, so a genuinely short
chapter on a manga-themed novel site was judged "not prose", packaged as `cbz`,
and died in `fetch_pages` with "no reader images" — the exact failure the prose
routing exists to remove. Measured across every captured reader fixture:

    fixture                        imgs  blocks   chars
    kolnovel chapter (prose)          0      80    8082
    rewayat chapter (prose)           0      56    6631
    wuxiabox chapter (prose)          0     122   19478
    madara reader (comic)             4       0       0
    madara chapter page (comic)       0       0       0
    vcomics reader (comic)            3       0       0

**Blocks separate them; characters do not.** 0 against 56 and up — and blocks
keep separating them when an image reader yields no images at all (row 5),
which is the case the floor was really guarding. The rule is now one block plus
a small residual character floor. Asking for *three* blocks was the first
attempt and an existing test caught it: a chapter served as one long paragraph
is still a chapter. `blocks_from` splits on `<br>`, so a single-`<p>` chapter
still reads as many blocks — wuxiabox's 122 come from one paragraph.

**Asking the wrong question to select a container.** `rewayat.fetch_text` used
`looks_like_prose` to *pick* its reader, so a short chapter failed with "the
reader's markup has changed" — wrong twice over: the markup was fine and the
chapter was readable. `riwayatarab`, which takes its container directly, read
the same input correctly, so the two adapters disagreed about the same chapter.
Whether a site serves prose is settled once; what is left is finding where it
put it. Selection is now "the first candidate that yields blocks".

**A selector whose absence is an answer must not cost the full timeout.**
`riwayatarab` search waits for a result link, which legitimately never appears
when a query has no matches, so every unsuccessful search paid the configured
10s. Measured: **12.2s** for an unanswerable query against 1.0s for a site that
settles quickly, and in a thirteen-site book fan-out that one site reported
`timeout` and pushed the whole search to its 20s ceiling. `fetch_html` now
takes an optional per-call `wait_timeout` (defaulting to the configured one, so
every existing caller is unchanged) and that search bounds itself to 4s. The
`wait_ms` settle went too: `_settled_content` only applies it when the selector
missed, and here a missed selector *is* the answer. Re-measured: **4.5s**.

Not a fixed delay instead — that would return before results mount on a slow
render and report "nothing found", trading a slow search for a wrong one.

**`owns_its_host` on a host you do not own.** `AcoAdapter` claimed all of
`sites.dlib.nyu.edu`, which is NYU's DLTS viewer serving many collections —
book ids are collection-prefixed and its root is a bare "Index of /". Because
`owns_its_host` skips fingerprinting entirely, every unrelated URL on that host
routed to ACO. Now guarded by `/viewer/books/`, the way `dlib.nyu.edu` was
already guarded by `/aco`. The adapter genuinely reads the *viewer*, not the
collection, and its docstring now says so — while `SOURCES.md` still claims
only ACO, because only ACO has an artifact.

**Documentation cited tools that would not exist in a clone.** `.gitignore`
excluded `scratchpad/*` wholesale while `SOURCES.md`, `HANDOFF.md` and the WP-8
recipe named `audit_search.py`, `probe_novels.py` and others as how to
reproduce a result. The curated evidence tooling is now allowlisted and a test
asserts every cited path exists and is not ignored; one-off probes stay
untracked, and a second test pins that too. `probe_aco.py` was ACO-shaped only
by accident — it is now `probe_network.py`, takes a URL, and filters analytics
out of the capture.

**When two measurements of one thing disagree, the disagreement is the
finding.** This session's recurring shape: string versus integer chapter
numbers on WuxiaBox, a `None` cross-check read as a passing one on RiwayatArab,
and here a character floor and a block count disagreeing about what a chapter
is. In each case the cheaper measurement was the one quietly lying.

## Findings — 2026-09-08, live health check of every shipped source

Ran the search gate against all **21 configured search URLs** and a real
download against all **24 sources with a retained artifact**. Report and
transcripts: `docs/evidence/health/`.

**No site is broken.** 21/21 answer a real query and return nothing for an
unanswerable one; 24/24 still download and pass artifact inspection, including
Noor's 111-page reader-bound PDF and ACO's 524-page 262 MB PDF.

**The one failure was the harness, and it exposed a real gap.** ACO reported
*"No selectable chapter matches the requested number/format"* for `--chapter 2`
because its chapters carried **no `number` at all** — and neither did
Gutenberg's. Both offer one book in several formats, so nothing that addresses
a chapter by number could reach the second one. Both now number each format by
position. It is selection only: `file` packaging still names each download
after the book, and `format_chapter_number` already fell back to the index, so
nothing that was working changed. Verified by taking ACO's *low*-resolution
copy on its own: 53,216,484 bytes against the high-resolution 262,256,337, both
524 pages.

**A source with several formats needs a number even though the UI never uses
one.** The web UI selects by checkbox, so this gap was invisible there and only
appeared the first time something addressed a chapter by name. Worth checking
for whenever an adapter builds chapters positionally from a list of files.

**Re-running a known-good chapter is not the same as re-running the source.**
Two sources needed their original parameters to be checked at all: 3asq's
chapter 1 has six source images that 404 (documented; the verified artifact is
chapter 420), and MangaDex needs `--language en` for this title. A health check
that ignores those reports two false failures.
