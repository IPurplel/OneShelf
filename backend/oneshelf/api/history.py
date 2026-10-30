"""Reading history API — what was read and when."""
from __future__ import annotations

from fastapi import APIRouter, Query, Request

from oneshelf.api.sources import services
from oneshelf.search.presentation import work_covers

router = APIRouter(prefix="/api")


@router.get("/history")
async def get_history(request: Request, limit: int = Query(default=200, ge=1, le=500)):
    conn = services(request).conn
    rows = conn.execute(
        "SELECT rs.updated_at, rs.read_state, rs.fraction,"
        " u.display_title, u.raw_title, u.source_number,"
        " t.work_id, w.display_title AS work_title"
        " FROM reading_state rs"
        " JOIN reading_units u ON u.id = rs.reading_unit_id"
        " JOIN source_tracks t ON t.id = u.track_id"
        " JOIN works w ON w.id = t.work_id"
        " WHERE rs.read_state != 'unread'"
        " ORDER BY rs.updated_at DESC"
        " LIMIT ?",
        (limit,),
    ).fetchall()
    # Works carry no cover of their own: it is chosen from their listings, once per work.
    covers = work_covers(conn, list(dict.fromkeys(r["work_id"] for r in rows)))
    return {"entries": [{
        "updated_at": r["updated_at"],
        "read_state": r["read_state"],
        "fraction": r["fraction"],
        "unit_title": r["display_title"] or r["raw_title"] or r["source_number"],
        "work_id": r["work_id"],
        "work_title": r["work_title"],
        "cover_url": covers.get(r["work_id"]),
    } for r in rows]}
