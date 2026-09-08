# Source evidence ledger

Reconciled 2026-09-08 UTC after Claude's WP-0–WP-5 work and initial
WP-6–WP-8 additions. Codex's changes and remaining tasks are recorded in
[CLAUDE_CONTINUATION.md](CLAUDE_CONTINUATION.md). The full 183-URL candidate
list is [docs/source-inventory.md](docs/source-inventory.md); its reachability
triage has run, but most candidates have not passed a reader/download audit.

The shipped defaults contain **21 search URLs: 13 Books, 7 Manga, 1 Comics**.
The table records **26 T4 hostnames, including aliases**, not 26 independent
platforms. User configuration can override the default search list.

**T0** excluded (account/purchase gate or shadow library); **T1** reachable;
**T2** positive *and* negative search proven; **T3** anonymous content
enumerable; **T4** complete artifact on disk, opened and inspected; **TB**
corroborated SNI filtering or an interactive Turnstile this environment cannot
clear; **TU** insufficient evidence for any other tier.

**T4 alone permits a support claim**, and T4 means a file: an absolute path, a
byte size, and a page or chapter count. "Search returns results" is not
evidence of support, and neither is "preview listed 400 chapters" — every
serious bug this project has shipped passed both and died at download.

Every artifact below was produced by `scratchpad/verify_dl.py`, which runs
preview → real queue → artifact inspection against isolated storage: it decodes
every CBZ page and rejects anything under 600px, renders PDF pages, and follows
an EPUB's own spine. Run directories are retained under `.state/verification/`;
the full paths and SHA-256 of each are in
[docs/evidence/wp2/](docs/evidence/wp2/) for that wave. Later retained reports,
including the novel adapters and ACO, are consolidated with absolute artifact
paths, sizes and hashes in
[source-reconciliation.json](docs/evidence/codex-2026-09-08/source-reconciliation.json).
The files were checked for existence and recorded byte size during this
reconciliation; that is not a fresh download of every source. Search verdicts come from
`scratchpad/audit_search.py`, which asks every configured site one query it can
answer and one it cannot — [search-audit.json](docs/evidence/wp2/search-audit.json).

## Verified sources

