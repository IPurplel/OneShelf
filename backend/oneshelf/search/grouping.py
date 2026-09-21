"""Soft Grouping (presentation) and concrete listing binding (Master §6.5–6.6, §6.9; INV-03, INV-27, INV-28).

group_results() never writes: it presents one logical Work per group while keeping every source listing
selectable. persist_listing() is what durable actions (Shelf, Follow, Download) call; it binds a concrete
Source Listing and Source Track and honours the user's Merge/Split/Unlink/Never Match decisions.
"""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field

from oneshelf.db.connection import transaction
from oneshelf.domain.clock import utcnow_iso
from oneshelf.domain.ids import new_id
from oneshelf.search.index import index_work
from oneshelf.search.presentation import cover_path, work_cover
from oneshelf.search.normalize import search_keys

SEQUENTIAL_FAMILY = {"manga", "manhwa", "manhua", "comic"}
BLOCKING_KINDS = ("never_match", "unlink", "split")


@dataclass(frozen=True)
class LiveListing:
    source_id: str
    listing_key: str
    title: str
    url: str | None = None
    content_type: str | None = None
    language: str | None = None
    cover_url: str | None = None
    creator: str | None = None
    original_title: str | None = None


@dataclass(frozen=True)
class Provenance:
    source_id: str
    listing_key: str
    language: str
    title: str
    url: str | None
    cover_url: str | None = None          # the source's own cover URL: presentation only (INV-28)


