"""Tags, collections and work notes API."""
from __future__ import annotations

import sqlite3

from fastapi import APIRouter, Request
from pydantic import BaseModel, Field

from oneshelf.api.sources import error, services
from oneshelf.domain.ids import new_id
from oneshelf.domain.clock import utcnow_iso

router = APIRouter(prefix="/api")


def _missing(conn, **rows: str):
    """A 404 for the first named row that does not exist, instead of a foreign-key failure (500)."""
    tables = {"work": "works", "tag": "tags", "collection": "collections"}
    for kind, row_id in rows.items():
        if conn.execute(f"SELECT 1 FROM {tables[kind]} WHERE id = ?", (row_id,)).fetchone() is None:
            return error(404, f"{kind.upper()}_NOT_FOUND", f"no {kind} {row_id}")
    return None


# ── Tags ─────────────────────────────────────────────────────────────────────

class TagBody(BaseModel):
    name: str = Field(min_length=1, max_length=60)
    color: str | None = None


@router.get("/tags")
async def list_tags(request: Request):
    conn = services(request).conn
    rows = conn.execute("SELECT * FROM tags ORDER BY name COLLATE NOCASE").fetchall()
    tags = []
    for r in rows:
        count = conn.execute("SELECT count(*) FROM work_tags WHERE tag_id = ?", (r["id"],)).fetchone()[0]
        tags.append({"id": r["id"], "name": r["name"], "color": r["color"], "work_count": count})
    return {"tags": tags}


@router.post("/tags")
async def create_tag(request: Request, body: TagBody):
    conn = services(request).conn
    existing = conn.execute("SELECT id FROM tags WHERE name = ? COLLATE NOCASE", (body.name,)).fetchone()
    if existing:
        return error(409, "TAG_EXISTS", f"tag {body.name!r} already exists")
    tag_id = new_id()
    try:
        conn.execute("INSERT INTO tags (id, name, color, created_at) VALUES (?, ?, ?, ?)",
                     (tag_id, body.name, body.color, utcnow_iso()))
    except sqlite3.IntegrityError:          # created by another request in the meantime
        return error(409, "TAG_EXISTS", f"tag {body.name!r} already exists")
    conn.commit()
    return {"id": tag_id, "name": body.name, "color": body.color}


@router.delete("/tags/{tag_id}")
async def delete_tag(request: Request, tag_id: str):
    conn = services(request).conn
    conn.execute("DELETE FROM work_tags WHERE tag_id = ?", (tag_id,))
    conn.execute("DELETE FROM tags WHERE id = ?", (tag_id,))
    conn.commit()
    return {"deleted": tag_id}


@router.post("/works/{work_id}/tags/{tag_id}")
async def tag_work(request: Request, work_id: str, tag_id: str):
    conn = services(request).conn
    if (problem := _missing(conn, work=work_id, tag=tag_id)) is not None:
        return problem
    conn.execute("INSERT OR IGNORE INTO work_tags (work_id, tag_id, created_at) VALUES (?, ?, ?)",
                 (work_id, tag_id, utcnow_iso()))
    conn.commit()
    return {"work_id": work_id, "tag_id": tag_id}


@router.delete("/works/{work_id}/tags/{tag_id}")
async def untag_work(request: Request, work_id: str, tag_id: str):
    conn = services(request).conn
    conn.execute("DELETE FROM work_tags WHERE work_id = ? AND tag_id = ?", (work_id, tag_id))
    conn.commit()
    return {"work_id": work_id, "tag_id": tag_id}


@router.get("/works/{work_id}/tags")
async def work_tags(request: Request, work_id: str):
    conn = services(request).conn
    rows = conn.execute(
        "SELECT t.* FROM tags t JOIN work_tags wt ON wt.tag_id = t.id WHERE wt.work_id = ? ORDER BY t.name COLLATE NOCASE",
        (work_id,)).fetchall()
    return {"tags": [{"id": r["id"], "name": r["name"], "color": r["color"]} for r in rows]}


# ── Collections ──────────────────────────────────────────────────────────────

