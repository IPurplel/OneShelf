"""Arabic Collections Online — NYU's open-access Arabic book corpus.

Strictly this reads NYU's **DLTS viewer**, whose IIIF manifests are not
particular to this collection, so it very likely serves the viewer's other
collections too. Only ACO is claimed as supported, because only ACO has a
verified artifact; the rest is untested and should not be advertised on the
strength of a shared API.

Investigated 2026-09-08. Everything here is anonymous: no account, no bot
check, no browser. Worth its own adapter rather than another special case in
:mod:`books` for one reason — **nothing useful is in the HTML**.

The page a reader lands on, ``aco.dlib.nyu.edu/book/<id>/1``, is a 6.5 KB
JavaScript shell. Scraping it finds no title, no author and no file. What it
does do, once running, is fetch a **IIIF Presentation 3.0 manifest**, and that
manifest holds the whole record:

* ``label`` — the title, in English *and* Arabic
* ``metadata`` — author, publisher, date, language, as labelled pairs
* ``viewingDirection`` — ``right-to-left`` for Arabic, which is exactly the
  thing this app otherwise has to guess
* ``items`` — one canvas per scanned page (524 on the test volume)
* ``rendering`` — **the whole book as a single PDF**, in two resolutions

So the adapter reads one JSON document and is done. It deliberately takes the
``rendering`` PDFs rather than assembling pages from the IIIF Image API: the
site has already bound the book, and rebuilding it from 524 JPEGs would be
slower, larger and worse.

The two resolutions are offered as two selectable downloads, the way a book
site offering EPUB and PDF is. They are not small — measured on
``aub_aco000056``: 53.22 MB low, 262.26 MB high — so which one a reader wants
is genuinely their choice, and the size is put in the title where they can see
it before starting.
"""

from __future__ import annotations

import logging
import re
from urllib.parse import urlparse

from urllib.parse import quote_plus

from ..models import Chapter, Page, SearchResult, Series
from .base import Adapter, AdapterError, query_matches

log = logging.getLogger(__name__)

#: ACO's own host: everything on it belongs to this collection.
KNOWN_HOSTS = {"aco.dlib.nyu.edu"}

#: Hosts shared with the rest of the university, claimed only under the path
#: that serves books. `sites.dlib.nyu.edu` is NYU's DLTS **viewer** -- its book
#: ids are collection-prefixed (`aub_…`, `princeton_…`) and its root is a bare
#: "Index of /" -- and `dlib.nyu.edu` is the library at large. Because this
#: adapter sets `owns_its_host`, the registry skips fingerprinting entirely, so
#: claiming either host outright routed every unrelated URL on it here.
SHARED_HOSTS = {
    "sites.dlib.nyu.edu": "/viewer/books/",
    "dlib.nyu.edu": "/aco",
}

MANIFEST = "https://sites.dlib.nyu.edu/viewer/api/presentation/books/{book}/manifest.json"

#: `/book/aub_aco000056/1`, `/viewer/books/aub_aco000056`, `/books/<id>/display`.
_BOOK_ID_RE = re.compile(r"/books?/([A-Za-z0-9_.-]+)")

#: Only whole-book renderings, not per-page images.
_WANTED_FORMATS = {"application/pdf": ".pdf", "application/epub+zip": ".epub"}


