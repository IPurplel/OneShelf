"""Storage, import, backup, restore and export API."""
from __future__ import annotations

import shutil
from dataclasses import asdict
from pathlib import Path, PurePosixPath
from typing import Literal

from fastapi import APIRouter, Query, Request
from pydantic import BaseModel, Field

from oneshelf.api.sources import error, services
from oneshelf.backup.service import BackupError
from oneshelf.domain.ids import new_id
from oneshelf.export.service import ExportBlocked, ExportContract, ExportError
from oneshelf.importer.service import ChooseWork, CreateLocalWork, ImportRejected, import_file, inspect_import
from oneshelf.importer.suggest import suggest_targets
from oneshelf.restore.service import RestoreBlocked, RestoreError
from oneshelf.storage.migration import MigrationError
from oneshelf.storage.roots import RootError, check_availability, list_roots, register_root, root_space, set_default_root
from oneshelf.storage.scanner import reconcile

router = APIRouter(prefix="/api")
MAX_IMPORT_BYTES = 2 * 1024**3


# -- storage ---------------------------------------------------------------------------------------

@router.get("/storage")
async def storage_overview(request: Request):
    s = services(request)
    roots = []
    for root in list_roots(s.conn):
        availability = check_availability(root)
        entry = {"id": root.id, "name": root.name, "path": root.path, "is_default": root.is_default,
                 "available": availability.available, "reason": availability.reason}
        if availability.available:
            space = root_space(root)
            entry |= {"total": space.total, "free": space.free, "reserve": space.reserve, "state": space.state.value}
        roots.append(entry)
    return {"roots": roots}


