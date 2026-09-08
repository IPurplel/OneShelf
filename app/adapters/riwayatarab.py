"""RiwayatArab (رواياتعرب) — Arabic translations of Asian web novels.

Investigated 2026-09-08. Reading is anonymous over plain HTTP; the site offers
accounts, but nothing on the reading path asks for one.

It is a Next.js **App Router** site, and that shapes what works:

* A **valid** novel page is server-rendered — 125 KB with its chapter links in
  the markup. Its ``self.__next_f`` flight payload is only the module manifest;
  there is no chapter data in it and no content API to call. So this adapter
  reads HTML, and the payload is a dead end worth not re-investigating.
* A **missing** novel is also 200, rendering a 16 KB shell titled
  *"رواية غير موجودة"* (novel not found) with zero anchors. A dead slug
  therefore looks exactly like a client-rendered page that has not finished, so
  the adapter checks for the title rather than concluding "needs a browser".

The chapter list is not on the novel page: that shows the first twenty and a
link reading *"عرض جميع الفصول (1344)"* — show all chapters. The list proper is
at ``/novel/<slug>/chapters``, paginated fifty at a time, **one-based and
non-overlapping** (page 27 of the test novel is 1301-1344, and 26x50+44 = 1344,
the count the link advertises). That is worth stating because the last two
paginated sources here were neither.
"""

from __future__ import annotations

import logging
import re
from urllib.parse import quote_plus, urlsplit

from ..models import Chapter, Page, SearchResult, Series, TextChapter
from .base import Adapter, AdapterError, query_matches
from .prose import blocks_from, strip_noise

log = logging.getLogger(__name__)

HOST = "riwayatarab.com"
ROOT = "https://riwayatarab.com"

#: `/novel/<slug>`, `/novel/<slug>/chapters`, `/novel/<slug>/chapter/<n>`.
_NOVEL_RE = re.compile(r"^/novel/([^/?#]+)(?:/(?:chapters|chapter/(\d+)))?/?$")
_CHAPTER_RE = re.compile(r"^/novel/([^/?#]+)/chapter/(\d+)/?$")

#: The reader's text container. One `<div>` and 232 `<br>`; `blocks_from`
#: already splits on those.
READER_SELECTOR = "div.chapter-content"

#: The site's own chapter count, used as a sanity check on the walk.
#:
#: Read from the page's schema.org JSON-LD rather than from the "عرض جميع
#: الفصول (1344)" link, because React's server rendering splits that number
#: from its own parentheses with comment markers -- the markup is literally
#: ``(<!-- -->1344<!-- -->)``, so matching on `\(…\)` finds nothing. JSON-LD is
#: meant for machines and survives that.
_COUNT_RE = re.compile(r'"numberOfPages"\s*:\s*(\d+)')

MAX_LIST_PAGES = 400
MAX_CHAPTERS = 30_000