| Site | Adapter | Tier | Evidence | Checked |
|------|---------|------|----------|---------|
| 3asq.online | madara | T4 | `Hunter X Hunter - c420.cbz`, **47,861,046 bytes; 16 pages**, fully decoded/rendered; reached via 3asq.org, which redirects here | 2026-09-08 |
| 3asq.org | madara | T4 | `Hunter X Hunter - c420.cbz`, **47,861,046 bytes; 16 pages**, fully decoded/rendered; redirects to 3asq.online | 2026-09-08 |
| arabtoons.net | madara | T4 | `تسونادي وناروتو في الينابيع الحارة - c001.cbz`, **13,682,367 bytes; 14 pages**, fully decoded/rendered | 2026-09-08 |
| azoramoon.com | vcomics | T4 | `Solo Leveling_ Ragnarok - c001.cbz`, **54,702,501 bytes; 46 pages**, fully decoded/rendered | 2026-09-08 |
| azorafly.com | vcomics | T4 | same platform and catalogue as azoramoon.com, which it redirects to; `Solo Leveling_ Ragnarok - c001.cbz`, **54,702,501 bytes; 46 pages**, fully decoded/rendered | 2026-09-08 |
| 8ghrb.com | books | T4 | `رواية الختم الكرزي.pdf`, **2,281,142 bytes; 188 pages**, fully decoded/rendered | 2026-09-08 |
| www.noor-book.com | books | T4 | `Download Book White Nights Pdf.pdf`, **33,679,155 bytes; 111 pages**, fully decoded/rendered; bound from its anonymous reader, no account | 2026-09-08 |
| kitaboka.com | books | T4 | `تحميل رواية حكاية زهرة PDF.pdf`, **4,777,827 bytes; 246 pages**, fully decoded/rendered; reached after the norkitab alias was reversed | 2026-09-08 |
| norkitab.com | books | TU | Not a backend: 976 bytes of HTML 4 frameset wrapping kitaboka.com. Kept as a known host so a pasted URL resolves; it serves nothing itself | 2026-09-08 |
| www.planetebook.com | books | T4 | `Frankenstein.epub`, **489,464 bytes; 2 spine-item spine**, fully decoded/rendered | 2026-09-08 |
| bettergutenberg.org | books | T4 | `Brief Lives, Vol. 1.epub`, **532,260 bytes; 231 spine-item spine**, fully decoded/rendered | 2026-09-08 |
| www.gutenberg.org | gutenberg | T4 | `Frankenstein; or, the modern prometheus.epub`, **474,161 bytes; 32 spine-item spine**, fully decoded/rendered | 2026-09-08 |
| www.royalroad.com | royalroad | T4 | `Mother of Learning - c001.epub`, **19,054 bytes; 1 spine-item spine**, fully decoded/rendered | 2026-09-08 |
| archiveofourown.org | ao3 | T4 | `Good Omens.epub`, **8,450 bytes; 4 spine-item spine**, fully decoded/rendered; site-provided EPUB, anonymous | 2026-09-08 |
| www.webtoons.com | webtoons | T4 | `Lore Olympus - c001.cbz`, **16,623,099 bytes; 84 pages**, fully decoded/rendered; free episode; `data-url`, not the spacer in `src` | 2026-09-08 |
| mangadex.org | mangadex | T4 | `Kuro no Shoukanshi - c001.cbz`, **28,793,525 bytes; 37 pages**, fully decoded/rendered; `--language en`; this title has no `ar` translation | 2026-09-08 |
| www.mangaread.org | madara | T4 | `Emperor of Solo Play - c001.cbz`, **13,572,089 bytes; 22 pages**, fully decoded/rendered | 2026-09-08 |
| manhuaplus.com | madara | T4 | `Martial God Chat Group - c001.cbz`, **10,168,699 bytes; 15 pages**, fully decoded/rendered | 2026-09-08 |
| comix.to | comix | T4 | `Attack on Titan - c001.cbz`, **4,766,673 bytes; 12 pages**, fully decoded/rendered; **12 pages, not the 3 the reader showed before scrolling** — see HANDOFF | 2026-09-08 |
| arcomixverse.blogspot.com | blogger | T4 | `ABSOLUTE BATMAN - Comicverse - c001.cbz`, **21,073,521 bytes; 52 pages**, fully decoded/rendered; unblocked by the stylesheet-fingerprint fix | 2026-09-08 |
| aco.dlib.nyu.edu | aco | T4 | `Sharḥ dīwān al-Mutanabbī v.3 (high resolution).pdf`, **262,256,337 bytes; 524 pages**, every page rendered — matching the manifest's 524 canvases exactly. Search proven in both scripts (10 hits for `المتنبي`, 10 for `mutanabbi`, 0 for the sentinel) | 2026-09-08 |
| kolnovel.com | mangathemesia | T4 | `هيمنة الإمبراطور - c001.epub`, **8,869 bytes; 1 spine item, 17 rendered pages** of Arabic prose; 6,703 chapters listed. A **novel site running a manga theme** — see below | 2026-09-08 |
| cenele.com | madara | T4 | `Cultivation Online - c001.epub`, **9,395 bytes; 1 spine item, 11 rendered pages**; 1,120 chapters listed (was 0 — its post-type slug is `/cont/`, not `/manga/`) | 2026-09-08 |
| riwayatarab.com | riwayatarab | T4 | `الإمبراطور الشيطاني - c001.epub`, **6,607 bytes; 1 spine item, 7 rendered pages**; **1,344 chapters** resolved, matching the count the site advertises in its own JSON-LD. Search proven both ways (11 hits for `الشيطاني`, 0 for the sentinel) | 2026-09-08 |
| rewayat.club | rewayat | T4 | `رواية ساطور الخطيئة - c001.epub`, **6,257 bytes; 1 spine item, 5 rendered pages**; **955 chapters** resolved, contiguous 1–955. Search proven both ways (1 hit for `ساطور`, 12 for `رواية`, 0 for the sentinel) | 2026-09-08 |
| wuxiabox.com | wuxiabox | T4 | `Absolute Resonance - c001.epub`, **9,390 bytes; 1 spine item, 15 rendered pages**; **1,216 distinct chapters** resolved from 1,333 listed links — see below | 2026-09-08 |
| sunovels.com | sunovels | T4 | `Cultivation Online - c001.epub`, **13,980 bytes; 1 spine-item spine**, fully decoded/rendered; prose chapter as EPUB; URL-only, it has no usable search | 2026-09-08 |

