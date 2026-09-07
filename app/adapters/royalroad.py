"""Royal Road — web fiction, published free by its authors.

Investigated 2026-09-07. Everything this adapter needs is served to an
anonymous plain-HTTP client; no browser, no account, no bot check was
encountered on any of the three request types.

The one thing worth knowing before reading the code: **the chapter list is not
in the DOM.** The fiction page renders a table of links, but it also ships the
authoritative list as a JSON array in an inline ``window.chapters`` assignment,
and that array is strictly better — it carries an explicit ``order`` field, the
publication date, and, decisively, ``isUnlocked``. Royal Road lets an author
put recent chapters behind a paid subscription tier, and a locked chapter is
still listed and still linked. Scraping the table would queue those and fail on
them one at a time; reading the array lets the adapter say up front how much of
the work is actually public.

Verified against ``/fiction/117332/becoming-the-dark-lord-litrpg`` on
2026-09-07: 702 chapters listed, ``order`` 0-701, all unlocked, and chapter 1's
reader (``/chapter/2292943/…``) yielding 121 paragraphs and ~14.7k characters
from ``div.chapter-inner.chapter-content``.
"""

from __future__ import annotations

import json
import logging
import re
from urllib.parse import quote_plus, urlparse

from ..models import Chapter, Page, SearchResult, Series, TextChapter
from .base import Adapter, AdapterError, query_matches, relevance
from .prose import blocks_from, strip_noise

log = logging.getLogger(__name__)

HOST = "royalroad.com"
ROOT = "https://www.royalroad.com"

#: The inline chapter list. Non-greedy up to the first ``];`` that closes it —
#: the assignment is emitted by the server as one line of compact JSON.
_CHAPTERS_RE = re.compile(r"window\.chapters\s*=\s*(\[.*?\])\s*;", re.S)

#: ``/fiction/<id>/<slug>`` identifies a work; anything deeper is a chapter.
_FICTION_RE = re.compile(r"/fiction/(\d+)(?:/([^/?#]+))?")

#: The reader. Both class names are required together: ``chapter-content``
#: alone also matches the wrapper that holds the author's note.
READER_SELECTOR = "div.chapter-inner.chapter-content"

#: A work with more entries than this is a parsing accident, not a serial.
MAX_CHAPTERS = 20_000


