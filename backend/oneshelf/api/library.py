"""Downloads and Reader API."""
from __future__ import annotations

import asyncio
import json
from dataclasses import asdict
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Query, Request
from fastapi.responses import FileResponse, JSONResponse, Response
from pydantic import BaseModel, Field

from oneshelf.diagnostics.redact import redact_text
from oneshelf.library.copies import PRESENT, copy_state, local_copy
from oneshelf.downloads.engine import KEEPABLE_FORMATS, NoStorageLocation
from oneshelf.net.governor import Priority
from oneshelf.api.sources import error, services
from oneshelf.settings.defaults import DEFAULTS
from oneshelf.plugins.manager import PluginUnavailable
from oneshelf.plugins.runtime import AuthRequired, CapabilityError, RateLimited
from oneshelf.reader.alternatives import alternatives
from oneshelf.reader.service import DownloadRequired, MarkOperationConflict, SourceUnavailable, StaleProgress

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
    # §26.21: a unit whose local copy is broken is downloaded again rather than left unreadable.
    repair: bool = False
    # §22, §41.3: the file formats wanted, for a source offering several (I-103). Omitted: the preferred one.
    formats: list[Literal["epub", "pdf", "cbz"]] | None = Field(default=None, min_length=1, max_length=3)


@router.post("/downloads")
async def enqueue(request: Request, body: EnqueueBody):
    s = services(request)
    try:
        batch_id = s.downloads.enqueue(body.unit_ids, root_id=body.root_id, one_time_method=body.method,
                                       label=body.label, repair=body.repair, formats=body.formats)
    except NoStorageLocation as exc:
        return error(409, "NO_STORAGE_LOCATION", str(exc))
    except (ValueError, PluginUnavailable) as exc:
        return error(422, "CANNOT_ENQUEUE", str(exc))
    return s.downloads.batch(batch_id)



@router.get("/reading-units/{unit_id}/formats")
async def unit_formats(request: Request, unit_id: str):
    """The files a source offers for one unit, which of them OneShelf can keep, and which are here (I-103)."""
    s = services(request)
    unit = s.conn.execute(
        "SELECT u.source_unit_key, u.url_hint, t.source_id, t.language FROM reading_units u"
        " JOIN source_tracks t ON t.id = u.track_id WHERE u.id = ?", (unit_id,)).fetchone()
    if unit is None:
        return error(404, "UNIT_NOT_FOUND", "This reading unit is not in your library.")
    here = {r[0] for r in s.conn.execute(
        "SELECT format FROM assets WHERE reading_unit_id = ? AND integrity = 'ok'", (unit_id,))}
    offered: list[dict] = []
    if unit["source_id"] != "local":
        try:
            package = s.plugins.load_active(unit["source_id"])
            if "downloads" in package.recipes:
                result = await s.source_service.run(
                    unit["source_id"], "downloads",
                    {"unit_key": unit["source_unit_key"], "url": unit["url_hint"], "language": unit["language"]},
                    priority=Priority.INTERACTIVE)
                seen = set()
                for entry in result.entries:
                    key = (str(entry.format).lower(), entry.variant)
                    if key in seen:
                        continue
                    seen.add(key)
                    offered.append({"format": key[0], "variant": entry.variant, "size_bytes": entry.size_bytes,
                                    "supported": key[0] in KEEPABLE_FORMATS, "downloaded": key[0] in here})
        except PluginUnavailable as exc:
            return error(409, "SOURCE_UNAVAILABLE", str(exc))
        except AuthRequired:
            return error(409, "SESSION_REQUIRED", "This source needs a connected account.")
        except RateLimited as exc:
            return error(429, "RATE_LIMITED", f"The source is rate limited (retry after {exc.retry_after}s).")
        except CapabilityError as exc:
            return error(502, "SOURCE_FAILED", f"{exc.category}: {exc}")
    for fmt in sorted(here - {o["format"] for o in offered}):   # local copies the source no longer lists
        offered.append({"format": fmt, "variant": None, "size_bytes": None, "supported": True, "downloaded": True})
    return {"unit_id": unit_id, "formats": offered}