### RiwayatArab: a 200 that means "not found"

Next.js App Router, and the parts behave differently. A **valid** novel page is
server-rendered — 138 KB with its chapter links in the markup. A **missing**
one is also 200, rendering a 16 KB shell titled *"رواية غير موجودة"* with zero
anchors, which is indistinguishable from a client-rendered page that has not
finished. The adapter checks for a title and says "probably gone" rather than
reaching for a browser.

Its **search** genuinely is client-side: over plain HTTP `/search?q=الشيطاني`
returns 25 KB whose `<title>` names the query and which links nothing at all.
That page costs a browser render; everything else here does not.

Chapter pagination is one-based and non-overlapping — worth stating only
because the previous two paginated sources were neither.

### Rewayat Club: the list is on the chapter, not the novel

The novel page shows the newest 24 chapters of a serial running to 955, with no
pagination control and no "all chapters" link — and three guessed
`api.rewayat.club` endpoints answer 404. It looked unsolvable, and was recorded
that way for a while.

Every **chapter** page carries the whole list. This is a Nuxt app, and each
chapter's hydration payload holds an `allChapters` array covering the entire
serial. Two details decide whether reading it works:

- It is **minified JavaScript, not JSON**. `value` is a reference to a
  single-letter variable assigned earlier in the same function, so the chapter
  number has to come from the literal `text` instead.
- **The entry for the chapter you are on is not a literal.** It is built by
  assignment (`i.text=e`), so a regex over `text:"…"` returns 954 of 955 — and
  *which* one is missing depends on which chapter you fetched. Both ends are
  pinned by fixtures: chapter 1's payload omits 1, chapter 955's omits 955.

Its search lives at `/library?search=`; `/search?q=` renders a page that
mentions the query and links nothing.

### WuxiaBox: 1,333 links, 1,216 chapters

A new adapter, and the whole of it is chapter-list arithmetic. Three traps, all
measured on `absolute-resonance`:

- The chapter list is behind `?tab=chapters`, a different page from the novel.
- The listing is **zero-based *and* overlapping**: `page=1` returns chapters
  **91–190**, not 101–200 — 100 rows at a stride of 90.
- The site publishes some chapters under **two URLs**, one zero-padded:
  `…_46.html` and `…_0046.html` are the same chapter.

De-duplicating on the URL handles the overlap and misses the padding entirely,
which would have downloaded and packaged **117 of 1,216 chapters twice**.
Chapters are keyed on their number instead.

Its chapters are one `<p>` and 234 `<br>`; `prose.blocks_from` already splits on
`<br>`, so the prose path took it unchanged.

26 numbers between 1 and 1,242 are absent from the site's own listing. The
adapter offers what the site lists; whether unlisted chapters exist at those
URLs could not be established, because the site began rate-limiting before it
could be checked.

### Arabic Collections Online: read the API, not the page

The page a reader lands on is a **6.5 KB JavaScript shell** — no title, no
author, no file. Everything is in a IIIF Presentation 3.0 manifest the viewer
fetches: the title in English *and* Arabic, the metadata, `viewingDirection:
right-to-left`, 524 page canvases, and — the part that matters — a `rendering`
array offering **the whole book as one PDF** in two resolutions.

So the adapter reads one JSON document. It deliberately takes the bound PDF
rather than assembling 524 JPEGs from the IIIF Image API: the site has already
done that work, and rebuilding it would be slower, larger and worse. This is
Group H's "look for the API before scraping HTML", and it paid.

### Two novel sites now download, and the fix was not per-site

`kolnovel.com` and `cenele.com` are Arabic web-novel sites running MangaThemesia
and Madara respectively. Both adapters assumed a chapter is pictures. They now
ask the chapter instead — `packaging_for` may answer asynchronously, and
`prose.looks_like_prose` decides — so the chapters come out as EPUB through the
text path that already existed for Sunovels and Royal Road.

Fixing them surfaced three bugs that were not about novels at all:

