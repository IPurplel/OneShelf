"""Work Details (Master §32.8, §4, §22).

One request, one screen: the work, its Source Tracks, the Reading Units of the track the user is
actually looking at, and the library state that belongs to the work. Units come from one track only —
mixing languages or sources silently is exactly what INV-02 forbids.
"""
from __future__ import annotations

import json
import sqlite3

from fastapi import APIRouter, Request, Response

router = APIRouter(prefix="/api")


def services(request: Request):
    return request.app.state.services


def error(status: int, code: str, message: str) -> Response:
    return Response(content=json.dumps({"error": {"code": code, "message": message}}), status_code=status,
                    media_type="application/json", headers={"Cache-Control": "no-store"})


def _tracks(conn: sqlite3.Connection, work_id: str) -> list[dict]:
    rows = conn.execute(
        "SELECT t.id, t.source_id, t.language, t.kind, t.availability,"
        " (SELECT count(*) FROM reading_units u WHERE u.track_id = t.id) AS unit_count"
        " FROM source_tracks t WHERE t.work_id = ? ORDER BY (t.kind = 'local') DESC, t.source_id, t.language",
        (work_id,)).fetchall()
    return [dict(row) for row in rows]


def _units(conn: sqlite3.Connection, track_id: str) -> list[dict]:
    rows = conn.execute(
        "SELECT u.id, u.raw_title, u.display_title, u.unit_type, u.source_number, u.derived_number, u.user_number,"
        " u.volume, u.source_order, u.release_date, u.availability, u.url_hint,"
        " rs.read_state, rs.fraction, rs.updated_at AS read_at"
        " FROM reading_units u LEFT JOIN reading_state rs ON rs.reading_unit_id = u.id"
        " WHERE u.track_id = ? ORDER BY u.source_order", (track_id,)).fetchall()
    # What Follow has recorded as new and not yet seen (§20, §26.12) — the reader's own record, not a guess.
    new_units = {r[0] for r in conn.execute(
        "SELECT reading_unit_id FROM release_events WHERE track_id = ? AND seen = 0"
        " AND reading_unit_id IS NOT NULL", (track_id,))}
    units = []
    for row in rows:
        assets = conn.execute(
            "SELECT format, integrity FROM assets WHERE reading_unit_id = ? ORDER BY format", (row["id"],)).fetchall()
        formats = sorted({a["format"] for a in assets if a["integrity"] == "ok"})
        # What the reader needs to tell "never downloaded" from "downloaded and now unreadable" (§26.21).
        states = {a["integrity"] for a in assets}
        integrity = ("ok" if formats else
                     "missing_local_file" if "missing_local_file" in states else
                     "corrupt" if "corrupt" in states else
                     "unknown" if states else "none")
        units.append({
            "id": row["id"],
            "title": row["display_title"] or row["raw_title"],
            "number": row["user_number"] or row["source_number"] or row["derived_number"],
            "unit_type": row["unit_type"],
            "volume": row["volume"],
            "order": row["source_order"],
            "release_date": row["release_date"],
            "availability": row["availability"],
            "url": row["url_hint"],
            "downloaded": bool(formats),
            "integrity": integrity,
            "is_new": row["id"] in new_units,
            "formats": formats,
            "read_state": row["read_state"] or "unread",
            "fraction": row["fraction"] if row["fraction"] is not None else 0.0,
            "read_at": row["read_at"],
        })
    return units


def _continue_unit(units: list[dict]) -> str | None:
    """Where reading would resume: the furthest partial unit, else the first unread one (§22)."""
    partial = [u for u in units if u["read_state"] == "partial"]
    if partial:
        return max(partial, key=lambda u: (u["read_at"] or "", u["order"]))["id"]
    unread = [u for u in units if u["read_state"] == "unread"]
    return unread[0]["id"] if unread else (units[-1]["id"] if units else None)


@router.get("/works/{work_id}")
async def work_details(request: Request, work_id: str, track_id: str | None = None):
    conn = services(request).conn
    work = conn.execute("SELECT * FROM works WHERE id = ?", (work_id,)).fetchone()
    if work is None:
        return error(404, "WORK_NOT_FOUND", "This work is not in your library.")

    tracks = _tracks(conn, work_id)
    selected = next((t for t in tracks if t["id"] == track_id), None)
    if selected is None:
        follow_row = conn.execute("SELECT track_id FROM follows WHERE work_id = ?", (work_id,)).fetchone()
        preferred = follow_row["track_id"] if follow_row else None
        selected = next((t for t in tracks if t["id"] == preferred), None) or (tracks[0] if tracks else None)

    units = _units(conn, selected["id"]) if selected else []
    shelf = conn.execute("SELECT * FROM shelf_entries WHERE work_id = ?", (work_id,)).fetchone()
    follow = conn.execute("SELECT * FROM follows WHERE work_id = ?", (work_id,)).fetchone()
    aliases = [r[0] for r in conn.execute("SELECT title FROM work_aliases WHERE work_id = ?", (work_id,))]

    return {
        "work": {
            "id": work["id"],
            "title": work["display_title"],
            "original_title": work["original_title"],
            "creator": work["creator"],
            "description": work["description"],
            "content_type": work["content_type"],
            "content_type_source": work["content_type_source"],
            # Covers are presentational and live with source listings, never with identity (INV-28),
            # so a work carries none of its own.
            "aliases": aliases,
        },
        "shelf": {
            "on_shelf": shelf is not None,
            "favorite": bool(shelf["is_favorite"]) if shelf else False,
            "pinned": bool(shelf["is_pinned"]) if shelf else False,
            "completed": bool(shelf["completed_at"]) if shelf else False,
        },
        "follow": {
            "following": follow is not None,
            "preferred_source_id": follow["preferred_source_id"] if follow else None,
            "track_id": follow["track_id"] if follow else None,
            "language": follow["language"] if follow else None,
            "last_successful_at": follow["last_successful_at"] if follow else None,
        },
        "tracks": tracks,
        "selected_track_id": selected["id"] if selected else None,
        "units": units,
        "continue_unit_id": _continue_unit(units),
    }