class RiwayatArabAdapter(Adapter):
    id = "riwayatarab"
    name = "RiwayatArab (رواياتعرب)"
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
        return urlsplit(url).netloc.lower().removeprefix("www.") == HOST

    # ------------------------------------------------------------- fetching

    async def _get(self, url: str, *, referer: str | None = None) -> str:
        cached = self._cache.get(url)
        if cached is not None:
            return cached
        html = await self.sessions.fetch_text_direct(url, referer=referer)
        self._cache[url] = html
        return html

    # ---------------------------------------------------------------- series

    async def fetch_series(self, url: str) -> Series:
        slug = _slug(url)
        novel_url = f"{ROOT}/novel/{slug}"
        tree = self.parse(await self._get(novel_url))

        title = self.text(tree.css_first("h1"))
        if not title:
            # A dead slug answers 200 with a "novel not found" shell, so this
            # is the difference between "gone" and "broken adapter".
            raise AdapterError(
                f"{novel_url} has no novel title. The site answers 200 for a "
                "novel it does not have, so this slug is probably gone — open "
                "the novel on the site and paste the URL from its address bar."
            )
        cover = tree.css_first("main img") or tree.css_first("img")
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
        advertised = _advertised_count(await self._get(series.url))

        found: dict[int, tuple[str, str]] = {}
        for page in range(1, MAX_LIST_PAGES + 1):
            url = f"{ROOT}/novel/{slug}/chapters" + (f"?page={page}" if page > 1 else "")
            try:
                tree = self.parse(await self._get(url, referer=series.url))
            except Exception as exc:
                # A transport failure is not an end-of-list marker. Returning
                # here makes an incomplete catalogue look like a good preview.
                raise AdapterError(
                    f"Could not read RiwayatArab chapter-list page {page} "
                    f"({url}) after collecting {len(found)} chapters. "
                    "The chapter list may be incomplete; retry the preview."
                ) from exc
            before = len(found)
            self._harvest(tree, found, series.url, slug)
            if len(found) == before:
                break
            if len(found) >= MAX_CHAPTERS:
                log.warning("RiwayatArab listing for %s passed %d chapters",
                            slug, MAX_CHAPTERS)
                break

        if not found:
            raise AdapterError(
                f"No chapters listed for {series.url}. Open the novel on the "
                "site and paste the URL from its address bar."
            )
        if advertised and len(found) != advertised:
            # Not fatal — the site's own count can lag — but it is exactly the
            # kind of gap that survives a preview, so it goes in the log.
            log.warning("RiwayatArab lists %d chapters for %s but advertises "
                        "%d", len(found), slug, advertised)

        chapters = [
            Chapter(url=href, title=label, number=str(number))
            for number, (href, label) in found.items()
        ]
        chapters.sort(key=lambda c: c.sort_key)
        for position, chapter in enumerate(chapters, start=1):
            chapter.index = position
        log.info("Resolved %d chapters from %s", len(chapters), series.url)
        return chapters

    def _harvest(self, tree, into: dict[int, tuple[str, str]], base: str,
                 slug: str) -> None:
        for link in tree.css("a"):
            href = self.absolute(base, link.attributes.get("href") or "")
            match = _CHAPTER_RE.match(urlsplit(href or "").path)
            if not match or match.group(1) != slug:
                continue
            number = int(match.group(2))
            if number in into:
                continue
            label = " ".join((self.text(link) or "").split())
            into[number] = (href, label or f"الفصل {number}")

    # ------------------------------------------------------------------ text

    async def fetch_pages(self, chapter: Chapter) -> list[Page]:
        raise AdapterError(
            f"{self.name} serves prose, not page images. Chapters are packaged "
            "as EPUB through fetch_text()."
        )

    async def fetch_text(self, chapter: Chapter) -> TextChapter:
        tree = self.parse(await self._get(chapter.url, referer=chapter.url))
        container = tree.css_first(READER_SELECTOR)
        if container is None:
            raise AdapterError(
                f"No chapter text on {chapter.url}. The page may not be a "
                "chapter, or the reader's markup has changed."
            )
        strip_noise(container)
        blocks = blocks_from(container)
        if not blocks:
            raise AdapterError(f"The reader on {chapter.url} held no text.")
        return TextChapter(title=chapter.title or f"Chapter {chapter.number}",
                           blocks=blocks)

    # --------------------------------------------------------------- search

    SEARCH = ROOT + "/search?q={query}"

    #: The results are mounted client-side, so this one page needs the browser.
    _RESULT_SELECTOR = "a[href^='/novel/']"

    #: Bounds the wait for that selector, well below the configured 10s.
    #:
    #: Its absence is a real answer here -- a query with no matches renders a
    #: page that says so and links nothing -- so the full timeout was paid on
    #: every unsuccessful search. Measured: **12.2s** for an unanswerable query
    #: against 2.8s for one that matched, and in a thirteen-site book fan-out
    #: this site alone pushed the whole search to its 20s ceiling. Results
    #: mount in well under a second when they exist.
    SEARCH_WAIT = 4.0

    async def search(self, site: str, query: str, limit: int = 12) -> list[SearchResult]:
        """Search is the one page here that is *not* server-rendered.

        Measured 2026-09-08: `/search?q=الشيطاني` returns 25 KB whose `<title>`
        is *"نتائج البحث عن الشيطاني"* — it names the query and contains
        **zero** result links. Rendered, the same URL shows five. So reading it
        over plain HTTP is not a site that found nothing; it is a page that had
        not run yet, and the two are indistinguishable without checking.
        """
        url = self.SEARCH.format(query=quote_plus(query))
        # No settle delay: `_settled_content` only applies one when the
        # selector missed, and on this page a missed selector *is* the answer
        # -- an empty result set renders no links however long it is given. It
        # was two more seconds spent on every unsuccessful search.
        tree = self.parse(await self.get_html(
            url, wait_for=self._RESULT_SELECTOR,
            wait_timeout=self.SEARCH_WAIT))

        results: list[SearchResult] = []
        seen: set[str] = set()
        for link in tree.css("a"):
            href = self.absolute(url, link.attributes.get("href") or "")
            path = urlsplit(href or "").path
            match = _NOVEL_RE.match(path)
            # A novel, not one of its chapters.
            if not match or match.group(2) or path.rstrip("/").endswith("/chapters"):
                continue
            if href in seen:
                continue
            title = " ".join((self.text(link.css_first("h2") or
                                        link.css_first("h3") or link) or "").split())
            if not title or not query_matches(query, title, path):
                continue
            seen.add(href)
            results.append(SearchResult(title=title, url=href,
                                        source=self.id, site=HOST))
            if len(results) >= limit:
                break
        return results


# ----------------------------------------------------------------- helpers


def _slug(url: str) -> str:
    parsed = urlsplit(url)
    if parsed.netloc and parsed.netloc.lower().removeprefix("www.") != HOST:
        raise AdapterError(f"{url} is not a RiwayatArab URL.")
    match = _NOVEL_RE.match(parsed.path)
    if not match:
        raise AdapterError(
            f"{url} does not name a novel. A novel URL looks like "
            "https://riwayatarab.com/novel/demonic-emperor"
        )
    return match.group(1)


def _advertised_count(html: str) -> int | None:
    """How many chapters the site says it has, or ``None`` if it does not say.

    ``None`` matters: it means the cross-check was *skipped*, not that it
    passed. The first version of this looked for the count inside the "show all
    chapters" link and silently returned ``None`` on every real page, so the
    walk was never checked against anything at all.
    """
    match = _COUNT_RE.search(html)
    return int(match.group(1)) if match else None