@dataclass
class ResultWork:
    work_id: str | None
    title: str
    content_type: str | None
    soft: bool
    provenance: list[Provenance] = field(default_factory=list)
    cover_url: str | None = None          # a same-origin /api/covers path chosen for display, never for grouping

    @property
    def availability(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for entry in self.provenance:
            counts[entry.language] = counts.get(entry.language, 0) + 1
        return counts


@dataclass(frozen=True)
class Binding:
    listing_id: str
    work_id: str | None
    track_id: str | None


def compatible(a: str | None, b: str | None) -> bool:
    """Unknown type is not negative evidence (§6.7); sequential art forms are broadly compatible (§6.5)."""
    if a is None or b is None:
        return True
    if a == b:
        return True
    return a in SEQUENTIAL_FAMILY and b in SEQUENTIAL_FAMILY


def _blocked_pairs(conn: sqlite3.Connection) -> set[tuple[str, str]]:
    placeholders = ",".join("?" * len(BLOCKING_KINDS))
    return {(r["listing_id"], r["work_id"]) for r in conn.execute(
        f"SELECT listing_id, work_id FROM work_mappings WHERE kind IN ({placeholders}) AND listing_id IS NOT NULL"
        f" AND work_id IS NOT NULL", BLOCKING_KINDS)}


def _listing_row(conn: sqlite3.Connection, listing: LiveListing) -> sqlite3.Row | None:
    return conn.execute("SELECT * FROM source_listings WHERE source_id = ? AND source_listing_key = ?",
                        (listing.source_id, listing.listing_key)).fetchone()


def _library_match(conn: sqlite3.Connection, listing: LiveListing, blocked: set[tuple[str, str]],
                   listing_id: str | None) -> sqlite3.Row | None:
    keys = search_keys(listing.title)
    for row in conn.execute("SELECT DISTINCT work_id FROM search_index WHERE normalized = ? OR loose = ?",
                            (keys.normalized, keys.loose)):
        work = conn.execute("SELECT * FROM works WHERE id = ?", (row["work_id"],)).fetchone()
        if work is None or not compatible(listing.content_type, work["content_type"]):
            continue
        if listing_id is not None and (listing_id, work["id"]) in blocked:
            continue
        return work
    return None


def group_results(conn: sqlite3.Connection, listings: list[LiveListing]) -> list[ResultWork]:
    blocked = _blocked_pairs(conn)
    groups: dict[tuple, ResultWork] = {}
    for listing in listings:
        row = _listing_row(conn, listing)
        listing_id = row["id"] if row is not None else None
        work_id, soft = None, True
        if row is not None and row["work_id"] and (listing_id, row["work_id"]) not in blocked:
            work_id, soft = row["work_id"], False
        if work_id is None:
            match = _library_match(conn, listing, blocked, listing_id)
            if match is not None:
                work_id = match["id"]
        keys = search_keys(listing.title)
        family = "sequential" if (listing.content_type in SEQUENTIAL_FAMILY) else listing.content_type
        key = ("work", work_id) if work_id else ("title", keys.loose, family)
        group = groups.get(key)
        if group is None:
            title, content_type = listing.title, listing.content_type
            if work_id:
                work = conn.execute("SELECT display_title, content_type FROM works WHERE id = ?", (work_id,)).fetchone()
                if work is not None:
                    title, content_type = work["display_title"], work["content_type"] or listing.content_type
            group = groups[key] = ResultWork(work_id=work_id, title=title, content_type=content_type, soft=soft)
        group.soft = group.soft and soft
        group.provenance.append(Provenance(listing.source_id, listing.listing_key, listing.language or "und",
                                           listing.title, listing.url, listing.cover_url))
        if group.cover_url is None:
            # The first cover a source offers is what the card shows. The grouping key above never sees it.
            group.cover_url = cover_path(listing.source_id, listing.cover_url)
    for group in groups.values():
        if group.cover_url is None and group.work_id:
            group.cover_url = work_cover(conn, group.work_id)
    return list(groups.values())


def persist_listing(conn: sqlite3.Connection, listing: LiveListing, *, work_id: str | None = None,
                    decided_by: str = "evidence") -> Binding:
    """Bind a concrete Source Listing (and its Source Track when a Work is known). Durable actions use this."""
    now = utcnow_iso()
    blocked = _blocked_pairs(conn)
    reindex = False
    with transaction(conn):
        row = _listing_row(conn, listing)
        listing_id = row["id"] if row is not None else new_id()
        current_work = row["work_id"] if row is not None else None
        current_decided_by = row["mapping_decided_by"] if row is not None else None
        target, decision = current_work, current_decided_by
        if work_id is not None and work_id != current_work:
            user_mapping_exists = current_work is not None and current_decided_by == "user"
            if not (user_mapping_exists and decided_by != "user"):  # evidence never overrides a user decision
                target, decision = work_id, decided_by
        if target is not None and (listing_id, target) in blocked:
            target, decision = (current_work, current_decided_by) if (listing_id, current_work) not in blocked else (None, None)
        if row is None:
            conn.execute(
                "INSERT INTO source_listings (id, source_id, source_listing_key, canonical_url, raw_title, work_id,"
                " mapping_decided_by, created_at, last_seen_at, cover_url) VALUES (?,?,?,?,?,?,?,?,?,?)",
                (listing_id, listing.source_id, listing.listing_key, listing.url, listing.title, target, decision, now,
                 now, listing.cover_url))
        else:
            previous_title = row["raw_title"]
            # A result that simply did not carry a cover never erases one that is known.
            conn.execute("UPDATE source_listings SET raw_title = ?, canonical_url = ?, work_id = ?,"
                         " mapping_decided_by = ?, last_seen_at = ?, cover_url = COALESCE(?, cover_url) WHERE id = ?",
                         (listing.title, listing.url, target, decision, now, listing.cover_url, listing_id))
            if previous_title and previous_title != listing.title and target:
                # Preserve title history across source renames (§6.8); display text is never rewritten.
                conn.execute("INSERT OR IGNORE INTO work_aliases (id, work_id, title, kind, created_at)"
                             " VALUES (?, ?, ?, 'source_title', ?)", (new_id(), target, previous_title, now))
                reindex = True
        if target is None:
            return Binding(listing_id, None, None)

        language = listing.language or "und"
        track = conn.execute("SELECT * FROM source_tracks WHERE work_id = ? AND source_id = ? AND language = ?",
                             (target, listing.source_id, language)).fetchone()
        if track is None:
            track_id = new_id()
            conn.execute("INSERT INTO source_tracks (id, work_id, source_id, language, kind, listing_id, availability,"
                         " created_at) VALUES (?,?,?,?,'source',?, 'available', ?)",
                         (track_id, target, listing.source_id, language, listing_id, now))
        else:
            track_id = track["id"]
            conn.execute("UPDATE source_tracks SET listing_id = coalesce(listing_id, ?) WHERE id = ?", (listing_id, track_id))
    if reindex:
        index_work(conn, target)
    return Binding(listing_id, target, track_id)
