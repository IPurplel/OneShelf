"""Adapter for the "vcomics" Astro platform — azoramoon.com and its mirrors.

A modern single-page-ish site with no WordPress underneath, so none of the
theme adapters recognise it. What it does have is an unusually convenient
property: **it server-renders everything**. The page ships hydration state for
its Astro islands, and one of those islands carries the entire chapter list —
all 165 of them on a series that shows 21 links — as JSON in a ``props``
attribute.

That is worth stating plainly, because the obvious reading of the page is the
opposite. Counting ``<a href*="/chapter-">`` finds only the newest twenty, the
"more chapters" control fires no network request, and no amount of waiting or
scrolling adds any: the rest were never missing, they are simply not links yet.
Look in the island, not in the DOM.

Three consequences shape this adapter:

* **No browser is needed.** Series pages, reader pages and the search API are
  all plain HTTP, so this runs over the same fast path as MangaDex. The browser
  stays available as a fallback for an install that turns out to be challenged.
* **Chapters can be locked.** Recent chapters are sold for coins; the record
  says so in ``isAccessible``. Those are dropped from the listing rather than
  queued to fail, and a locked reader page is reported as locked rather than as
  a parse error.
* **Its search only indexes Latin titles.** Handing it an Arabic query does not
  return nothing — it returns *the entire catalogue*, newest first, which reads
  exactly like a working search that found 12 things. See :func:`_relevant`.
"""

from __future__ import annotations

import json
import logging
import re
from urllib.parse import quote, urlparse

from selectolax.parser import HTMLParser

from ..models import Chapter, Page, SearchResult, Series
from .base import Adapter, AdapterError, query_matches

log = logging.getLogger(__name__)

#: Hosts known to run this platform. Matching one is proof enough to skip the
#: fingerprinting fetch; anything else still has to look like the platform.
KNOWN_HOSTS = {"azoramoon.com", "azorafly.com"}

#: Markup only this platform emits: Astro's island custom element plus its own
#: asset directory.
FINGERPRINTS = ("astro-island", "/_vcomics/")

#: The reader's page container. Every page image is an ``<img>`` inside it,
#: already in reading order and at full size.
READER_SELECTOR = ".comic-images-wrapper"

#: Where the frontend keeps the API root it talks to.
_API_URL_RE = re.compile(r'"PUBLIC_API_URL"\s*:\s*"([^"]+)"')

#: ``/series/<slug>`` and ``/series/<slug>/<chapter-slug>``.
_SERIES_RE = re.compile(r"/series/([^/?#]+)")


class VComicsAdapter(Adapter):
    id = "vcomics"
    name = "VComics (Astro)"
    # Above the WordPress themes: this platform carries none of their markup,
    # but its pages are generic enough that the heuristic adapter would happily
    # claim them and produce nonsense.
    priority = 115
    content_type = "manga"
    right_to_left = True  # an Arabic manhwa/manga site

    def __init__(self, session_manager) -> None:
        super().__init__(session_manager)
        self._page_cache: dict[str, str] = {}

    # -------------------------------------------------------- identification

    # Only reached when the URL alone identified the site, which here means one
    # of KNOWN_HOSTS — a page render to confirm it would be pure cost, and on a
    # filtered network it is a render that can fail.
    owns_its_host = True

    @classmethod
    def matches(cls, url: str, html: str | None = None) -> bool:
        host = urlparse(url).netloc.lower().removeprefix("www.")
        if host in KNOWN_HOSTS:
            return True
        if html:
            return all(marker in html for marker in FINGERPRINTS)
        return False

    # ------------------------------------------------------------- fetching

    async def _get(self, url: str) -> str:
        """Fetch a page, preferring plain HTTP.

        Nothing here needs JavaScript or a cookie, and this site is one the
        browser cannot always reach — so HTTP first, with the browser kept as
        the fallback for an install that does challenge us.
        """
        cached = self._page_cache.get(url)
        if cached is not None:
            return cached
        try:
            html = await self.sessions.fetch_text_direct(url)
        except Exception as exc:
            log.info("Direct fetch of %s failed (%s); using the browser", url, exc)
            html = await self.get_html(url)
        self._page_cache[url] = html
        return html

    # --------------------------------------------------------------- series

    async def fetch_series(self, url: str) -> Series:
        url = _series_url(url)
        post = _series_props(await self._get(url))["post"]
        return Series(
            url=url,
            title=str(post.get("postTitle") or "").strip() or "Unknown Series",
            source=self.id,
            cover_url=post.get("featuredImage") or None,
            description=(post.get("postContent") or None),
            site_id=str(post.get("id") or "") or None,
        )

    # ------------------------------------------------------------- chapters

    async def fetch_chapters(self, series: Series) -> list[Chapter]:
        url = _series_url(series.url)
        props = _series_props(await self._get(url))
        records = props.get("initialChap") or []
        if not records:
            raise AdapterError(f"No chapters listed for {url}")

        collected: list[Chapter] = []
        locked = 0
        for record in records:
            # One authoritative flag, set by the site itself. A chapter sold
            # for coins renders a paywall instead of pages, so queueing it
            # would only manufacture a failure later.
            if not record.get("isAccessible", True):
                locked += 1
                continue
            slug = str(record.get("slug") or "").strip()
            if not slug:
                continue
            number = _number(record.get("number"))
            collected.append(Chapter(
                url=f"{_root(url)}/series/{_slug(url)}/{slug}",
                title=str(record.get("title") or "").strip()
                      or (f"Chapter {number}" if number else slug),
                number=number,
                date=record.get("createdAt"),
            ))

        if locked:
            log.info("Skipped %d locked chapter(s) on %s — they are sold for "
                     "coins and render a paywall instead of pages", locked, url)
        if not collected:
            raise AdapterError(
                f"Every chapter of {url} is locked. This site sells early "
                "access, so only purchased chapters can be downloaded."
            )

        collected.sort(key=lambda c: c.sort_key)
        for position, chapter in enumerate(collected, start=1):
            chapter.index = position
        log.info("Resolved %d chapter(s) from %s", len(collected), url)
        return collected

    # ---------------------------------------------------------------- pages

    async def fetch_pages(self, chapter: Chapter) -> list[Page]:
        html = await self._get(chapter.url)
        tree = self.parse(html)

        urls: list[str] = []
        seen: set[str] = set()
        wrapper = tree.css_first(READER_SELECTOR)
        for node in (wrapper.css("img") if wrapper else []):
            src = (node.attributes.get("src") or "").strip()
            if src and src not in seen:
                seen.add(src)
                urls.append(src)

        if not urls:
            if _locked_chapter(html):
                raise AdapterError(
                    f"{chapter.url} is locked. This site sells early access to "
                    "recent chapters, and a locked chapter serves a paywall "
                    "instead of its pages."
                )
            raise AdapterError(f"No page images found in the reader at {chapter.url}")

        return [
            Page(index=i, url=self.absolute(chapter.url, url) or url,
                 referer=chapter.url)
            for i, url in enumerate(urls, start=1)
        ]

    # --------------------------------------------------------------- search

    search_path = "/series/"

    async def search(self, site: str, query: str, limit: int = 12) -> list[SearchResult]:
        root = _root(site)
        api = _API_URL_RE.search(await self._get(root + "/"))
        if not api:
            log.info("%s exposes no API root; cannot search it", root)
            return []

        data = await self.sessions.fetch_json_direct(
            f"{api.group(1).rstrip('/')}/api/query"
            f"?searchTerm={quote(query)}&perPage={max(limit, 1) * 4}"
        )
        posts = data.get("posts") or []

        results: list[SearchResult] = []
        host = urlparse(root).netloc
        for post in posts:
            title = str(post.get("postTitle") or "").strip()
            slug = str(post.get("slug") or "").strip()
            if not title or not slug or not _relevant(query, title, slug):
                continue
            if str(post.get("seriesType") or "").upper() == "NOVEL":
                # Prose, not pages: it would parse and then produce an empty
                # CBZ. Excluded until the app can package a book.
                continue
            results.append(SearchResult(
                title=title,
                url=f"{root}/series/{slug}",
                source=self.id,
                site=host,
                cover_url=post.get("featuredImage") or None,
            ))
            if len(results) >= limit:
                break
        return results


