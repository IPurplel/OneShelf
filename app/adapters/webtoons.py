"""WEBTOON — the publisher's own site, free episodes only.

Investigated 2026-09-07. Everything below was observed against
``/en/action/eleceed`` on that date, over plain anonymous HTTP with no browser
and no account.

Three facts shape this adapter:

**The page URL is not in ``src``.** Every viewer image ships with a shared
transparent placeholder in ``src`` and the real URL in ``data-url``. Reading
``src`` yields a chapter of identical 1×1 spacers that validates as a real
image and packs into a real CBZ — the worst kind of failure, because nothing
downstream can tell it is wrong. ``IMAGE_ATTRS`` puts ``data-url`` first.

**The image host requires the referer.** Measured on one page URL: with the
viewer as ``Referer`` it answers 200 ``image/jpeg``; without, **403**. The
project already carries a referer per page, so this costs nothing — but it is
why the images cannot simply be handed to a bare fetcher.

**Only some episodes are free.** WEBTOON sells early access ("Fast Pass") and a
locked episode is not readable anonymously. Locked rows are dropped from the
listing rather than queued to fail, and a viewer that serves no images is
reported as locked rather than as a parse error. **This adapter therefore
covers the free back catalogue and says so — never the whole series.**

Episode order comes from ``data-episode-no`` on each row, not from the label:
the site lists newest-first and its labels are free text ("Prologue",
"Episode 12 - Part 2"), while the attribute is the site's own number.
"""

from __future__ import annotations

import logging
import re
from urllib.parse import parse_qs, quote_plus, urlsplit, urlunsplit

from ..models import Chapter, Page, SearchResult, Series
from .base import Adapter, AdapterError, first_attr, query_matches, relevance

log = logging.getLogger(__name__)

HOST = "webtoons.com"

#: ``data-url`` first, and that ordering is the whole point — see the module
#: docstring. ``src`` stays last so a layout without lazy-loading still works.
IMAGE_ATTRS = ("data-url", "data-src", "srcset", "src")

#: The viewer's page images. The class is what separates them from the site
#: furniture, which is also served from the same CDN.
READER_SELECTOR = "img._images"

#: One row of the episode list.
EPISODE_ROW = "ul#_listUl li"

#: How far a listing will page. A very long serial runs to a few hundred
#: episodes at ten per page; the cap stops a malformed pagination block from
#: walking forever.
MAX_LIST_PAGES = 500

#: Row markers for an episode that is not free yet.
_LOCK_MARKERS = ("ico_lock", "_lock", "lock_ico", "daily_pass_lock")

_LIST_RE = re.compile(r"^/(?:[a-z-]+/)?[a-z-]+/[^/]+/list$")


class WebtoonsAdapter(Adapter):
    id = "webtoons"
    name = "WEBTOON (free episodes)"
    priority = 75
    content_type = "comics"
    owns_its_host = True
    right_to_left = False
    """Webtoons are vertical-scroll and read top to bottom; the page order is
    linear either way, but a comic reader must not flip them."""

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
        url = _list_url(url)
        html = await self._get(url)
        tree = self.parse(html)

        title = self.text(tree.css_first("h1.subj")) or self.text(
            tree.css_first("h3.subj")
        )
        if not title:
            raise AdapterError(
                f"{url} has no series title — it is probably not a WEBTOON "
                "episode-list page."
            )

        cover = None
        og = tree.css_first('meta[property="og:image"]')
        if og is not None:
            cover = self.absolute(url, og.attributes.get("content"))

        # The *first* author area only. The list page also carries a
        # "you may also like" strip whose cards each have their own `.author`,
        # and collecting them all credited Eleceed to seven different people.
        author = self.text(tree.css_first("div.author_area")) or None
        if author:
            # The block ends with an "author info" affordance that is a control,
            # not a name.
            author = re.sub(r"\s*author info\s*$", "", author).strip() or None

        return Series(
            url=url,
            title=title,
            source=self.id,
            cover_url=cover,
            author=author,
            description=self.text(tree.css_first("p.summary")) or None,
            site_id=_title_no(url),
        )

    # -------------------------------------------------------------- chapters

    async def fetch_chapters(self, series: Series) -> list[Chapter]:
        found: dict[int, tuple[str, str, str | None]] = {}
        locked = 0

        page = 1
        while page <= MAX_LIST_PAGES:
            page_url = _with_page(series.url, page)
            try:
                html = await self._get(page_url, referer=series.url)
            except Exception as exc:
                log.warning(
                    "WEBTOON: episode list stopped at page %d for %s (%s). "
                    "Listing the %d episodes read so far.",
                    page, series.url, exc, len(found),
                )
                break

            before = len(found)
            locked += _collect(self, html, series.url, found)
            if len(found) == before:
                # Past the last page: WEBTOON keeps answering 200 with an empty
                # list rather than 404, so "nothing new" is the end condition.
                break
            page += 1

        if locked:
            log.info(
                "%s: %d episode(s) are behind Fast Pass and were not listed",
                series.url, locked,
            )
        if not found:
            raise AdapterError(
                f"No free episodes listed at {series.url}"
                + (f" — all {locked} listed episodes require Fast Pass."
                   if locked else ".")
            )

        return [
            Chapter(url=url, title=title, number=str(number),
                    index=index, date=date)
            for index, (number, (url, title, date))
            in enumerate(sorted(found.items()), start=1)
        ]

    # ----------------------------------------------------------------- pages

    async def fetch_pages(self, chapter: Chapter) -> list[Page]:
        html = await self._get(chapter.url, referer=chapter.url)
        tree = self.parse(html)

        urls: list[str] = []
        seen: set[str] = set()
        for node in tree.css(READER_SELECTOR):
            raw = first_attr(node, *IMAGE_ATTRS)
            absolute = self.absolute(chapter.url, raw)
            if not absolute or absolute in seen:
                continue
            if _is_placeholder(absolute):
                # The shared spacer every lazy-loaded image carries in `src`.
                # Reaching this means `data-url` was missing on that node.
                continue
            seen.add(absolute)
            urls.append(absolute)

        if not urls:
            if _viewer_is_locked(html):
                raise AdapterError(
                    f"{chapter.url} is not free to read. WEBTOON sells early "
                    "access to recent episodes, and a locked episode serves a "
                    "purchase prompt instead of its pages."
                )
            raise AdapterError(
                f"No page images in the viewer at {chapter.url}. The episode "
                "may have been removed, or the viewer markup changed."
            )

        # DOM order is reading order: a webtoon is one vertical strip cut into
        # slices, and the viewer emits them top to bottom.
        return [
            Page(index=i, url=url, referer=chapter.url)
            for i, url in enumerate(urls, start=1)
        ]

    # ---------------------------------------------------------------- search

    search_path = "/en/search"

    async def search(self, site: str, query: str, limit: int = 12) -> list[SearchResult]:
        url = f"https://www.webtoons.com/en/search?keyword={quote_plus(query)}"
        try:
            html = await self._get(url)
        except Exception as exc:
            log.info("WEBTOON search failed: %s", exc)
            return []

        tree = self.parse(html)
        results: list[SearchResult] = []
        seen: set[str] = set()
        for node in tree.css("a._card_item, a.card_item, a"):
            href = node.attributes.get("href") or ""
            if "/list?title_no=" not in href:
                continue
            target = _list_url(self.absolute(url, href) or "")
            # `strong.title` and not the anchor's own text: the card also holds
            # the author, the view count and a status badge, and reading the
            # whole anchor produced "EleceedJeho Son / ZHENA497M Views".
            title = self.text(node.css_first("strong.title"))
            author = self.text(node.css_first("div.author")) or None
            if not title or target in seen or not query_matches(query, title):
                continue
            seen.add(target)
            results.append(SearchResult(
                title=title, url=target, source=self.id, site=HOST, author=author,
            ))
            if len(results) >= limit:
                break
        results.sort(key=lambda hit: -relevance(query, hit.title, author=hit.author))
        return results


