"""Adapter for comic blogs published on Blogger/Blogspot.

Blogger has no notion of a series, so themes invent one. On the blogs this
targets, a **post is a series landing page** and its issues are listed in a
widget the theme injects with JavaScript after the page loads. That last
detail drives the whole design: the served HTML contains no issue links at all,
so the list has to be read from the rendered DOM.

Two dead ends, recorded so they are not retried:

* **The Blogger JSON feed does not contain the issues.** ``/feeds/posts/...``
  returns only the landing posts. A feed query for a series label returns zero
  results, because series have no label of their own — the labels are genres,
  publishers and ratings.
* **The issue number is never in the URL.** Slugs look like ``18.html``,
  ``16_16.html`` and ``19_02077140790.html``; only the link text carries the
  real number (``العدد#19`` — "issue #19").
"""

from __future__ import annotations

import logging
import re
from urllib.parse import urlparse

from ..models import Chapter, Page, Series
from .base import Adapter, AdapterError, extract_number, first_attr

log = logging.getLogger(__name__)

#: The theme's injected issue list. Captured from the rendered DOM, not guessed.
#:
#: Wait on a *link*, not the container: `div.chapter-table` is in the served
#: markup already and starts empty, so waiting for it returns immediately and
#: the issues are read before the script has added any.
CHAPTER_TABLE = "div.chapter-item a, div.chapter-table a"
CHAPTER_LINKS = ("div.chapter-item a", "div.chapter-table a")

#: The widget took a few seconds to populate when measured; be generous, since
#: the alternative is reporting a series as having no issues at all.
SETTLE_MS = 4000

#: Blogger permalinks are always /YYYY/MM/<slug>.html.
POST_PATH_RE = re.compile(r"^/\d{4}/\d{2}/.+\.html$")

IMAGE_ATTRS = ("data-src", "data-lazy-src", "data-original", "srcset", "src")

#: Where Blogger serves uploaded images from.
IMAGE_HOSTS = ("blogger.googleusercontent.com", "bp.blogspot.com", "blogspot.com")

POST_BODY_SELECTORS = (
    "div.post-body",
    "div.entry-content",
    "article .post-body",
    "#post-body",
)

#: Theme furniture that lives in the post body but is not a comic page.
_DECORATIVE = ("data:image", "/img/blank", "icon", "logo", "avatar", "emoji",
               "blogger.com/img", "/s35/", "/s72-c/", "/w72-h72")


