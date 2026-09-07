"""Scribble Hub — original web fiction, published free by its authors.

Investigated 2026-09-07. Reading is anonymous, but the site sits behind
Cloudflare and *does* rate-limit: paging its table of contents produced a 403
"Attention Required" interstitial on one request in a run of two. That single
measurement shapes two decisions here:

* the table of contents is paged **serially**, never concurrently, and
* :data:`MAX_TOC_PAGES` caps how far a listing will walk, so a long serial
  cannot turn one preview into a hundred requests.

Both are cheap. Getting the address blocked costs far more than the listing
saves.

**The chapter list is paged, newest first.** ``/series/<id>/<slug>/`` shows
fifteen rows and links the rest as ``?toc=<n>``; the highest ``n`` in
``ul#pagination-mesh-toc`` is the last page. Each row carries the site's own
sequence number in an ``order`` attribute, which is what this adapter sorts on —
the label is free text and a serial that restarts its numbering per arc (they
do) cannot be ordered from it.

Verified against ``/series/1730819/the-deity-entertainment-network/`` on
2026-09-07: 15 rows per page across 21 pages, ``order`` running to 302, and a
reader (``/read/2498335-…/chapter/2542508/``) yielding 28 paragraphs and ~10k
characters from ``#chp_raw``.
"""

from __future__ import annotations

import logging
import re
from urllib.parse import quote_plus, urlparse, urlsplit, urlunsplit

from ..models import Chapter, Page, SearchResult, Series, TextChapter
from .base import Adapter, AdapterError, query_matches, relevance
from .prose import blocks_from, strip_noise

log = logging.getLogger(__name__)

HOST = "scribblehub.com"
ROOT = "https://www.scribblehub.com"

#: The reader's text. One id, and it holds nothing but the chapter.
READER_SELECTOR = "#chp_raw"

#: One row of the table of contents.
TOC_ROW = "li.toc_w"

#: How far a listing will page. 21 pages was the real serial measured; the cap
#: is generous enough for a very long one and finite enough that a malformed
#: pagination block cannot walk forever.
MAX_TOC_PAGES = 200

_SERIES_RE = re.compile(r"/series/(\d+)(?:/([^/?#]+))?")
_READ_RE = re.compile(r"/read/(\d+)-([^/?#]+)/chapter/(\d+)")
_TOC_PAGE_RE = re.compile(r"[?&]toc=(\d+)")


class ScribbleHubAdapter(Adapter):
    id = "scribblehub"
    name = "Scribble Hub"
    priority = 75
    content_type = "book"
    packaging = "text"
    owns_its_host = True
    right_to_left = False

    def __init__(self, session_manager) -> None:
        super().__init__(session_manager)
        self._cache: dict[str, str] = {}

    @classmethod
    def matches(cls, url: str, html: str | None = None) -> bool:
        host = urlparse(url).netloc.lower()
        return host == HOST or host.endswith(f".{HOST}")

    async def _get(self, url: str, *, referer: str | None = None) -> str:
        """Fetch through the browser session.

        Not the plain-HTTP path the other prose adapters use: Cloudflare
        answers a bare request here, and the session manager is what clears it
        and keeps the clearance for the rest of the run.
        """
        cached = self._cache.get(url)
        if cached is not None:
            return cached
        html = await self.get_html(url, referer=referer)
        self._cache[url] = html
        return html

    # ---------------------------------------------------------------- series

    async def fetch_series(self, url: str) -> Series:
        url = _series_url(url)
        html = await self._get(url)
        tree = self.parse(html)

        title = self.text(tree.css_first("div.fic_title")) or self.text(
            tree.css_first("h1")
        )
        if not title:
            raise AdapterError(
                f"{url} has no series title — it is probably not a Scribble "
                "Hub series page."
            )

        cover = None
        og = tree.css_first('meta[property="og:image"]')
        if og is not None:
            cover = self.absolute(url, og.attributes.get("content"))

        match = _SERIES_RE.search(urlparse(url).path)
        return Series(
            url=url,
            title=title,
            source=self.id,
            cover_url=cover,
            author=self.text(tree.css_first("span.auth_name_fic")) or None,
            description=self.text(tree.css_first("div.wi_fic_desc")) or None,
            site_id=match.group(1) if match else None,
        )

    # -------------------------------------------------------------- chapters

    async def fetch_chapters(self, series: Series) -> list[Chapter]:
        first = await self._get(series.url)
        rows = _rows(self, first, series.url)
        last_page = _last_toc_page(self.parse(first))

        # Serial, not concurrent: see the module docstring. Each page is one
        # request and the site has already shown it will refuse a burst.
        for page in range(2, min(last_page, MAX_TOC_PAGES) + 1):
            page_url = _with_toc(series.url, page)
            try:
                html = await self._get(page_url, referer=series.url)
            except Exception as exc:
                # A partial list is worth far more than no list. Say so loudly
                # and keep what was read, rather than failing the whole preview.
                log.warning(
                    "Scribble Hub: table of contents stopped at page %d of %d "
                    "for %s (%s). Listing the %d chapters read so far.",
                    page - 1, last_page, series.url, exc, len(rows),
                )
                break
            page_rows = _rows(self, html, series.url)
            if not page_rows:
                break
            rows.extend(page_rows)

        if not rows:
            raise AdapterError(
                f"No chapters listed at {series.url}. Scribble Hub renders its "
                f"table of contents as {TOC_ROW} rows; a page without any is "
                "not a series page."
            )

        # `order` is the site's own sequence number; the label is free text and
        # a serial that restarts numbering per arc cannot be ordered from it.
        # Deduplicated because the last page can repeat a row when a chapter is
        # published between two requests.
        unique: dict[str, tuple[int, str, str | None]] = {}
        for url, order, title, date in rows:
            unique.setdefault(url, (order, title, date))

        ordered = sorted(unique.items(), key=lambda item: item[1][0])
        return [
            # Sorted on `order`, numbered from the label. The two disagree —
            # measured, `order` 289 is the row labelled "Chapter 288", because
            # the count includes a prologue the numbering does not — and each
            # is right for a different job: `order` is the only thing that
            # sorts a serial whose labels restart per arc, while the label is
            # the number a reader expects to see on the file.
            Chapter(url=url, title=title,
                    number=_label_number(title) or str(order),
                    index=index, date=date)
            for index, (url, (order, title, date)) in enumerate(ordered, start=1)
        ]

    # ------------------------------------------------------------------ text

    async def fetch_pages(self, chapter: Chapter) -> list[Page]:
        raise AdapterError(
            "Scribble Hub chapters are text, not images — this adapter "
            "packages them as EPUB through fetch_text()."
        )

    async def fetch_text(self, chapter: Chapter) -> TextChapter:
        html = await self._get(chapter.url, referer=chapter.url)
        tree = self.parse(html)

        container = tree.css_first(READER_SELECTOR)
        if container is None:
            raise AdapterError(
                f"No chapter text at {chapter.url} — the reader markup did not "
                f"contain {READER_SELECTOR}. Either the chapter was removed, or "
                "the request was answered by Cloudflare rather than the site."
            )

        strip_noise(container)
        blocks = blocks_from(container)
        if not blocks:
            raise AdapterError(
                f"The reader at {chapter.url} contained no text."
            )

        heading = self.text(tree.css_first("div.chapter-title")) or chapter.title
        return TextChapter(title=heading, blocks=blocks, language="en")

    # ---------------------------------------------------------------- search

    search_path = "/?s="

    async def search(self, site: str, query: str, limit: int = 12) -> list[SearchResult]:
        url = f"{ROOT}/?s={quote_plus(query)}&post_type=fictionposts"
        try:
            html = await self._get(url)
        except Exception as exc:
            log.info("Scribble Hub search failed: %s", exc)
            return []

        tree = self.parse(html)
        results: list[SearchResult] = []
        seen: set[str] = set()
        for node in tree.css("div.search_title a, div.fic_title a"):
            href = node.attributes.get("href") or ""
            if not _SERIES_RE.search(href):
                continue
            target = _series_url(self.absolute(ROOT, href) or "")
            title = self.text(node)
            if not title or target in seen or not query_matches(query, title):
                continue
            seen.add(target)
            results.append(SearchResult(
                title=title, url=target, source=self.id, site=HOST,
            ))
            if len(results) >= limit:
                break
        results.sort(key=lambda hit: -relevance(query, hit.title))
        return results


