"""My Shelf, Follow, notifications and health API."""
from __future__ import annotations

from dataclasses import asdict

from fastapi import APIRouter, Request
from pydantic import BaseModel, Field

from oneshelf.api.sources import error, services
from oneshelf.downloads.contract import Settings

router = APIRouter(prefix="/api")


def _entry(entry) -> dict:
    return asdict(entry)


@router.get("/shelf")
async def shelf_view(request: Request, view: str = "all", q: str | None = None):
    shelf = services(request).shelf
    try:
        entries = shelf.search(q) if q else shelf.view(view)
    except ValueError as exc:
        return error(422, "UNKNOWN_VIEW", str(exc))
    return {"view": "search" if q else view, "entries": [_entry(e) for e in entries]}


class ShelfBody(BaseModel):
    favorite: bool | None = None
    pinned: bool | None = None
    completed: bool | None = None


class BatchBody(BaseModel):
    work_ids: list[str] = Field(min_length=1, max_length=200)
    action: str = Field(pattern=r"^(favorite|unfavorite|complete|uncomplete|remove|delete_files)$")


# Registered before `/shelf/{work_id}`: that route would otherwise take "batch" for a work id.
@router.post("/shelf/batch")
async def shelf_batch(request: Request, body: BatchBody):
    shelf = services(request).shelf
    count = deleted = freed = 0
    for wid in body.work_ids:
        if shelf.get(wid) is None:         # not on the shelf: nothing to change for that one
            continue
        try:
            if body.action == "delete_files":
                # Files only: the Work stays on the shelf, followed and with its progress (§23, INV-10).
                files, size = shelf.delete_work_files(wid)
                if not files:
                    continue
                deleted, freed = deleted + files, freed + size
            elif body.action == "favorite":
                shelf.set_favorite(wid, True)
            elif body.action == "unfavorite":
                shelf.set_favorite(wid, False)
            elif body.action == "complete":
                shelf.set_completed(wid, True)
            elif body.action == "uncomplete":
                shelf.set_completed(wid, False)
            elif body.action == "remove":
                shelf.remove(wid, delete_files=False)
        except ValueError:
            continue
        count += 1
    if body.action == "delete_files":
        return {"action": body.action, "affected": count, "deleted_files": deleted, "freed_bytes": freed}
    return {"action": body.action, "affected": count}


@router.post("/shelf/{work_id}")
async def shelf_add(request: Request, work_id: str, body: ShelfBody | None = None):
    shelf = services(request).shelf
    try:
        entry = shelf.add(work_id)
    except ValueError as exc:
        return error(404, "WORK_NOT_FOUND", str(exc))
    body = body or ShelfBody()
    if body.favorite is not None:
        entry = shelf.set_favorite(work_id, body.favorite)
    if body.pinned is not None:
        entry = shelf.set_pinned(work_id, body.pinned)
    if body.completed is not None:
        entry = shelf.set_completed(work_id, body.completed)
    return _entry(entry)


@router.get("/shelf/{work_id}/removal-summary")
async def removal_summary(request: Request, work_id: str):
    return services(request).shelf.removal_summary(work_id)


@router.delete("/shelf/{work_id}")
async def shelf_remove(request: Request, work_id: str, delete_files: bool = False):
    """Removing from the Shelf never unfollows and only deletes files when asked (§23)."""
    return services(request).shelf.remove(work_id, delete_files=delete_files)


@router.delete("/works/{work_id}/files")
async def delete_files(request: Request, work_id: str):
    files, freed = services(request).shelf.delete_work_files(work_id)
    return {"work_id": work_id, "deleted_files": files, "freed_bytes": freed}


@router.delete("/units/{unit_id}/files")
async def delete_unit_files(request: Request, unit_id: str):
    """One chapter's or book's files. The unit, its progress and its Work stay (§23)."""
    outcome = services(request).shelf.delete_unit_files(unit_id)
    if outcome is None:
        return error(404, "UNIT_NOT_FOUND", "No reading unit by that id.")
    return {"unit_id": unit_id, "deleted_files": outcome[0], "freed_bytes": outcome[1]}


class FollowBody(BaseModel):
    language: str = Field(min_length=1, max_length=35)
    source_id: str = Field(min_length=1, max_length=64)
    track_id: str = Field(min_length=1, max_length=64)


