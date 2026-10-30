"""Work Details (Master §32.8, §4, §22).

One request, one screen: the work, its Source Tracks, the Reading Units of the track the user is
actually looking at, and the library state that belongs to the work. Units come from one track only —
mixing languages or sources silently is exactly what INV-02 forbids.
"""
from __future__ import annotations

import json
import sqlite3

from fastapi import APIRouter, Request, Response
from pydantic import BaseModel, ConfigDict

from oneshelf.library import overrides
from oneshelf.search.presentation import work_cover

router = APIRouter(prefix="/api")


def services(request: Request):
    return request.app.state.services


def error(status: int, code: str, message: str) -> Response:
    return Response(content=json.dumps({"error": {"code": code, "message": message}}), status_code=status,
                    media_type="application/json", headers={"Cache-Control": "no-store"})


def _tracks(conn: sqlite3.Connection, work_id: str) -> list[dict]:
    rows = conn.execute(
        "SELECT t.id, t.source_id, t.language, t.kind, t.availability, t.listing_id,"
        " coalesce(l.raw_title, t.listing_title) AS listing_title,"
        " coalesce(l.source_listing_key, t.listing_key) AS listing_key, l.canonical_url AS listing_url,"
        " (SELECT count(*) FROM reading_units u WHERE u.track_id = t.id) AS unit_count"
        " FROM source_tracks t LEFT JOIN source_listings l ON l.id = t.listing_id"
        " WHERE t.work_id = ? ORDER BY (t.kind = 'local') DESC, t.source_id, t.language, t.id",
        (work_id,)).fetchall()
    return [dict(row) for row in rows]


def _units(conn: sqlite3.Connection, track_id: str) -> list[dict]:
    rows = conn.execute(
        "SELECT u.id, u.raw_title, u.display_title, u.unit_type, u.source_number, u.derived_number, u.user_number,"
        " u.volume, u.source_order, u.release_date, u.availability, u.url_hint,"
        " rs.read_state, rs.fraction, rs.updated_at AS read_at"
        " FROM reading_units u LEFT JOIN reading_state rs ON rs.reading_unit_id = u.id"
        " WHERE u.track_id = ? ORDER BY u.source_order", (track_id,)).fetchall()
    new_units = {r[0] for r in conn.execute(
        "SELECT reading_unit_id FROM release_events WHERE track_id = ? AND seen = 0"
        " AND reading_unit_id IS NOT NULL", (track_id,))}
    unit_ids = [row["id"] for row in rows]
    asset_map: dict[str, list[dict]] = {uid: [] for uid in unit_ids}
    if unit_ids:
        placeholders = ",".join("?" * len(unit_ids))
        for a in conn.execute(
                f"SELECT reading_unit_id, format, integrity FROM assets"
                f" WHERE reading_unit_id IN ({placeholders})", unit_ids).fetchall():
            asset_map[a["reading_unit_id"]].append(a)
    units = []
    for row in rows:
        assets = asset_map.get(row["id"], [])
        formats = sorted({a["format"] for a in assets if a["integrity"] == "ok"})
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


def _describe_sources(s, tracks: list[dict]) -> None:
    """Each track's source by name, and whether it can deliver content at all (read online or download).

    A source that only lists and describes a book (Noor Book) is still worth showing, but the interface
    must not offer reading or downloading from it."""
    known: dict[str, tuple[str | None, bool]] = {}
    for track in tracks:
        source_id = track["source_id"]
        if track["kind"] == "local" or source_id == "local":
            track["source_name"], track["delivers"] = None, True
            continue
        if source_id not in known:
            try:
                name = s.plugins.get(source_id).name
            except Exception:
                name = None
            sources = s.source_service
            # A disabled or removed source keeps its own "unavailable" explanations; this is about capability.
            delivers = (not sources.available(source_id) or sources.reads_online(source_id)
                        or sources.downloads(source_id))
            known[source_id] = (name, delivers)
        track["source_name"], track["delivers"] = known[source_id]


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
    _describe_sources(services(request), tracks)
    selected = next((t for t in tracks if t["id"] == track_id), None)
    if selected is None:
        follow_row = conn.execute("SELECT track_id FROM follows WHERE work_id = ?", (work_id,)).fetchone()
        preferred = follow_row["track_id"] if follow_row else None
        selected = next((t for t in tracks if t["id"] == preferred), None) or (tracks[0] if tracks else None)

    units = _units(conn, selected["id"]) if selected else []
    shelf = conn.execute("SELECT * FROM shelf_entries WHERE work_id = ?", (work_id,)).fetchone()
    follow = conn.execute("SELECT * FROM follows WHERE work_id = ? AND language = ?",
                          (work_id, selected["language"])).fetchone() if selected else None
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
        # Presentation only (INV-28): the selected track's listing cover, as a same-origin path.
        "cover_url": work_cover(conn, work_id, selected["id"] if selected else None),
        "units": units,
        "continue_unit_id": _continue_unit(units),
    }


class WorkPatch(BaseModel):
    """Only the fields sent are changed; `null` clears the user's correction (I-102)."""
    model_config = ConfigDict(extra="forbid")
    content_type: str | None = None
    title: str | None = None


class UnitPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    number: str | None = None
    title: str | None = None
    unit_type: str | None = None


def _given(body: BaseModel, name: str):
    return getattr(body, name) if name in body.model_fields_set else overrides.UNSET


@router.patch("/works/{work_id}")
async def correct_work(request: Request, work_id: str, body: WorkPatch):
    """Master §9.2: the user's classification and title win over source and plugin values."""
    try:
        overrides.set_work(services(request).conn, work_id, content_type=_given(body, "content_type"),
                           display_title=_given(body, "title"))
    except overrides.NotFound as exc:
        return error(404, "WORK_NOT_FOUND", str(exc))
    except overrides.OverrideError as exc:
        return error(422, "INVALID_CORRECTION", str(exc))
    return await work_details(request, work_id)


@router.patch("/reading-units/{unit_id}")
async def correct_unit(request: Request, unit_id: str, body: UnitPatch):
    """Master §4.4: a user correction overrides source and derived numbering, title and type."""
    conn = services(request).conn
    try:
        overrides.set_unit(conn, unit_id, number=_given(body, "number"), display_title=_given(body, "title"),
                           unit_type=_given(body, "unit_type"))
    except overrides.NotFound as exc:
        return error(404, "UNIT_NOT_FOUND", str(exc))
    except overrides.OverrideError as exc:
        return error(422, "INVALID_CORRECTION", str(exc))
    work_id = conn.execute("SELECT t.work_id FROM reading_units u JOIN source_tracks t ON t.id = u.track_id"
                           " WHERE u.id = ?", (unit_id,)).fetchone()[0]
    return await work_details(request, work_id)


@router.get("/maintenance/reclassification")
async def reclassification_preview(request: Request):
    """Dry run: what the classification repair would change (I-92, I-94). Nothing is written."""
    from oneshelf.library import reclassify
    s = services(request)
    return reclassify.preview(s.conn, s.plugins).as_dict()


@router.post("/maintenance/reclassification")
async def reclassification_apply(request: Request):
    """Apply the repair the preview showed, after a consistent snapshot of the library database."""
    from pathlib import Path

    from oneshelf.library import reclassify
    s = services(request)
    snapshots = Path(request.app.state.config.data_dir) / "snapshots"
    return reclassify.apply(s.conn, s.plugins, snapshot_dir=snapshots).as_dict()
