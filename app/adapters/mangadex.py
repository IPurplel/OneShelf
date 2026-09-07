"""Adapter for MangaDex.

The one supported site with a real, documented, public API — no scraping, no
bot check, no browser. That makes it both the fastest adapter here and the most
stable: the endpoints are versioned and published, unlike theme markup that
changes whenever a site restyles.

It also matters for language. MangaDex hosts translations per chapter, so a
series carries separate Arabic, English and other feeds, and the app asks for
the language in ``settings.language`` — the same setting already written into
each CBZ's ComicInfo. Berserk, for instance, has 108 chapters in Arabic.

Endpoints used, all public:

    GET /manga?title=...&includes[]=cover_art        search
    GET /manga/{id}?includes[]=cover_art             series metadata
    GET /manga/{id}/feed?translatedLanguage[]=..     chapter list (paginated)
    GET /at-home/server/{chapterId}                  page filenames + host

Pages are assembled as ``{baseUrl}/data/{hash}/{filename}``. The ``data`` set
is the original upload; ``dataSaver`` is a recompressed copy, so it is never
used — this downloader's whole point is the original bytes.
"""

from __future__ import annotations

import asyncio
import logging
import re
from urllib.parse import urlparse

from ..models import Chapter, Page, SearchResult, Series
from .base import Adapter, AdapterError

log = logging.getLogger(__name__)

API = "https://api.mangadex.org"
COVERS = "https://uploads.mangadex.org/covers"

#: /title/<uuid> — the slug after it is decoration and may be absent.
UUID_RE = re.compile(
    r"([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})", re.I
)

#: Ask for everything; the site's own filtering is not this tool's business,
#: and omitting these silently hides chapters from a series the user chose.
CONTENT_RATINGS = ["safe", "suggestive", "erotica", "pornographic"]

#: The API caps a feed page at 500.
FEED_PAGE = 500
MAX_FEED_PAGES = 20

#: How many name matches to accept from ``/author?name=``. The lookup is fuzzy,
#: so a common surname returns a long tail of unrelated people; taking a few
#: keeps the follow-up query a sane length.
MAX_AUTHOR_MATCHES = 5