@router.get("/follows")
async def list_follows(request: Request):
    s = services(request)
    rows = s.conn.execute(
        "SELECT f.work_id, f.language, w.display_title AS work_title"
        " FROM follows f JOIN works w ON w.id = f.work_id"
        " ORDER BY f.created_at DESC, f.language").fetchall()
    names = {plugin.id: plugin.name for plugin in s.plugins.list()}
    follows = []
    for r in rows:
        status = asdict(s.follows.status(r["work_id"], language=r["language"]))
        follows.append({**status, "work_title": r["work_title"],
                        "source_name": names.get(status["source_id"], status["source_id"])})
    return {"follows": follows}


class UndoBody(BaseModel):
    undo_token: str = Field(min_length=1, max_length=64)


@router.post("/follows/undo")
async def undo_unfollow(request: Request, body: UndoBody):
    try:
        return asdict(services(request).follows.undo_unfollow(body.undo_token))
    except ValueError as exc:
        return error(409, "UNDO_EXPIRED", str(exc))


@router.post("/follows/check-all")
async def check_all_follows(request: Request):
    return {"checked": await services(request).follow_runner.check_all(manual=True)}


@router.post("/follows/{work_id}")
async def follow(request: Request, work_id: str, body: FollowBody):
    s = services(request)
    try:
        record = s.follows.follow(work_id, language=body.language, source_id=body.source_id, track_id=body.track_id)
    except ValueError as exc:
        return error(422, "INVALID_FOLLOW", str(exc))
    return asdict(record)


@router.post("/follows/{work_id}/preferred-source")
async def change_preferred_source(request: Request, work_id: str, body: FollowBody):
    s = services(request)
    try:
        return asdict(s.follows.change_preferred_source(work_id, language=body.language,
                                                          source_id=body.source_id, track_id=body.track_id))
    except ValueError as exc:
        return error(404, "NOT_FOLLOWED", str(exc))


@router.delete("/follows/{work_id}")
async def unfollow(request: Request, work_id: str, language: str | None = None):
    try:
        token = services(request).follows.unfollow(work_id, language=language)
    except ValueError as exc:
        return error(404, "NOT_FOLLOWED", str(exc))
    return {"work_id": work_id, "undo_token": token}


@router.post("/follows/{work_id}/seen")
async def mark_releases_seen(request: Request, work_id: str, language: str | None = None):
    """§20, §26.12: acknowledging releases is what makes "new" stop being new."""
    return {"work_id": work_id, "marked": services(request).follows.mark_releases_seen(work_id, language=language)}


@router.post("/follows/{work_id}/check")
async def check_follow(request: Request, work_id: str, language: str | None = None):
    try:
        return await services(request).follow_runner.check_work(work_id, language=language)
    except ValueError as exc:
        return error(404, "NOT_FOLLOWED", str(exc))


class NotificationSettingsBody(BaseModel):
    source_recovered: bool


@router.get("/notifications/settings")
async def notification_settings(request: Request):
    """Declared before `/notifications/{action}`, which would otherwise swallow it (I-15)."""
    settings = Settings(services(request).conn)
    return {"source_recovered": settings.get("global", None, "notifications.source_recovered", False)}


@router.post("/notifications/settings")
async def set_notification_settings(request: Request, body: NotificationSettingsBody):
    settings = Settings(services(request).conn)
    settings.set("global", None, "notifications.source_recovered", body.source_recovered)
    return {"source_recovered": body.source_recovered}


@router.get("/notifications")
async def list_notifications(request: Request, attention: bool = False):
    service = services(request).notifications
    items = service.needs_attention() if attention else service.active()
    return {"notifications": [asdict(n) for n in items], "needs_attention": len(service.needs_attention())}


@router.post("/notifications/{action}")
async def notification_action(request: Request, action: str):
    service = services(request).notifications
    if action == "mark-all-seen":
        return {"updated": service.mark_all_seen()}
    if action == "clear-seen":
        return {"removed": service.clear_seen()}
    if action == "cleanup":
        return {"removed": service.cleanup()}
    return error(404, "UNKNOWN_ACTION", f"unknown notification action {action!r}")


@router.get("/sources/{source_id}/health/state")
async def health_state(request: Request, source_id: str):
    service = services(request).health
    capabilities = service.evaluate(source_id)
    return {"source_id": source_id, "overall": service.overall(source_id),
            "capabilities": {name: asdict(value) for name, value in capabilities.items()}}
