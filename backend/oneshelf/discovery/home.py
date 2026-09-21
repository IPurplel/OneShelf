"""Home discovery semantics (Master §31, §32.3–32.4).

Trending and Latest Releases exist only when sources actually provide them; nothing is invented.
Recently Added means recently added to My Shelf. Hero is contextual but never performs a network request:
Continue Reading, then a pinned Work, then cached discovery data.
"""
from __future__ import annotations

import sqlite3
from dataclasses import asdict, dataclass, field

from oneshelf.net.governor import Priority
from oneshelf.search.cache import DiscoveryCache
from oneshelf.search.grouping import LiveListing, ResultWork, group_results
from oneshelf.search.presentation import cover_path, work_cover

SECTION_LIMIT = 12
FEED_KINDS = ("trending", "latest")


@dataclass(frozen=True)
class LibraryItem:
    work_id: str
    title: str
    cover_url: str | None = None
    fraction: float | None = None
    content_type: str | None = None


@dataclass
class HomeSections:
    continue_reading: list[LibraryItem] = field(default_factory=list)
    trending: list[ResultWork] = field(default_factory=list)
    latest: list[ResultWork] = field(default_factory=list)
    recently_added: list[LibraryItem] = field(default_factory=list)


@dataclass(frozen=True)
class HeroChoice:
    reason: str  # continue_reading | pinned | cached_discovery
    title: str
    work_id: str | None = None
    cover_url: str | None = None
    description: str | None = None
    content_type: str | None = None


class HomeService:
    def __init__(self, conn: sqlite3.Connection, sources, cache: DiscoveryCache) -> None:
        self.conn = conn
        self.sources = sources
        self.cache = cache

    # -- library sections --------------------------------------------------------------------------

    def continue_reading(self) -> list[LibraryItem]:
        rows = self.conn.execute(
            "SELECT w.id AS work_id, w.display_title, w.content_type, max(rs.updated_at) AS at, rs.fraction"
            " FROM reading_state rs JOIN reading_units u ON u.id = rs.reading_unit_id"
            " JOIN source_tracks t ON t.id = u.track_id JOIN works w ON w.id = t.work_id"
            " WHERE rs.read_state = 'partial' GROUP BY w.id ORDER BY at DESC LIMIT ?",
            (SECTION_LIMIT,)).fetchall()
        return [LibraryItem(r["work_id"], r["display_title"], work_cover(self.conn, r["work_id"]),
                            fraction=r["fraction"], content_type=r["content_type"]) for r in rows]

    def recently_added(self) -> list[LibraryItem]:
        rows = self.conn.execute(
            "SELECT w.id AS work_id, w.display_title, w.content_type FROM shelf_entries s"
            " JOIN works w ON w.id = s.work_id ORDER BY s.added_at DESC LIMIT ?", (SECTION_LIMIT,)).fetchall()
        return [LibraryItem(r["work_id"], r["display_title"], work_cover(self.conn, r["work_id"]),
                            content_type=r["content_type"]) for r in rows]

    # -- source feeds ------------------------------------------------------------------------------

    def _cached_feed(self, kind: str) -> list[LiveListing]:
        listings: list[LiveListing] = []
        for source_id, version in self.sources.sources_with_capability(kind):
            payload = self.cache.get(source_id, version, kind, kind)
            if payload:
                listings.extend(LiveListing(**item) for item in payload["listings"])
        return listings

    async def _feed(self, kind: str) -> list[ResultWork]:
        listings: list[LiveListing] = []
        for source_id, version in self.sources.sources_with_capability(kind):
            cached = self.cache.get(source_id, version, kind, kind)
            if cached is not None:
                listings.extend(LiveListing(**item) for item in cached["listings"])
                continue
            try:
                result = await self.sources.run(source_id, kind, {}, priority=Priority.INTERACTIVE)
            except Exception:  # a failing feed hides its section, never fabricates data
                continue
            entries = [LiveListing(source_id=source_id, listing_key=e.listing_key, title=e.title, url=e.url,
                                   content_type=e.content_type, language=e.language, cover_url=e.cover_url,
                                   creator=e.creator, original_title=e.original_title) for e in result.entries]
            self.cache.put(source_id, version, kind, kind, {"listings": [asdict(e) for e in entries]})
            listings.extend(entries)
        return group_results(self.conn, listings)[:SECTION_LIMIT] if listings else []

    async def sections(self) -> HomeSections:
        return HomeSections(continue_reading=self.continue_reading(), trending=await self._feed("trending"),
                            latest=await self._feed("latest"), recently_added=self.recently_added())

    def _about(self, work_id: str | None) -> dict:
        if work_id is None:
            return {"description": None, "content_type": None}
        row = self.conn.execute("SELECT description, content_type FROM works WHERE id = ?", (work_id,)).fetchone()
        return {"description": row["description"] if row else None,
                "content_type": row["content_type"] if row else None}

    async def hero(self) -> HeroChoice | None:
        reading = self.continue_reading()
        if reading:
            about = self._about(reading[0].work_id)
            return HeroChoice("continue_reading", reading[0].title, reading[0].work_id, reading[0].cover_url,
                              about["description"], about["content_type"])
        pinned = self.conn.execute(
            "SELECT w.id, w.display_title, w.description, w.content_type FROM shelf_entries s"
            " JOIN works w ON w.id = s.work_id WHERE s.is_pinned = 1 ORDER BY s.added_at DESC LIMIT 1").fetchone()
        if pinned is not None:
            return HeroChoice("pinned", pinned["display_title"], pinned["id"], work_cover(self.conn, pinned["id"]),
                              pinned["description"], pinned["content_type"])
        for kind in FEED_KINDS:
            listings = self._cached_feed(kind)
            if listings:
                groups = group_results(self.conn, listings)
                if groups:
                    return HeroChoice("cached_discovery", groups[0].title, groups[0].work_id,
                                      groups[0].cover_url or cover_path(listings[0].source_id, listings[0].cover_url))
        return None
