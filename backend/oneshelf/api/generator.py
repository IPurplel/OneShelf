"""Adapter Generator endpoints (Master §12).

Each step is its own request, because each step is its own decision: discover, inspect, test, Generate,
prepare a submission bundle, repair. Installing a generated package is the existing install action on
the Sources API — nothing here activates anything.
"""
from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path

import aiohttp
from fastapi import APIRouter, Request, Response
from pydantic import BaseModel, Field

from oneshelf.generator.service import GeneratorError
from oneshelf.plugins.manager import InstallRejected, PluginUnavailable

router = APIRouter(prefix="/api/generator")


def services(request: Request):
    return request.app.state.services


def error(status: int, code: str, message: str) -> Response:
    return Response(content=json.dumps({"error": {"code": code, "message": message}}), status_code=status,
                    media_type="application/json", headers={"Cache-Control": "no-store"})


class DraftBody(BaseModel):
    url: str = Field(min_length=8, max_length=2048)
    name: str = Field(min_length=1, max_length=80)


class MarkupBody(BaseModel):
    version: int = Field(ge=1, le=2)


class InstallBody(BaseModel):
    """Installing is a separate decision with its own permission review (§10, §12.3)."""
    approved_permissions: list[str] = Field(default_factory=list, max_length=200)
    path: str | None = Field(default=None, max_length=4096)


def _generated_path(s, candidate: str) -> Path | None:
    """Only packages this generator produced may be installed through these routes."""
    path = Path(candidate).resolve()
    work_dir = Path(s.generator.work_dir).resolve()
    return path if path.is_file() and path.suffix == ".osp" and work_dir in path.parents else None


@router.post("/drafts")
async def create_draft(request: Request, body: DraftBody):
    s = services(request)
    try:
        draft_id, _draft = await s.generator.start(body.url, name=body.name)
    except GeneratorError as exc:
        return error(422, "DISCOVERY_FAILED", str(exc))
    return {"id": draft_id, **s.generator.preview(draft_id)}


@router.get("/drafts")
async def list_drafts(request: Request):
    return {"drafts": [asdict(d) for d in services(request).generator.list_drafts()]}


@router.get("/drafts/{draft_id}")
async def draft_preview(request: Request, draft_id: str):
    try:
        return services(request).generator.preview(draft_id)
    except GeneratorError as exc:
        return error(404, "DRAFT_NOT_FOUND", str(exc))


@router.post("/drafts/{draft_id}/test")
async def test_draft(request: Request, draft_id: str):
    try:
        return await services(request).generator.run_tests(draft_id)
    except GeneratorError as exc:
        return error(404, "DRAFT_NOT_FOUND", str(exc))


@router.post("/drafts/{draft_id}/generate")
async def generate(request: Request, draft_id: str):
    try:
        return services(request).generator.generate(draft_id)
    except GeneratorError as exc:
        return error(422, "GENERATE_FAILED", str(exc))


@router.post("/drafts/{draft_id}/install")
async def install_draft(request: Request, draft_id: str, body: InstallBody):
    s = services(request)
    try:
        preview = s.generator.preview(draft_id)
    except GeneratorError as exc:
        return error(404, "DRAFT_NOT_FOUND", str(exc))
    if not preview.get("package_path"):
        return error(409, "NOT_GENERATED", "Generate the package before installing it.")
    path = _generated_path(s, preview["package_path"])
    if path is None:
        return error(404, "PACKAGE_MISSING", "the generated package is no longer on disk")
    try:
        outcome = await s.plugins.install_file(path, approved_permissions=body.approved_permissions)
    except InstallRejected as exc:
        return error(422, "INSTALL_REJECTED", str(exc))
    return {"plugin_id": outcome.plugin_id, "version": outcome.version, "state": outcome.state}


@router.post("/repair/{plugin_id}/activate")
async def activate_repair(request: Request, plugin_id: str, body: InstallBody):
    """Atomic activation of a validated repair; a rejected package leaves the installed one active."""
    s = services(request)
    if not body.path:
        return error(422, "PATH_REQUIRED", "pass the path of the validated repair package")
    path = _generated_path(s, body.path)
    if path is None:
        return error(404, "PACKAGE_MISSING", "the repaired package is no longer on disk")
    try:
        outcome = await s.plugins.install_file(path, approved_permissions=body.approved_permissions)
    except InstallRejected as exc:
        return error(422, "ACTIVATION_REJECTED", str(exc))
    return {"plugin_id": outcome.plugin_id, "version": outcome.version, "state": outcome.state}


@router.post("/drafts/{draft_id}/submission")
async def submission(request: Request, draft_id: str):
    try:
        return services(request).generator.submission_bundle(draft_id)
    except GeneratorError as exc:
        return error(422, "SUBMISSION_FAILED", str(exc))


@router.post("/repair/{plugin_id}/diagnose")
async def diagnose(request: Request, plugin_id: str):
    s = services(request)
    try:
        package = s.plugins.load_active(plugin_id)
    except PluginUnavailable as exc:
        return error(404, "PLUGIN_NOT_FOUND", str(exc))
    report = await s.generator.diagnose(package)
    return {"plugin_id": plugin_id, "checked": report.checked, "broken": report.broken,
            "details": report.details, "healthy": report.healthy}


@router.post("/repair/{plugin_id}")
async def repair_plugin(request: Request, plugin_id: str):
    s = services(request)
    try:
        package = s.plugins.load_active(plugin_id)
    except PluginUnavailable as exc:
        return error(404, "PLUGIN_NOT_FOUND", str(exc))
    try:
        outcome = await s.generator.repair(package)
    except GeneratorError as exc:
        return error(422, "REPAIR_REFUSED", str(exc))
    return {"plugin_id": outcome.plugin_id, "version": outcome.version, "path": str(outcome.path),
            "validated": outcome.validated, "installed": False,
            "changes": [asdict(change) for change in outcome.changes], "notes": outcome.notes}


@router.post("/test-source/markup")
async def test_source_markup(request: Request, body: MarkupBody):
    """Development helper: switch the bundled Test Source's markup so repair can be exercised."""
    config = request.app.state.config
    if not (config.dev_test_source and config.dev_test_source_address):
        return error(404, "NOT_AVAILABLE", "the OneShelf Test Source is not enabled on this instance")
    async with aiohttp.ClientSession() as session:
        url = f"http://{config.dev_test_source_address}/__control"
        async with session.post(url, json={"markup_version": body.version}) as response:
            if response.status != 200:
                return error(502, "TEST_SOURCE_UNAVAILABLE", "the Test Source did not accept the change")
    return {"markup_version": body.version}