class AutoDownloadBody(BaseModel):
    enabled: bool | None = None
    mode: Literal["current", "read_ahead", "current_plus_read_ahead"] | None = None
    read_ahead: int | None = Field(default=None, ge=1, le=20)
    threshold: float | None = Field(default=None, ge=0.01, le=1.0)


class ExtractionBody(BaseModel):
    method: Literal["direct", "html_api", "reader_media", "browser"] | None = None
    mode: Literal["preferred_ask", "strict", "automatic"] | None = None
    fallback_order: list[Literal["direct", "html_api", "reader_media", "browser"]] | None = None


class DownloadSettingsBody(BaseModel):
    auto_download: AutoDownloadBody | None = None
    keep_partial_on_cancel: bool | None = None
    extraction: ExtractionBody | None = None


def _download_settings(settings) -> dict:
    """Exactly the knobs the engine reads (§19, §16.6, §14); the §42 registry supplies every default."""
    auto = DEFAULTS.auto_download
    mode = settings.get("global", None, "reader.auto_download.mode", "current")
    return {
        "auto_download": {
            "enabled": settings.get("global", None, "reader.auto_download.enabled", auto.enabled),
            "mode": "read_ahead" if mode == "current_plus_read_ahead" else mode,
            "read_ahead": settings.get("global", None, "reader.auto_download.read_ahead", auto.read_ahead_units),
            "threshold": settings.get("global", None, "reader.auto_download.threshold", auto.engagement_threshold),
        },
        "keep_partial_on_cancel": settings.get("global", None, "downloads.keep_partial_on_cancel", False),
        "extraction": {
            "method": settings.get("global", None, "extraction.method"),
            "mode": settings.get("global", None, "extraction.mode") or DEFAULTS.downloads.fallback_mode,
            "fallback_order": settings.get("global", None, "extraction.fallback_order") or [],
        },
    }


@router.get("/downloads/settings")
async def download_settings(request: Request):
    return _download_settings(services(request).settings)


@router.post("/downloads/settings")
async def set_download_settings(request: Request, body: DownloadSettingsBody):
    settings = services(request).settings
    if body.auto_download is not None:
        for field, key in (("enabled", "reader.auto_download.enabled"), ("mode", "reader.auto_download.mode"),
                           ("read_ahead", "reader.auto_download.read_ahead"),
                           ("threshold", "reader.auto_download.threshold")):
            value = getattr(body.auto_download, field)
            if value is not None:
                settings.set("global", None, key, value)
    if body.keep_partial_on_cancel is not None:
        settings.set("global", None, "downloads.keep_partial_on_cancel", body.keep_partial_on_cancel)
    if body.extraction is not None:
        for field, key in (("method", "extraction.method"), ("mode", "extraction.mode"),
                           ("fallback_order", "extraction.fallback_order")):
            value = getattr(body.extraction, field)
            if value is not None:
                settings.set("global", None, key, value)
    return _download_settings(settings)


@router.get("/downloads")
async def list_batches(request: Request, limit: int = Query(default=20, ge=1, le=200)):
    s = services(request)
    rows = s.conn.execute("SELECT id FROM download_batches ORDER BY created_at DESC LIMIT ?", (limit,)).fetchall()
    return {"batches": [s.downloads.batch(r[0]) for r in rows]}


def _job_available(conn, job, roots: dict) -> bool:
    """Whether a finished job's unit opens from this device now: the copy the Reader opens is there (UI-003).

    The job's own file decides the format. A job whose file was deleted, or that finished before jobs were
    linked to their files, says what the unit has now: the Reader opens the unit, not the job.
    """
    if job["state"] != "COMPLETED":
        return False
    own = conn.execute("SELECT format FROM assets WHERE id = ?", (job["asset_id"],)).fetchone() \
        if job["asset_id"] else None
    copy = local_copy(conn, job["reading_unit_id"], own["format"] if own else None)
    return copy is not None and copy_state(conn, copy, roots) == PRESENT


