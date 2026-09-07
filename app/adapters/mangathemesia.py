"""Adapter for the MangaThemesia / "TS" WordPress theme.

The second most widely deployed manga theme after Madara, and the one most
Arabic and Indonesian scanlation groups use. Like the Madara adapter this
targets the *theme*, so one implementation covers hundreds of sites and keeps
working when any of them changes hostname.

The theme is recognisable by three things that Madara never has: a chapter list
in ``div.eplister``, a reader in ``#readerarea``, and — the important one — a
``ts_reader.run({...})`` call holding the page list as JSON.

That JSON is the reliable source for pages. The reader also writes ``<img>``
tags, but lazily: several builds ship a placeholder in ``src`` and the real URL
in ``data-src``, and some only insert images once the reader script runs. The
JSON is present in the served HTML either way, so it is tried first and the DOM
is the fallback.
"""

from __future__ import annotations

import json
import logging
import re
from urllib.parse import quote_plus, urlparse

from ..models import Chapter, Page, SearchResult, Series
from .base import Adapter, AdapterError, extract_number, first_attr

log = logging.getLogger(__name__)

#: Post-type bases these installs use for a series.
SERIES_BASES = ("manga", "series", "komik", "manhwa", "manhua", "comic")

#: DOM fingerprints. `eplister` and `readerarea` are the theme's own class
#: names and do not appear in Madara, so matching cannot cross over.
FINGERPRINTS = ("eplister", "readerarea", "ts_reader", "bixbox", "wp-manga-list")

#: The reader's page list: ts_reader.run({... "sources":[{"images":[...]}]}).
TS_READER_RE = re.compile(r"ts_reader\.run\(\s*(\{.*?\})\s*\)\s*;", re.S)

IMAGE_ATTRS = ("data-src", "data-lazy-src", "data-original", "srcset", "src")

#: Some installs keep the theme's markup but answer search from a JSON endpoint
#: wired up in JavaScript, leaving ``?s=`` to serve the **homepage** with a
#: perfectly ordinary 200. Its grid parses into a tidy list of series that has
#: nothing to do with the query — the same handful every time — so the marker
#: has to be checked before the page is believed.
LIVE_SEARCH_MARKER = "Index/live_search"
LIVE_SEARCH_PATH = "/Index/live_search"

#: These builds link a series as ``/series/<prefix>-<slug>`` with a site-wide
#: prefix that appears nowhere but their own markup, and the endpoint returns
#: no URL of its own — so the link is rebuilt exactly as the site's script does.
_SERIES_PREFIX_RE = re.compile(r"/series/([a-z]\d+)-")

_DECORATIVE = ("data:image", "/wp-content/themes/", "logo", "spinner",
               "loading.gif", "/avatar", "gravatar")


