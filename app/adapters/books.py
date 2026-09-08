"""Adapter for book sites: pages that link straight to an EPUB, PDF or MOBI.

Books do not fit the manga model and this adapter does not pretend otherwise.
There are no pages to order and nothing to package: the site links a finished
file, and the file *is* the artifact. So the mapping is deliberately flat —

    series  = the book page              (its title, its cover, its blurb)
    chapter = one downloadable file      ("agnes-grey.epub", "12.pdf")
    page    = that file's URL

which means a book with three formats arrives as three selectable items, and a
collection page listing seventy-two volumes arrives as seventy-two. The queue
sees ordinary work either way; only :attr:`packaging` tells it to write the
bytes through instead of building a CBZ.

Two rules, both learned by getting them wrong first:

* **Match on the extension in the path, never on the word "download".**
  Filtering by that word matched an Adobe help page linked in a footer.
* **Send the book page as the referer.** The file often lives on a different
  host from the site (8ghrb links bookleaks.com), and those hosts check.

Verified against planetebook.com (``/agnes-grey/`` → ``/free-ebooks/agnes-grey
.epub|.pdf|.mobi``) and 8ghrb.com (a page of 72 PDFs on bookleaks.com).
"""

from __future__ import annotations

import base64
import binascii
import logging
import json
import time
import re
from urllib.parse import quote, quote_plus, unquote, urlparse, urlsplit

from ..models import Chapter, Page, SearchResult, Series, sanitize_filename
from .base import Adapter, AdapterError, first_attr, query_matches

log = logging.getLogger(__name__)

#: Extensions that make a link a book. Kept in step with the packager's
#: LIBRARY_EXTENSIONS, minus .cbz — a comic archive is the other pipeline's job.
BOOK_EXTENSIONS = (".epub", ".pdf", ".mobi", ".azw3")

#: A link is a book link when its *path* ends in one of those, before any query
#: string. Anchored so "…/report.pdf.html" is not mistaken for a PDF.
_FILE_RE = re.compile(
    r"\.(" + "|".join(ext.lstrip(".") for ext in BOOK_EXTENSIONS) + r")$", re.I
)


def _path_of(url: str) -> str:
    """The URL's path — via ``urlsplit``, which is the whole point.

    ``urlparse`` still implements RFC 2396 ``;params``, so it cuts the last path
    segment at a semicolon: bettergutenberg's
    ``/library/007_Frankenstein; or, the modern prometheus_pg84.epub`` parses to
    a path of ``…/007_Frankenstein`` with the rest — extension included — filed
    under ``params``. Every book link on that site then looks like no book link
    at all. ``urlsplit`` leaves the path whole.
    """
    return urlsplit(url).path

#: Sites confirmed to work. Matching one skips the fingerprint fetch; any other
#: site still has to prove itself by linking actual files.
KNOWN_HOSTS = {
    "planetebook.com",
    "8ghrb.com",
    "bettergutenberg.org",
    "arabic-book.net",
    # ktobati.com is deliberately absent. Its reader and its Download control
    # both require an account: the adapter's own error used to tell the user to
    # sign in and make sure their account was "allowed to download this book".
    # A site that needs an account to reach readable content is excluded, not
    # worked around, so it is neither a known host nor a search site.
    "noor-book.com",
    "kitaboka.com",
    "norkitab.com",
    # Hindawi's library, which now serves from safahat.org — hindawi.org/books
    # redirects there. Every book page links an official EPUB and PDF on
    # downloads.hindawi.org, anonymously; verified 2026-09-07 (a 2.45 MB EPUB,
    # 44 entries). Both hostnames are listed because the redirect is the thing
    # a pasted URL will still name.
    "safahat.org",
    "hindawi.org",
}

# Legacy browser sources. Noor now opens its anonymous reader over a
# cookie-preserving HTTP session first; its Download action remains unused.
_BROWSER_SESSION_HOSTS = {"noor-book.com"}

# Noor creates the final PDF anchor after its download-preparation script runs.
_NOOR_FILE_SELECTOR = 'a[href$=".pdf"], a[href*=".pdf?"]'