class AcoAdapter(Adapter):
    id = "aco"
    name = "Arabic Collections Online (NYU)"
    priority = 118  # an exact host match, like the other API-shaped sources
    content_type = "book"
    packaging = "file"
    owns_its_host = True
    right_to_left = True
    """The manifest says so itself; see `_series_from_manifest`."""

    def __init__(self, session_manager) -> None:
        super().__init__(session_manager)
        self._manifests: dict[str, dict] = {}
        self._pages: dict[str, str] = {}

    # -------------------------------------------------------- identification

    @classmethod
    def matches(cls, url: str, html: str | None = None) -> bool:
        parsed = urlparse(url)
        host = parsed.netloc.lower().removeprefix("www.")
        if host in KNOWN_HOSTS:
            return True
        prefix = SHARED_HOSTS.get(host)
        return prefix is not None and parsed.path.startswith(prefix)

    # ------------------------------------------------------------- fetching

    async def _get(self, url: str) -> str:
        cached = self._pages.get(url)
        if cached is None:
            cached = await self.sessions.fetch_text_direct(url)
            self._pages[url] = cached
        return cached

    async def _manifest(self, url: str) -> dict:
        book = book_id(url)
        cached = self._manifests.get(book)
        if cached is not None:
            return cached
        payload = await self.sessions.fetch_json_direct(MANIFEST.format(book=book))
        if not isinstance(payload, dict) or not payload.get("items"):
            raise AdapterError(
                f"No IIIF manifest for {book}. Open the book on the site and "
                "paste the URL from its address bar."
            )
        self._manifests[book] = payload
        return payload

    # --------------------------------------------------------------- search

    SEARCH = "https://aco.dlib.nyu.edu/search?q={query}"

    async def search(self, site: str, query: str, limit: int = 12) -> list[SearchResult]:
        """Search is plain server-rendered HTML, unlike the reader.

        Each hit appears **twice**: once under its romanised title and once,
        with `?lang=ar`, under the Arabic one. They are the same book, so the
        Arabic title is kept as the alt title rather than listed again -- which
        is also what makes an Arabic query visibly land on the right record
        when the romanised name is what gets displayed.
        """
        url = self.SEARCH.format(query=quote_plus(query))
        tree = self.parse(await self._get(url))

        found: dict[str, dict[str, str]] = {}
        order: list[str] = []
        for link in tree.css("a"):
            href = self.absolute(url, link.attributes.get("href") or "")
            if not href:
                continue
            parsed = urlparse(href)
            # Only the reader link carries the book's name. A result card also
            # holds a "Read Online" button and two PDF links on
            # `mc.dlib.nyu.edu/files/books/<id>/…`, and all of them match the
            # book-id pattern -- so an unrestricted sweep read the title off
            # whichever came last and produced "تحميل دِقّة منخفضةLow-resolution
            # PDF(34.…)" as the title of every hit.
            if (parsed.netloc.lower().removeprefix("www.") != "aco.dlib.nyu.edu"
                    or not parsed.path.startswith("/book/")):
                continue
            title = " ".join((self.text(link) or "").split())
            if not title:
                continue
            try:
                book = book_id(href)
            except AdapterError:
                continue
            arabic = "lang=ar" in (parsed.query or "")
            record = found.setdefault(book, {})
            if book not in order:
                order.append(book)
            # First one wins: the card leads with the title and follows it with
            # a "Read Online" control pointing at the same page.
            record.setdefault("alt_title" if arabic else "title", title)

        results: list[SearchResult] = []
        for book in order:
            record = found[book]
            title = record.get("title") or record.get("alt_title") or ""
            alt = record.get("alt_title") if record.get("title") else None
            # This search page also carries navigation and "related title"
            # links into the same collection, so the text is the gate.
            if not title or not query_matches(query, title, alt or "", book):
                continue
            results.append(SearchResult(
                title=title, url=f"https://aco.dlib.nyu.edu/book/{book}/1",
                source=self.id, site="aco.dlib.nyu.edu", alt_title=alt))
            if len(results) >= limit:
                break
        return results

    # ---------------------------------------------------------------- series

    async def fetch_series(self, url: str) -> Series:
        manifest = await self._manifest(url)
        book = book_id(url)
        return Series(
            url=f"https://aco.dlib.nyu.edu/book/{book}/1",
            title=_label(manifest.get("label")) or book,
            source=self.id,
            cover_url=_thumbnail(manifest),
            description=_metadata(manifest, "Author/Contributor") or None,
            site_id=book,
        )

    # -------------------------------------------------------------- chapters

    async def fetch_chapters(self, series: Series) -> list[Chapter]:
        manifest = await self._manifest(series.url)
        files = _renderings(manifest)
        if not files:
            pages = len(manifest.get("items") or [])
            raise AdapterError(
                f"{series.title} offers no whole-book download. Its manifest "
                f"lists {pages} scanned page(s) but no PDF rendering, so there "
                "is no file here to store."
            )
        # The extension goes **last**. A download is matched on the path's
        # extension, so appending the manifest's own label -- "High-resolution
        # PDF rendering (262.26 MB)" -- after it produced a name ending in
        # "MB))" and the queue refused the file as a type it does not store.
            # Numbered by position as well as indexed. `number` is what
            # selects a single item from the command line and from any tool
            # that addresses a chapter by name; without it a multi-format book
            # could only ever be taken whole. It does not reach the filename --
            # `file` packaging names each download after the book -- and
            # `format_chapter_number` already falls back to the index, so this
            # changes nothing that was working.
        return [
            Chapter(url=f"{series.url}#{position}",
                    title=f"{series.title}{_variant(label, position)}{extension}",
                    number=str(position), index=position)
            for position, (_url, extension, label) in enumerate(files, start=1)
        ]

    # ----------------------------------------------------------------- pages

    async def fetch_pages(self, chapter: Chapter) -> list[Page]:
        book_url, _, fragment = chapter.url.partition("#")
        files = _renderings(await self._manifest(book_url))
        try:
            position = int(fragment)
        except ValueError:
            position = 0
        if not (1 <= position <= len(files)):
            raise AdapterError(
                f"{chapter.title} is no longer offered for {book_url}."
            )
        return [Page(index=1, url=files[position - 1][0], referer=book_url)]