class MangaThemesiaAdapter(Adapter):
    id = "mangathemesia"
    name = "MangaThemesia / TS (WordPress)"
    # Above Madara: some installs carry leftover Madara strings in shared
    # plugins, and the TS fingerprints are the more specific signal.
    priority = 110
    content_type = "manga"

    # -------------------------------------------------------- identification

    @classmethod
    def matches(cls, url: str, html: str | None = None) -> bool:
        if html:
            return any(marker in html for marker in FINGERPRINTS)
        # Without a page to fingerprint the URL shape is shared with Madara, so
        # claim nothing and let the DOM decide on the next attempt.
        return False

    # ---------------------------------------------------------------- search

    search_path = "/?s={query}"

    async def search(self, site: str, query: str, limit: int = 12) -> list[SearchResult]:
        url = site.rstrip("/") + self.search_path.format(query=quote_plus(query))
        html = await self.get_html(url)
        if LIVE_SEARCH_MARKER in html:
            return await self._live_search(site, html, query, limit)
        tree = self.parse(html)

        results: list[SearchResult] = []
        seen: set[str] = set()
        for card in tree.css("div.listupd div.bs") or tree.css("div.bs"):
            link = card.css_first("a")
            href = self.absolute(url, first_attr(link, "href"))
            # The theme puts the full title in the anchor's title attribute and
            # a possibly-truncated one in .tt.
            title = (
                first_attr(link, "title")
                or self.text(card.css_first(".tt"))
                or self.text(link)
            )
            if not href or not title:
                continue
            # The same series appears in both a carousel and the grid.
            if href.rstrip("/") in seen:
                continue
            seen.add(href.rstrip("/"))
            cover = first_attr(card.css_first("img"), *IMAGE_ATTRS)
            results.append(SearchResult(
                title=title.strip(), url=href, source=self.id,
                site=urlparse(href).netloc,
                cover_url=self.absolute(url, cover),
            ))
            if len(results) >= limit:
                break
        return results

    async def _live_search(
        self, site: str, html: str, query: str, limit: int
    ) -> list[SearchResult]:
        """Search an install whose ``?s=`` page is really just its homepage.

        Returning nothing would be a poor outcome; returning the front-page
        grid is a worse one, because it looks like an answer. The endpoint the
        site's own search box calls gives real matches, so use that.
        """
        root = site.rstrip("/")
        prefix = _SERIES_PREFIX_RE.search(html)
        if not prefix:
            log.info("%s uses a live search but exposes no series prefix", root)
            return []

        try:
            body = await self.sessions.post_form(
                root + LIVE_SEARCH_PATH, {"search_value": query}, referer=root + "/"
            )
            items = json.loads(body)
        except Exception as exc:
            log.info("Live search failed on %s: %s", root, exc)
            return []
        if not isinstance(items, list):
            return []

        host = urlparse(root).netloc
        results: list[SearchResult] = []
        for item in items[:limit]:
            title = str((item or {}).get("title") or "").strip()
            if not title:
                continue
            image = item.get("image_url")
            results.append(SearchResult(
                title=title,
                url=f"{root}/series/{prefix.group(1)}-{_live_slug(title)}",
                source=self.id,
                site=host,
                cover_url=f"{root}/assets/images/{image}" if image else None,
            ))
        return results

    # ---------------------------------------------------------------- series

    async def fetch_series(self, url: str) -> Series:
        url = _normalise_series_url(url)
        html = await self.get_html(url)
        tree = self.parse(html)

        title = (
            self.text(tree.css_first("h1.entry-title"))
            or self.text(tree.css_first(".seriestuheader h1"))
            or first_attr(tree.css_first("meta[property='og:title']"), "content")
            or _title_from_url(url)
        )
        cover = (
            first_attr(tree.css_first("div.thumb img"), *IMAGE_ATTRS)
            or first_attr(tree.css_first(".seriestucontl img"), *IMAGE_ATTRS)
            or first_attr(tree.css_first("meta[property='og:image']"), "content")
        )
        description = (
            self.text(tree.css_first("div.entry-content"))
            or self.text(tree.css_first(".seriestuentry"))
            or None
        )

        author = None
        for row in tree.css(".infotable tr, .tsinfo .imptdt"):
            label = self.text(row).lower()
            if "author" in label or "المؤلف" in label:
                author = self.text(row.css_first("td:nth-child(2)")) or None
                break

        series = Series(
            url=url,
            title=title.strip(),
            source=self.id,
            cover_url=self.absolute(url, cover),
            author=author,
            description=description,
        )
        self._last_html = (url, html)
        return series

    # -------------------------------------------------------------- chapters

    async def fetch_chapters(self, series: Series) -> list[Chapter]:
        html = await self._series_html(series.url)
        tree = self.parse(html)

        nodes = tree.css("div.eplister ul li a") or tree.css("#chapterlist ul li a")
        collected: list[tuple[str, str, str | None]] = []
        seen: set[str] = set()

        for node in nodes:
            href = self.absolute(series.url, first_attr(node, "href"))
            if not href or href in seen:
                continue
            # A "chapter" that is the series itself is navigation markup, the
            # same trap that once produced a one-chapter series on Madara.
            if href.rstrip("/") == series.url.rstrip("/"):
                continue
            seen.add(href)
            label = (
                self.text(node.css_first("span.chapternum"))
                or self.text(node.css_first(".chapternum"))
                or self.text(node)
            )
            date = self.text(node.css_first("span.chapterdate")) or None
            collected.append((href, label, date))

        if not collected:
            raise AdapterError(
                f"No chapter list on {series.url}. Open the series page on the "
                "site and paste that URL."
            )

        chapters = [
            Chapter(url=href, title=label, number=extract_number(label, href), date=date)
            for href, label, date in collected
        ]
        chapters.sort(key=lambda c: c.sort_key)
        for position, chapter in enumerate(chapters, start=1):
            chapter.index = position
        log.info("Resolved %d chapters from %s", len(chapters), series.url)
        return chapters

    # ----------------------------------------------------------------- pages

    async def fetch_pages(self, chapter: Chapter) -> list[Page]:
        html = await self.get_html(chapter.url, referer=chapter.url)

        urls = _images_from_ts_reader(html)
        if not urls:
            urls = self._images_from_dom(html, chapter.url)

        if not urls:
            raise AdapterError(
                f"No page images found in {chapter.url}. The reader may be "
                "empty, or this may not be a chapter page."
            )
        return [
            Page(index=i, url=self.absolute(chapter.url, url) or url,
                 referer=chapter.url)
            for i, url in enumerate(urls, start=1)
        ]

    def _images_from_dom(self, html: str, base: str) -> list[str]:
        tree = self.parse(html)
        area = tree.css_first("#readerarea") or tree.css_first("div.reader-area")
        urls: list[str] = []
        seen: set[str] = set()
        for node in (area or tree).css("img"):
            candidate = first_attr(node, *IMAGE_ATTRS)
            resolved = self.absolute(base, candidate)
            if not resolved or resolved in seen or _is_decorative(resolved):
                continue
            seen.add(resolved)
            urls.append(resolved)
        return urls

    async def _series_html(self, url: str) -> str:
        cached = getattr(self, "_last_html", None)
        if cached and cached[0] == url:
            return cached[1]
        html = await self.get_html(url)
        self._last_html = (url, html)
        return html