# ---------------------------------------------------------------- Noor's reader
#
# Noor's Download control is gated: it asks for an account, and on a title that
# has none of the licensing it wants it produces no link at all -- measured on
# a live book, the download click yielded zero PDF anchors while the same book
# read fine in the browser.
#
# Its *reader* is not gated. Clicking Read runs a page-by-page viewer that
# serves each page as an SVG wrapping a base64 PNG:
#
#     POST /en/book/read_book?o=<token>              opens the reader
#     GET  /book/read_book_image/0/<book>/<n>/<tok>.svg   page n
#
# Both hashes and the page count are in the DOM once the reader is open
# (``curr_reading_pages``, ``book_hash``, and the token in the first page URLs
# it lazy-loads), so the pages can be minted and handed to the ordinary fetcher
# -- rate limiting, retries and resume all come for free. The result is bound
# into a PDF rather than a CBZ: it is a book.
_NOOR_READER_SELECTOR = 'img[src*="read_book_image"]'
_NOOR_READ_TEXTS = ("Read", "اقرأ", "قراءة")

#: ``read_book_image/<set>/<book hash>/<page>/<session token>.svg``
_NOOR_PAGE_RE = re.compile(
    r"read_book_image/(\d+)/([0-9a-f]{16,})/(\d+)/([0-9a-f]{16,})\.svg"
)

#: The reader publishes the total as a plain global before the first page loads.
_NOOR_COUNT_RE = re.compile(r"curr_reading_pages\s*=\s*(\d+)")

#: Each page is an SVG whose only content is one embedded raster image.
_NOOR_EMBEDDED_RE = re.compile(
    rb"""xlink:href\s*=\s*["']data:image/(png|jpe?g|webp);base64,([A-Za-z0-9+/=\s]+)["']""",
    re.I,
)

#: A book with more pages than this is not a book, it is a parsing accident.
_NOOR_MAX_PAGES = 5000

#: Noor runs Google vignette ads, and an interstitial swallows the Read click
#: often enough that one attempt reports a readable book as unreadable.
_NOOR_READER_ATTEMPTS = 3

# 8ghrb search contains ordinary posts that only link to a Facebook group.
# Validate result pages before presenting them as downloadable books.
_SEARCH_FILE_CHECK_HOSTS = {"8ghrb.com"}

#: Below every comic adapter. A manga page that happens to link one PDF must
#: never be claimed as a book, and the comic adapters are the specific ones.
PRIORITY = 40

#: Anything longer is a page of links, not a book page.
MAX_FILES = 500

#: Both sites are WordPress, so search results are its usual post list. Themes
#: disagree about the wrapper — planetebook emits ``<article>``, 8ghrb's theme
#: emits ``<li class="post">`` — so several are tried in order of specificity.
RESULT_CONTAINERS = ("article", "li.post", "div.post", ".post-item", ".search-result")

#: Archive pages that a search result list links to but which are not books.
_ARCHIVE_PATHS = ("/category/", "/tag/", "/author/", "/page/", "/wp-content/")

#: How deep a book's own page sits, for sites whose section listings are
#: indistinguishable from their books. bettergutenberg builds both as ordinary
#: WordPress pages with `rel="bookmark"` — "Novels" and "Frankenstein…" differ
#: only in that a book lives *under* a section. Nothing else here can tell them
#: apart, and a global depth rule would be wrong: planetebook's books are at the
#: root (`/agnes-grey/`).
_MIN_PATH_DEPTH = {"bettergutenberg.org": 2}

#: Hosts whose ``<h1>`` is the section heading rather than the book's name.
#: Per host, like ``_MIN_PATH_DEPTH`` above and for the same reason: preferring
#: ``og:title`` everywhere would regress the sites whose h1 *is* the title.
_TITLE_IS_NOT_THE_H1 = {"safahat.org", "hindawi.org"}

IMAGE_ATTRS = ("data-src", "data-lazy-src", "data-original", "srcset", "src")


