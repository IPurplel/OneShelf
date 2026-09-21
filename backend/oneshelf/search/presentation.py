"""Presentation covers (INV-28): chosen for display, never used for identity, grouping or matching.

A cover belongs to a concrete Source Listing. The browser never receives the source's own URL: every cover
it sees is a same-origin `/api/covers` path, which Core serves through that source's network policy.
"""
from __future__ import annotations

import sqlite3
from urllib.parse import parse_qs, urlencode, urlsplit

COVER_ROUTE = "/api/covers"


def cover_path(source_id: str | None, url: str | None) -> str | None:
    """The same-origin path for a source's cover, or None when there is nothing safe to show."""
    if not source_id or not url or urlsplit(url).scheme not in ("http", "https"):
        return None
    return f"{COVER_ROUTE}?{urlencode({'source': source_id, 'url': url})}"


def raw_cover_url(path: str | None, source_id: str) -> str | None:
    """Read back a cover path this API issued, for the same source only. Anything else is ignored."""
    if not path:
        return None
    parts = urlsplit(path)
    if parts.scheme or parts.netloc or parts.path != COVER_ROUTE:
        return None
    query = parse_qs(parts.query)
    if query.get("source") != [source_id] or len(query.get("url", [])) != 1:
        return None
    url = query["url"][0]
    return url if urlsplit(url).scheme in ("http", "https") and len(url) <= 2048 else None


def work_cover(conn: sqlite3.Connection, work_id: str, track_id: str | None = None) -> str | None:
    """A Work's presentation cover: the selected track's listing, then the followed track's, then the first
    of its listings in a fixed order. Which one is shown is a display choice; it decides nothing else."""
    rows = conn.execute(
        "SELECT t.id AS track_id, l.source_id, l.cover_url FROM source_tracks t"
        " JOIN source_listings l ON l.id = t.listing_id"
        " WHERE t.work_id = ? AND l.cover_url IS NOT NULL ORDER BY t.source_id, t.language, t.id",
        (work_id,)).fetchall()
    if not rows:
        row = conn.execute("SELECT source_id, cover_url FROM source_listings WHERE work_id = ? AND cover_url IS NOT NULL"
                           " ORDER BY source_id, source_listing_key LIMIT 1", (work_id,)).fetchone()
        return cover_path(row["source_id"], row["cover_url"]) if row else None
    followed = conn.execute("SELECT track_id FROM follows WHERE work_id = ?", (work_id,)).fetchone()
    for wanted in (track_id, followed["track_id"] if followed else None):
        chosen = next((r for r in rows if wanted and r["track_id"] == wanted), None)
        if chosen is not None:
            return cover_path(chosen["source_id"], chosen["cover_url"])
    # The selected source has no cover: another of the Work's covers stands in, so a Work that has one never
    # looks empty. It is still only presentation.
    return cover_path(rows[0]["source_id"], rows[0]["cover_url"])
