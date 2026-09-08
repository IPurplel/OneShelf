"""WuxiaBox — English translations of Chinese web novels.

Investigated 2026-09-08. Reading is anonymous over plain HTTP: no account, no
browser, no bot check on any request type.

Three things about this site are worth stating before the code, because none of
them is guessable and each one silently loses chapters if guessed wrong:

**The chapter list is behind a tab, and the tab is a different page.** The
novel page shows a description; the chapters live at ``?tab=chapters``.

**The listing is paged, the page number is zero-based, and duplicate links
consume rows.** On ``/novel/absolute-resonance.html``, the saved tab has 100
links representing **90 distinct chapters (1-90)**; ``page=1`` lists **91-190**.
Later pagination was observed at a stride of 90 against 100 rows. Neither row
count nor URL uniqueness establishes chapter count: padded and unpadded URLs
can name the same chapter. The walk de-duplicates on the chapter number, and
the last page comes from the paginator's own ``>>`` link instead of a guess.

**A chapter is one paragraph and 234 line breaks.** ``div.chapter-content``
holds a single ``<p>`` whose lines are separated by ``<br>``; reading
``node.text()`` would return 19,000 characters as one run-on sentence.
``prose.blocks_from`` already splits on ``<br>`` for exactly this reason.
"""

from __future__ import annotations

import logging
import re
from urllib.parse import parse_qs, urlsplit

from ..models import Chapter, Page, Series, TextChapter
from .base import Adapter, AdapterError
from .prose import blocks_from, strip_noise

log = logging.getLogger(__name__)

HOST = "wuxiabox.com"
ROOT = "https://wuxiabox.com"

#: `/novel/<slug>.html` is a novel; `/novel/<slug>_<n>.html` is its chapter n.
_NOVEL_RE = re.compile(r"^/novel/([a-z0-9-]+?)(?:_(\d+))?\.html$", re.I)

#: The paginated listing. `page` is zero-based; `wjm` is the novel's slug.
_LISTING = ROOT + "/e/extend/fy.php?page={page}&wjm={slug}"

#: The reader's text container, and the chapter's own heading inside it.
READER_SELECTOR = "div.chapter-content"

#: Pages are bounded by the paginator, but a runaway needs a stop.
MAX_LIST_PAGES = 200

#: A novel longer than this is a parsing accident.
MAX_CHAPTERS = 30_000