class BooksAdapter(Adapter):
    id = "books"
    name = "Book site (direct file links)"
    priority = PRIORITY
    content_type = "book"
    packaging = "file"
    """The queue writes each download through unchanged instead of packing it."""

    def packaging_for(self, chapter: Chapter) -> str:
        """Noor is bound from reader pages; every other site links a file.

        Per chapter rather than per class because these sites share everything
        else — the same search, the same series parsing, the same failure
        messages — and differ only in whether a finished file exists to fetch.
        """
        return "pdf" if _is_noor_reader(chapter.url) else self.packaging

    def transform_page(self, content: bytes) -> bytes:
        """Unwrap Noor's SVG-around-a-PNG; pass anything else through."""
        return _noor_unwrap(content)

    pages_expire = True
    """Re-list failed reader pages and retry only casualties.

    Noor's historical mid-book failures were throttling, not proven token
    expiry: the same URL worked later. Re-listing can still recover failures,
    but a conservative host rate is what prevents the sustained overload.
    """

    async def refresh_pages(self, chapter: Chapter) -> list[Page]:
        """Re-list after a failure, from a genuinely fresh page.

        The cache has to be dropped first or this hands back the same dead
        token it was called to replace.
        """
        page_url, _, _ = chapter.url.partition("#")
        self._cache.pop(page_url, None)
        return await self.fetch_pages(chapter)
    # Only consulted when the URL alone identified the site — here, one of
    # KNOWN_HOSTS. These are static pages; rendering one in a browser to
    # confirm what the hostname already said costs seconds and a Chromium.
    owns_its_host = True

    def __init__(self, session_manager) -> None:
        super().__init__(session_manager)
        self._cache: dict[str, str] = {}

    # -------------------------------------------------------- identification

    @classmethod
    def matches(cls, url: str, html: str | None = None) -> bool:
        host = urlparse(url).netloc.lower().removeprefix("www.")
        if host in KNOWN_HOSTS:
            return True
        if html:
            return bool(_file_links(html, url))
        return False

    # --------------------------------------------------------------- search

    search_path = "/?s={query}"

    async def search(self, site: str, query: str, limit: int = 12) -> list[SearchResult]:
        """Find books through the site's own search page.

        Both sites are WordPress and answer ``?s=`` properly — including
        returning nothing for a query they do not have, which is what makes
        them safe to put in a multi-site search. A result is a *book page*, the
        same thing you would paste in by hand, so picking one leads to the
        ordinary preview with its formats listed.
        """
        root = site.rstrip("/")
        if _host_of(root) == "noor-book.com":
            return await self._search_noor(root, query, limit)
        if _host_of(root) in {"kitaboka.com", "norkitab.com"}:
            return await self._search_kitaboka(query, limit)

        url = root + self.search_path.format(query=quote_plus(query))
        tree = self.parse(await self._get(url))
        host = urlparse(root).netloc

        results: list[SearchResult] = []
        seen: set[str] = set()
        for container in _result_nodes(tree):
            # Headings first and in order: the container's own first anchor is
            # usually the cover image, which carries the right URL and no text.
            link = next(
                (found for selector in ("h1 a", "h2 a", "h3 a", "h4 a", "a")
                 if (found := container.css_first(selector))
                 and first_attr(found, "href")),
                None,
            )
            href = self.absolute(url, first_attr(link, "href"))
            title = self.text(link) or (first_attr(link, "aria-label") or "")
            if not href or not title or href.rstrip("/") in seen:
                continue
            if urlparse(href).netloc != host or _is_archive(href) \
                    or href.rstrip("/") == root or _too_shallow(href, host):
                continue
            # A book site's search page is happy to render a widget of recent
            # titles whether or not anything matched, in the same markup as a
            # result. Nothing structural separates the two.
            if not query_matches(query, title, _path_of(href)):
                continue

            if _host_of(href) in _SEARCH_FILE_CHECK_HOSTS:
                try:
                    if not _file_links(await self._get(href), href):
                        continue
                except Exception as exc:
                    log.info("Skipping unavailable book result %s: %s", href, exc)
                    continue

            seen.add(href.rstrip("/"))
            cover = first_attr(container.css_first("img"), *IMAGE_ATTRS)
            results.append(SearchResult(
                # Not run through _clean_title: a result's anchor text is the
                # post title, with no site branding to strip, and these are
                # books — "“أمواج أكما – قواعد جارتين 3”" carries a dash of its
                # own that trimming would cut the title in half at.
                title=" ".join(title.split()),
                url=href, source=self.id, site=host,
                cover_url=self.absolute(url, cover),
            ))
            if len(results) >= limit:
                break
        return results

    async def _search_noor(
        self, root: str, query: str, limit: int
    ) -> list[SearchResult]:
        """Search Noor's tag index and exclude catalog-only records."""
        url = f"{root}/en/tag/{quote(query.strip(), safe='')}"
        tree = self.parse(await self._get(url))
        host = urlparse(root).netloc

        results: list[SearchResult] = []
        seen: set[str] = set()
        # Only /ebook- links: the filter below requires that segment anyway, so
        # also selecting /book/review/ ones collected rows that could never
        # survive it — and made the review branch of _noor_unavailable look
        # like it was doing work here when nothing ever reached it.
        for link in tree.css('a[href*="/ebook-"]'):
            href = self.absolute(url, first_attr(link, "href"))
            image = link.css_first("img")
            title = (
                self.text(link)
                or (first_attr(link, "aria-label", "title") or "")
                or (first_attr(image, "alt") or "")
            )
            title = " ".join(title.split())
            key = href.rstrip("/") if href else ""
            if not href or not title or key in seen:
                continue
            if urlparse(href).netloc != host or "/ebook-" not in _path_of(href):
                continue
            if _noor_unavailable(href, title):
                continue
            if not query_matches(query, title, _path_of(href)):
                continue

            seen.add(key)
            cover = first_attr(image, *IMAGE_ATTRS)
            results.append(SearchResult(
                title=title,
                url=href,
                source=self.id,
                site=host,
                cover_url=self.absolute(url, cover),
            ))
            if len(results) >= limit:
                break
        return results

    async def _search_kitaboka(
        self, query: str, limit: int
    ) -> list[SearchResult]:
        """Search Kitaboka for books that actually link a file.

        Kitaboka ignores a query it cannot answer and returns its catalogue --
        the same failure mode as rizzfables, azoramoon, arabic-book, sunovels
        and books.e3raf. Measured: the sentinel
        ``zzqvoneshelfnonexistent987654321`` came back with **27 book links**,
        overlapping the real query's results. ``query_matches`` is what turns
        that back into "nothing found", so it stays.
        """
        root = "https://kitaboka.com"
        url = f"{root}/books?search={quote_plus(query)}"
        tree = self.parse(await self._get(url))

        results: list[SearchResult] = []
        seen: set[str] = set()
        for link in tree.css('a[href*="/books/"]'):
            href = _canonical_kitaboka_url(
                self.absolute(url, first_attr(link, "href")) or ""
            )
            if not href or _host_of(href) != "kitaboka.com":
                continue
            path = _path_of(href)
            if not path.startswith("/books/") or path.startswith("/books/read/"):
                continue

            image = _result_image(link)
            title = (
                self.text(link)
                or (first_attr(link, "aria-label", "title") or "")
                or (first_attr(image, "alt") or "")
            )
            title = " ".join(title.split())
            key = href.rstrip("/")
            if not title or key in seen:
                continue
            if not query_matches(query, title, path):
                continue

            try:
                if not _file_links(await self._get(href), href):
                    continue
            except Exception as exc:
                log.info(
                    "Skipping unavailable Kitaboka result %s: %s", href, exc
                )
                continue

            seen.add(key)
            cover = first_attr(image, *IMAGE_ATTRS)
            results.append(SearchResult(
                title=title,
                url=href,
                source=self.id,
                site="kitaboka.com",
                cover_url=self.absolute(root, cover),
            ))
            if len(results) >= limit:
                break
        return results

    # ------------------------------------------------------------- fetching

    async def _get(self, url: str) -> str:
        """Fetch a page with the least expensive transport its source supports."""
        cached = self._cache.get(url)
        if cached is not None:
            return cached
        host = _host_of(url)
        if host in _BROWSER_SESSION_HOSTS:
            if host == "noor-book.com" and any(marker in unquote(_path_of(url))
                                                   for marker in ("/ebook-", "/كتاب-")):
                html = await self._open_noor_reader(url)
            elif host == "noor-book.com":
                try:
                    html = await self.sessions.fetch_text_direct(url)
                except Exception:
                    html = await self.get_html(url)
            else:
                html = await self.get_html(url)
            self._cache[url] = html
            return html
        try:
            html = await self.sessions.fetch_text_direct(url)
        except Exception as exc:
            log.info("Direct fetch of %s failed (%s); using the browser", url, exc)
            html = await self.get_html(url)
        self._cache[url] = html
        return html

    async def _open_noor_reader(self, url: str) -> str:
        """Use the anonymous HTTP reader; keep browser fallback for challenges."""
        try:
            return await self._open_noor_reader_direct(url)
        except Exception as direct_error:
            log.info("Noor HTTP reader failed for %s: %s", url, direct_error)
            try:
                html = await self._open_noor_reader_browser(url)
                if _noor_reader_pages(html) is None:
                    raise AdapterError("The browser returned no anonymous reader pages")
                return html
            except Exception as browser_error:
                raise AdapterError(
                    f"Noor reader did not open: HTTP ({direct_error}) and "
                    f"browser ({browser_error})."
                ) from browser_error

    async def _open_noor_reader_direct(self, url: str) -> str:
        """Replay the public reader's anonymous setup, never its Download flow.

        Captured 2026-09-08: GET book -> Verification/check_user (is_logged=0)
        -> book/read_book. The anonymous setup cookies must survive both POSTs;
        discarding them gives a 403. Image URLs themselves work independently.
        """
        async with self.sessions.direct_http_client() as client:
            response = await client.get(url)
            response.raise_for_status()
            html = response.text
            tree = self.parse(html)
            if tree.css_first(".read-btn") is None:
                raise AdapterError("This page has no anonymous Read control")
            values = {}
            for key in ("csrf_token", "crypto_token", "b_h", "book_hash"):
                match = re.search(r"var\s+" + key + r"\s*=\s*['\"]([^'\"]+)['\"]", html)
                if match is None:
                    raise AdapterError(f"Noor reader setup is missing {key}")
                values[key] = match.group(1)
            final_url = str(response.url)
            parts = urlsplit(final_url)
            root = f"{parts.scheme}://{parts.netloc}"
            locale = "/en" if parts.path.startswith("/en/") else ""
            headers = {"Referer": final_url, "Origin": root,
                       "X-Requested-With": "XMLHttpRequest"}
            setup = await client.post(
                root + locale + "/Verification/check_user",
                params={"o": str(time.time())},
                data={"csrf_token": values["csrf_token"], "book_hash": values["b_h"],
                      "_": values["crypto_token"], "ls": "null"}, headers=headers,
            )
            setup.raise_for_status()
            state = json.loads(setup.text)
            if state.get("x") or state.get("is_logged") not in (0, False):
                raise AdapterError("Noor did not establish an anonymous reader session")
            reader = await client.post(
                root + locale + "/book/read_book", params={"o": str(time.time())},
                data={"book_hash": values["book_hash"], "csrf_token": state["osf"],
                      "_": values["crypto_token"], "ls": state["ls"]}, headers=headers,
            )
            reader.raise_for_status()
            if _noor_reader_pages(reader.text) is None:
                raise AdapterError("Noor returned no pages for the anonymous reader")
            return html + reader.text

    async def _open_noor_reader_browser(self, url: str) -> str:
        """Click Read, and try again if an ad interstitial ate the click.

        Read, not Download: the download control is account-gated and on a live
        book produced no link at all, while the reader served the same book's
        124 pages without asking for anything.

        The retry is not defensive padding. Noor runs Google vignette ads, and
        an interstitial swallows the first click often enough that a single
        attempt reports a perfectly readable book as unreadable — observed as
        the page URL coming back with ``#google_vignette`` appended and no
        reader in the DOM.
        """
        last = ""
        failure: Exception | None = None
        for attempt in range(1, _NOOR_READER_ATTEMPTS + 1):
            try:
                last = await self.sessions.fetch_html_after_click(
                    url,
                    click_texts=_NOOR_READ_TEXTS,
                    consent_texts=("Agree", "موافق", "Close", "إغلاق"),
                    wait_for=_NOOR_READER_SELECTOR,
                )
            except Exception as exc:
                # A reset mid-navigation is the other way the reader fails to
                # open, and on a filtered connection it is intermittent — the
                # same URL loaded a minute earlier. Retried, then re-raised
                # rather than swallowed, so a real failure still surfaces.
                failure = exc
                log.info("Noor page load failed for %s (attempt %d/%d): %s",
                         url, attempt, _NOOR_READER_ATTEMPTS, exc)
                continue
            if _noor_reader_pages(last) is not None:
                return last
            log.info("Noor reader did not open for %s (attempt %d/%d)",
                     url, attempt, _NOOR_READER_ATTEMPTS)

        if not last and failure is not None:
            raise failure
        return last

    # --------------------------------------------------------------- series

    async def fetch_series(self, url: str) -> Series:
        url = _canonical_kitaboka_url(url)
        tree = self.parse(await self._get(url))
        candidates = [
            self.text(tree.css_first("h1")),
            _meta(tree, "og:title"),
            self.text(tree.css_first("title")),
        ]
        if _host_of(url) in _TITLE_IS_NOT_THE_H1:
            # On these sites the <h1> is the section heading, not the book:
            # every Hindawi/Safahat book page is headed "الكتب" ("Books"), so
            # taking the h1 named every book the same and made each download
            # collide with the last. og:title carries the real one.
            candidates.insert(0, candidates.pop(1))
        title = next((c for c in candidates if c), "Unknown Book")
        return Series(
            url=url,
            title=_clean_title(title),
            source=self.id,
            cover_url=self.absolute(url, _meta(tree, "og:image")),
            description=_meta(tree, "og:description") or _meta(tree, "description"),
        )

    # ------------------------------------------------------------- chapters

    async def fetch_chapters(self, series: Series) -> list[Chapter]:
        html = await self._get(series.url)

        # Noor serves a book only through its reader, so there is no file to
        # list: the whole book is one artifact, bound from its pages.
        if _host_of(series.url) == "noor-book.com":
            return _noor_chapters(series, html)

        links = _file_links(html, series.url)
        if not links:
            raise AdapterError(
                f"No book files are linked from {series.url}. This adapter "
                f"looks for links ending in {', '.join(BOOK_EXTENSIONS)} — some "
                "posts on these sites only point at a discussion group rather "
                "than hosting a file."
            )

        links = links[:MAX_FILES]
        by_title = _one_book_in_formats(links)

        chapters: list[Chapter] = []
        used: set[str] = set()
        for position, (href, label) in enumerate(links, start=1):
            if by_title:
                # One book offered in a few formats: name it after the book.
                # The site's own filename is often just an id ("2463.pdf"),
                # which is no use at all in a library.
                name = f"{series.title}{_extension(href)}"
            else:
                name = _filename(href, label, position, used)
            used.add(name.lower())
            chapters.append(Chapter(
                # The book page, not the file: it survives a restart, gives the
                # referer the file host wants, and keeps one identity per file
                # even when two formats share a filename stem.
                url=f"{series.url}#{position}",
                title=name,
                index=position,
            ))
        log.info("Found %d book file(s) on %s", len(chapters), series.url)
        return chapters

    # ---------------------------------------------------------------- pages

    async def fetch_pages(self, chapter: Chapter) -> list[Page]:
        page_url, _, fragment = chapter.url.partition("#")
        if _is_noor_reader(chapter.url):
            return _noor_pages(await self._get(page_url), page_url)

        links = _file_links(await self._get(page_url), page_url)
        try:
            position = int(fragment)
        except ValueError:
            position = 0
        if not (1 <= position <= len(links)):
            raise AdapterError(
                f"{chapter.title} is no longer linked from {page_url}; the page "
                "has changed since it was listed."
            )
        href, _label = links[position - 1]
        # The file host is often not the site host, and those hosts check.
        return [Page(index=1, url=_encoded(href), referer=page_url)]