def _bytes_total(conn, job) -> int | None:
    """How many bytes the job transfers in all, when that is known (UI-003).

    A finished job transferred what `bytes_done` counts. Jobs finished before it was counted fall back to the
    stored file's size. A whole file in progress uses the size the source announced; image pages have none.
    """
    if job["state"] == "COMPLETED":
        if job["bytes_done"]:
            return job["bytes_done"]
        row = conn.execute("SELECT size_bytes FROM assets WHERE id = ?", (job["asset_id"],)).fetchone() \
            if job["asset_id"] else None
        return row[0] if row else None
    expected = json.loads(job["manifest_json"] or "{}").get("file", {}).get("expected")
    return expected if isinstance(expected, int) and expected >= 0 else None


@router.get("/downloads/{batch_id}")
async def batch_detail(request: Request, batch_id: str, offset: int = Query(default=0, ge=0),
                       limit: int = Query(default=500, ge=1, le=1000)):
    """One batch, its jobs named by Work and unit, and whether each finished unit can be opened (UI-003)."""
    s = services(request)
    batch = s.conn.execute("SELECT selection_json FROM download_batches WHERE id = ?", (batch_id,)).fetchone()
    if batch is None:
        return error(404, "BATCH_NOT_FOUND", "There is no such download batch.")
    total = s.conn.execute("SELECT count(*) FROM download_jobs WHERE batch_id = ?", (batch_id,)).fetchone()[0]
    rows = s.conn.execute(
        "SELECT j.id, j.reading_unit_id, j.state, j.method, j.attempts, j.error_category, j.last_error,"
        " j.queue_position, j.bytes_done, j.asset_id, j.manifest_json, t.work_id, w.display_title AS work_title,"
        " u.track_id, coalesce(u.display_title, u.raw_title) AS unit_title"
        " FROM download_jobs j LEFT JOIN reading_units u ON u.id = j.reading_unit_id"
        " LEFT JOIN source_tracks t ON t.id = u.track_id LEFT JOIN works w ON w.id = t.work_id"
        " WHERE j.batch_id = ? ORDER BY j.queue_position, j.id LIMIT ? OFFSET ?",
        (batch_id, limit, offset)).fetchall()
    roots: dict = {}
    jobs = []
    for row in rows:
        job = {key: row[key] for key in ("id", "reading_unit_id", "state", "method", "attempts", "error_category",
                                         "queue_position", "bytes_done", "work_id", "work_title", "track_id",
                                         "unit_title")}
        # Errors can quote a URL; whatever it carried (a signed token, a session id) is redacted (§43).
        job["last_error"] = redact_text(row["last_error"]) if row["last_error"] else None
        job["available"] = _job_available(s.conn, row, roots)
        job["bytes_total"] = _bytes_total(s.conn, row)
        jobs.append(job)
    selection = json.loads(batch["selection_json"] or "{}")
    details = selection.get("skipped_details") or [{"reading_unit_id": u, "reason": None}
                                                   for u in selection.get("skipped", [])]
    skipped_units = []
    for detail in details[offset:offset + limit]:
        title = s.conn.execute("SELECT coalesce(display_title, raw_title) FROM reading_units WHERE id = ?",
                               (detail["reading_unit_id"],)).fetchone()
        skipped_units.append({"reading_unit_id": detail["reading_unit_id"], "unit_title": title[0] if title else None,
                              "reason": detail.get("reason")})
    return {**s.downloads.batch(batch_id), "jobs": jobs, "jobs_total": total, "offset": offset, "limit": limit,
            "skipped_units": skipped_units, "skipped_total": len(details)}


class ReorderBody(BaseModel):
    job_ids: list[str] = Field(min_length=1, max_length=2000)


@router.post("/downloads/{batch_id}/reorder")
async def reorder(request: Request, batch_id: str, body: ReorderBody):
    s = services(request)
    s.downloads.reorder(batch_id, body.job_ids)
    return await batch_detail(request, batch_id, offset=0, limit=500)


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


DOWNLOAD_REQUIRED = "This book has to be downloaded before it can be read."


