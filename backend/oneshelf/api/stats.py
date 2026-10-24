"""Reading statistics API — aggregate reading progress, library composition, and activity."""
from __future__ import annotations

from fastapi import APIRouter, Request

from oneshelf.api.sources import services

router = APIRouter(prefix="/api")


@router.get("/stats")
async def reading_stats(request: Request):
    conn = services(request).conn

    shelf_count = conn.execute("SELECT count(*) FROM shelf_entries").fetchone()[0]
    works_count = conn.execute("SELECT count(*) FROM works").fetchone()[0]
    units_count = conn.execute("SELECT count(*) FROM reading_units").fetchone()[0]

    progress = conn.execute(
        "SELECT read_state, count(*) AS n FROM reading_state GROUP BY read_state"
    ).fetchall()
    by_state = {row["read_state"]: row["n"] for row in progress}

    content_types = conn.execute(
        "SELECT content_type, count(*) AS n FROM works"
        " WHERE id IN (SELECT work_id FROM shelf_entries)"
        " GROUP BY content_type ORDER BY n DESC"
    ).fetchall()

    downloads_completed = conn.execute(
        "SELECT count(*) FROM download_jobs WHERE state = 'COMPLETED'"
    ).fetchone()[0]
    downloads_total_bytes = conn.execute(
        "SELECT coalesce(sum(a.size_bytes), 0) FROM assets a WHERE a.integrity = 'ok'"
    ).fetchone()[0]
    total_pages = conn.execute(
        "SELECT coalesce(sum(a.page_count), 0) FROM assets a WHERE a.integrity = 'ok' AND a.page_count IS NOT NULL"
    ).fetchone()[0]

    recent_activity = conn.execute(
        "SELECT date(rs.updated_at) AS day, count(*) AS units_read"
        " FROM reading_state rs"
        " WHERE rs.read_state IN ('partial', 'read')"
        " AND rs.updated_at >= date('now', '-30 days')"
        " GROUP BY day ORDER BY day"
    ).fetchall()

    completion_rate = conn.execute(
        "SELECT count(CASE WHEN rs.read_state = 'read' THEN 1 END) AS completed,"
        " count(*) AS started"
        " FROM reading_state rs WHERE rs.read_state != 'unread'"
    ).fetchone()

    favorites_count = conn.execute(
        "SELECT count(*) FROM shelf_entries WHERE is_favorite = 1"
    ).fetchone()[0]

    follows_count = conn.execute("SELECT count(*) FROM follows").fetchone()[0]

    return {
        "library": {
            "works": works_count,
            "shelf": shelf_count,
            "units": units_count,
            "favorites": favorites_count,
            "follows": follows_count,
        },
        "reading": {
            "unread": by_state.get("unread", 0),
            "partial": by_state.get("partial", 0),
            "read": by_state.get("read", 0),
            "completion_rate": round(completion_rate["completed"] / max(1, completion_rate["started"]), 2),
        },
        "downloads": {
            "completed": downloads_completed,
            "total_bytes": downloads_total_bytes,
            "total_pages": total_pages,
        },
        "content_types": [{"type": row["content_type"], "count": row["n"]} for row in content_types],
        "activity": [{"day": row["day"], "count": row["units_read"]} for row in recent_activity],
    }