# ----------------------------------------------------------------- helpers


def _host_of(url: str) -> str:
    return urlparse(url).netloc.lower().removeprefix("www.")


def _canonical_kitaboka_url(url: str) -> str:
    """Resolve either Kitaboka hostname to the one that serves the books.

    The alias runs the opposite way round to what this adapter first assumed.
    ``norkitab.com`` is not a backend: it answers **976 bytes of HTML 4
    frameset** whose only content is ``<frame src="…kitaboka.com/books">``.
    ``kitaboka.com`` serves the real 227 KB listing. Searching the mask
    returned an empty document every time, so the site answered nothing for
    every query -- measured 2026-09-08, against the captured fixtures in
    ``tests/fixtures/kitaboka``.

    The mask doubles the prefix on the links it does emit
    (``/books/books/…``, ``/books/storage/…``), so those are unwrapped.
    """
    if _host_of(url) not in {"kitaboka.com", "norkitab.com"}:
        return url
    parts = urlsplit(url)
    path = parts.path or "/"
    if path.startswith("/books/books/") or path.startswith("/books/storage/"):
        path = path[len("/books"):]
    return parts._replace(
        scheme="https", netloc="kitaboka.com", path=path
    ).geturl()


def _result_image(link):
    """Find the cover in a result link or its nearby card wrapper."""
    node = link
    for _ in range(5):
        image = node.css_first("img")
        if image is not None:
            return image
        node = node.parent
        if node is None:
            break
    return None


