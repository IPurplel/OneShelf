# OneShelf development

The supported deployment entry point is `bash startup.sh`. It builds local
source through `deploy/docker-compose.yml` and `deploy/Dockerfile`. There is
no frontend build step.

## Tests

For development checks, install `requirements-dev.txt` into an isolated Python
environment. The application dependencies are pinned in `requirements.txt`.

```bash
python -m pytest -q
python -m pyflakes app tests
bash -n startup.sh
```

The test suite uses saved HTML and fake network clients. Startup tests run the
real Bash script against a simulated Docker CLI; they do not build a container.
Run these tests on Linux or another environment with `/bin/bash` and `/bin/sh`.

Before releasing deployment changes, also validate the resolved Compose
configuration and run a clean installation on a Docker-capable host. Confirm
browser startup, health, writable volumes, restart/recreation persistence, and
UI/API/live progress from another LAN device.

## Code layout

- `app/adapters/`: identify source platforms and extract titles, chapters, and files.
- `app/session.py` and `app/browser.py`: browser sessions and page retrieval.
- `app/fetcher.py`: HTTP requests, retries, and image fetching.
- `app/queue.py` and `app/packager.py`: resumable jobs and archive creation.
- `web/`: browser UI, served by the application.
- `tools/optimize_cbz.py`: optional utility for existing CBZ files.

For a new source adapter, subclass `Adapter`, implement its extraction methods,
and register it in the adapter registry. Prefer DOM fingerprints to hostname
checks when supporting a shared site theme. Add saved HTML fixtures and test
both useful matches and unrelated searches that should return nothing.

[HANDOFF.md](../HANDOFF.md) preserves historical source investigations. Treat
its measurements as observations from those sessions, not current guarantees
about external sites or deployment instructions.

## Adding a source: reader to file

If content can be **read** in a browser without an account, this tool should be
able to **save** it — whether or not the site offers a download button, and
never using one that requires an account. A site that gates readable content
behind an account, subscription or purchase is excluded, not worked around.

The steps below are in cost order. Stop at the first that works; each one is
cheaper and more durable than the next.

### 1. Find where the content actually lives

Do this before writing anything. The page a reader lands on is often not where
the content is.

1. **Server-rendered HTML.** Fetch the page with plain HTTP and look. Cheapest
   by far, and more common than it looks.
2. **A hydration payload.** Astro islands, `__NEXT_DATA__`, Nuxt state, a
   query-cache blob. *azoramoon* server-renders its entire 165-chapter list
   into an `astro-island`'s `props` attribute on a page showing 21 anchors —
   counting `<a>` finds the newest twenty and no amount of scrolling adds any.
   **Look in the payload before concluding something is not there.**
3. **An XHR the reader makes.** Capture the network rather than guessing:
   drive the page with patchright, log every request, and read the list.
   `scratchpad/probe_network.py <url>` does exactly this. It is how
   *Arabic Collections Online* was solved — its book page is a 6.5 KB
   JavaScript shell with no title, no author and no file, and one capture found
   a **IIIF Presentation 3.0 manifest** holding the entire record, including
   the whole book as a single PDF.
4. **The rendered DOM.** Last, because it is the slowest and the most fragile.

**A 200 is not content.** This project has met domains for sale, ad-network
redirects and challenge shells all answering 200 — one of them with a 114-byte
body. Check the final URL and the body size before believing a status code.

### 2. Prefer the file the site already made

If the site publishes the whole work as a file, take it. ACO offers its books
as bound PDFs through the manifest's `rendering` array; assembling the same
book from its 524 IIIF page images would be slower, larger and worse. Only mint
per-page URLs when there is no whole-object download.

### 3. Mint stable URLs and hand them to the ordinary fetcher

Do **not** build a private download loop. Produce `Page` objects and let
`app/fetcher.py` do the work — rate limiting, retries, resume, quality
upgrading and the HTTP/1.1 downgrade all come free, and a source-specific
loop gets none of them. *Noor* mints its reader's SVG page URLs this way and
inherits the per-host rate limit that finally made a complete book land.

### 4. Unwrap in `transform_page()` if the payload is not an image

SVG wrappers, base64 data URIs, canvas blobs, XOR-obfuscated bytes. Unwrap
**before** `validate_image()`.

### 5. Choose the container from the chapter, not the class

`packaging_for(chapter)` decides: `cbz` for comics, `pdf` for scanned books,
`text` for prose, `file` for a real linked document. It **may be async**, and
for some sources it has to be: a platform's theme is markup and says nothing
about what a site puts in it. *kolnovel* runs MangaThemesia and *cenele* runs
Madara, and both serve Arabic web novels — so those adapters open the chapter
and ask. `prose.looks_like_prose` is the decision.

Prose then goes through `prose.blocks_from` and `packager.write_epub`, which
already handle `<br>`-separated paragraphs, document order and RTL languages.

Note the division of labour, and keep it: `adapters.base.SITE_CONTENT_TYPES`
is a **declaration**, used by `/api/sources` where nothing may be fetched;
`packaging_for` is a **detection**, made from the chapter itself.

### 6. Verify the artifact, then verify the *count*

`scratchpad/verify_dl.py <url>` runs preview → real queue → artifact
inspection against isolated storage. It decodes every CBZ page and rejects
anything under 600px, renders PDF pages, and follows an EPUB's own spine.

**That is not enough on its own.** A file can be complete, valid, openable and
still wrong:

- *comix* returned **3 pages of a 12-page chapter**. All three were real,
  full-size, 785×1200, and packed into a perfectly good CBZ. The reader mounts
  pages as they scroll into view; `fetch_html(scroll_for=…)` is the fix.