class BloggerAdapter(Adapter):
    id = "blogger"
    name = "Blogger / Blogspot"
    priority = 90
    content_type = "comics"
    right_to_left = False
    """These blogs publish Marvel/DC comics, which read left to right."""

    # -------------------------------------------------------- identification

    @classmethod
    def matches(cls, url: str, html: str | None = None) -> bool:
        host = urlparse(url).netloc.lower()
        if host.endswith(".blogspot.com") or host == "blogspot.com":
            return True
        if html:
            # A custom domain on Blogger still gives itself away in the DOM.
            lowered = html[:200_000].lower()
            return (
                'content="blogger"' in lowered
                or "blogger.googleusercontent.com" in lowered
                or "www.blogger.com/static" in lowered
            )
        return False

    # ---------------------------------------------------------------- series

    async def fetch_series(self, url: str) -> Series:
        url = url.split("#")[0]
        html = await self._rendered(url)
        tree = self.parse(html)

        title = (
            self.text(tree.css_first("h1.post-title"))
            or self.text(tree.css_first("h1.entry-title"))
            or self.text(tree.css_first(".post-title"))
            or first_attr(tree.css_first("meta[property='og:title']"), "content")
            or _title_from_url(url)
        )
        cover = first_attr(
            tree.css_first("meta[property='og:image']"), "content"
        ) or self._first_image(tree, url)

        series = Series(
            url=url,
            title=_strip_site_name(title, tree),
            source=self.id,
            cover_url=self.absolute(url, cover),
            description=first_attr(
                tree.css_first("meta[property='og:description']"), "content"
            ),
        )
        self._rendered_cache = (url, html)
        return series

    # -------------------------------------------------------------- chapters

    async def fetch_chapters(self, series: Series) -> list[Chapter]:
        html = await self._rendered(series.url)
        tree = self.parse(html)

        seen: set[str] = set()
        collected: list[tuple[str, str]] = []
        for selector in CHAPTER_LINKS:
            for node in tree.css(selector):
                href = self.absolute(series.url, first_attr(node, "href"))
                label = self.text(node)
                if not href or href in seen:
                    continue
                if not self._is_issue_link(href, series.url):
                    continue
                seen.add(href)
                collected.append((href, label or _title_from_url(href)))
            if collected:
                break

        if not collected:
            raise AdapterError(
                f"No issue list found on {series.url}. The issues on these blogs "
                "are added by the page's own script after it loads — if the "
                "series page shows none in a browser either, there are none yet."
            )

        chapters = [
            # The number comes from the label, never the slug: "16_16.html" and
            # "19_02077140790.html" would otherwise parse as nonsense.
            Chapter(url=href, title=label, number=extract_number(label, href),
                    index=position)
            for position, (href, label) in enumerate(collected, start=1)
        ]
        chapters.sort(key=lambda c: c.sort_key)
        for position, chapter in enumerate(chapters, start=1):
            chapter.index = position
        log.info("Resolved %d issues from %s", len(chapters), series.url)
        return chapters

    def _is_issue_link(self, href: str, series_url: str) -> bool:
        """A real issue: another post on this blog, not the series itself."""
        if href.rstrip("/") == series_url.rstrip("/"):
            return False
        parsed, series_parsed = urlparse(href), urlparse(series_url)
        if parsed.netloc != series_parsed.netloc:
            return False
        return bool(POST_PATH_RE.match(parsed.path))

    # ----------------------------------------------------------------- pages

    async def fetch_pages(self, chapter: Chapter) -> list[Page]:
        html = await self._rendered(chapter.url, referer=chapter.url)
        tree = self.parse(html)

        body = None
        for selector in POST_BODY_SELECTORS:
            body = tree.css_first(selector)
            if body is not None:
                break

        urls: list[str] = []
        seen: set[str] = set()
        for node in (body or tree).css("img"):
            raw = first_attr(node, *IMAGE_ATTRS)
            resolved = self.absolute(chapter.url, raw)
            if not resolved or resolved in seen:
                continue
            if not _is_page_image(resolved):
                continue
            seen.add(resolved)
            urls.append(resolved)

        if not urls:
            raise AdapterError(
                f"No page images found in {chapter.url}. The post may link to "
                "its pages elsewhere rather than embedding them."
            )
        return [
            Page(index=i, url=url, referer=chapter.url)
            for i, url in enumerate(urls, start=1)
        ]

    # ------------------------------------------------------------- internals

    async def _rendered(self, url: str, *, referer: str | None = None) -> str:
        """Fetch with the theme's script given time to inject its content.

        Caches under its own name rather than reusing ``_last_html``: the
        registry pre-fetches the page to fingerprint it and stores the result
        there, and that copy is *unrendered*. Reusing it silently skipped the
        wait and made every series look as though it had no issues.
        """
        cached = getattr(self, "_rendered_cache", None)
        if cached and cached[0] == url:
            return cached[1]
        html = await self.get_html(
            url, referer=referer, wait_for=CHAPTER_TABLE, wait_ms=SETTLE_MS
        )
        self._rendered_cache = (url, html)
        return html

    def _first_image(self, tree, base: str) -> str | None:
        for node in tree.css("img"):
            candidate = self.absolute(base, first_attr(node, *IMAGE_ATTRS))
            if candidate and _is_page_image(candidate):
                return candidate
        return None


def _is_page_image(url: str) -> bool:
    lowered = url.lower()
    if any(marker in lowered for marker in _DECORATIVE):
        return False
    return any(host in lowered for host in IMAGE_HOSTS)


def _strip_site_name(title: str, tree) -> str:
    """Drop the blog's own name from a post title.

    Blogger themes append it ("ABSOLUTE BATMAN - Comicverse"), and the title
    becomes the folder name on disk, so the branding would end up in every
    path. Uses the blog's declared name rather than a hardcoded list.
    """
    cleaned = " ".join(title.split())
    site = first_attr(tree.css_first("meta[property='og:site_name']"), "content")
    if site:
        cleaned = re.sub(
            rf"\s*[|–-]\s*{re.escape(site.strip())}\s*$", "", cleaned, flags=re.I
        )
    return cleaned.strip(" -|–") or title.strip()


def _title_from_url(url: str) -> str:
    slug = urlparse(url).path.rstrip("/").rsplit("/", 1)[-1]
    slug = re.sub(r"\.html$", "", slug)
    return slug.replace("-", " ").replace("_", " ").strip().title() or "Untitled"