def _visible_text(html: str) -> str:
    """The readable text of a page, with markup, scripts and styles removed.

    Substring tests against raw HTML answer on things no reader ever sees. A
    class name, an ``aria-label`` or a string inside a minified bundle is enough
    to match a single word like "unavailable", and the page is then reported as
    restricted on the strength of a stylesheet. Match what the page *says*.
    """
    from selectolax.parser import HTMLParser

    tree = HTMLParser(html)
    for node in tree.css("script, style, noscript"):
        node.decompose()
    body = tree.css_first("body")
    return " ".join((body.text(strip=True) if body is not None else "").split())


#: Marks a chapter as "the whole book, read from Noor's viewer" rather than a
#: file to fetch. A fragment because a chapter is identified by its URL
#: everywhere — the database, the queue, resume — and this has to survive all
#: of them without a parallel field.
NOOR_READ_FRAGMENT = "read"


def _is_noor_reader(url: str) -> bool:
    page, _, fragment = url.partition("#")
    return fragment == NOOR_READ_FRAGMENT and _host_of(page) == "noor-book.com"


def _noor_reader_pages(html: str) -> tuple[int, str, str, str] | None:
    """``(count, set, book hash, session token)`` from an opened reader.

    ``None`` when the reader did not open — which is the only honest way to
    tell "this title is not readable" from "the click did not land", since Noor
    renders the same page either way.
    """
    found = _NOOR_PAGE_RE.search(html)
    count = _NOOR_COUNT_RE.search(html)
    if not found or not count:
        return None
    total = int(count.group(1))
    if not 1 <= total <= _NOOR_MAX_PAGES:
        return None
    return total, found.group(1), found.group(2), found.group(4)