class RoyalRoadAdapter(Adapter):
    id = "royalroad"
    name = "Royal Road"
    priority = 75
    content_type = "book"
    packaging = "text"
    owns_its_host = True
    """Nothing else can be at royalroad.com, and fingerprinting it would cost a
    page fetch to conclude what the hostname already said."""

    right_to_left = False

    def __init__(self, session_manager) -> None:
        super().__init__(session_manager)
        self._cache: dict[str, str] = {}

    @classmethod
    def matches(cls, url: str, html: str | None = None) -> bool:
        host = urlparse(url).netloc.lower()
        return host == HOST or host.endswith(f".{HOST}")

    # ------------------------------------------------------------------ http

    async def _get(self, url: str, *, referer: str | None = None) -> str:
        """Fetch over plain HTTP, caching per instance.

        A preview asks for the fiction page and then, for the chapter list,
        would ask for it again. Nothing here needs a browser: measured
        2026-09-07, the listing, the fiction page and the reader all answer a
        plain anonymous request with the full content.
        """
        cached = self._cache.get(url)
        if cached is not None:
            return cached
        html = await self.sessions.fetch_text_direct(url, referer=referer)
        self._cache[url] = html
        return html

    # ---------------------------------------------------------------- series

    async def fetch_series(self, url: str) -> Series:
        url = _fiction_url(url)
        html = await self._get(url)
        tree = self.parse(html)

        title = self.text(tree.css_first("h1"))
        meta = _ld_json(html)
        if not title:
            title = str(meta.get("name") or "").strip()
        if not title:
            raise AdapterError(
                f"{url} has no title — it is probably not a Royal Road "
                "fiction page."
            )

        author = None
        person = meta.get("author")
        if isinstance(person, dict):
            author = str(person.get("name") or "").strip() or None

        cover = None
        og = tree.css_first('meta[property="og:image"]')
        if og is not None:
            cover = self.absolute(url, og.attributes.get("content"))

        description = str(meta.get("description") or "").strip() or None

        match = _FICTION_RE.search(urlparse(url).path)
        return Series(
            url=url,
            title=title,
            source=self.id,
            cover_url=cover,
            author=author,
            description=description,
            site_id=match.group(1) if match else None,
        )

    # -------------------------------------------------------------- chapters

    async def fetch_chapters(self, series: Series) -> list[Chapter]:
        html = await self._get(series.url)
        entries = _chapter_json(html)
        if entries is None:
            raise AdapterError(
                f"{series.url} carries no chapter list. Royal Road ships it as "
                "an inline window.chapters array; a page without one is not a "
                "fiction page."
            )

        # `order` is the site's own sequence number and is authoritative.
        # Sorting on it rather than trusting array order costs nothing and
        # survives the site reordering its own payload.
        entries.sort(key=lambda entry: _int(entry.get("order")))

        chapters: list[Chapter] = []
        locked = 0
        for index, entry in enumerate(entries[:MAX_CHAPTERS], start=1):
            href = str(entry.get("url") or "").strip()
            title = str(entry.get("title") or "").strip()
            if not href or not title:
                continue
            if entry.get("visible") is False:
                continue
            if entry.get("isUnlocked") is False:
                # Author-gated early access. Listing it would queue a chapter
                # that can only fail, and reporting that as a download error
                # would blame the adapter for the site's paywall.
                locked += 1
                continue
            chapters.append(Chapter(
                url=self.absolute(series.url, href) or href,
                title=title,
                number=_number_from(title, index),
                index=len(chapters) + 1,
                date=str(entry.get("date") or "") or None,
            ))

        if locked:
            log.info(
                "%s: %d of %d chapters are behind the author's paid tier and "
                "were not listed", series.url, locked, len(entries),
            )
        if not chapters:
            raise AdapterError(
                f"No readable chapters at {series.url}"
                + (f" — all {locked} are behind a paid subscription tier."
                   if locked else ".")
            )
        return chapters

    # ------------------------------------------------------------------ text

    async def fetch_pages(self, chapter: Chapter) -> list[Page]:
        """Royal Road serves prose; there are no page images to download."""
        raise AdapterError(
            "Royal Road chapters are text, not images — this adapter packages "
            "them as EPUB through fetch_text()."
        )

    async def fetch_text(self, chapter: Chapter) -> TextChapter:
        html = await self._get(chapter.url, referer=chapter.url)
        tree = self.parse(html)

        container = tree.css_first(READER_SELECTOR)
        if container is None:
            if _is_locked(html):
                raise AdapterError(
                    f"{chapter.url} is locked. Royal Road lets an author sell "
                    "early access, and a locked chapter serves a subscription "
                    "prompt instead of its text."
                )
            raise AdapterError(
                f"No chapter text at {chapter.url} — the reader markup did not "
                f"contain {READER_SELECTOR}. The chapter may have been removed."
            )

        strip_noise(container)
        blocks = blocks_from(container)
        if not blocks:
            raise AdapterError(
                f"The reader at {chapter.url} contained no text. This is "
                "either a removed chapter or a change to the site's markup."
            )

        heading = self.text(tree.css_first("h1")) or chapter.title
        return TextChapter(title=heading, blocks=blocks, language="en")

    # ---------------------------------------------------------------- search

    search_path = "/fictions/search"

    async def search(self, site: str, query: str, limit: int = 12) -> list[SearchResult]:
        url = f"{ROOT}{self.search_path}?title={quote_plus(query)}"
        try:
            html = await self._get(url)
        except Exception as exc:  # one site must never break a fan-out search
            log.info("Royal Road search failed: %s", exc)
            return []

        tree = self.parse(html)
        results: list[SearchResult] = []
        seen: set[str] = set()
        for node in tree.css("h2.fiction-title a, a.font-red-sunglo"):
            href = node.attributes.get("href") or ""
            if not _FICTION_RE.search(href):
                continue
            target = self.absolute(ROOT, href) or ""
            target = _fiction_url(target)
            title = self.text(node)
            if not title or target in seen:
                continue
            # Royal Road's search matches descriptions and tags too, so a query
            # it cannot answer still returns a full page. Requiring the query
            # in the hit turns that back into "nothing found" — the same guard
            # the other adapters here apply, for the same reason.
            if not query_matches(query, title):
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

def _fiction_url(url: str) -> str:
    """Normalise any Royal Road URL to the fiction's own page.

    Pasting a chapter URL is the natural thing to do when you are reading one,
    and every part of this adapter is anchored on the fiction page.
    """
    parsed = urlparse(url)
    match = _FICTION_RE.search(parsed.path)
    if not match:
        return url
    slug = match.group(2) or ""
    tail = f"/{slug}" if slug else ""
    return f"{ROOT}/fiction/{match.group(1)}{tail}"


def _chapter_json(html: str) -> list[dict] | None:
    match = _CHAPTERS_RE.search(html)
    if not match:
        return None
    try:
        data = json.loads(match.group(1))
    except ValueError:
        return None
    return [entry for entry in data if isinstance(entry, dict)]


def _ld_json(html: str) -> dict:
    """The page's schema.org record, or an empty dict.

    Used only as a fallback for the title and as the source of the author and
    blurb, so a page that omits it still produces a usable series.
    """
    for match in re.finditer(
        r'<script[^>]+type="application/ld\+json"[^>]*>(.*?)</script>', html, re.S
    ):
        try:
            data = json.loads(match.group(1))
        except ValueError:
            continue
        if isinstance(data, dict):
            return data
    return {}


_NUM_IN_TITLE = re.compile(r"(?:chapter|ch\.?|episode|ep\.?|part)\s*0*(\d+(?:\.\d+)?)", re.I)


def _number_from(title: str, fallback: int) -> str:
    """The chapter's own number when its title states one.

    Deliberately *not* `base.extract_number`: that falls back to any leading or
    trailing number in the label, and web-fiction titles routinely end in one
    ("...Volume 2", "...Level 40"), which would file the chapter under it.
    Where the title does not say, the position in the list is the honest answer.
    """
    match = _NUM_IN_TITLE.search(title)
    return match.group(1) if match else str(fallback)


def _int(value) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


_LOCK_MARKERS = ("subscription", "unlock this chapter", "patreon", "early access")


def _is_locked(html: str) -> bool:
    lowered = html.lower()
    return any(marker in lowered for marker in _LOCK_MARKERS)
