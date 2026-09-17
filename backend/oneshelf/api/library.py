"""Downloads and Reader API."""
from __future__ import annotations

from dataclasses import asdict
from typing import Literal

from fastapi import APIRouter, Request
from fastapi.responses import Response
from pydantic import BaseModel, Field

from oneshelf.api.sources import error, services
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


class ProgressBody(BaseModel):
    locator: dict | None = None
    fraction: float | None = Field(default=None, ge=0, le=1)
    revision: int | None = Field(default=None, ge=0)


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


@router.post("/reader/units/{unit_id}/{action}")
async def reading_state_action(request: Request, unit_id: str, action: str):
    reader = services(request).reader
    if action == "mark-read":
        return asdict(reader.mark_read(unit_id))
    if action == "mark-unread":
        return asdict(reader.mark_unread(unit_id))
    return error(404, "UNKNOWN_ACTION", f"unknown reader action {action!r}")