class CollectionBody(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    is_smart: bool = False
    filter_json: str | None = None


@router.get("/collections")
async def list_collections(request: Request):
    conn = services(request).conn
    rows = conn.execute("SELECT * FROM collections ORDER BY name").fetchall()
    result = []
    for r in rows:
        count = conn.execute("SELECT count(*) FROM collection_works WHERE collection_id = ?", (r["id"],)).fetchone()[0]
        result.append({"id": r["id"], "name": r["name"], "is_smart": bool(r["is_smart"]),
                        "filter_json": r["filter_json"], "work_count": count})
    return {"collections": result}


@router.post("/collections")
async def create_collection(request: Request, body: CollectionBody):
    conn = services(request).conn
    cid = new_id()
    now = utcnow_iso()
    conn.execute("INSERT INTO collections (id, name, is_smart, filter_json, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?)",
                 (cid, body.name, int(body.is_smart), body.filter_json, now, now))
    conn.commit()
    return {"id": cid, "name": body.name, "is_smart": body.is_smart}


@router.delete("/collections/{collection_id}")
async def delete_collection(request: Request, collection_id: str):
    conn = services(request).conn
    conn.execute("DELETE FROM collection_works WHERE collection_id = ?", (collection_id,))
    conn.execute("DELETE FROM collections WHERE id = ?", (collection_id,))
    conn.commit()
    return {"deleted": collection_id}


@router.post("/collections/{collection_id}/works/{work_id}")
async def add_to_collection(request: Request, collection_id: str, work_id: str):
    conn = services(request).conn
    if (problem := _missing(conn, collection=collection_id, work=work_id)) is not None:
        return problem
    conn.execute("INSERT OR IGNORE INTO collection_works (collection_id, work_id, added_at) VALUES (?, ?, ?)",
                 (collection_id, work_id, utcnow_iso()))
    conn.commit()
    return {"collection_id": collection_id, "work_id": work_id}


@router.delete("/collections/{collection_id}/works/{work_id}")
async def remove_from_collection(request: Request, collection_id: str, work_id: str):
    conn = services(request).conn
    conn.execute("DELETE FROM collection_works WHERE collection_id = ? AND work_id = ?", (collection_id, work_id))
    conn.commit()
    return {"collection_id": collection_id, "work_id": work_id}


@router.get("/collections/{collection_id}/works")
async def collection_works(request: Request, collection_id: str):
    conn = services(request).conn
    rows = conn.execute(
        "SELECT w.id, w.display_title FROM works w JOIN collection_works cw ON cw.work_id = w.id"
        " WHERE cw.collection_id = ? ORDER BY cw.added_at DESC", (collection_id,)).fetchall()
    return {"works": [{"work_id": r["id"], "title": r["display_title"]} for r in rows]}


# ── Work Notes & Ratings ─────────────────────────────────────────────────────

class NoteBody(BaseModel):
    rating: int | None = Field(default=None, ge=1, le=10)
    note: str | None = None


@router.get("/works/{work_id}/notes")
async def get_notes(request: Request, work_id: str):
    conn = services(request).conn
    row = conn.execute("SELECT * FROM work_notes WHERE work_id = ?", (work_id,)).fetchone()
    if row is None:
        return {"work_id": work_id, "rating": None, "note": None}
    return {"work_id": work_id, "rating": row["rating"], "note": row["note"]}


@router.put("/works/{work_id}/notes")
async def set_notes(request: Request, work_id: str, body: NoteBody):
    conn = services(request).conn
    if (problem := _missing(conn, work=work_id)) is not None:
        return problem
    now = utcnow_iso()
    conn.execute(
        "INSERT INTO work_notes (work_id, rating, note, created_at, updated_at) VALUES (?, ?, ?, ?, ?)"
        " ON CONFLICT(work_id) DO UPDATE SET rating = excluded.rating, note = excluded.note, updated_at = excluded.updated_at",
        (work_id, body.rating, body.note, now, now))
    conn.commit()
    return {"work_id": work_id, "rating": body.rating, "note": body.note}


@router.delete("/works/{work_id}/notes")
async def delete_notes(request: Request, work_id: str):
    conn = services(request).conn
    conn.execute("DELETE FROM work_notes WHERE work_id = ?", (work_id,))
    conn.commit()
    return {"work_id": work_id}
