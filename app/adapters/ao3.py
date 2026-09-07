"""Archive of Our Own — fan and original fiction, published free by its authors.

Investigated 2026-09-07. AO3 is the unusual case in this project: it does not
have to be scraped at all. Every public work offers **official downloads** —
EPUB, MOBI, PDF, AZW3 and HTML — from the work page itself, to anonymous
visitors, with no account:

    /downloads/<work id>/<name>.epub?updated_at=<stamp>

So this adapter deliberately does *not* extract chapter text. Taking the file
the archive itself generates is both simpler and better: it carries the work's
own metadata, notes and chapter structure, already assembled, in one request
instead of one per chapter. Verified 2026-09-07 against ``/works/19368172``:
the EPUB is 415 KB and a valid container with 69 entries.

The mapping is the one the ``books`` adapter established, for the same reason —

    series  = the work
    chapter = one downloadable format
    page    = that file's URL

— so a work offers four selectable items and the queue writes each straight
through. ``.html`` is offered by the site and skipped here: the library stores
documents, and an HTML file is not one of the formats it owns.

**What this adapter will not do.** A work marked as adult is served behind an
interstitial that asks the visitor to confirm, and a work can be restricted to
logged-in users entirely. Neither is answered here. The first is a statement
the *reader* makes and not one an unattended downloader should make for them;
the second is an account gate. Both are reported as what they are.
"""

from __future__ import annotations

import logging
import re
from urllib.parse import quote_plus, urlsplit

from ..models import Chapter, Page, SearchResult, Series, sanitize_filename
from .base import Adapter, AdapterError, query_matches, relevance

log = logging.getLogger(__name__)

HOST = "archiveofourown.org"
ROOT = "https://archiveofourown.org"

#: Formats to keep, best first. The order decides nothing but presentation:
#: every one of them becomes its own selectable download.
FORMATS = ("epub", "azw3", "mobi", "pdf")

_WORK_RE = re.compile(r"/works/(\d+)")

#: The archive's own download links. Anchored on the path so a link to some
#: other site that happens to say "download" cannot match — the lesson the
#: ``books`` adapter records the hard way.
_DOWNLOAD_RE = re.compile(r"^/downloads/\d+/.+\.([a-z0-9]+)$", re.I)

#: Markers for the two ways a work is not publicly readable.
_ADULT_MARKER = "This work could have adult content"
_RESTRICTED_MARKERS = (
    "This work is only available to registered users",
    "only available to registered users of the Archive",
)