- **MangaThemesia counted every anchor in a chapter row as a chapter.** kolnovel
  puts an unlabelled `/pdf/` link beside each one, so a 6,703-chapter novel
  listed **13,406** — and the `/pdf/` copy could win the sort and be downloaded.
- **MangaThemesia harvested images from the whole document** when it could not
  find `#readerarea`. On kolnovel that returned **8 "pages", every one an
  analytics tracking pixel**. They download with a 200, so nothing downstream
  would have caught it.
- **Madara required `/manga/` in every chapter path.** The slug is configurable;
  cenele uses `/cont/`, so all its chapters were discarded and the site reported
  "could not read the chapter list" against a page whose list had parsed fine.

The three existing Madara sites were re-verified afterwards and produced
**byte-identical** artifacts, so none of this changed what already worked.

Both are filed under **Books**, not Manga: the content kind is now the site's
rather than the adapter's (`adapters.base.SITE_CONTENT_TYPES`). Verified
through the running API — `/api/sources` counts 10 book sites, 7 manga, 1
comics, and a Books search for `هيمنة` returns the kolnovel series tagged
`book`.

### The novel sweep so far

`wuxiabox.com` is done (above). What the other live novel sites turned out to
be, probed 2026-09-08 through the app's own session:

| Site | State | What was established |
|---|---|---|
| rwaiaty.com | T1 | A WordPress blog with `/author` and Arabic category paths, not a `/novel/` structure |
| ruya.com | T0 (mislabelled) | **Not an Arabic novel site.** WordPress 7.0.2 serving Turkish dream interpretation — `/ruyada-yumurta-sarisi-gormek`, `/harf/…`. The inventory's category is wrong; nothing to support here |
| novelfull.com · novelfire.net · freewebnovel.com · readnovelfull.com | unproven | Answered 39–105 KB of real content to the triage and ~5 KB Cloudflare pages to a rapid probe loop hours later. Nothing recorded either way: they need probing through the app's session, spaced out |
| wanderinginn.com | T1 | 901 KB table of contents, 835 chapter links, and a chapter of 163 paragraphs — but WordPress **via Elementor**, so no `.entry-content`; the prose sits in an `.elementor-*` container needing its own selectors |

**Framework did not predict markup, again.** `novelfull` and `readnovelfull`
share a URL shape but not markup with `wuxiabox`. There is no platform-sized
cluster among these: they are individual adapters, or small families at best.

## Not verified

| Site | Adapter | Tier | Reason | Checked |
|------|---------|------|--------|---------|
| manga-starz.net | madara | TB | `ERR_CONNECTION_RESET` before any HTTP response, in `curl` **and** the browser — the ISP-level SNI filtering this project documents. Not an adapter fault; re-testable on an unfiltered network. Removed from `search_sites` so it cannot cost every manga search a timeout. Its redirect target `starzmanga.com` answers HTTP 200 and is a candidate once a chapter has landed | 2026-09-08 |
| www.scribblehub.com | scribblehub | TB | `ChallengeError: Challenge did not clear within 20s`. Plain `curl` gets HTTP 403. This container has never cleared an interactive Turnstile — bundled Chromium 131 never passes, and Chromium 151 over `browser_cdp` did not either, headless. Code and tests kept | 2026-09-08 |
| rizzfables.com | mangathemesia | T3 | Parses, lists chapters and enumerates page URLs correctly — then **every image 404s**: `cdn.rizzfables.com` answers **HTTP 526** (Cloudflare, invalid origin certificate) to every request *including its own root*, under plain `curl` with and without a Referer. The site's own infrastructure, not a bot check and not this network. Removed from `search_sites`; returns the moment its CDN does | 2026-09-08 |
| ktobati.com | — | T0 | Reaching readable content requires an account. The adapter's own error told the user to "sign in to Ktobati in the app's persistent browser profile and make sure your account is allowed to download this book" — instructing someone to authenticate is not a download path. Removed from `KNOWN_HOSTS`, from the browser-session hosts, and from the tree's claims | 2026-09-08 |

### MangaThemesia: prose verified; image downloads remain unproven