@router.get("/reader/units/{unit_id}/pages")
async def reader_pages(request: Request, unit_id: str):
    s = services(request)
    try:
        pages = await s.reader.pages(unit_id)
    except DownloadRequired:
        return error(409, "DOWNLOAD_REQUIRED", DOWNLOAD_REQUIRED)
    except SourceUnavailable as exc:
        return error(409, "SOURCE_UNAVAILABLE", str(exc))
    except FileNotFoundError as exc:
        return error(404, "PAGES_NOT_AVAILABLE", str(exc))
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
async def reader_page(request: Request, unit_id: str, index: int, prefetch: bool = False):
    s = services(request)
    try:
        if prefetch:
            page_task = asyncio.create_task(s.reader.page(unit_id, index, prefetch=True))
            try:
                while not page_task.done():
                    if await request.is_disconnected():
                        return Response(status_code=204, headers=CONTENT_HEADERS)
                    await asyncio.wait({page_task}, timeout=0.05)
                page = await page_task
            finally:
                if not page_task.done():
                    page_task.cancel()
                    try:
                        await page_task
                    except asyncio.CancelledError:
                        pass
        else:
            page = await s.reader.page(unit_id, index, prefetch=False)
    except DownloadRequired:
        return error(409, "DOWNLOAD_REQUIRED", DOWNLOAD_REQUIRED)
    except SourceUnavailable as exc:
        return error(409, "SOURCE_UNAVAILABLE", str(exc))
    except FileNotFoundError as exc:
        return error(404, "PAGES_NOT_AVAILABLE", str(exc))
    except (ValueError, IndexError) as exc:
        return error(404, "PAGE_NOT_FOUND", str(exc))
    except AuthRequired:
        return error(409, "SESSION_REQUIRED", "This source needs a connected account.")
    except RateLimited as exc:
        return error(429, "RATE_LIMITED", f"The source is rate limited (retry after {exc.retry_after}s).")
    except CapabilityError as exc:
        return error(502, "SOURCE_FAILED", f"{exc.category}: {exc}")
    return Response(page.data, media_type="application/octet-stream",
                    headers={**CONTENT_HEADERS, "X-OneShelf-Origin": page.origin})


MEDIA_TYPES = {"pdf": "application/pdf", "epub": "application/epub+zip", "cbz": "application/vnd.comicbook+zip",
               "text": "application/vnd.oneshelf.text+zip"}
EXTENSIONS = {"text": "ostext"}


@router.get("/reader/units/{unit_id}/context")
async def reader_context(request: Request, unit_id: str):
    try:
        return services(request).reader.context(unit_id)
    except ValueError as exc:
        return error(404, "UNIT_NOT_FOUND", str(exc))


@router.get("/reader/units/{unit_id}/file")
async def reader_file(request: Request, unit_id: str, format: Literal["epub", "pdf", "cbz", "text"] | None = None):
    """The whole local artefact, for the isolated Book Reader (§26.22, §27).

    It is served with a sandbox CSP and nosniff so the document can never reach the application origin,
    its session, or any privileged action.
    """
    s = services(request)
    try:
        artefact = s.reader.local_file(unit_id, format=format)
    except FileNotFoundError as exc:
        return error(404, "FILE_NOT_AVAILABLE", str(exc))
    except ValueError as exc:
        return error(404, "UNIT_NOT_FOUND", str(exc))
    media_type = MEDIA_TYPES.get(artefact.format, "application/octet-stream")
    # Streamed from disk with Range support, so pdf.js can fetch what it shows (§56, I-101).
    return FileResponse(artefact.path, media_type=media_type, content_disposition_type="inline",
                        filename=f"{unit_id}.{EXTENSIONS.get(artefact.format, artefact.format)}",
                        headers={**CONTENT_HEADERS, "Content-Security-Policy": "sandbox; default-src 'none'"})


