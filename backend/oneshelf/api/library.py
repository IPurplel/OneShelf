"""Downloads and Reader API."""
from __future__ import annotations

from dataclasses import asdict
from typing import Literal

from fastapi import APIRouter, Request
from fastapi.responses import Response
from pydantic import BaseModel, Field

from oneshelf.api.sources import error, services
from oneshelf.settings.defaults import DEFAULTS
from oneshelf.plugins.manager import PluginUnavailable
from oneshelf.plugins.runtime import AuthRequired, CapabilityError, RateLimited
from oneshelf.reader.service import StaleProgress

router = APIRouter(prefix="/api")

# Reader content is served sandboxed and never inline in the application origin (Master §27).
CONTENT_HEADERS = {
    "Content-Security-Policy": "sandbox; default-src 'none'; img-src data: blob:; style-src 'unsafe-inline'",
    "X-Content-Type-Options": "nosniff",
    "Cache-Control": "no-store",
    "Cross-Origin-Resource-Policy": "same-origin",
}


class EnqueueBody(BaseModel):
    unit_ids: list[str] = Field(min_length=1, max_length=2000)
    method: Literal["direct", "html_api", "reader_media", "browser"] | None = None
    root_id: str | None = None
    label: str | None = Field(default=None, max_length=120)


@router.post("/downloads")
async def enqueue(request: Request, body: EnqueueBody):
    s = services(request)
    try:
        batch_id = s.downloads.enqueue(body.unit_ids, root_id=body.root_id, one_time_method=body.method,
                                       label=body.label)
    except (ValueError, PluginUnavailable) as exc:
        return error(422, "CANNOT_ENQUEUE", str(exc))
    return s.downloads.batch(batch_id)


@router.get("/downloads")
async def list_batches(request: Request, limit: int = 20):
    s = services(request)
    rows = s.conn.execute("SELECT id FROM download_batches ORDER BY created_at DESC LIMIT ?", (limit,)).fetchall()
    return {"batches": [s.downloads.batch(r[0]) for r in rows]}


@router.get("/downloads/{batch_id}")
async def batch_detail(request: Request, batch_id: str):
    s = services(request)
    jobs = s.conn.execute(
        "SELECT id, reading_unit_id, state, method, attempts, error_category, last_error, queue_position, bytes_done"
        " FROM download_jobs WHERE batch_id = ? ORDER BY queue_position", (batch_id,)).fetchall()
    return {**s.downloads.batch(batch_id), "jobs": [dict(j) for j in jobs]}


@router.post("/downloads/{batch_id}/{action}")
async def batch_action(request: Request, batch_id: str, action: str):
    s = services(request)
    if action == "pause":
        s.downloads.pause(batch_id)
    elif action == "resume":
        s.downloads.resume(batch_id)
    elif action == "retry-failed":
        return {"requeued": s.downloads.retry_all_failed(batch_id), **s.downloads.batch(batch_id)}
    elif action == "cancel":
        return {"canceled": s.downloads.cancel_batch(batch_id), **s.downloads.batch(batch_id)}
    else:
        return error(404, "UNKNOWN_ACTION", f"unknown batch action {action!r}")
    return s.downloads.batch(batch_id)


class ReorderBody(BaseModel):
    job_ids: list[str] = Field(min_length=1, max_length=2000)


@router.post("/downloads/{batch_id}/reorder")
async def reorder(request: Request, batch_id: str, body: ReorderBody):
    s = services(request)
    s.downloads.reorder(batch_id, body.job_ids)
    return await batch_detail(request, batch_id)


class JobActionBody(BaseModel):
    method: Literal["direct", "html_api", "reader_media", "browser"] | None = None
    delete_partial: bool | None = None


@router.post("/downloads/jobs/{job_id}/{action}")
async def job_action(request: Request, job_id: str, action: str, body: JobActionBody | None = None):
    s = services(request)
    body = body or JobActionBody()
    try:
        if action == "retry":
            s.downloads.retry_job(job_id, method=body.method)
        elif action == "cancel":
            s.downloads.cancel_job(job_id, delete_partial=body.delete_partial)
        else:
            return error(404, "UNKNOWN_ACTION", f"unknown job action {action!r}")
    except ValueError as exc:
        return error(404, "JOB_NOT_FOUND", str(exc))
    job = s.downloads.job(job_id)
    return {"job_id": job_id, "state": job["state"], "method": job["method"]}


