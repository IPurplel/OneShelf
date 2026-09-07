"""Heuristic fallback adapter.

When no specific adapter recognises a site, this one guesses. It looks for the
largest group of images that share a URL "shape" — same host, same directory,
sequential numeric filenames — which is what a manga reader page almost always
contains, surrounded by logos, avatars and ad slots that do not share that shape.

It will not work everywhere, but degrading to "probably works" beats refusing
outright, and it keeps the tool useful on sites that are not Madara.
"""

from __future__ import annotations

import logging
import re
from collections import defaultdict
from urllib.parse import urlparse

from ..models import Chapter, Page, Series
from .base import Adapter, AdapterError, first_attr

log = logging.getLogger(__name__)

IMAGE_ATTRS = ("data-src", "data-lazy-src", "data-original", "data-url", "srcset", "src")
IMAGE_EXT_RE = re.compile(r"\.(jpe?g|png|webp|gif|avif)(?:$|\?)", re.I)
NUMERIC_RE = re.compile(r"(\d+)")

CHAPTER_HINTS = ("chapter", "chap", "/ch-", "episode", "فصل")
SKIP_HINTS = ("logo", "avatar", "banner", "icon", "sprite", "ads", "thumb", "cover")


class GenericAdapter(Adapter):
    id = "generic"
    name = "Generic (heuristic)"
    priority = -100  # only chosen when nothing else claims the URL
    # It produces chapter archives, so it belongs with manga — and that keeps
    # the fallback behaving exactly as it did before search grew a type filter.
    content_type = "manga"

    @classmethod
    def matches(cls, url: str, html: str | None = None) -> bool:
        return True  # universal last resort

    async def fetch_series(self, url: str) -> Series:
        html = await self.get_html(url)
        tree = self.parse(html)

        title = (
            first_attr(tree.css_first("meta[property='og:title']"), "content")
            or self.text(tree.css_first("h1"))
            or self.text(tree.css_first("title"))
            or urlparse(url).path.rstrip("/").rsplit("/", 1)[-1]
        )
        cover = first_attr(tree.css_first("meta[property='og:image']"), "content")

        self._last_html = (url, html)
        return Series(
            url=url,
            title=title.strip(),
            source=self.id,
            cover_url=self.absolute(url, cover),
            description=first_attr(
                tree.css_first("meta[name='description']"), "content"
            ),
        )

    async def fetch_chapters(self, series: Series) -> list[Chapter]:
        cached = getattr(self, "_last_html", None)
        html = cached[1] if cached and cached[0] == series.url else await self.get_html(series.url)
        tree = self.parse(html)

        base_path = urlparse(series.url).path.rstrip("/")
        seen: set[str] = set()
        found: list[tuple[str, str]] = []

        for link in tree.css("a"):
            href = self.absolute(series.url, first_attr(link, "href"))
            if not href or href in seen:
                continue
            path = urlparse(href).path
            # A chapter lives under the series path, or names itself as one.
            under_series = base_path and path.startswith(base_path) and path.rstrip("/") != base_path
            looks_like_chapter = any(h in href.lower() for h in CHAPTER_HINTS)
            if not (under_series or looks_like_chapter):
                continue
            seen.add(href)
            found.append((href, self.text(link) or path.rstrip("/").rsplit("/", 1)[-1]))

        if not found:
            raise AdapterError(f"No chapter links recognised on {series.url}")

        found.reverse()  # assume newest-first listing, as most sites do
        chapters = [
            Chapter(url=href, title=title, number=_first_number(title, href), index=i + 1)
            for i, (href, title) in enumerate(found)
        ]
        chapters.sort(key=lambda c: c.sort_key)
        for position, chapter in enumerate(chapters, start=1):
            chapter.index = position
        return chapters

    async def fetch_pages(self, chapter: Chapter) -> list[Page]:
        html = await self.get_html(chapter.url, referer=chapter.url)
        tree = self.parse(html)

        candidates: list[str] = []
        for node in tree.css("img"):
            raw = first_attr(node, *IMAGE_ATTRS)
            absolute = self.absolute(chapter.url, raw)
            if not absolute or absolute in candidates:
                continue
            lowered = absolute.lower()
            if lowered.startswith("data:") or any(s in lowered for s in SKIP_HINTS):
                continue
            if not IMAGE_EXT_RE.search(absolute):
                continue
            candidates.append(absolute)

        best = _largest_sequential_group(candidates)
        if not best:
            raise AdapterError(f"No page images recognised in {chapter.url}")

        return [Page(index=i + 1, url=u, referer=chapter.url) for i, u in enumerate(best)]


def _shape(url: str) -> tuple[str, str, str]:
    """Group key: host + directory + filename with digits masked out.

    ``/uploads/ch12/003.jpg`` and ``/uploads/ch12/004.jpg`` share a shape;
    ``/assets/logo.png`` does not.
    """
    parsed = urlparse(url)
    directory, _, filename = parsed.path.rpartition("/")
    return parsed.netloc, directory, NUMERIC_RE.sub("#", filename)


def _largest_sequential_group(urls: list[str]) -> list[str]:
    """Return the biggest same-shape run, preserving document order."""
    groups: dict[tuple[str, str, str], list[str]] = defaultdict(list)
    for url in urls:
        groups[_shape(url)].append(url)

    if not groups:
        return []

    best = max(groups.values(), key=len)
    # A single stray image is not a chapter; fall back to everything we saw.
    if len(best) < 2:
        return urls
    return best


def _first_number(title: str, url: str) -> str | None:
    match = NUMERIC_RE.search(title)
    if match:
        return match.group(1)
    slug = urlparse(url).path.rstrip("/").rsplit("/", 1)[-1]
    match = NUMERIC_RE.search(slug)
    return match.group(1) if match else None
