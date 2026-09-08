"""Rewayat Club — Arabic translations of Asian web novels.

Investigated 2026-09-08. Reading is anonymous over plain HTTP; no account, no
browser, no bot check on any request type.

**The novel page does not list the chapters.** It shows the newest two dozen of
a serial that runs past nine hundred, has no pagination control, and no
"all chapters" link. Three guessed `api.rewayat.club` endpoints answer 404.

**A chapter page does.** This is a Nuxt app, and every chapter's hydration
payload carries an ``allChapters`` array — the whole serial, as
``{value: <id>, text: "الفصل N"}`` — alongside the chapter being read. So the
list costs one extra request to a chapter, not a walk.

Two details of that payload matter, and both are the sort of thing that reads
as a parsing bug months later:

* It is **minified JavaScript, not JSON**. Values are references to
  single-letter variables assigned earlier in the same function, so
  ``{value:j,text:"الفصل 2"}`` cannot be decoded by reading ``value``. The
  chapter number is taken from ``text`` instead, which is a literal.
* **The entry for the chapter you are on is not a literal at all.** It is
  built by assignment (``i.text=e``), so a regex over ``text:"…"`` returns
  every chapter *except* the current one — 954 of 955. The chapter being read
  is therefore added back explicitly, from the URL that fetched it.

Measured on ``/novel/cleaver-of-sin``: 954 literal entries spanning 2-955,
plus the chapter fetched, giving a contiguous 1-955.
"""

from __future__ import annotations

import logging
import re
from urllib.parse import quote_plus, urlsplit, urlunsplit

from ..models import Chapter, Page, SearchResult, Series, TextChapter
from .base import Adapter, AdapterError, query_matches
from .prose import blocks_from, strip_noise

log = logging.getLogger(__name__)

HOST = "rewayat.club"
ROOT = "https://rewayat.club"

#: `/novel/<slug>` is a novel; `/novel/<slug>/<n>` is its chapter n.
_NOVEL_RE = re.compile(r"^/novel/([^/?#]+)(?:/(\d+))?/?$")

#: The reader. Vuetify, so the class is the component's, not the site's.
READER_SELECTORS = ("div.v-card--flat", "div.v-card", "#__nuxt")

#: `text:"الفصل 12"` inside the payload's allChapters array.
_ENTRY_RE = re.compile(r'text:"([^"]*?(\d+)[^"]*)"')

#: A serial longer than this is a parsing accident.
MAX_CHAPTERS = 20_000


