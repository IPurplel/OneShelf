"""Reading history API — what was read and when."""
from __future__ import annotations

from fastapi import APIRouter, Request

from oneshelf.api.sources import services

router = APIRouter(prefix="/api")


@router.get("/history")
async def get_history(request: Request, limit: int = 200):
    conn = services(request).conn
    rows = conn.execute(
        "SELECT rs.updated_at, rs.read_state, rs.fraction,"
        " u.display_title, u.raw_title, u.source_number,"
        " t.work_id, w.title AS work_title, w.cover_url"
        " FROM reading_state rs"
        " JOIN reading_units u ON u.id = rs.reading_unit_id"
        " JOIN source_tracks t ON t.id = u.track_id"
        " JOIN works w ON w.id = t.work_id"
        " WHERE rs.read_state != 'unread'"
        " ORDER BY rs.updated_at DESC"
        " LIMIT ?",
        (min(limit, 500),),
    ).fetchall()

    entries = []
    for r in rows:
        entries.append({
            "updated_at": r["updated_at"],
            "read_state": r["read_state"],
            "fraction": r["fraction"],
            "unit_title": r["display_title"] or r["raw_title"] or r["source_number"],
            "work_id": r["work_id"],
            "work_title": r["work_title"],
            "cover_url": r["cover_url"],
        })

    return {"entries": entries}