# ------------------------------------------------------------------ helpers

def _series_url(url: str) -> str:
    """Normalise any Scribble Hub URL to the series page.

    A reader URL (``/read/<id>-<slug>/chapter/<n>/``) carries the same series id
    as the series page, so pasting the chapter you are on works.
    """
    parsed = urlsplit(url)
    match = _SERIES_RE.search(parsed.path)
    if match:
        slug = match.group(2) or ""
        tail = f"/{slug}" if slug else ""
        return f"{ROOT}/series/{match.group(1)}{tail}/"
    read = _READ_RE.search(parsed.path)
    if read:
        return f"{ROOT}/series/{read.group(1)}/{read.group(2)}/"
    return url


def _with_toc(url: str, page: int) -> str:
    """``url`` with the table-of-contents page number set."""
    parts = urlsplit(url)
    query = "&".join(
        [q for q in parts.query.split("&") if q and not q.startswith("toc=")]
        + [f"toc={page}"]
    )
    return urlunsplit((parts.scheme, parts.netloc, parts.path, query, ""))


def _rows(adapter: Adapter, html: str, base: str) -> list[tuple[str, int, str, str | None]]:
    """``(url, order, title, date)`` for every table-of-contents row."""
    out: list[tuple[str, int, str, str | None]] = []
    for node in adapter.parse(html).css(TOC_ROW):
        link = node.css_first("a")
        if link is None:
            continue
        href = adapter.absolute(base, link.attributes.get("href"))
        title = adapter.text(link)
        if not href or not title:
            continue
        try:
            order = int(node.attributes.get("order") or 0)
        except ValueError:
            order = 0
        date_node = node.css_first("span.fic_date_pub")
        date = (date_node.attributes.get("title") if date_node is not None else None)
        out.append((href, order, title, date))
    return out


_LABEL_NUM_RE = re.compile(
    r"(?:chapter|ch\.?|episode|ep\.?|part)\s*0*(\d+(?:\.\d+)?)", re.I
)


def _label_number(title: str) -> str | None:
    """The chapter number the row's own label states, if it states one.

    Only an explicit "Chapter N" counts. A bare trailing number in a title is
    far more often part of the title than a chapter number here.
    """
    match = _LABEL_NUM_RE.search(title)
    return match.group(1) if match else None


def _last_toc_page(tree) -> int:
    """The highest ``?toc=`` page the pagination block offers.

    Returns 1 when there is no pagination, which is the correct answer for a
    serial short enough to fit on one page.
    """
    highest = 1
    for node in tree.css("ul#pagination-mesh-toc a, a.page-link"):
        match = _TOC_PAGE_RE.search(node.attributes.get("href") or "")
        if match:
            highest = max(highest, int(match.group(1)))
    return highest
