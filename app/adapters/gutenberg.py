"""Adapter for Project Gutenberg.

The largest source this app supports — 77,000 public-domain books — and the one
that least resembles a "book page with a download link", which is why it gets
its own adapter rather than another special case inside :mod:`books`.

Three things are different here:

* **Search is a real endpoint**, ``/ebooks/search/?query=``, returning a tidy
  ``li.booklink`` list with title, author and cover. No theme guessing.
* **Filenames are not filenames.** A download is ``/ebooks/84.epub3.images``,
  which ends in ``.images`` and would be stored as a file no reader opens. Each
  link is mapped to what it actually is (``.epub``, ``.azw3``) and named after
  the book.
* **The same book is offered several times over.** EPUB3, legacy EPUB and a
  no-images EPUB are all "the EPUB", plus one "send to Dropbox/Drive/OneDrive"
  link per format that is not a file at all. Offering nine entries for two real
  choices is worse than useless, so the variants are ranked and the best of each
  format kept.
"""

from __future__ import annotations

import logging
import re
from urllib.parse import quote_plus, urljoin, urlparse

from ..models import Chapter, Page, SearchResult, Series
from .base import Adapter, AdapterError, first_attr

log = logging.getLogger(__name__)

SITE = "https://www.gutenberg.org"

KNOWN_HOSTS = {"gutenberg.org", "m.gutenberg.org"}

#: ``/ebooks/84`` — the id is the whole identity of a book here.
_ID_RE = re.compile(r"/ebooks/(\d+)")

#: A download link, and what the file it returns actually is. Ordered best
#: first within each format, because that order decides which variant wins.
_FORMATS: tuple[tuple[re.Pattern, str], ...] = (
    (re.compile(r"\.epub3\.images$", re.I), ".epub"),
    (re.compile(r"\.epub\.images$", re.I), ".epub"),
    (re.compile(r"\.epub\.noimages$", re.I), ".epub"),
    (re.compile(r"\.epub$", re.I), ".epub"),
    (re.compile(r"\.kf8\.images$", re.I), ".azw3"),
    (re.compile(r"\.kindle\.images$", re.I), ".azw3"),
    (re.compile(r"\.pdf$", re.I), ".pdf"),
)

#: "Send to Dropbox" and friends: an OAuth flow, not a download.
_NOT_A_FILE = re.compile(r"/ebooks/send/", re.I)


