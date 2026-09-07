"""Sunovels (شمس الروايات) — Arabic translations of Asian web novels.

Investigated 2026-09-07. Reading is anonymous over plain HTTP; no browser, no
account, no bot check was seen on any request type.

Two things about this site are worth stating before the code, because neither
is guessable:

**The chapter list is paged, and the page number is zero-based.** The series
page's chapters tab shows the first fifty; ``&page=1`` is the *second* fifty.
Measured 2026-09-07 on ``/novel/reverend-insanity``: no parameter → 1-50,
``page=1`` → 51-100, ``page=2`` → 101-150, ``page=3`` → 151-200. Treating it as
one-based silently skips chapters 51-100, which is exactly the kind of hole
that survives a preview and shows up as a missing chapter months later.

**The total is not in the listing.** It is in the "read the last chapter"
shortcut at the top of the series page, whose URL ends in the highest chapter
number. That number is what bounds the paging, so the walk stops rather than
guessing when it has reached the end.

Chapter numbers come from the URL, not the label: rows read ``1 الفصل``
(right-to-left, so the number leads visually but trails in the source), and the
path segment is unambiguous.

Verified: ``/novel/reverend-insanity`` lists 2500 chapters; chapter 1's reader
yields 182 paragraphs and ~15.2k characters of Arabic from
``div.chapter-content``.
"""

from __future__ import annotations

import logging
import re
from urllib.parse import urlsplit, urlunsplit

from ..models import Chapter, Page, Series, TextChapter
from .base import Adapter, AdapterError
from .prose import blocks_from, strip_noise

log = logging.getLogger(__name__)

HOST = "sunovels.com"
ROOT = "https://sunovels.com"

#: The reader's text container.
READER_SELECTOR = "div.chapter-content"

#: ``/novel/<slug>`` is a novel; ``/novel/<slug>/<n>`` is one of its chapters.
_NOVEL_RE = re.compile(r"^/novel/([^/?#]+)(?:/(\d+))?/?$")

#: Rows per listing page, measured. Only used to bound the walk.
PAGE_SIZE = 50

#: A novel longer than this is a parsing accident. The longest serials on the
#: site run to a few thousand chapters.
MAX_CHAPTERS = 20_000

#: The site's own name, which is the first ``h1`` on every page.
_SITE_NAME = "شمس الروايات"