def _noor_chapters(series: Series, html: str) -> list[Chapter]:
    """One chapter: the book itself, to be bound from the reader's pages."""
    reader = _noor_reader_pages(html)
    if reader is None:
        # Deliberately not guessing at *why*. The old code scanned the page for
        # the word "unavailable" and told the user the book was "not licensed
        # for distribution" — but every Noor book page carries a sidebar of
        # other titles each labelled "Unavailable", so that fired on a page
        # whose reader had simply been blocked by an ad interstitial. Saying
        # the reader did not open is the only thing that is actually known.
        raise AdapterError(
            "Noor Book's reader did not open for this title, so there are no "
            "pages to read. Retry or check the connection and reader in a browser."
        )

    total = reader[0]
    log.info("Noor reader has %d page(s) for %s", total, series.url)
    return [Chapter(
        url=f"{series.url}#{NOOR_READ_FRAGMENT}",
        # The extension decides what book_path writes, and the queue binds a PDF.
        title=f"{sanitize_filename(series.title)}.pdf",
        number=None,
        index=1,
    )]


def _noor_pages(html: str, page_url: str) -> list[Page]:
    reader = _noor_reader_pages(html)
    if reader is None:
        raise AdapterError(
            f"Noor Book's reader is no longer open for {page_url}; its page "
            "links are minted per reading session."
        )
    total, group, book, token = reader
    root = f"https://{urlparse(page_url).netloc}"
    return [
        Page(index=number,
             url=f"{root}/book/read_book_image/{group}/{book}/{number}/{token}.svg",
             referer=page_url)
        for number in range(1, total + 1)
    ]


