"""Adapter for comix.to.

An Astro site that server-renders a shell and fills in the parts that matter —
the chapter list and the reader's pages — from JavaScript afterwards. So both
are read from the rendered DOM.

**The REST API is a dead end, and this is worth recording.** The reader really
does call a clean API:

    /api/v1/manga/<hid>/chapters?page=<token>
    /api/v1/chapters/<chapter_id>?_=<token>

but every call without the token answers ``{"message":"Missing token."}``, and
the tokens are minted by the site's own bundle. Calling it from the browser's
request context is worse still: **403**, because that carries cookies but not
the same-origin headers a page ``fetch`` sends. Rendering sidesteps the whole
question — the page fetches its own images with its own tokens, and we read the
result.

Page images live on a sharded host (``j24n.wowpic1.store/i5/<id>``) with opaque
ids: three consecutive pages differed by a single character mid-string, so they
are derived, not sequential. They are only ever taken from the DOM, never
constructed, and the host is treated as data rather than hardcoded.
"""

from __future__ import annotations

import asyncio
import logging
import re
from urllib.parse import urlparse

from ..models import Chapter, Page, Series
from .base import Adapter, AdapterError, first_attr

log = logging.getLogger(__name__)

#: /title/<hid>-<slug> for a series, plus /<chapter_id>-chapter-<n> for a chapter.
TITLE_PATH_RE = re.compile(r"^/title/(?P<hid>[0-9a-z]+)-(?P<slug>[^/]+)/?$", re.I)
CHAPTER_PATH_RE = re.compile(
    r"^/title/(?P<hid>[0-9a-z]+)-(?P<slug>[^/]+)/(?P<id>\d+)-chapter-(?P<number>[\d.]+)",
    re.I,
)

#: What to wait for before reading each kind of page.
CHAPTER_LIST_SELECTOR = "a[href*='-chapter-']"
READER_SELECTOR = "img[src*='/i5/'], img[src*='store/']"

#: How many list pages to walk before giving up; the list is paginated ~20 at
#: a time and a long series would otherwise scroll forever.
MAX_LIST_PAGES = 40
#: List pages fetched at once. Modest on purpose — each is a real browser tab,
#: and hammering a site is how an IP gets banned.
LIST_BATCH = 6