class SunovelsAdapter(Adapter):
    id = "sunovels"
    name = "Sunovels (شمس الروايات)"
    priority = 75
    content_type = "book"
    packaging = "text"
    owns_its_host = True
    right_to_left = True
    """Arabic prose. The EPUB's own direction comes from the language tag, but
    declaring it here keeps the adapter honest about what it serves."""

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
        self._cache[url] = html
        return html

    # ---------------------------------------------------------------- series

    async def fetch_series(self, url: str) -> Series:
        url = _novel_url(url)
        html = await self._get(url)
        tree = self.parse(html)

        # Every page opens with the site's own name in an <h1>; the novel's
        # title is the next one. Filtering by text rather than by position so a
        # layout change drops the brand rather than the title.
        headings = [self.text(node) for node in tree.css("h1")]
        title = next(
            (text for text in headings if text and text != _SITE_NAME), ""
        )
        if not title:
            raise AdapterError(
                f"{url} has no novel title — it is probably not a Sunovels "
                "novel page."
            )

        cover = None
        og = tree.css_first('meta[property="og:image"]')
        if og is not None:
            cover = self.absolute(url, og.attributes.get("content"))

        slug = _slug_of(url)
        return Series(
            url=url,
            title=title,
            source=self.id,
            cover_url=cover,
            description=self.text(tree.css_first("div.description")) or None,
            site_id=slug,
        )

    # -------------------------------------------------------------- chapters

    async def fetch_chapters(self, series: Series) -> list[Chapter]:
        slug = _slug_of(series.url)
        listing = _chapters_url(series.url)
        first = await self._get(listing)

        found: dict[int, tuple[str, str | None]] = {}
        highest = _highest_linked(self, first, slug)
        _collect(self, first, slug, found)

        # Zero-based: page=0 is the same fifty the bare URL already served, so
        # the walk starts at 1. It stops at the highest chapter the page linked
        # (the "last chapter" shortcut), or as soon as a page adds nothing.
        pages = min((highest + PAGE_SIZE - 1) // PAGE_SIZE, MAX_CHAPTERS // PAGE_SIZE)
        for page in range(1, pages):
            page_url = _with_page(listing, page)
            try:
                html = await self._get(page_url, referer=listing)
            except Exception as exc:
                log.warning(
                    "Sunovels: chapter listing stopped at page %d of %d for %s "
                    "(%s). Listing the %d chapters read so far.",
                    page, pages, series.url, exc, len(found),
                )
                break
            before = len(found)
            _collect(self, html, slug, found)
            if len(found) == before:
                break

        if not found:
            raise AdapterError(
                f"No chapters listed at {series.url}. Sunovels links each "
                "chapter as /novel/<slug>/<number>; a page with none is not a "
                "novel page."
            )

        return [
            Chapter(url=f"{ROOT}/novel/{slug}/{number}",
                    title=title, number=str(number), index=index, date=date)
            for index, (number, (title, date)) in enumerate(sorted(found.items()), start=1)
        ]

    # ------------------------------------------------------------------ text

    async def fetch_pages(self, chapter: Chapter) -> list[Page]:
        raise AdapterError(
            "Sunovels chapters are text, not images — this adapter packages "
            "them as EPUB through fetch_text()."
        )

    async def fetch_text(self, chapter: Chapter) -> TextChapter:
        html = await self._get(chapter.url, referer=chapter.url)
        tree = self.parse(html)

        container = tree.css_first(READER_SELECTOR)
        if container is None:
            raise AdapterError(
                f"No chapter text at {chapter.url} — the reader markup did not "
                f"contain {READER_SELECTOR}. The chapter may have been removed."
            )

        strip_noise(container)
        blocks = blocks_from(container)
        if not blocks:
            raise AdapterError(f"The reader at {chapter.url} contained no text.")

        heading = self.text(tree.css_first("h2")) or chapter.title
        return TextChapter(title=heading, blocks=blocks, language="ar")

    # ---------------------------------------------------------------- search
    #
    # Deliberately none. `/library` accepts `search=`, `q=`, `keyword=` and
    # `title=` and **ignores all four**: measured 2026-09-07, every one of them
    # returned the same twenty-four catalogue cards, which is indistinguishable
    # from a page of real results. That is the third site in this project to
    # answer an unanswerable query with something that merely looks like an
    # answer, and inheriting the base class's "return nothing" is the honest
    # outcome. Sunovels is paste-by-URL only until a real search endpoint is
    # found — the same call already made for arabic-book.net.

# ------------------------------------------------------------------ helpers

def _slug_of(url: str) -> str:
    match = _NOVEL_RE.match(urlsplit(url).path)
    return match.group(1) if match else ""


def _novel_url(url: str) -> str:
    """Normalise a chapter URL back to its novel's page."""
    slug = _slug_of(url)
    return f"{ROOT}/novel/{slug}" if slug else url


def _chapters_url(url: str) -> str:
    return _with_query(_novel_url(url), {"activeTab": "chapters"})


def _with_page(url: str, page: int) -> str:
    return _with_query(url, {"page": str(page)})


def _with_query(url: str, extra: dict[str, str]) -> str:
    parts = urlsplit(url)
    kept = [
        item for item in parts.query.split("&")
        if item and item.split("=", 1)[0] not in extra
    ]
    query = "&".join(kept + [f"{k}={v}" for k, v in extra.items()])
    return urlunsplit((parts.scheme, parts.netloc, parts.path, query, ""))


def _chapter_links(adapter: Adapter, html: str, slug: str):
    """Every ``/novel/<slug>/<n>`` anchor, as ``(number, node)``."""
    prefix = f"/novel/{slug}/"
    for node in adapter.parse(html).css("a"):
        href = node.attributes.get("href") or ""
        path = urlsplit(href).path
        if not path.startswith(prefix):
            continue
        tail = path[len(prefix):].strip("/")
        if tail.isdigit():
            yield int(tail), node


def _highest_linked(adapter: Adapter, html: str, slug: str) -> int:
    """The highest chapter number the page links anywhere.

    That is the "read the last chapter" shortcut, and it is the only statement
    of how long the novel is that the markup makes.
    """
    return max((number for number, _ in _chapter_links(adapter, html, slug)), default=0)


def _collect(adapter: Adapter, html: str, slug: str,
             found: dict[int, tuple[str, str | None]]) -> None:
    """Add this page's rows to ``found``, keeping the first label seen."""
    for number, node in _chapter_links(adapter, html, slug):
        if number in found:
            continue
        label = node.css_first("strong.chapter-title")
        title = adapter.text(label) or (node.attributes.get("title") or "").strip()
        if not title:
            # The first/last shortcuts carry no row markup and no useful label.
            # Skipping them here would drop two real chapters, so name them.
            title = f"الفصل {number}"
        time_node = node.css_first("time.chapter-update")
        date = time_node.attributes.get("datetime") if time_node is not None else None
        found[number] = (" ".join(title.split()), date)