# ------------------------------------------------------------------ helpers

def _title_no(url: str) -> str | None:
    values = parse_qs(urlsplit(url).query).get("title_no")
    return values[0] if values else None


def _list_url(url: str) -> str:
    """Normalise a viewer URL to the series' episode list.

    Pasting the episode you are reading is the natural thing to do, and the
    viewer URL carries the same ``title_no`` the list needs.
    """
    parts = urlsplit(url)
    if _LIST_RE.match(parts.path):
        return _clean(parts, keep_page=False)
    number = _title_no(url)
    if not number:
        return url
    # ``/en/action/eleceed/episode-401/viewer`` -> ``/en/action/eleceed/list``
    segments = [seg for seg in parts.path.split("/") if seg]
    if segments and segments[-1] == "viewer":
        segments = segments[:-2] + ["list"]
    path = "/" + "/".join(segments)
    return urlunsplit((parts.scheme, parts.netloc, path, f"title_no={number}", ""))


def _clean(parts, *, keep_page: bool) -> str:
    kept = [
        item for item in parts.query.split("&")
        if item and (item.startswith("title_no=") or (keep_page and item.startswith("page=")))
    ]
    return urlunsplit((parts.scheme, parts.netloc, parts.path, "&".join(kept), ""))


def _with_page(url: str, page: int) -> str:
    parts = urlsplit(url)
    kept = [
        item for item in parts.query.split("&")
        if item and not item.startswith("page=")
    ]
    if page > 1:
        kept.append(f"page={page}")
    return urlunsplit((parts.scheme, parts.netloc, parts.path, "&".join(kept), ""))


def _collect(adapter: Adapter, html: str, base: str,
             found: dict[int, tuple[str, str, str | None]]) -> int:
    """Add one list page's episodes to ``found``; return how many were locked."""
    locked = 0
    for row in adapter.parse(html).css(EPISODE_ROW):
        raw = row.attributes.get("data-episode-no")
        if not raw or not raw.isdigit():
            continue
        number = int(raw)
        if number in found:
            continue
        markup = row.html or ""
        if any(marker in markup for marker in _LOCK_MARKERS):
            locked += 1
            continue
        link = row.css_first("a")
        if link is None:
            continue
        href = adapter.absolute(base, link.attributes.get("href"))
        if not href:
            continue
        title = adapter.text(row.css_first("span.subj")) or f"Episode {number}"
        date_node = row.css_first("span.date")
        date = adapter.text(date_node) or None
        found[number] = (href, " ".join(title.split()), date)
    return locked


def _is_placeholder(url: str) -> bool:
    """The shared 1×1/transparent spacer WEBTOON puts in every lazy ``src``."""
    return "bg_transparency" in url or url.startswith("data:")


_VIEWER_LOCK_MARKERS = ("fast pass", "unlock", "daily pass", "coin")


def _viewer_is_locked(html: str) -> bool:
    lowered = html.lower()
    return any(marker in lowered for marker in _VIEWER_LOCK_MARKERS)