class RewayatAdapter(Adapter):
    id = "rewayat"
    name = "Rewayat Club (نادي الروايات)"
    priority = 75
    content_type = "book"
    packaging = "text"
    owns_its_host = True
    right_to_left = True

    def __init__(self, session_manager) -> None:
        super().__init__(session_manager)
        self._cache: dict[str, str] = {}

    # -------------------------------------------------------- identification

    @classmethod
    def matches(cls, url: str, html: str | None = None) -> bool:
        host = urlsplit(url).netloc.lower().removeprefix("www.")
        return host == HOST

    # ------------------------------------------------------------- fetching

    async def _get(self, url: str, *, referer: str | None = None) -> str:
        cached = self._cache.get(url)
        if cached is not None:
            return cached
        html = await self.sessions.fetch_text_direct(url, referer=referer)
        self._cache[url] = html
        return html

    # --------------------------------------------------------------- search

    #: `/search?q=` renders a page that mentions the query and links nothing.
    #: The library's filter is the one that answers.
    SEARCH = ROOT + "/library?search={query}"

    async def search(self, site: str, query: str, limit: int = 12) -> list[SearchResult]:
        url = self.SEARCH.format(query=quote_plus(query))
        tree = self.parse(await self._get(url))

        results: list[SearchResult] = []
        seen: set[str] = set()
        for link in tree.css("a"):
            href = _clean(self.absolute(url, link.attributes.get("href") or ""))
            if not href or not _NOVEL_RE.match(urlsplit(href).path):
                continue
            if urlsplit(href).path.rstrip("/").count("/") != 2:
                continue          # a chapter, not a novel
            if href in seen:
                continue
            # The result card wraps the title *and* its genre tags in one
            # anchor, so the anchor's own text reads
            # "ساطور الخطيئة مترجمة أكشن فانتازيا" -- a title no reader would
            # recognise and one nothing else would match. Vuetify's title
            # element holds just the name.
            title = " ".join(
                (self.text(link.css_first("div.v-list-item__title"))
                 or self.text(link) or "").split())
            if not title:
                continue
            # The library page also carries its own navigation into `/novel/`,
            # so the text is the gate.
            if not query_matches(query, title, urlsplit(href).path):
                continue
            seen.add(href)
            results.append(SearchResult(
                title=title, url=href, source=self.id, site=HOST))
            if len(results) >= limit:
                break
        return results

    # ---------------------------------------------------------------- series

    async def fetch_series(self, url: str) -> Series:
        slug = _slug(url)
        novel_url = f"{ROOT}/novel/{slug}"
        tree = self.parse(await self._get(novel_url))

        title = self.text(tree.css_first("h1"))
        if not title:
            raise AdapterError(
                f"{novel_url} has no novel title — it is probably not a "
                "Rewayat Club novel page."
            )
        cover = tree.css_first("img[src*='/media/novel/']") or tree.css_first("img")
        return Series(
            url=novel_url,
            title=title,
            source=self.id,
            cover_url=self.absolute(novel_url, (cover.attributes.get("src")
                                                if cover is not None else "")),
            site_id=slug,
        )

    # -------------------------------------------------------------- chapters

    async def fetch_chapters(self, series: Series) -> list[Chapter]:
        slug = _slug(series.url)
        novel = await self._get(series.url)

        # Any chapter will do: each one's payload carries the whole list. The
        # newest is the one link the novel page is guaranteed to have.
        entry = _newest_chapter(novel, slug)
        if entry is None:
            raise AdapterError(
                f"No chapter links on {series.url}. Open the novel on the site "
                "and paste the URL from its address bar."
            )
        chapter_url = f"{ROOT}/novel/{slug}/{entry}"
        payload = await self._get(chapter_url, referer=series.url)

        numbers = _all_chapter_numbers(payload)
        # The chapter whose page this is has no literal entry of its own.
        numbers[entry] = numbers.get(entry) or f"الفصل {entry}"
        if not numbers:
            raise AdapterError(
                f"{chapter_url} carried no chapter list. The site's reader may "
                "have changed."
            )
        if len(numbers) > MAX_CHAPTERS:
            log.warning("Rewayat listed %d chapters for %s; truncating",
                        len(numbers), slug)
            numbers = dict(sorted(numbers.items())[:MAX_CHAPTERS])

        chapters = [
            Chapter(url=f"{ROOT}/novel/{slug}/{number}", title=label,
                    number=str(number))
            for number, label in numbers.items()
        ]
        chapters.sort(key=lambda c: c.sort_key)
        for position, chapter in enumerate(chapters, start=1):
            chapter.index = position
        log.info("Resolved %d chapters from %s", len(chapters), series.url)
        return chapters

    # ------------------------------------------------------------------ text

    async def fetch_pages(self, chapter: Chapter) -> list[Page]:
        raise AdapterError(
            f"{self.name} serves prose, not page images. Chapters are packaged "
            "as EPUB through fetch_text()."
        )

    async def fetch_text(self, chapter: Chapter) -> TextChapter:
        tree = self.parse(await self._get(chapter.url, referer=chapter.url))

        # The first candidate that actually yields text. Vuetify's class names
        # are the component's, not the site's, so several nodes can match and
        # the shallowest is not always the reader -- but only one of them holds
        # prose.
        #
        # Selection used to ask `looks_like_prose`, which answers "prose or
        # pictures?" and carries a length floor with it. That is the wrong
        # question here: it made a genuinely short chapter fail with "the
        # reader's markup has changed", which is wrong twice over -- the markup
        # was fine and the chapter was readable. Whether this site serves prose
        # at all is settled; what is left is finding where it put it.
        blocks = []
        for selector in READER_SELECTORS:
            node = tree.css_first(selector)
            if node is None:
                continue
            strip_noise(node)
            blocks = blocks_from(node)
            if blocks:
                break

        if not blocks:
            raise AdapterError(
                f"No chapter text on {chapter.url}. The page may not be a "
                "chapter, or the reader's markup has changed."
            )
        return TextChapter(title=chapter.title or f"Chapter {chapter.number}",
                           blocks=blocks)


# ----------------------------------------------------------------- helpers


def _slug(url: str) -> str:
    parsed = urlsplit(url)
    if parsed.netloc and parsed.netloc.lower().removeprefix("www.") != HOST:
        raise AdapterError(f"{url} is not a Rewayat Club URL.")
    match = _NOVEL_RE.match(parsed.path)
    if not match:
        raise AdapterError(
            f"{url} does not name a novel. A novel URL looks like "
            "https://rewayat.club/novel/cleaver-of-sin"
        )
    return match.group(1)


def _clean(url: str) -> str:
    """Drop the query. Chapter links carry a `?username=` attribution tag, and
    keeping it would make the same chapter two different chapters."""
    parts = urlsplit(url)
    return urlunsplit((parts.scheme, parts.netloc, parts.path, "", ""))


def _newest_chapter(html: str, slug: str) -> int | None:
    """The highest chapter number linked from a novel page."""
    found = [int(n) for n in re.findall(
        rf"/novel/{re.escape(slug)}/(\d+)", html)]
    return max(found) if found else None


def _all_chapter_numbers(html: str) -> dict[int, str]:
    """Every chapter in the reader's ``allChapters`` array, number -> label.

    Scoped to that array rather than run over the whole payload: the same
    ``text:"…"`` shape appears elsewhere in the hydration state, and a loose
    match would invent chapters out of menu labels.
    """
    start = html.find("allChapters:[")
    if start < 0:
        return {}
    block = html[start + len("allChapters:"):]
    depth = 0
    end = None
    for position, char in enumerate(block):
        if char == "[":
            depth += 1
        elif char == "]":
            depth -= 1
            if depth == 0:
                end = position
                break
    if end is None:
        return {}

    out: dict[int, str] = {}
    for label, number in _ENTRY_RE.findall(block[:end + 1]):
        out.setdefault(int(number), label.strip())
    return out