class ComixAdapter(Adapter):
    id = "comix"
    name = "Comix.to"
    priority = 95
    content_type = "comics"

    # -------------------------------------------------------- identification

    @classmethod
    def matches(cls, url: str, html: str | None = None) -> bool:
        host = urlparse(url).netloc.lower()
        if host == "comix.to" or host.endswith(".comix.to"):
            return True
        if html:
            return "/api/v1/manga/" in html and "/title/" in html
        return False

    # ---------------------------------------------------------------- series

    async def fetch_series(self, url: str) -> Series:
        series_url = _series_url(url)
        html = await self.get_html(
            series_url, wait_for=CHAPTER_LIST_SELECTOR, wait_ms=1200
        )
        tree = self.parse(html)

        title = (
            first_attr(tree.css_first("meta[property='og:title']"), "content")
            or self.text(tree.css_first("h1"))
            or _slug_title(series_url)
        )
        # The site appends its own branding to the document title.
        title = re.sub(r"\s*[|–-]\s*Comix.*$", "", title).strip()

        series = Series(
            url=series_url,
            title=title or _slug_title(series_url),
            source=self.id,
            cover_url=_poster(html) or first_attr(
                tree.css_first("meta[property='og:image']"), "content"
            ),
            description=first_attr(
                tree.css_first("meta[name='description']"), "content"
            ),
            site_id=_hid(series_url),
        )
        self._rendered_cache = (series_url, html)
        return series

    # -------------------------------------------------------------- chapters

    async def fetch_chapters(self, series: Series) -> list[Chapter]:
        found: dict[str, str] = {}

        # Only a *rendered* copy may be reused. The registry pre-fetches the
        # page to fingerprint it and stores that under `_last_html`, but the
        # chapter list is not in the served markup — trusting it would
        # silently skip the wait and find nothing.
        cached = getattr(self, "_rendered_cache", None)
        first = (
            cached[1]
            if cached and cached[0] == series.url
            else await self.get_html(series.url, wait_for=CHAPTER_LIST_SELECTOR)
        )
        self._harvest_links(first, series.url, found)

        # Pages after the first are fetched in batches rather than one at a
        # time. The list paginates ~20 at a time, so a long series meant two
        # dozen sequential page loads — about two minutes of mostly waiting.
        # The API that would answer in one call returns an encrypted payload,
        # so reading the rendered pages is the honest route; doing several at
        # once is what makes it quick.
        page_number = 2
        while page_number <= MAX_LIST_PAGES:
            batch = range(page_number, min(page_number + LIST_BATCH, MAX_LIST_PAGES + 1))
            pages = await asyncio.gather(
                *(
                    self.get_html(
                        f"{series.url}?page={n}", wait_for=CHAPTER_LIST_SELECTOR
                    )
                    for n in batch
                ),
                return_exceptions=True,
            )
            before = len(found)
            for html in pages:
                if isinstance(html, Exception):
                    log.debug("Chapter list page failed: %s", html)
                    continue
                self._harvest_links(html, series.url, found)
            # A whole batch adding nothing means the list has ended (or is not
            # paginated at all), so stop rather than keep fetching the same
            # final page over and over.
            if len(found) == before:
                break
            page_number += LIST_BATCH

        if not found:
            raise AdapterError(
                f"No chapters found on {series.url}. The list is drawn by the "
                "site's own script; if the page shows none in a browser, the "
                "series has none."
            )

        chapters = []
        for href, label in found.items():
            match = CHAPTER_PATH_RE.match(urlparse(href).path)
            number = match.group("number") if match else None
            chapters.append(
                Chapter(url=href, title=label or f"Chapter {number}", number=number)
            )
        chapters.sort(key=lambda c: c.sort_key)
        for position, chapter in enumerate(chapters, start=1):
            chapter.index = position
        log.info("Resolved %d chapters from %s", len(chapters), series.url)
        return chapters

    def _harvest_links(self, html: str, base: str, into: dict[str, str]) -> None:
        for node in self.parse(html).css(CHAPTER_LIST_SELECTOR):
            href = self.absolute(base, first_attr(node, "href"))
            if href and CHAPTER_PATH_RE.match(urlparse(href).path):
                into.setdefault(href, self.text(node))

    # ----------------------------------------------------------------- pages

    async def fetch_pages(self, chapter: Chapter) -> list[Page]:
        html = await self.get_html(
            chapter.url, referer=chapter.url, wait_for=READER_SELECTOR, wait_ms=2500
        )
        urls: list[str] = []
        seen: set[str] = set()
        for node in self.parse(html).css("img"):
            candidate = self.absolute(
                chapter.url, first_attr(node, "data-src", "srcset", "src")
            )
            if not candidate or candidate in seen or not _is_page_image(candidate):
                continue
            seen.add(candidate)
            urls.append(candidate)

        if not urls:
            raise AdapterError(
                f"No page images appeared on {chapter.url}. The reader loads "
                "them with JavaScript, so this usually means it was still "
                "loading or the chapter is unavailable."
            )
        return [
            Page(index=i, url=url, referer=chapter.url)
            for i, url in enumerate(urls, start=1)
        ]


#: The hydration payload carries a `poster` field; the page has no og:image.
_POSTER_RE = re.compile(r'"poster"\s*:\s*"(https?://[^"\\]+)"')


def _poster(html: str) -> str | None:
    """Cover art from the page's hydration payload.

    Read with a regex rather than by parsing the whole blob: it is a large
    nested query cache whose shape is theirs to change, and one field is all
    this needs.
    """
    match = _POSTER_RE.search(html)
    return match.group(1) if match else None


def _hid(url: str) -> str | None:
    match = TITLE_PATH_RE.match(urlparse(url).path) or CHAPTER_PATH_RE.match(
        urlparse(url).path
    )
    return match.group("hid") if match else None


def _series_url(url: str) -> str:
    """Reduce a chapter URL to its series URL.

    Someone pasting the chapter they are reading means "this series" — the same
    trim the Madara adapter performs, and the absence of which once produced a
    one-chapter series pointing at a site index.
    """
    parsed = urlparse(url.split("?")[0].split("#")[0])
    match = CHAPTER_PATH_RE.match(parsed.path)
    if match:
        path = f"/title/{match.group('hid')}-{match.group('slug')}"
        return f"{parsed.scheme}://{parsed.netloc}{path}"
    if TITLE_PATH_RE.match(parsed.path):
        return f"{parsed.scheme}://{parsed.netloc}{parsed.path.rstrip('/')}"
    raise AdapterError(
        f"{url} is not a comix.to series or chapter URL. Open the title's own "
        "page and paste that address (it looks like /title/<id>-<name>)."
    )


def _slug_title(url: str) -> str:
    match = TITLE_PATH_RE.match(urlparse(url).path)
    slug = match.group("slug") if match else urlparse(url).path.rsplit("/", 1)[-1]
    return slug.replace("-", " ").strip().title() or "Untitled"


def _is_page_image(url: str) -> bool:
    lowered = url.lower()
    if lowered.startswith("data:") or "/avatars/" in lowered:
        return False
    if "/images/" in lowered and "comix.to" in lowered:
        return False  # site furniture: avatars, badges, covers
    return "/i5/" in lowered or ".store/" in lowered