- *WEBTOON*'s `src` is a shared transparent spacer; the real page is in
  `data-url`. A chapter of 1×1 images validates perfectly.
- *kolnovel* returned **8 "pages"**, every one an analytics tracking pixel,
  because the image harvester fell back to scanning the whole document when it
  could not find the reader. They answer 200 and are not 1×1.

So check the count against something the *source* says: the manifest's canvas
count, the reader's page total, the chapter list's length. ACO's 524-page PDF
matching its 524 canvases is what makes that artifact evidence.

### 7. Check the chapter list for holes and doubles

The list is where silent, long-lived bugs live, because a preview looks fine.

- **A list longer than its highest chapter number means duplicates.**
  *WuxiaBox* publishes some chapters under two URLs, one zero-padded
  (`…_46.html` and `…_0046.html`): 1,333 links for 1,216 chapters. Key on the
  chapter number, not the URL.
- **Pagination is not obvious.** *Sunovels* is zero-based. *WuxiaBox* is
  zero-based **and** overlapping — `page=1` is chapters 91-190, a stride of 90
  against a page size of 100. Measure the first row of the second page.
- **One row can hold more than one link.** *kolnovel* puts an unlabelled
  `/pdf/` anchor beside every chapter; reading every `<a>` counted each chapter
  twice and could download the wrong one. Walk rows, not anchors.

### 8. Search: both halves, or no search at all

A source joins `search_sites` only when it returns real hits for a real query
**and nothing** for one it cannot answer. Seven sites in this project have
answered an unanswerable query with a front-page grid, a latest-posts widget or
their whole catalogue. `base.query_matches()` is the gate; `scratchpad/audit_search.py`
runs both halves. A site that cannot answer is paste-by-URL only — that is a
complete outcome, not a failure.

Gate a *generic* sweep, never the site's own result cards: ranking near misses
is `/api/search`'s job, and gating them twice drops what it exists to rank.

### 9. Fixtures from real pages, always

Capture what the site actually served, record how in a `PROVENANCE.md` beside
it, and trim only what the code never reads (ACO's manifest keeps everything
but its 524 page canvases). Hand-written fixtures pass while the adapter is
silently wrong: the Madara adapter passed invented markup while mis-ordering
chapters and downloading thumbnails, and *kitaboka* shipped with its two
hostnames the wrong way round — every search fetching an empty document — for
as long as its fixtures agreed with the mistake.

## Source verification (WP-0)

Create a separate Linux environment when the existing `.venv` is a Windows
installation; do not replace it:

```bash
python -m venv .venv-linux
. .venv-linux/bin/activate
python -m pip install -r requirements-dev.txt
export PYTHONIOENCODING=utf-8
```

The audit tooling lives in `scratchpad/` and is **tracked**, because the
evidence in `SOURCES.md` and `HANDOFF.md` cites it by name: `verify_dl.py`
(preview -> queue -> artifact inspection), `audit_search.py` (the positive and
negative search gate), `triage_sites.py` / `triage_pass2.py` (inventory
reachability), `measure_arabic.py`, `probe_novels.py`, `probe_network.py`,
`probe_via_app.py`, `wp4_search_again.py` and `fix_endings.py`. The `.gitignore`
allowlist is the record of which those are; everything else under `scratchpad/`
is a one-off probe kept locally and deliberately not tracked. Run the real download pipeline with:

```bash
MD_CONFIG_FILE=/dev/null MD_DESYNC_ENABLED=false MD_HEADLESS=true \
  python scratchpad/verify_dl.py https://www.gutenberg.org/ebooks/84 --format epub
python scratchpad/audit_connectivity.py
```

The first command uses application defaults and direct HTTP, as used for the
WP-0 Gutenberg artifact. Omit those overrides to retain your configured network
route. Every verifier run creates a unique directory below `.state/verification`
(or the **parent** supplied with `--out`), containing independent configuration
storage, database, browser profile, downloads, `run.log`, and `evidence.json`.
It never attaches an existing browser or imports its cookies. Success and failure
artifacts stay on disk; `--keep` is accepted for compatibility but is unnecessary.
`--timeout` bounds the asynchronous preview/download phase (default 600 seconds);
local artifact inspection and cleanup may take additional time.

Verification decodes all CBZ pages and rejects widths below 600 pixels, opens and
renders every PDF page, and follows each EPUB's own container/OPF/spine before
rendering it. Reader-generated PDF and CBZ page counts must match the queue's
source page count. Direct files count as one transport item, so that queue count
is not compared to their internal page count. EPUB counts distinguish spine
items from renderer-dependent pages. The app's shallow PDF/signature checks and
its generated-EPUB-specific verifier alone are not sufficient source evidence.
MOBI/AZW3 signature checks cannot establish readability here; those formats
require a separate reader inspection and the script does not issue a pass.
These checks detect structural failures, not every possible content error; inspect
representative pages and compare against the source before advertising support.

The connectivity tool binds an ephemeral loopback HTTP server and isolates all
state under `.state/connectivity`. It calls the real `POST /api/connectivity`
for every effective `search_sites` URL. A labelled supplemental GET using the
same route and UA captures redirects and DOM fingerprints, which the endpoint
does not expose. It retains an atomic `connectivity.json` in each run directory, checkpointed
after every endpoint response, and prints a transcript. Failed endpoint calls
become `audit_error` results without aborting the remaining hosts. Startup
failures and partial results are retained too. The curated WP-0 snapshot is in
[the evidence report](evidence/wp0/REPORT.md); later runs never overwrite it.

[SOURCES.md](../SOURCES.md) defines the support ladder, including **TU** for
unavailable or insufficiently verified sources. HTTP success and a DOM match do
not establish search correctness, anonymous reader access, or a valid download.