class MangaDexAdapter(Adapter):
    id = "mangadex"
    name = "MangaDex"
    priority = 120  # an exact host match; nothing else can claim these URLs
    content_type = "manga"
    owns_its_host = True  # so a job never renders the site to identify it

    #: ``at-home`` names one node and mints a short-lived URL for it. When that
    #: node is mid-fetch from upstream it answers 403/503/404, and when it drops
    #: out of the pool its links stop working altogether — both of which a fresh
    #: request fixes, because MangaDex hands out whichever node is healthy now.
    pages_expire = True

    @classmethod
    def matches(cls, url: str, html: str | None = None) -> bool:
        host = urlparse(url).netloc.lower()
        return host.endswith("mangadex.org")

    # ---------------------------------------------------------------- search

    search_path = "/manga"

    async def search(self, site: str, query: str, limit: int = 12) -> list[SearchResult]:
        """Search titles and authors, and merge the two.

        ``/manga?title=`` matches titles only, so a query that is a person's
        name finds nothing they wrote — "Kentaro Miura" returned a memorial
        anthology and Berserk Gaiden, but not Berserk. Authors need their own
        lookup (``/author?name=`` for ids, then ``/manga?authors[]=``), so both
        run concurrently and the results are merged by manga id.
        """
        by_title, by_author = await asyncio.gather(
            self._search_titles(query, limit),
            self._search_authors(query, limit),
            return_exceptions=True,
        )

        merged: dict[str, dict] = {}
        for outcome in (by_title, by_author):
            if isinstance(outcome, BaseException):
                # One half failing is not a failed search: the other half is
                # still a real answer, and author lookup is the optional one.
                log.info("MangaDex search half failed: %s", outcome)
                continue
            for item in outcome:
                merged.setdefault(item["id"], item)

        results = []
        for item in list(merged.values())[:limit]:
            title = _pick_title(item)
            results.append(SearchResult(
                title=title,
                url=f"https://mangadex.org/title/{item['id']}",
                source=self.id,
                site="mangadex.org",
                cover_url=_cover_url(item),
                alt_title=_matched_title(item, query, title),
                author=_author_name(item),
            ))
        return results

    async def _search_titles(self, query: str, limit: int) -> list[dict]:
        data = await self.sessions.fetch_json_direct(
            f"{API}/manga",
            params=[
                ("title", query), ("limit", min(limit, 100)),
                ("includes[]", "cover_art"), ("includes[]", "author"),
                *[("contentRating[]", r) for r in CONTENT_RATINGS],
            ],
        )
        return data.get("data", [])

    async def _search_authors(self, query: str, limit: int) -> list[dict]:
        """Everything written by anyone whose name matches ``query``.

        Two hops, because the manga endpoint filters on author *ids* and has no
        free-text author parameter. The name lookup is fuzzy at MangaDex's end —
        "Kentaro Miura" finds "Miura Kentarou" — which is exactly why this
        cannot be approximated by matching the author string ourselves.
        """
        found = await self.sessions.fetch_json_direct(
            f"{API}/author", params=[("name", query), ("limit", MAX_AUTHOR_MATCHES)]
        )
        ids = [a["id"] for a in found.get("data", []) if a.get("id")]
        if not ids:
            return []

        data = await self.sessions.fetch_json_direct(
            f"{API}/manga",
            params=[
                ("limit", min(limit, 100)),
                ("includes[]", "cover_art"), ("includes[]", "author"),
                *[("authors[]", i) for i in ids],
                *[("contentRating[]", r) for r in CONTENT_RATINGS],
            ],
        )
        return data.get("data", [])

    # ---------------------------------------------------------------- series

    async def fetch_series(self, url: str) -> Series:
        manga_id = _manga_id(url)
        data = await self.sessions.fetch_json_direct(
            f"{API}/manga/{manga_id}", params=[("includes[]", "cover_art")]
        )
        item = data.get("data") or {}
        attributes = item.get("attributes") or {}

        description = attributes.get("description") or {}
        return Series(
            url=f"https://mangadex.org/title/{manga_id}",
            title=_pick_title(item),
            source=self.id,
            cover_url=_cover_url(item),
            description=(
                description.get(self._language())
                or description.get("en")
                or next(iter(description.values()), None)
            ),
            site_id=manga_id,
        )

    # -------------------------------------------------------------- chapters

    async def fetch_chapters(self, series: Series) -> list[Chapter]:
        manga_id = series.site_id or _manga_id(series.url)
        language = self._language()

        collected: list[Chapter] = []
        offset = 0
        for _page in range(MAX_FEED_PAGES):
            data = await self.sessions.fetch_json_direct(
                f"{API}/manga/{manga_id}/feed",
                params=[
                    ("translatedLanguage[]", language),
                    ("limit", FEED_PAGE), ("offset", offset),
                    ("order[chapter]", "asc"),
                    *[("contentRating[]", r) for r in CONTENT_RATINGS],
                ],
            )
            batch = data.get("data") or []
            for entry in batch:
                attributes = entry.get("attributes") or {}
                # Chapters hosted elsewhere, or withdrawn, have no pages here.
                # Including them would queue work that can only ever fail.
                if attributes.get("externalUrl") or attributes.get("isUnavailable"):
                    continue
                number = attributes.get("chapter")
                label = attributes.get("title") or ""
                collected.append(Chapter(
                    url=f"https://mangadex.org/chapter/{entry['id']}",
                    title=label or (f"Chapter {number}" if number else "Oneshot"),
                    number=number,
                    date=attributes.get("publishAt"),
                ))
            offset += FEED_PAGE
            if offset >= int(data.get("total") or 0) or not batch:
                break

        if not collected:
            raise AdapterError(
                f"No chapters in '{language}' for this series. MangaDex hosts "
                "each translation separately — change `language` in Settings "
                "to a language this series is translated into."
            )

        collected.sort(key=lambda c: c.sort_key)
        for position, chapter in enumerate(collected, start=1):
            chapter.index = position
        log.info("Resolved %d '%s' chapters from MangaDex", len(collected), language)
        return collected

    # ----------------------------------------------------------------- pages

    async def fetch_pages(self, chapter: Chapter) -> list[Page]:
        chapter_id = _manga_id(chapter.url)
        data = await self.sessions.fetch_json_direct(
            f"{API}/at-home/server/{chapter_id}"
        )
        base = (data.get("baseUrl") or "").rstrip("/")
        block = data.get("chapter") or {}
        # `data` is the original upload; `dataSaver` is recompressed and would
        # quietly undo the point of storing images byte-for-byte.
        files = block.get("data") or []
        if not base or not files:
            raise AdapterError(f"MangaDex served no pages for {chapter.url}")

        return [
            Page(index=i, url=f"{base}/data/{block['hash']}/{name}",
                 referer="https://mangadex.org/")
            for i, name in enumerate(files, start=1)
        ]

    def _language(self) -> str:
        return getattr(self.sessions, "_settings", None) and \
            self.sessions._settings.language or "en"