@router.get("/reader/units/{unit_id}/text")
async def reader_text(request: Request, unit_id: str):
    """A text unit's sanitised sections for the isolated Book Reader (§26.22, §27).

    The markup was reduced to an allowlist on the server; the reader still renders it only inside its
    empty-sandbox frame with its own CSP, never in the application document.
    """
    s = services(request)
    try:
        unit, origin = await s.reader.text(unit_id)
    except SourceUnavailable as exc:
        return error(409, "SOURCE_UNAVAILABLE", str(exc))
    except FileNotFoundError as exc:
        return error(404, "TEXT_NOT_AVAILABLE", str(exc))
    except ValueError as exc:
        return error(404, "UNIT_NOT_FOUND", str(exc))
    except AuthRequired:
        return error(409, "SESSION_REQUIRED", "This source needs a connected account.")
    except RateLimited as exc:
        return error(429, "RATE_LIMITED", f"The source is rate limited (retry after {exc.retry_after}s).")
    except CapabilityError as exc:
        return error(502, "SOURCE_FAILED", f"{exc.category}: {exc}")
    body = {"reading_unit_id": unit_id, "origin": origin, "title": unit.title, "language": unit.language,
            "direction": unit.direction,
            "sections": [{"title": x.title, "html": x.html, "characters": x.characters} for x in unit.sections]}
    return JSONResponse(body, headers={**CONTENT_HEADERS, "Content-Security-Policy": "sandbox; default-src 'none'"})


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


@router.get("/reader/units/{unit_id}/alternatives")
async def unit_alternatives(request: Request, unit_id: str):
    """§26.16: which same-language sources could serve this unit, and which of them can say so honestly."""
    try:
        return alternatives(services(request).conn, unit_id)
    except ValueError as exc:
        return error(404, "UNIT_NOT_FOUND", str(exc))


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
    except ValueError as exc:
        return error(404, "UNIT_NOT_FOUND", str(exc))
    return asdict(state)


class EngagementBody(BaseModel):
    fraction: float = Field(ge=0, le=1)
    interacted: bool = False


@router.post("/reader/units/{unit_id}/engagement")
async def engagement(request: Request, unit_id: str, body: EngagementBody):
    try:
        queued = await services(request).reader.record_engagement(unit_id, fraction=body.fraction,
                                                                  interacted=body.interacted)
    except ValueError as exc:
        return error(404, "UNIT_NOT_FOUND", str(exc))
    return {"reading_unit_id": unit_id, "queued": queued}


@router.post("/reader/works/{work_id}/leave")
async def leave_work(request: Request, work_id: str):
    return {"work_id": work_id, "canceled": await services(request).reader.leaving_work(work_id)}


class BookmarkBody(BaseModel):
    locator: dict
    label: str | None = Field(default=None, max_length=200)
    operation_id: UUID | None = None


class HighlightBody(BaseModel):
    locator: dict
    text: str = Field(min_length=1, max_length=4000)
    colour: Literal["yellow", "green", "blue", "pink"] = "yellow"
    operation_id: UUID | None = None


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
        return asdict(services(request).reader.add_bookmark(unit_id, locator=body.locator, label=body.label,
                                                            operation_id=str(body.operation_id) if body.operation_id else None))
    except MarkOperationConflict as exc:
        return error(409, "MARK_OPERATION_CONFLICT", str(exc))
    except ValueError as exc:
        return error(404, "UNIT_NOT_FOUND", str(exc))


@router.post("/reader/units/{unit_id}/highlights")
async def add_highlight(request: Request, unit_id: str, body: HighlightBody):
    try:
        return asdict(services(request).reader.add_highlight(unit_id, locator=body.locator, text=body.text,
                                                             colour=body.colour,
                                                             operation_id=str(body.operation_id) if body.operation_id else None))
    except MarkOperationConflict as exc:
        return error(409, "MARK_OPERATION_CONFLICT", str(exc))
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
    try:
        if action == "mark-read":
            return asdict(reader.mark_read(unit_id))
        if action == "mark-unread":
            return asdict(reader.mark_unread(unit_id))
    except ValueError as exc:
        return error(404, "UNIT_NOT_FOUND", str(exc))
    return error(404, "UNKNOWN_ACTION", f"unknown reader action {action!r}")