class RootBody(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    path: str = Field(min_length=1, max_length=4096)


@router.post("/storage/roots")
async def add_root(request: Request, body: RootBody):
    try:
        root = register_root(services(request).conn, body.name, body.path)
    except RootError as exc:
        return error(422, "ROOT_REJECTED", str(exc))
    return {"id": root.id, "name": root.name, "path": root.path, "is_default": root.is_default}


class PathBody(BaseModel):
    path: str = Field(min_length=1, max_length=4096)


@router.post("/storage/roots/{root_id}/default")
async def make_default(request: Request, root_id: str):
    try:
        set_default_root(services(request).conn, root_id)
    except RootError as exc:
        return error(404, "ROOT_NOT_FOUND", str(exc))
    return await storage_overview(request)


@router.post("/storage/roots/{root_id}/remap")
async def remap(request: Request, root_id: str, body: PathBody):
    try:
        root = services(request).migrations.remap(root_id, body.path)
    except (RootError, MigrationError) as exc:
        return error(422, "REMAP_REFUSED", str(exc))
    return {"id": root.id, "path": root.path}


@router.post("/storage/roots/{root_id}/migrate")
async def migrate_root(request: Request, root_id: str, body: PathBody):
    s = services(request)
    try:
        plan = s.migrations.plan(root_id, body.path)
        report = s.migrations.run(plan)
    except MigrationError as exc:
        return error(422, "MIGRATION_REFUSED", str(exc))
    return {"migration_id": plan.id, "state": report.state, "files": plan.files, "bytes": plan.bytes,
            "copied": report.copied, "verified": report.verified}


@router.post("/storage/migrations/{migration_id}/discard-old-copy")
async def discard_old_copy(request: Request, migration_id: str):
    try:
        return {"migration_id": migration_id, "removed": services(request).migrations.discard_old_copy(migration_id)}
    except MigrationError as exc:
        return error(409, "MIGRATION_NOT_COMPLETE", str(exc))


@router.post("/storage/scan")
async def scan(request: Request, verify_checksums: bool = False):
    report = reconcile(services(request).conn, verify_checksums=verify_checksums)
    return asdict(report)


# -- import ----------------------------------------------------------------------------------------

@router.post("/import/uploads")
async def upload_import(request: Request, filename: str | None = Query(default=None, max_length=300)):
    s = services(request)
    directory = Path(request.app.state.config.data_dir) / "uploads" / "import"
    directory.mkdir(parents=True, exist_ok=True)
    upload_id = new_id()
    path = directory / upload_id
    size = 0
    with open(path, "wb") as handle:
        async for chunk in request.stream():
            size += len(chunk)
            if size > MAX_IMPORT_BYTES:
                handle.close()
                path.unlink(missing_ok=True)
                return error(413, "FILE_TOO_LARGE", "Imported files are limited to 2 GB.")
            handle.write(chunk)
    # the client's filename is a label only: the stored path is always the opaque upload id
    info = inspect_import(path, display_name=PurePosixPath(filename).name if filename else None)
    if not info.valid:
        path.unlink(missing_ok=True)
        return error(422, "UNSUPPORTED_FILE", info.reason or "unsupported file")
    suggestions = suggest_targets(s.conn, info.suggested_title)
    return {"upload_id": upload_id, "format": info.format, "suggested_title": info.suggested_title,
            "language": info.language, "page_count": info.page_count, "warnings": info.warnings,
            "suggestions": [asdict(x) for x in suggestions]}


class ImportBody(BaseModel):
    upload_id: str = Field(min_length=1, max_length=64)
    mode: Literal["copy", "move"] = "copy"
    work_id: str | None = None
    title: str | None = Field(default=None, max_length=500)
    content_type: str = "unknown"
    language: str | None = None
    unit_label: str | None = Field(default=None, max_length=300)
    unit_id: str | None = None
    add_to_shelf: bool = True


@router.post("/import")
async def run_import(request: Request, body: ImportBody):
    s = services(request)
    path = Path(request.app.state.config.data_dir) / "uploads" / "import" / body.upload_id
    if not body.upload_id.isalnum() or not path.is_file():
        return error(404, "UPLOAD_NOT_FOUND", "Upload the file again.")
    decision = ChooseWork(body.work_id) if body.work_id else CreateLocalWork(
        title=body.title or path.name, content_type=body.content_type, language=body.language)
    try:
        outcome = import_file(s.conn, path, decision=decision, mode="copy", language=body.language,
                              unit_id=body.unit_id, unit_label=body.unit_label, add_to_shelf=body.add_to_shelf)
    except ImportRejected as exc:
        return error(422, "IMPORT_REJECTED", str(exc))
    finally:
        if body.mode == "move" or path.exists():
            path.unlink(missing_ok=True)   # the upload copy is temporary either way
    return {"import_id": outcome.import_id, "work_id": outcome.work_id, "track_id": outcome.track_id,
            "reading_unit_id": outcome.unit_id, "asset_id": outcome.asset_id, "path": outcome.relative_path,
            "warnings": outcome.warnings}


# -- backup and restore ----------------------------------------------------------------------------

class BackupBody(BaseModel):
    kind: Literal["library", "full"] = "library"
    works: list[str] | None = None
    location: str | None = None


def _backup_view(record) -> dict:
    """An archive is a file on a disk: say how big it is, and say plainly when it is no longer there."""
    view = asdict(record)
    path = Path(record.path)
    stat = path.stat() if path.is_file() else None
    view["size_bytes"] = stat.st_size if stat else 0
    view["present"] = stat is not None
    return view


@router.get("/diagnostics")
async def diagnostics_summary(request: Request):
    """§43: what the local store holds and the bounds it is kept within. It goes nowhere else."""
    return services(request).diagnostics.summary()


@router.get("/diagnostics/recent")
async def diagnostics_recent(request: Request, limit: int = Query(default=100, ge=1, le=500)):
    return {"entries": services(request).diagnostics.recent(limit=limit)}


@router.delete("/diagnostics")
async def clear_diagnostics(request: Request):
    return {"cleared": services(request).diagnostics.clear()}


@router.get("/backups")
async def list_backups(request: Request):
    s = services(request)
    return {"backups": [_backup_view(b) for b in s.backups.list_backups()], "due": s.backups.due(),
            "location_warning": s.backups.location_warning(s.backups.backup_dir)}


@router.post("/backups")
async def create_backup(request: Request, body: BackupBody):
    try:
        record = services(request).backups.create(body.kind, works=body.works, location=body.location)
    except BackupError as exc:
        return error(422, "BACKUP_FAILED", str(exc))
    return asdict(record)


@router.post("/backups/verify")
async def verify_backup(request: Request, body: PathBody):
    result = services(request).backups.verify(body.path)
    return {"ok": result.ok, "reason": result.reason}


@router.post("/restore/preflight")
async def restore_preflight(request: Request, body: PathBody):
    try:
        preflight = services(request).restore.preflight(body.path)
    except RestoreError as exc:
        return error(422, "BACKUP_UNREADABLE", str(exc))
    return {**asdict(preflight), "plugins": [asdict(p) for p in preflight.plugins]}


class RestoreBody(BaseModel):
    path: str = Field(min_length=1, max_length=4096)
    mode: Literal["merge", "replace"] = "merge"
    approve_new_permissions: bool = False


@router.post("/restore")
async def restore(request: Request, body: RestoreBody):
    try:
        report = services(request).restore.restore(body.path, mode=body.mode,
                                                   approve_new_permissions=body.approve_new_permissions)
    except RestoreBlocked as exc:
        return error(409, "PERMISSION_REVIEW_REQUIRED", str(exc))
    except RestoreError as exc:
        return error(422, "RESTORE_REFUSED", str(exc))
    return asdict(report)


# -- export ----------------------------------------------------------------------------------------

class WorkSelection(BaseModel):
    work_id: str
    language: str
    source_id: str
    unit_ids: list[str] = Field(min_length=1, max_length=5000)


class ExportBody(BaseModel):
    work_id: str | None = None
    language: str | None = None
    source_id: str | None = None
    unit_ids: list[str] | None = None
    works: list[WorkSelection] | None = Field(default=None, max_length=500)   # §34.1 Selected Works
    destination: str
    formats: list[str] | None = None
    output: Literal["folder", "zip"] = "folder"
    conflict: Literal["skip_identical", "replace", "keep_both"] = "skip_identical"
    missing_policy: Literal["export_downloaded_only", "download_missing_then_export", "cancel"] = \
        "export_downloaded_only"
    acknowledge_permanent_download: bool = False


def _contracts(body: ExportBody) -> list[ExportContract]:
    selections = body.works or []
    if not selections:
        if not (body.work_id and body.language and body.source_id and body.unit_ids):
            raise ExportError("select at least one work, language, source and unit")
        selections = [WorkSelection(work_id=body.work_id, language=body.language, source_id=body.source_id,
                                    unit_ids=body.unit_ids)]
    return [ExportContract(work_id=w.work_id, language=w.language, source_id=w.source_id, unit_ids=w.unit_ids,
                           destination=body.destination, formats=body.formats, output=body.output,
                           conflict=body.conflict) for w in selections]


@router.post("/export/preview")
async def export_preview(request: Request, body: ExportBody):
    s = services(request)
    try:
        plan = s.exports.plan_selection(_contracts(body))
    except ExportError as exc:
        return error(422, "EXPORT_REFUSED", str(exc))
    return {"files": len(plan.files), "total_bytes": plan.total_bytes, "missing_units": plan.missing_units,
            "choices": plan.choices, "disclosure": s.exports.disclosure(plan) if plan.missing_units else None}


@router.post("/export")
async def start_export(request: Request, body: ExportBody):
    s = services(request)
    try:
        plan = s.exports.plan_selection(_contracts(body))
        job_id = s.exports.start(plan, missing_policy=body.missing_policy,
                                 acknowledge_permanent_download=body.acknowledge_permanent_download)
        report = await s.exports.run(job_id)
    except ExportBlocked as exc:
        return error(409, "PERMANENT_DOWNLOAD_NOTICE_REQUIRED", str(exc))
    except ExportError as exc:
        return error(422, "EXPORT_REFUSED", str(exc))
    return asdict(report)


@router.get("/export/{job_id}")
async def export_status(request: Request, job_id: str):
    try:
        job = services(request).exports.job(job_id)
    except ExportError as exc:
        return error(404, "EXPORT_NOT_FOUND", str(exc))
    return dict(job)


@router.post("/export/{job_id}/retry-failed")
async def export_retry(request: Request, job_id: str):
    s = services(request)
    requeued = s.exports.retry_failed(job_id)
    report = await s.exports.run(job_id)
    return {"requeued": requeued, **asdict(report)}


@router.delete("/export/history")
async def export_history_cleanup(request: Request):
    """Cleaning export history never deletes exported files (§34.11)."""
    return {"removed": services(request).exports.cleanup_history()}