class AO3Adapter(Adapter):
    id = "ao3"
    name = "Archive of Our Own"
    priority = 75
    content_type = "book"
    packaging = "file"
    """The archive generates the finished book; the queue writes it through."""

    owns_its_host = True
    right_to_left = False

    def __init__(self, session_manager) -> None:
        super().__init__(session_manager)
        self._cache: dict[str, str] = {}

    @classmethod
    def matches(cls, url: str, html: str | None = None) -> bool:
        host = urlsplit(url).netloc.lower()
        return host == HOST or host.endswith(f".{HOST}")

    async def _get(self, url: str, *, referer: str | None = None) -> str:
        cached = self._cache.get(url)
        if cached is not None:
            return cached
        html = await self.sessions.fetch_text_direct(url, referer=referer)
        _guard(html, url)
        self._cache[url] = html
        return html

    # ---------------------------------------------------------------- series

    async def fetch_series(self, url: str) -> Series:
        url = _work_url(url)
        html = await self._get(url)
        tree = self.parse(html)

        title = self.text(tree.css_first("h2.title.heading"))
        if not title:
            raise AdapterError(
                f"{url} has no work title — it is probably not an AO3 work page."
            )

        author = self.text(tree.css_first("a[rel=author]")) or self.text(
            tree.css_first("h3.byline.heading")
        )
        summary = self.text(tree.css_first("div.summary blockquote")) or None

        match = _WORK_RE.search(urlsplit(url).path)
        return Series(
            url=url,
            title=title,
            source=self.id,
            # AO3 hosts no cover art; leaving this None is the honest answer
            # rather than pointing the UI at the site logo.
            cover_url=None,
            author=author or None,
            description=summary,
            site_id=match.group(1) if match else None,
        )

    # -------------------------------------------------------------- chapters

    async def fetch_chapters(self, series: Series) -> list[Chapter]:
        html = await self._get(series.url)
        tree = self.parse(html)

        by_format: dict[str, str] = {}
        for node in tree.css('a[href^="/downloads/"]'):
            href = (node.attributes.get("href") or "").strip()
            match = _DOWNLOAD_RE.match(urlsplit(href).path)
            if not match:
                continue
            extension = match.group(1).lower()
            if extension not in FORMATS:
                continue          # .html: the library does not store it
            by_format.setdefault(extension, self.absolute(series.url, href) or href)

        if not by_format:
            raise AdapterError(
                f"No download links on {series.url}. AO3 offers them on every "
                "public work, so this is either a restricted work or a page "
                "that is not a work."
            )

        # Named after the work rather than after the archive's own filename,
        # which truncates the title ("Badass_Virginians_to.epub"). Same rule
        # the books adapter follows: the extensions are all distinct, so each
        # download can safely carry the book's name.
        stem = sanitize_filename(series.title, fallback=f"work-{series.site_id}")
        return [
            Chapter(
                # Identity is the work page plus the format, not the file URL:
                # the URL carries an `updated_at` stamp that changes whenever
                # the author edits, and a chapter whose id moved would download
                # again on every run.
                url=f"{series.url}#{extension}",
                title=f"{stem}.{extension}",
                number=None,
                index=index,
            )
            for index, extension in enumerate(
                [f for f in FORMATS if f in by_format], start=1
            )
        ]

    # ------------------------------------------------------------------ file

    async def fetch_pages(self, chapter: Chapter) -> list[Page]:
        work_url, _, extension = chapter.url.partition("#")
        html = await self._get(work_url)
        tree = self.parse(html)

        for node in tree.css('a[href^="/downloads/"]'):
            href = (node.attributes.get("href") or "").strip()
            match = _DOWNLOAD_RE.match(urlsplit(href).path)
            if match and match.group(1).lower() == extension:
                return [Page(index=1,
                             url=self.absolute(work_url, href) or href,
                             referer=work_url)]

        raise AdapterError(
            f"{work_url} no longer offers a {extension.upper()} download."
        )

    # ---------------------------------------------------------------- search

    search_path = "/works/search"

    async def search(self, site: str, query: str, limit: int = 12) -> list[SearchResult]:
        url = f"{ROOT}/works/search?work_search%5Bquery%5D={quote_plus(query)}"
        try:
            html = await self._get(url)
        except Exception as exc:
            log.info("AO3 search failed: %s", exc)
            return []

        tree = self.parse(html)
        results: list[SearchResult] = []
        seen: set[str] = set()
        for node in tree.css("h4.heading a[href^='/works/']"):
            href = node.attributes.get("href") or ""
            if not _WORK_RE.search(urlsplit(href).path):
                continue
            target = _work_url(self.absolute(ROOT, href) or "")
            title = self.text(node)
            if not title or target in seen:
                continue
            seen.add(target)
            author = None
            parent = node.parent
            if parent is not None:
                author_node = parent.css_first("a[rel=author]")
                author = self.text(author_node) or None
            if not query_matches(query, title, author or ""):
                continue
            results.append(SearchResult(
                title=title, url=target, source=self.id, site=HOST, author=author,
            ))
            if len(results) >= limit:
                break
        results.sort(key=lambda hit: -relevance(query, hit.title, author=hit.author))
        return results


# ------------------------------------------------------------------ helpers

def _work_url(url: str) -> str:
    """Normalise any AO3 URL to the work's own page.

    A multi-chapter work redirects ``/works/<id>`` to ``/works/<id>/chapters/
    <first>``, and pasting a chapter URL is the natural thing to do while
    reading one. Both carry the work id, and the download links are on either.
    """
    match = _WORK_RE.search(urlsplit(url).path)
    return f"{ROOT}/works/{match.group(1)}" if match else url


def _guard(html: str, url: str) -> None:
    """Turn AO3's two access screens into errors that say which one it was.

    Both render a perfectly ordinary page with no download links on it, so
    without this the user is told the work offers no downloads — which is true
    and useless.
    """
    if any(marker in html for marker in _RESTRICTED_MARKERS):
        raise AdapterError(
            f"{url} is restricted to logged-in AO3 users. This downloader does "
            "not sign in, so the work cannot be fetched."
        )
    if _ADULT_MARKER in html:
        raise AdapterError(
            f"{url} is gated behind AO3's adult-content confirmation. That is a "
            "choice for you to make in your own browser, not one this "
            "downloader makes on your behalf; open the work, confirm, and the "
            "downloads are then the ordinary public ones."
        )
