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
    return {"work_id": work_id, "deleted_files": services(request).shelf.delete_files(work_id)}


class FollowBody(BaseModel):
    language: str = Field(min_length=1, max_length=35)
    source_id: str = Field(min_length=1, max_length=64)
    track_id: str = Field(min_length=1, max_length=64)


@router.get("/follows")
async def list_follows(request: Request):
    s = services(request)
    rows = s.conn.execute("SELECT work_id FROM follows ORDER BY created_at DESC").fetchall()
    return {"follows": [asdict(s.follows.status(r[0])) for r in rows]}


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
    return {"checked": await services(request).follow_runner.check_all()}


@router.post("/follows/{work_id}")
async def follow(request: Request, work_id: str, body: FollowBody):
    s = services(request)
    record = s.follows.follow(work_id, language=body.language, source_id=body.source_id, track_id=body.track_id)
    return asdict(record)


@router.post("/follows/{work_id}/preferred-source")
async def change_preferred_source(request: Request, work_id: str, body: FollowBody):
    s = services(request)
    try:
        return asdict(s.follows.change_preferred_source(work_id, source_id=body.source_id, track_id=body.track_id))
    except ValueError as exc:
        return error(404, "NOT_FOLLOWED", str(exc))


@router.delete("/follows/{work_id}")
async def unfollow(request: Request, work_id: str):
    try:
        token = services(request).follows.unfollow(work_id)
    except ValueError as exc:
        return error(404, "NOT_FOLLOWED", str(exc))
    return {"work_id": work_id, "undo_token": token}


@router.post("/follows/{work_id}/seen")
async def mark_releases_seen(request: Request, work_id: str):
    """§20, §26.12: acknowledging releases is what makes "new" stop being new."""
    return {"work_id": work_id, "marked": services(request).follows.mark_releases_seen(work_id)}


@router.post("/follows/{work_id}/check")
async def check_follow(request: Request, work_id: str):
    try:
        return await services(request).follow_runner.check_work(work_id)
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