# ----------------------------------------------------------------- helpers


def book_id(url: str) -> str:
    """The book's identifier, from any of the URL shapes the site uses."""
    match = _BOOK_ID_RE.search(urlparse(url).path)
    if not match:
        raise AdapterError(
            f"{url} does not name a book. A book URL looks like "
            "https://aco.dlib.nyu.edu/book/aub_aco000056/1"
        )
    return match.group(1)


def _label(value, *, prefer: str = "en") -> str:
    """One string from a IIIF language map.

    IIIF 3 labels are ``{"en": [...], "ar": [...]}``. English is preferred for
    the *filename* — it is the half that survives a filesystem and a library
    listing — but any language is better than none.
    """
    if isinstance(value, str):
        return value.strip()
    if not isinstance(value, dict):
        return ""
    for key in (prefer, *value):
        entries = value.get(key)
        if isinstance(entries, list) and entries:
            return str(entries[0]).strip()
    return ""


def _metadata(manifest: dict, label: str) -> str:
    for entry in manifest.get("metadata") or []:
        if _label(entry.get("label")) == label:
            return _label(entry.get("value"))
    return ""


def _thumbnail(manifest: dict) -> str | None:
    for entry in manifest.get("thumbnail") or []:
        if isinstance(entry, dict) and entry.get("id"):
            return str(entry["id"])
    return None


def _variant(label: str, position: int) -> str:
    """How one rendering is told from another, as part of a filename.

    The manifest offers the same book twice and the only real difference is
    resolution, so that is what the name has to carry -- a library listing two
    identically-named PDFs is a library where one silently overwrites the
    other. The size stays out of the name: it changes when the site re-scans,
    and a filename that encodes it goes stale.
    """
    lowered = label.lower()
    for word in ("high", "low", "medium"):
        if word in lowered:
            return f" ({word} resolution)"
    return f" ({position})" if position > 1 else ""


def _renderings(manifest: dict) -> list[tuple[str, str, str]]:
    """Whole-book downloads: ``(url, extension, label)``, best first.

    A IIIF ``rendering`` is the standard place a manifest advertises "the whole
    object as one file", which is exactly what a library wants and what the
    Image API cannot give. Anything that is not a format we store is skipped
    rather than guessed at.
    """
    out: list[tuple[str, str, str]] = []
    for entry in manifest.get("rendering") or []:
        if not isinstance(entry, dict):
            continue
        url = entry.get("id") or entry.get("@id")
        extension = _WANTED_FORMATS.get(str(entry.get("format") or "").lower())
        if not url or not extension:
            continue
        # The label carries the size, which is the whole basis on which someone
        # picks between a 53 MB and a 262 MB copy of the same book.
        out.append((str(url), extension, _label(entry.get("label"))))
    return out