@router.delete("/downloads/history")
async def clear_history(request: Request, before: str | None = None):
    """Clearing history never deletes downloaded content or reading progress (INV-23)."""
    return {"removed": services(request).downloads.clear_history(before=before)}


@router.get("/reader/units/{unit_id}/pages")
async def reader_pages(request: Request, unit_id: str):
    s = services(request)
    try:
        pages = await s.reader.pages(unit_id)
    except ValueError as exc:
        return error(404, "UNIT_NOT_FOUND", str(exc))
    except AuthRequired:
        return error(409, "SESSION_REQUIRED", "This source needs a connected account.")
    except RateLimited as exc:
        return error(429, "RATE_LIMITED", f"The source is rate limited (retry after {exc.retry_after}s).")
    except CapabilityError as exc:
        return error(502, "SOURCE_FAILED", f"{exc.category}: {exc}")
    return {"reading_unit_id": unit_id, "pages": [asdict(p) for p in pages]}


@router.get("/reader/units/{unit_id}/pages/{index}")
async def reader_page(request: Request, unit_id: str, index: int):
    s = services(request)
    try:
        page = await s.reader.page(unit_id, index)
    except (ValueError, IndexError) as exc:
        return error(404, "PAGE_NOT_FOUND", str(exc))
    except AuthRequired:
        return error(409, "SESSION_REQUIRED", "This source needs a connected account.")
    return Response(page.data, media_type="application/octet-stream",
                    headers={**CONTENT_HEADERS, "X-OneShelf-Origin": page.origin})


MEDIA_TYPES = {"pdf": "application/pdf", "epub": "application/epub+zip", "cbz": "application/vnd.comicbook+zip"}


@router.get("/reader/units/{unit_id}/file")
async def reader_file(request: Request, unit_id: str):
    """The whole local artefact, for the isolated Book Reader (§26.22, §27).

    It is served with a sandbox CSP and nosniff so the document can never reach the application origin,
    its session, or any privileged action.
    """
    s = services(request)
    try:
        artefact = s.reader.local_file(unit_id)
    except FileNotFoundError as exc:
        return error(404, "FILE_NOT_AVAILABLE", str(exc))
    media_type = MEDIA_TYPES.get(artefact.format, "application/octet-stream")
    return Response(artefact.data, media_type=media_type, headers={
        **CONTENT_HEADERS,
        "Content-Security-Policy": "sandbox; default-src 'none'",
        "Content-Disposition": f'inline; filename="{unit_id}.{artefact.format}"',
    })


class ProgressBody(BaseModel):
    locator: dict | None = None
    fraction: float | None = Field(default=None, ge=0, le=1)
    revision: int | None = Field(default=None, ge=0)


class ReaderSettingsBody(BaseModel):
    """Only what §26.17 calls a reader setting; each one is bounded so a value cannot be absurd."""
    auto_mark_read_threshold: float | None = Field(default=None, ge=0.5, le=1.0)
    smart_controls_hide_after_ms: int | None = Field(default=None, ge=500, le=60_000)
    remember_per_work: bool | None = None
    preload_next: int | None = Field(default=None, ge=1, le=50)
    preload_previous: int | None = Field(default=None, ge=0, le=50)


def _reader_settings(settings) -> dict:
    """The §42 registry is the source; a stored override replaces a value, never the shape (D2)."""
    reader = DEFAULTS.reader
    return {
        "auto_mark_read_threshold": settings.get("global", None, "reader.auto_read_threshold",
                                                 reader.auto_mark_read_threshold),
        "smart_controls_hide_after_ms": settings.get(
            "global", None, "reader.smart_controls_hide_after_ms",
            int(reader.smart_controls_hide_after.total_seconds() * 1000)),
        "remember_per_work": settings.get("global", None, "reader.remember_per_work", reader.remember_per_work),
        "preload_next": settings.get("global", None, "reader.preload_next", reader.preload_next),
        "preload_previous": settings.get("global", None, "reader.preload_previous", reader.preload_previous),
    }


@router.get("/reader/settings")
async def reader_settings(request: Request):
    return _reader_settings(services(request).settings)