def _images_from_ts_reader(html: str) -> list[str]:
    """Page URLs from the reader's own JSON payload.

    Preferred over the DOM because several builds ship a placeholder in ``src``
    and only fill the real URL in later — reading the markup then yields a page
    of identical spinner images.
    """
    match = TS_READER_RE.search(html)
    if not match:
        return []
    try:
        data = json.loads(match.group(1))
    except ValueError:
        log.debug("ts_reader payload was not valid JSON")
        return []

    for source in data.get("sources") or []:
        images = [str(u).strip() for u in (source.get("images") or []) if u]
        if images:
            return images
    return []


def _live_slug(title: str) -> str:
    """Rebuild the slug the site's own script derives from a title.

    Faithful to that script rather than tidy: it collapses every run of
    non-alphanumerics into a hyphen — leaving a trailing one when the title
    ends in punctuation — and then applies two fix-ups for English contractions
    ("The Devil's Boy" -> ``devils-boy``). Its regexes carry no ``g`` flag, so
    each fix-up changes only the first match, and so does this.
    """
    slug = re.sub(r"[^a-z0-9]+", "-", title.lower())
    slug = slug.replace("-s-", "s-", 1)
    return slug.replace("-ll-", "ll-", 1)


def _is_decorative(url: str) -> bool:
    lowered = url.lower()
    return any(marker in lowered for marker in _DECORATIVE)


def _normalise_series_url(url: str) -> str:
    """Trim a chapter URL back to its series, as the Madara adapter does.

    TS puts chapters on their own top-level slug (``/one-piece-chapter-1050/``)
    rather than under the series, so only a ``/<base>/<slug>/<extra>`` shape can
    be trimmed; anything else is returned untouched and verified by the parse.
    """
    url = url.strip().split("?")[0].split("#")[0]
    parsed = urlparse(url)
    segments = [s for s in parsed.path.split("/") if s]
    for position, segment in enumerate(segments):
        if segment.lower() in SERIES_BASES and position + 2 <= len(segments) - 1:
            path = "/" + "/".join(segments[: position + 2]) + "/"
            return f"{parsed.scheme}://{parsed.netloc}{path}"
    return url if url.endswith("/") else url + "/"


def _title_from_url(url: str) -> str:
    slug = urlparse(url).path.rstrip("/").rsplit("/", 1)[-1]
    return slug.replace("-", " ").replace("_", " ").title() or "Unknown Series"