The adapter has produced a verified EPUB from **kolnovel.com** using its
chapter-specific prose routing. Its image path still lacks a successful live
artifact: rizzfables is blocked by its own CDN (above). A spot check of the
MangaThemesia candidates in the meta prompt's Group D found none still carrying
the theme's fingerprint:
`asuracomic.net` now redirects to `asurascans.com` and is a different stack
entirely, `flamecomics.com` and `rawkuma.com` carry no TS markers, and
`gate-manga.com`, `golden-manga.com` and `areamanga.com` did not resolve.
Group D was a **hypothesis list, not a verdict list**; the completed WP-5
reachability triage supersedes it.

### The `generic` adapter

A heuristic fallback for pages no adapter claims, not a source. It has no site
of its own to verify and makes no support claim.

## Historical WP-2 changes

- At the end of WP-2, `search_sites` held **16 sites, every one of them T4**.
  Later additions brought it to 21. Two came out during WP-2:
  `manga-starz.net` (TB) and `rizzfables.com` (T3).
- `ktobati.com` is excluded outright under the no-account rule.
- `kitaboka.com` moved from *never produced a file* to T4 — its search was
  querying `norkitab.com`, which is a frameset wrapper, not a backend.
- `comix.to`, `blogger` and `bettergutenberg.org` produced their first files.
- Six adapters that had never produced anything — `mangathemesia`, `comix`,
  `blogger`, `generic`, `kitaboka`, `ktobati` — now each have a tier and the
  evidence behind it.

## Coverage against the supplied inventory

The user supplied 183 candidate URLs and asked for a majority verified.
**10 supplied hostnames** match T4 rows after removing only `www.`:
`3asq.org`, `cenele.com`, `gutenberg.org`, `kolnovel.com`, `mangadex.org`,
`noor-book.com`, `rewayat.club`, `riwayatarab.com`, `royalroad.com`, and
`wuxiabox.com`. Arabic Collections Online is additionally verified at
`aco.dlib.nyu.edu`; the inventory lists its parent `dlib.nyu.edu`, so this is
related collection coverage, not an exact-host match. The 92-site target is
still unmet. Counts and the exact comparison are retained in the reconciliation
JSON above.

## WP-5 — the 183 supplied sites, triaged 2026-09-08

Full report: [docs/evidence/wp5/REPORT.md](docs/evidence/wp5/REPORT.md);
raw probes in [triage.json](docs/evidence/wp5/triage.json) and
[triage-pass2.json](docs/evidence/wp5/triage-pass2.json). No tier is assigned
from a homepage fetch — this is a work queue, not a support claim.

| Outcome | Count |
|---|---|
| Live — returned real content | **74** |
| Not live — dead, parked, challenged, or unreachable even through the bypass | **80** |
| Excluded — account gate (Group A) or shadow library (Group B) | **29** |

Two results change the plan:

- **Group D does not hold.** Of the ~32 sites the meta prompt expected an
  existing adapter to claim outright, exactly **one** does (`kolnovel.com`, and
  as MangaThemesia rather than the Madara it was listed under). WP-6 is worth
  about four sites, not thirty-two.
- **Some novel sites run manga platforms' themes.** `kolnovel.com` initially
  listed 13,406 links and then failed on "no page images": its chapters are
  **180 `<p>` and 0 `<img>`**. Subsequent work removed duplicate PDF links,
  yielding **6,703 chapters**, and added prose routing for KolNovel and Cenele.
  This is proven on those two sites; the other novel sites need individual
  markup checks.

**This snapshot does not establish a path to 92 verified sites**: only 74
were classified as live and not excluded in that run. Unavailable sources may
recover; homepage reachability alone does not establish anonymous reader access.

## Next evidence gates

Finish the remaining WP-6 candidates (`www.rwayat.online`, Hindawi and the
Blogspot series-page investigation) with an anonymous reader check and either
a verified artifact or a recorded reason for stopping. Continue WP-7 by reader
markup rather than framework labels; TeamX and The Wandering Inn remain leads.
The WP-8 extraction recipe is already in `docs/development.md`; reconcile its
five-reader evidence requirement explicitly. WP-9 still needs a complete
inventory-to-evidence table and preservation of the ignored audit scripts.
Use the ranked checklist in [CLAUDE_CONTINUATION.md](CLAUDE_CONTINUATION.md).