@router.post("/reader/settings")
async def set_reader_settings(request: Request, body: ReaderSettingsBody):
    settings = services(request).settings
    keys = {"auto_mark_read_threshold": "reader.auto_read_threshold",
            "smart_controls_hide_after_ms": "reader.smart_controls_hide_after_ms",
            "remember_per_work": "reader.remember_per_work",
            "preload_next": "reader.preload_next",
            "preload_previous": "reader.preload_previous"}
    for field, key in keys.items():
        value = getattr(body, field)
        if value is not None:
            settings.set("global", None, key, value)
    return _reader_settings(settings)


@router.get("/reader/units/{unit_id}/progress")
async def read_progress(request: Request, unit_id: str):
    """A tab must be able to read the revision it has to carry, or every later write is stale (§26.23)."""
    try:
        return asdict(services(request).reader.progress(unit_id))
    except ValueError as exc:
        return error(404, "UNIT_NOT_FOUND", str(exc))


@router.post("/reader/units/{unit_id}/progress")
async def set_progress(request: Request, unit_id: str, body: ProgressBody):
    try:
        state = services(request).reader.set_progress(unit_id, locator=body.locator, fraction=body.fraction,
                                                      revision=body.revision)
    except StaleProgress as exc:
        return error(409, "STALE_PROGRESS", str(exc))
    return asdict(state)


class EngagementBody(BaseModel):
    fraction: float = Field(ge=0, le=1)
    interacted: bool = False


@router.post("/reader/units/{unit_id}/engagement")
async def engagement(request: Request, unit_id: str, body: EngagementBody):
    queued = await services(request).reader.record_engagement(unit_id, fraction=body.fraction,
                                                              interacted=body.interacted)
    return {"reading_unit_id": unit_id, "queued": queued}


@router.post("/reader/works/{work_id}/leave")
async def leave_work(request: Request, work_id: str):
    return {"work_id": work_id, "canceled": await services(request).reader.leaving_work(work_id)}


class BookmarkBody(BaseModel):
    locator: dict
    label: str | None = Field(default=None, max_length=200)


class HighlightBody(BaseModel):
    locator: dict
    text: str = Field(min_length=1, max_length=4000)
    colour: Literal["yellow", "green", "blue", "pink"] = "yellow"


@router.get("/reader/units/{unit_id}/marks")
async def marks(request: Request, unit_id: str):
    """Bookmarks and highlights live with the library, so they survive a browser and reach every device."""
    try:
        state = services(request).reader.marks(unit_id)
    except ValueError as exc:
        return error(404, "UNIT_NOT_FOUND", str(exc))
    return {"bookmarks": [asdict(b) for b in state.bookmarks], "highlights": [asdict(h) for h in state.highlights]}


@router.post("/reader/units/{unit_id}/bookmarks")
async def add_bookmark(request: Request, unit_id: str, body: BookmarkBody):
    try:
        return asdict(services(request).reader.add_bookmark(unit_id, locator=body.locator, label=body.label))
    except ValueError as exc:
        return error(404, "UNIT_NOT_FOUND", str(exc))


@router.post("/reader/units/{unit_id}/highlights")
async def add_highlight(request: Request, unit_id: str, body: HighlightBody):
    try:
        return asdict(services(request).reader.add_highlight(unit_id, locator=body.locator, text=body.text,
                                                             colour=body.colour))
    except ValueError as exc:
        return error(404, "UNIT_NOT_FOUND", str(exc))


@router.delete("/reader/bookmarks/{mark_id}")
async def remove_bookmark(request: Request, mark_id: str):
    return {"removed": services(request).reader.remove_mark("bookmark", mark_id)}


@router.delete("/reader/highlights/{mark_id}")
async def remove_highlight(request: Request, mark_id: str):
    return {"removed": services(request).reader.remove_mark("highlight", mark_id)}


@router.post("/reader/units/{unit_id}/{action}")
async def reading_state_action(request: Request, unit_id: str, action: str):
    reader = services(request).reader
    if action == "mark-read":
        return asdict(reader.mark_read(unit_id))
    if action == "mark-unread":
        return asdict(reader.mark_unread(unit_id))
    return error(404, "UNKNOWN_ACTION", f"unknown reader action {action!r}")