def _noor_unwrap(content: bytes) -> bytes:
    """Pull the raster image out of one of Noor's reader SVGs.

    Each page is an ``<svg>`` whose only content is a single ``<image>`` with a
    base64 data URI. Anything that is not one of those is returned untouched,
    so this is safe to run over every book site's pages.
    """
    if b"<svg" not in content[:512].lower():
        return content
    match = _NOOR_EMBEDDED_RE.search(content)
    if match is None:
        return content
    payload = re.sub(rb"\s+", b"", match.group(2))
    try:
        return base64.b64decode(payload, validate=True)
    except (ValueError, binascii.Error):
        return content


def _noor_unavailable(url: str, text: str) -> bool:
    """Whether Noor identifies a title as catalog-only.

    ``text`` must be readable text — a title, or a page put through
    :func:`_visible_text` — never raw HTML.
    """
    if "/book/review/" in _path_of(url).lower():
        return True
    lowered = " ".join(text.lower().split())
    return any(marker in lowered for marker in (
        "download is not available",
        "not available for download",
        "unavailable",
        "غير متاح للتحميل",
        "التحميل غير متاح",
    ))


def _file_links(html: str, base: str) -> list[tuple[str, str]]:
    """Every ``(url, link text)`` on the page that points at a book file.

    Order is document order, which on both verified sites is the order a reader
    would expect: format by format, or volume by volume.
    """
    from selectolax.parser import HTMLParser

    tree = HTMLParser(html)
    found: list[tuple[str, str]] = []
    seen: set[str] = set()
    for anchor in tree.css("a"):
        href = first_attr(anchor, "href")
        if not href:
            continue
        absolute = Adapter.absolute(base, href)
        if not absolute or absolute in seen:
            continue
        if not _FILE_RE.search(_path_of(absolute)):
            continue
        seen.add(absolute)
        found.append((absolute, " ".join(anchor.text(strip=True).split())))

    for url, label in _encoded_links(tree, base):
        if url not in seen:
            seen.add(url)
            found.append((url, label))
    return found


