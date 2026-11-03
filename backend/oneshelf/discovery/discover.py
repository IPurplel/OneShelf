"""Discover: browse a source's own lists, and two honest surprises (docs/adr/0004-discover.md).

A source that publishes a `latest` or `trending` list can be browsed one page at a time. Nothing is ranked,
scored or invented here: the order is the source's, the page is the source's, and a result is a Work exactly
as in search (INV-27). A surprise says where it came from — a source's list, or the reader's own shelf — and
never offers what is already on the shelf as something new.
"""
from __future__ import annotations

import random
import sqlite3
import time
from collections.abc import Callable
from dataclasses import asdict, dataclass

from oneshelf.net.governor import Priority
from oneshelf.search.cache import DiscoveryCache
from oneshelf.search.grouping import LiveListing, ResultWork, group_results

FEEDS = ("latest", "trending")
MAX_PAGE = 50
# A page read this recently is shown again as it was; older, it is asked for again (and kept as a fallback).
FRESH_SECONDS = 6 * 3600
# A surprise looks only near the top of a list: deep pages cost requests and are rarely what a person wants.
SURPRISE_PAGES = 3


class UnknownSource(LookupError):
    pass


class FeedUnavailable(RuntimeError):
    def __init__(self, category: str, message: str) -> None:
        super().__init__(message)
        self.category = category


@dataclass(frozen=True)
class DiscoverSource:
    source_id: str
    name: str
    feeds: list[str]
    category: str | None
    languages: list[str]


@dataclass
class FeedPage:
    source_id: str
    kind: str
    page: int
    items: list[ResultWork]
    has_more: bool
    cached: bool


class DiscoverService:
    def __init__(self, conn: sqlite3.Connection, sources, plugins, cache: DiscoveryCache, *,
                 rng: random.Random | None = None, clock: Callable[[], float] = time.time) -> None:
        self.conn = conn
        self.sources = sources
        self.plugins = plugins
        self.cache = cache
        self.rng = rng or random.Random()
        self.clock = clock

    # -- sources ------------------------------------------------------------------------------------

    def browsable(self) -> list[DiscoverSource]:
        feeds: dict[str, list[str]] = {}
        for kind in FEEDS:
            for source_id, _version in self.sources.sources_with_capability(kind):
                feeds.setdefault(source_id, []).append(kind)
        found = []
        for record in self.plugins.list():
            if record.id in feeds:
                found.append(DiscoverSource(record.id, record.name, feeds[record.id], record.category,
                                            list(record.languages)))
        return sorted(found, key=lambda s: s.name.lower())

    def _version(self, source_id: str, kind: str) -> str:
        for candidate, version in self.sources.sources_with_capability(kind):
            if candidate == source_id:
                return version
        raise UnknownSource(source_id)

    # -- feeds --------------------------------------------------------------------------------------

    async def feed(self, source_id: str, kind: str, page: int) -> FeedPage:
        if kind not in FEEDS or not 1 <= page <= MAX_PAGE:
            raise ValueError("unknown feed or page")
        if not any(s.source_id == source_id for s in self.browsable()):
            raise UnknownSource(source_id)
        if kind not in next(s.feeds for s in self.browsable() if s.source_id == source_id):
            raise ValueError("this source does not offer that list")
        version = self._version(source_id, kind)
        key = f"discover:{page}"
        stored = self.cache.get(source_id, version, kind, key)
        if stored is not None and self.clock() - stored.get("at", 0) < FRESH_SECONDS:
            return self._page(source_id, kind, page, stored, cached=True)
        try:
            result = await self.sources.run(source_id, kind, {}, priority=Priority.INTERACTIVE,
                                            pages=(page - 1, 1))
        except Exception as exc:
            if stored is not None:
                return self._page(source_id, kind, page, stored, cached=True)   # an older page beats none
            raise FeedUnavailable(getattr(exc, "category", "transport"), str(exc)) from exc
        entries = list(result.entries)
        issues = [i.category for i in result.evidence.issues]
        if not entries and issues and set(issues) != {"not_found"}:
            if stored is not None:
                return self._page(source_id, kind, page, stored, cached=True)
            raise FeedUnavailable(issues[0], "the source did not return this page")
        # An empty page, a 404 past the end, or a list the source itself says is complete: nothing more.
        has_more = bool(entries) and not result.complete and page < MAX_PAGE
        payload = {"at": self.clock(), "has_more": has_more, "listings": [asdict(LiveListing(
            source_id=source_id, listing_key=e.listing_key, title=e.title, url=e.url, content_type=e.content_type,
            language=e.language, cover_url=e.cover_url, creator=e.creator, original_title=e.original_title,
            available_languages=getattr(e, "available_languages", None))) for e in entries]}
        self.cache.put(source_id, version, kind, key, payload)
        return self._page(source_id, kind, page, payload, cached=False)

    def _page(self, source_id: str, kind: str, page: int, payload: dict, *, cached: bool) -> FeedPage:
        listings = [LiveListing(**item) for item in payload["listings"]]
        items = group_results(self.conn, listings) if listings else []
        return FeedPage(source_id, kind, page, items, bool(payload.get("has_more")), cached)

    def shelf_ids(self) -> set[str]:
        return {row[0] for row in self.conn.execute("SELECT work_id FROM shelf_entries")}

    # -- surprises ----------------------------------------------------------------------------------

    async def surprise_from_sources(self, source_id: str | None = None) -> tuple[ResultWork, DiscoverSource, str] | None:
        """One work from a source's list that is not on the shelf, with the list it came from."""
        candidates = [s for s in self.browsable() if source_id is None or s.source_id == source_id]
        if source_id is not None and not candidates:
            raise UnknownSource(source_id)
        on_shelf = self.shelf_ids()
        attempts = [(s, kind, page) for s in candidates for kind in s.feeds for page in range(1, SURPRISE_PAGES + 1)]
        self.rng.shuffle(attempts)
        # First pages are cheaper and usually cached: they are tried before the deeper ones of the same list.
        attempts.sort(key=lambda attempt: attempt[2] > 1)
        for source, kind, page in attempts[:6]:
            try:
                found = await self.feed(source.source_id, kind, page)
            except (FeedUnavailable, ValueError):
                continue
            fresh = [item for item in found.items if item.work_id not in on_shelf]
            if fresh:
                return self.rng.choice(fresh), source, kind
        return None

    def surprise_from_shelf(self, content_type: str | None = None) -> dict | None:
        """A work on the shelf that reading has not started, chosen at random."""
        rows = self.conn.execute(
            "SELECT s.work_id FROM shelf_entries s JOIN works w ON w.id = s.work_id"
            " WHERE s.completed_at IS NULL AND (? IS NULL OR w.content_type = ?) AND NOT EXISTS ("
            "  SELECT 1 FROM reading_state rs JOIN reading_units u ON u.id = rs.reading_unit_id"
            "  JOIN source_tracks t ON t.id = u.track_id"
            "  WHERE t.work_id = s.work_id AND rs.read_state IN ('partial', 'read'))",
            (content_type, content_type)).fetchall()
        if not rows:
            return None
        return {"work_id": self.rng.choice(rows)["work_id"]}
