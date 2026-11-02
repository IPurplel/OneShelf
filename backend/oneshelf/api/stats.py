"""Reading statistics API — aggregate reading progress, library composition, and activity.

The library is the shelf: a work only opened from search is not counted. A chapter never opened is unread,
whether or not it has a reading-state row, and a downloaded file counts only while it is on this device.
"""
from __future__ import annotations

from fastapi import APIRouter, Request

from oneshelf.api.sources import services
from oneshelf.library.copies import PRESENT, copy_state

router = APIRouter(prefix="/api")

SHELF_UNITS = ("SELECT u.id FROM reading_units u JOIN source_tracks t ON t.id = u.track_id"
               " JOIN shelf_entries s ON s.work_id = t.work_id")


@router.get("/stats")
async def reading_stats(request: Request):
    conn = services(request).conn

    shelf_count = conn.execute("SELECT count(*) FROM shelf_entries").fetchone()[0]
    units_count = conn.execute(f"SELECT count(*) FROM ({SHELF_UNITS})").fetchone()[0]

    progress = conn.execute(
        f"SELECT read_state, count(*) AS n FROM reading_state WHERE reading_unit_id IN ({SHELF_UNITS})"
        " GROUP BY read_state").fetchall()
    by_state = {row["read_state"]: row["n"] for row in progress}
    read, partial = by_state.get("read", 0), by_state.get("partial", 0)

    content_types = conn.execute(
        "SELECT content_type, count(*) AS n FROM works"
        " WHERE id IN (SELECT work_id FROM shelf_entries)"
        " GROUP BY content_type ORDER BY n DESC"
    ).fetchall()

    roots: dict = {}
    present = [a for a in conn.execute("SELECT * FROM assets WHERE integrity = 'ok'").fetchall()
               if copy_state(conn, a, roots) == PRESENT]

    recent_activity = conn.execute(
        "SELECT date(rs.updated_at) AS day, count(*) AS units_read"
        " FROM reading_state rs"
        " WHERE rs.read_state IN ('partial', 'read')"
        " AND rs.updated_at >= date('now', '-30 days')"
        " GROUP BY day ORDER BY day"
    ).fetchall()

    favorites_count = conn.execute("SELECT count(*) FROM shelf_entries WHERE is_favorite = 1").fetchone()[0]
    follows_count = conn.execute("SELECT count(*) FROM follows").fetchone()[0]

    return {
        "library": {
            "works": shelf_count,
            "shelf": shelf_count,
            "units": units_count,
            "favorites": favorites_count,
            "follows": follows_count,
        },
        "reading": {
            "unread": max(0, units_count - read - partial),
            "partial": partial,
            "read": read,
            "completion_rate": round(read / max(1, read + partial), 2),
        },
        "downloads": {
            "completed": len(present),
            "total_bytes": sum(a["size_bytes"] for a in present),
            "total_pages": sum(a["page_count"] or 0 for a in present),
        },
        "content_types": [{"type": row["content_type"], "count": row["n"]} for row in content_types],
        "activity": [{"day": row["day"], "count": row["units_read"]} for row in recent_activity],
    }