def _encoded_links(tree, base: str) -> list[tuple[str, str]]:
    """File URLs a page hides as base64 in a ``data-`` attribute.

    arabic-book.net puts its PDF in ``<span data-href="aHR0cHM6…">`` rather than
    an anchor — obfuscation against scrapers, and a page that otherwise looks
    like it offers no book at all. Only decoded values that are plainly a URL to
    a known book format are accepted, so this cannot turn arbitrary data into a
    download.
    """
    found: list[tuple[str, str]] = []
    for node in tree.css("*"):
        for key, value in node.attributes.items():
            if not key.startswith("data-") or not value or len(value) < 24:
                continue
            try:
                decoded = base64.b64decode(value + "==", validate=False).decode()
            except (ValueError, UnicodeDecodeError):
                continue
            if not decoded.startswith(("http://", "https://")):
                continue
            if not _FILE_RE.search(_path_of(decoded)):
                continue
            absolute = Adapter.absolute(base, decoded) or decoded
            found.append((absolute, " ".join(node.text(strip=True).split())))
    return found


def _result_nodes(tree) -> list:
    """The result items on a search page, from the first wrapper that matches.

    First match wins rather than everything combined: a theme that uses both
    would otherwise yield each book twice, once nested inside the other.
    """
    for selector in RESULT_CONTAINERS:
        nodes = tree.css(selector)
        if nodes:
            return nodes
    return []


def _is_archive(url: str) -> bool:
    """Whether a result link is a category/tag listing rather than a book."""
    path = _path_of(url).lower()
    return any(marker in path for marker in _ARCHIVE_PATHS)


def _too_shallow(url: str, host: str) -> bool:
    """Whether this URL is a section listing on a site that needs depth to tell."""
    minimum = _MIN_PATH_DEPTH.get(host.removeprefix("www."))
    if not minimum:
        return False
    return len([part for part in _path_of(url).split("/") if part]) < minimum


def _meta(tree, name: str) -> str | None:
    node = (tree.css_first(f'meta[property="{name}"]')
            or tree.css_first(f'meta[name="{name}"]'))
    value = (node.attributes.get("content") if node else None) or ""
    return value.strip() or None


def _clean_title(title: str) -> str:
    """Trim the site's own branding off a page title.

    "Agnes Grey — Download Free at Planet eBook" is a page title; the book is
    called Agnes Grey, and that is what the folder should be named.
    """
    for separator in ("—", "–", " - ", " | "):
        if separator in title:
            title = title.split(separator)[0]
    return " ".join(title.split()).strip() or "Unknown Book"


def _encoded(url: str) -> str:
    """Percent-encode the characters a real filename can contain.

    Publishers name uploads after the book, so a link's path legitimately holds
    spaces, commas and semicolons — bettergutenberg serves
    ``…/007_Frankenstein; or, the modern prometheus_pg84.epub``. Browsers encode
    those on the way out; an HTTP client that does not gets a 404 or a
    malformed request. Already-encoded URLs are left alone.
    """
    from urllib.parse import quote, unquote

    return quote(unquote(url), safe=":/?#[]@!$&'()*+,;=%~")


def _extension(href: str) -> str:
    match = _FILE_RE.search(_path_of(href))
    return f".{match.group(1).lower()}" if match else ".pdf"


def _one_book_in_formats(links: list[tuple[str, str]]) -> bool:
    """Whether this page is one book offered in several formats.

    The distinction decides how downloads are named. A handful of links whose
    extensions are all different is a single book (EPUB + PDF + MOBI), and
    naming those after the book reads far better than after the site's own
    filenames. A page of twenty PDFs is a collection, where the site's numbering
    is the only thing keeping the volumes apart.
    """
    if not links or len(links) > len(BOOK_EXTENSIONS):
        return False
    extensions = [_extension(href) for href, _ in links]
    return len(set(extensions)) == len(extensions)


def _filename(href: str, label: str, position: int, used: set[str]) -> str:
    """The name to store this file under.

    The site's own filename, because it is already unique across a collection
    of numbered volumes *and* across one book's formats — and because a reader
    recognises it. Only when two links genuinely collide does the position get
    involved.
    """
    name = unquote(_path_of(href).rsplit("/", 1)[-1]).strip()
    if not _FILE_RE.search(name):
        extension = _FILE_RE.search(_path_of(href))
        name = f"{label or 'book'}.{extension.group(1).lower() if extension else 'pdf'}"
    if name.lower() in used:
        stem, _, extension = name.rpartition(".")
        name = f"{stem}-{position}.{extension}"
    return name