# ----------------------------------------------------------------- helpers


def _root(url: str) -> str:
    parsed = urlparse(url if "//" in url else f"https://{url}")
    return f"{parsed.scheme}://{parsed.netloc}"


def _slug(url: str) -> str:
    match = _SERIES_RE.search(urlparse(url).path)
    if not match:
        raise AdapterError(
            f"{url} is not a series URL for this site. It should look like "
            "https://azoramoon.com/series/<slug>."
        )
    return match.group(1)


def _series_url(url: str) -> str:
    """The canonical series URL, even when given a chapter's."""
    return f"{_root(url)}/series/{_slug(url)}"


def _number(value) -> str | None:
    """Chapter numbers arrive as JSON numbers; keep them looking like labels."""
    if value is None:
        return None
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value)


def _decode_props(value):
    """Undo Astro's ``[type, payload]`` props encoding.

    Astro tags every value with a small type code so it can round-trip Dates,
    Maps and the like. Only two matter here: 0 wraps a plain value and 1 wraps
    an array, and both need unwrapping all the way down or the chapter list
    reads as a list of two-element lists.
    """
    if isinstance(value, list) and len(value) == 2 and isinstance(value[0], int):
        kind, payload = value
        if kind == 1:
            return [_decode_props(item) for item in payload]
        return _decode_props(payload)
    if isinstance(value, dict):
        return {key: _decode_props(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_decode_props(item) for item in value]
    return value


def _islands(html: str) -> list[dict]:
    """Every decoded ``astro-island`` props object on the page."""
    found: list[dict] = []
    for island in HTMLParser(html).css("astro-island"):
        raw = island.attributes.get("props")
        if not raw:
            continue
        try:
            decoded = _decode_props(json.loads(raw))
        except ValueError:
            continue
        if isinstance(decoded, dict):
            found.append(decoded)
    return found


def _series_props(html: str) -> dict:
    """The island holding the series record and its full chapter list."""
    for props in _islands(html):
        if "initialChap" in props and isinstance(props.get("post"), dict):
            return props
    raise AdapterError(
        "This page carries no series data. The chapter list lives in an "
        "astro-island's props, so a page without one is not a series page on "
        "this platform."
    )


def _locked_chapter(html: str) -> bool:
    """Whether the reader was replaced by a paywall."""
    return any("lockedChapter" in props for props in _islands(html))


def _relevant(query: str, title: str, slug: str) -> bool:
    """Whether a hit plausibly answers ``query``.

    This API only indexes Latin titles, and — this is the part that bites — a
    query it cannot match is not rejected but *ignored*: it answers with the
    whole catalogue, newest first, which is indistinguishable from a page of
    real results. Enough sites do a version of this that the test itself now
    lives in :func:`app.adapters.base.query_matches`.
    """
    return query_matches(query, title, slug)