class WuxiaBoxAdapter(Adapter):
    id = "wuxiabox"
    name = "WuxiaBox"
    priority = 75
    content_type = "book"
    packaging = "text"
    owns_its_host = True

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

    # ---------------------------------------------------------------- series

    async def fetch_series(self, url: str) -> Series:
        slug = _slug(url)
        novel_url = f"{ROOT}/novel/{slug}.html"
        tree = self.parse(await self._get(novel_url))

        title = self.text(tree.css_first("h1"))
        if not title:
            raise AdapterError(
                f"{novel_url} has no novel title — it is probably not a "
                "WuxiaBox novel page."
            )
        cover = tree.css_first("div.book-img img") or tree.css_first("img")
        return Series(
            url=novel_url,
            title=title,
            source=self.id,
            cover_url=self.absolute(novel_url, _first_src(cover)),
            description=self.text(tree.css_first("div.book-desc")) or None,
            site_id=slug,
        )

    # -------------------------------------------------------------- chapters

    async def fetch_chapters(self, series: Series) -> list[Chapter]:
        slug = _slug(series.url)
        first = await self._get(f"{series.url}?tab=chapters", referer=series.url)
        tree = self.parse(first)

        collected: dict[str, tuple[str, str]] = {}
        self._harvest(tree, collected, series.url, slug)
        last = _last_page(tree)

        for page in range(1, min(last, MAX_LIST_PAGES) + 1):
            url = _LISTING.format(page=page, slug=slug)
            try:
                more = self.parse(await self._get(url, referer=series.url))
            except Exception as exc:
                raise AdapterError(
                    f"Could not read WuxiaBox chapter-list page {page} "
                    f"({url}) after collecting {len(collected)} chapters. "
                    "The chapter list may be incomplete; retry the preview."
                ) from exc
            before = len(collected)
            self._harvest(more, collected, series.url, slug)
            if len(collected) == before:
                # Pages overlap by design, but a page adding *nothing* means the
                # walk has run past the end.
                break
            if len(collected) >= MAX_CHAPTERS:
                log.warning("WuxiaBox listing for %s passed %d chapters; stopping",
                            slug, MAX_CHAPTERS)
                break

        if not collected:
            raise AdapterError(
                f"No chapters listed for {series.url}. Open the novel on the "
                "site and paste the URL from its address bar."
            )

        chapters = [
            Chapter(url=href, title=label, number=number)
            for number, (href, label) in collected.items()
        ]
        chapters.sort(key=lambda c: c.sort_key)
        for position, chapter in enumerate(chapters, start=1):
            chapter.index = position
        log.info("Resolved %d chapters from %s", len(chapters), series.url)
        return chapters

    def _harvest(self, tree, into: dict[str, tuple[str, str]], base: str,
                 slug: str) -> None:
        """Add this page's rows, keyed by chapter number rather than by URL.

        Two things make the URL the wrong key. Consecutive listing pages
        overlap by ten rows, which de-duplicating on anything would handle --
        but the site also publishes some chapters under **two URLs**, one
        zero-padded: ``…_46.html`` and ``…_0046.html`` are the same chapter.
        Measured on ``absolute-resonance``: 1,333 links, 1,216 chapters, so 117
        of them would have been downloaded and packaged twice.

        Rows for *other* novels are dropped: listing pages carry
        recommendation panels, and their chapter numbers would collide with
        this novel's.
        """
        container = tree.css_first("ul.chapter-list") or tree
        for link in container.css("a"):
            href = self.absolute(base, link.attributes.get("href") or "")
            if not href:
                continue
            number = _chapter_number(href)
            if not number:
                continue
            try:
                if _slug(href) != slug:
                    continue
            except AdapterError:
                continue
            label = " ".join((self.text(link) or "").split())
            key = number.lstrip("0") or "0"
            if key not in into and label:
                into[key] = (href, label)

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
        heading = self.text(tree.css_first("h2")) or chapter.title
        return TextChapter(title=heading or f"Chapter {chapter.number}",
                           blocks=blocks)


# ----------------------------------------------------------------- helpers


def _slug(url: str) -> str:
    """The novel's slug, from a novel URL or one of its chapters."""
    parsed = urlsplit(url)
    if parsed.netloc and parsed.netloc.lower().removeprefix("www.") != HOST:
        raise AdapterError(f"{url} is not a WuxiaBox URL.")
    # The listing endpoint names the novel in a query parameter instead.
    if parsed.path.startswith("/e/extend/"):
        wjm = parse_qs(parsed.query).get("wjm")
        if wjm:
            return wjm[0]
    match = _NOVEL_RE.match(parsed.path)
    if not match:
        raise AdapterError(
            f"{url} does not name a novel. A novel URL looks like "
            "https://wuxiabox.com/novel/absolute-resonance.html"
        )
    return match.group(1)


def _chapter_number(url: str) -> str | None:
    match = _NOVEL_RE.match(urlsplit(url).path)
    return match.group(2) if match else None


def _last_page(tree) -> int:
    """The highest listing page, from the paginator's own links.

    Read rather than computed: the pages overlap, so chapter counts cannot be
    divided into a page count.
    """
    highest = 0
    for link in tree.css("ul.pagination a") or tree.css(".pagination a"):
        query = urlsplit(link.attributes.get("href") or "").query
        for value in parse_qs(query).get("page", []):
            if value.isdigit():
                highest = max(highest, int(value))
    return highest


def _first_src(node) -> str:
    if node is None:
        return ""
    for attr in ("data-src", "data-original", "src"):
        value = node.attributes.get(attr)
        if value:
            return value
    return ""