class GutenbergAdapter(Adapter):
    id = "gutenberg"
    name = "Project Gutenberg"
    priority = 118  # an exact host match, like the other API-shaped sources
    content_type = "book"
    packaging = "file"
    owns_its_host = True

    def __init__(self, session_manager) -> None:
        super().__init__(session_manager)
        self._cache: dict[str, str] = {}

    # -------------------------------------------------------- identification

    @classmethod
    def matches(cls, url: str, html: str | None = None) -> bool:
        host = urlparse(url).netloc.lower().removeprefix("www.")
        return host in KNOWN_HOSTS

    # ------------------------------------------------------------- fetching

    async def _get(self, url: str) -> str:
        cached = self._cache.get(url)
        if cached is not None:
            return cached
        try:
            html = await self.sessions.fetch_text_direct(url)
        except Exception as exc:
            log.info("Direct fetch of %s failed (%s); using the browser", url, exc)
            html = await self.get_html(url)
        self._cache[url] = html
        return html

    # --------------------------------------------------------------- search

    search_path = "/ebooks/search/?query={query}"

    async def search(self, site: str, query: str, limit: int = 12) -> list[SearchResult]:
        url = f"{SITE}/ebooks/search/?query={quote_plus(query)}"
        tree = self.parse(await self._get(url))

        results: list[SearchResult] = []
        for item in tree.css("li.booklink"):
            link = item.css_first("a")
            href = first_attr(link, "href")
            title = self.text(item.css_first("span.title"))
            if not href or not title:
                continue
            author = self.text(item.css_first("span.subtitle"))
            cover = first_attr(item.css_first("img"), "src")
            results.append(SearchResult(
                # The author used to be appended to the title so that an author
                # query would score against *something*. It bought that by
                # making every displayed title wrong — "The Mystery of Edwin
                # Drood — Charles Dickens" is not the name of the book. It now
                # travels in its own field, which relevance() scores directly.
                title=title,
                url=urljoin(SITE, href),
                source=self.id,
                site="gutenberg.org",
                cover_url=urljoin(SITE, cover) if cover else None,
                author=author or None,
            ))
            if len(results) >= limit:
                break
        return results

    # --------------------------------------------------------------- series

    async def fetch_series(self, url: str) -> Series:
        book_url = _book_url(url)
        tree = self.parse(await self._get(book_url))

        title = self.text(tree.css_first("td[itemprop=headline]"))
        if not title:
            meta = tree.css_first('meta[property="og:title"]')
            title = (meta.attributes.get("content") if meta else "") or ""
            title = title.split(" by ")[0]
        cover = first_attr(tree.css_first("img.cover-art"), "src")

        author = None
        for row in tree.css("table.bibrec tr"):
            header, cell = row.css_first("th"), row.css_first("td")
            if header and cell and header.text(strip=True).lower() == "author":
                author = cell.text(strip=True)
                break

        return Series(
            url=book_url,
            title=(title or "Unknown Book").strip(),
            source=self.id,
            cover_url=urljoin(book_url, cover) if cover else None,
            author=author,
            site_id=_book_id(book_url),
        )

    # ------------------------------------------------------------- chapters

    async def fetch_chapters(self, series: Series) -> list[Chapter]:
        book_url = _book_url(series.url)
        files = _downloads(await self._get(book_url), book_url)
        if not files:
            raise AdapterError(
                f"{book_url} offers no EPUB, Kindle or PDF edition. Some entries "
                "here are audio or plain text only."
            )

        chapters: list[Chapter] = []
        for position, (_url, extension) in enumerate(files, start=1):
            chapters.append(Chapter(
                url=f"{book_url}#{position}",
                title=f"{series.title}{extension}",
                index=position,
            ))
        log.info("Gutenberg %s offers %d format(s)", series.title, len(chapters))
        return chapters

    # ---------------------------------------------------------------- pages

    async def fetch_pages(self, chapter: Chapter) -> list[Page]:
        book_url, _, fragment = chapter.url.partition("#")
        files = _downloads(await self._get(book_url), book_url)
        try:
            position = int(fragment)
        except ValueError:
            position = 0
        if not (1 <= position <= len(files)):
            raise AdapterError(
                f"{chapter.title} is no longer offered for {book_url}."
            )
        return [Page(index=1, url=files[position - 1][0], referer=book_url)]


# ----------------------------------------------------------------- helpers


def _book_id(url: str) -> str:
    match = _ID_RE.search(urlparse(url).path)
    if not match:
        raise AdapterError(
            f"{url} is not a Project Gutenberg book URL. It should look like "
            "https://www.gutenberg.org/ebooks/84."
        )
    return match.group(1)


def _book_url(url: str) -> str:
    return f"{SITE}/ebooks/{_book_id(url)}"


def _downloads(html: str, base: str) -> list[tuple[str, str]]:
    """``(url, extension)`` for each distinct format the page offers.

    One entry per real format: Gutenberg lists three EPUB variants of the same
    text plus a cloud-transfer link for each, and a reader wants "the EPUB".
    """
    from selectolax.parser import HTMLParser

    best: dict[str, tuple[int, str]] = {}
    for anchor in HTMLParser(html).css("a"):
        href = first_attr(anchor, "href")
        if not href:
            continue
        absolute = urljoin(base, href)
        if _NOT_A_FILE.search(absolute):
            continue
        path = urlparse(absolute).path
        for rank, (pattern, extension) in enumerate(_FORMATS):
            if not pattern.search(path):
                continue
            current = best.get(extension)
            if current is None or rank < current[0]:
                best[extension] = (rank, absolute)
            break

    # Stable, useful order: EPUB first, then Kindle, then PDF.
    order = [".epub", ".azw3", ".pdf"]
    return [(best[ext][1], ext) for ext in order if ext in best]