def _manga_id(url: str) -> str:
    match = UUID_RE.search(url)
    if not match:
        raise AdapterError(
            f"{url} is not a MangaDex title URL. It should look like "
            "https://mangadex.org/title/<id>."
        )
    return match.group(1)


def _pick_title(item: dict) -> str:
    """Best available title, preferring Latin script for a folder name."""
    attributes = item.get("attributes") or {}
    titles = attributes.get("title") or {}
    for key in ("en", "ja-ro", "ja"):
        if titles.get(key):
            return titles[key]
    if titles:
        return next(iter(titles.values()))
    for alt in attributes.get("altTitles") or []:
        if alt:
            return next(iter(alt.values()))
    return "Unknown Series"


def _matched_title(item: dict, query: str, shown: str) -> str | None:
    """The alternative title ``query`` matched, when ``shown`` does not.

    MangaDex indexes every name a series is known by, so searching in Arabic
    legitimately returns series whose displayed title is romanised — "الغريب"
    matches JoJo's Bizarre Adventure through "مغامرة جوجو الغريبة". Showing
    only the romanised name makes a correct hit look like the search ignored
    the query, which is the whole difference between "this is broken" and
    "here is your series".
    """
    needle = query.strip().casefold()
    if not needle or needle in shown.casefold():
        return None

    attributes = item.get("attributes") or {}
    for group in (attributes.get("altTitles") or []):
        for value in (group or {}).values():
            if value and needle in str(value).casefold():
                return str(value)

    # The primary title in another script can match while the one we chose to
    # display does not.
    for value in (attributes.get("title") or {}).values():
        if value and needle in str(value).casefold():
            return str(value)
    return None


def _author_name(item: dict) -> str | None:
    """The author from an ``includes[]=author`` expansion, if it is there.

    Only populated when the caller asked for the expansion — the relationship
    is always listed but carries no ``attributes`` otherwise, which is why this
    reads the name rather than assuming the entry means anything by itself.
    """
    for relation in item.get("relationships") or []:
        if relation.get("type") != "author":
            continue
        name = (relation.get("attributes") or {}).get("name")
        if name:
            return name
    return None


def _cover_url(item: dict) -> str | None:
    for relation in item.get("relationships") or []:
        if relation.get("type") != "cover_art":
            continue
        filename = (relation.get("attributes") or {}).get("fileName")
        if filename:
            return f"{COVERS}/{item['id']}/{filename}.512.jpg"
    return None
