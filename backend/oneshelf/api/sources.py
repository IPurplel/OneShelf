"""Sources management API: upload/review/install, lifecycle, sessions, login, passive health."""
from __future__ import annotations

import time
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, Field

from oneshelf.domain.ids import new_id
from oneshelf.plugins.manager import InstallRejected, PluginUnavailable
from oneshelf.plugins.package import PackageError, load_package
from oneshelf.plugins.registry import RegistryError, api_supported
from oneshelf.plugins.runtime import run_packaged_tests
from oneshelf.sessions.login import LoginError
from oneshelf.sources.health import recent_signals

MAX_UPLOAD_BYTES = 20 * 1024 * 1024
UPLOAD_TTL_SECONDS = 3600

router = APIRouter(prefix="/api")


def error(status: int, code: str, message: str) -> JSONResponse:
    return JSONResponse({"error": {"code": code, "message": message}}, status_code=status)


def services(request: Request):
    return request.app.state.services


def _uploads_dir(request: Request) -> Path:
    path = Path(request.app.state.config.data_dir) / "uploads" / "plugins"
    path.mkdir(parents=True, exist_ok=True)
    for old in path.glob("*.osp"):
        if time.time() - old.stat().st_mtime > UPLOAD_TTL_SECONDS:
            old.unlink(missing_ok=True)
    return path


def _exists(s, plugin_id: str) -> bool:
    return s.conn.execute("SELECT 1 FROM plugins WHERE id = ?", (plugin_id,)).fetchone() is not None


def _source_view(s, record) -> dict:
    capabilities, auth_available = [], False
    if record.active_version is not None:
        try:
            package = s.plugins.load_active(record.id) if record.state == "active" else None
        except PluginUnavailable:
            package = None
        if package is not None:
            capabilities, auth_available = list(package.manifest.capabilities), package.manifest.auth is not None
    return {"id": record.id, "name": record.name, "state": record.state, "version": record.active_version,
            "trust_label": record.trust_label, "channel": record.channel, "capabilities": capabilities,
            "auth_available": auth_available, "session_state": s.sessions.state(record.id)}


@router.get("/sources")
async def list_sources(request: Request):
    s = services(request)
    return {"sources": [_source_view(s, r) for r in s.plugins.list()]}


@router.post("/sources/uploads")
async def upload_package(request: Request):
    body = bytearray()
    async for chunk in request.stream():
        body.extend(chunk)
        if len(body) > MAX_UPLOAD_BYTES:
            return error(413, "PACKAGE_TOO_LARGE", "Plugin packages are limited to 20 MB.")
    upload_id = new_id()
    path = _uploads_dir(request) / f"{upload_id}.osp"
    path.write_bytes(body)
    try:
        package = load_package(path)
    except PackageError as exc:
        path.unlink(missing_ok=True)
        return error(422, "INVALID_PACKAGE", str(exc))
    report = await run_packaged_tests(package)
    manifest = package.manifest
    return {
        "upload_id": upload_id, "id": package.id, "name": manifest.name, "version": package.version,
        "description": manifest.description, "publisher": manifest.publisher, "sha256": package.sha256,
        "capabilities": list(manifest.capabilities), "browser_capabilities": list(manifest.browser.capabilities),
        "permissions": sorted(package.permissions), "auth_available": manifest.auth is not None,
        "tests": {"passed": report.passed, "cases": report.cases, "failures": report.failures},
    }


class InstallBody(BaseModel):
    upload_id: str = Field(pattern=r"^[a-z0-9]{12}$|^[A-Za-z0-9_-]{1,64}$")
    approved_permissions: list[str] = Field(default_factory=list, max_length=200)


def _outcome(outcome) -> dict:
    return {"plugin_id": outcome.plugin_id, "version": outcome.version, "state": outcome.state,
            "added_permissions": sorted(outcome.added_permissions), "auth_available": outcome.auth_available,
            "steps": outcome.steps}


@router.post("/sources/install")
async def install_package(request: Request, body: InstallBody):
    s = services(request)
    path = _uploads_dir(request) / f"{body.upload_id}.osp"
    if not body.upload_id.isalnum() or not path.is_file():
        return error(404, "UPLOAD_NOT_FOUND", "Upload the package again to review it.")
    try:
        outcome = await s.plugins.install_file(path, approved_permissions=body.approved_permissions)
    except InstallRejected as exc:
        return error(422, "INSTALL_REJECTED", str(exc))
    finally:
        path.unlink(missing_ok=True)
    return _outcome(outcome)


class ApproveBody(BaseModel):
    version: str = Field(pattern=r"^\d+\.\d+\.\d+$")
    approved_permissions: list[str] = Field(default_factory=list, max_length=200)


@router.post("/sources/{plugin_id}/approve")
async def approve(request: Request, plugin_id: str, body: ApproveBody):
    s = services(request)
    try:
        return _outcome(await s.plugins.approve(plugin_id, body.version, approved_permissions=body.approved_permissions))
    except InstallRejected as exc:
        return error(409, "NO_PENDING_REVIEW", str(exc))


async def _lifecycle(request: Request, plugin_id: str, action: str):
    s = services(request)
    if not _exists(s, plugin_id):
        return error(404, "SOURCE_NOT_FOUND", "This source is not installed.")
    try:
        getattr(s.plugins, action)(plugin_id)
    except PluginUnavailable as exc:
        return error(409, "INVALID_SOURCE_STATE", str(exc))
    return _source_view(s, s.plugins.get(plugin_id))


@router.post("/sources/{plugin_id}/disable")
async def disable(request: Request, plugin_id: str):
    return await _lifecycle(request, plugin_id, "disable")


@router.post("/sources/{plugin_id}/enable")
async def enable(request: Request, plugin_id: str):
    return await _lifecycle(request, plugin_id, "enable")


@router.post("/sources/{plugin_id}/rollback")
async def rollback(request: Request, plugin_id: str):
    return await _lifecycle(request, plugin_id, "rollback")


@router.delete("/sources/{plugin_id}")
async def uninstall(request: Request, plugin_id: str):
    return await _lifecycle(request, plugin_id, "uninstall")


@router.get("/sources/{plugin_id}/session")
async def session_state(request: Request, plugin_id: str):
    return {"source_id": plugin_id, "state": services(request).sessions.state(plugin_id)}


@router.post("/sources/{plugin_id}/session/validate")
async def validate_session(request: Request, plugin_id: str):
    s = services(request)
    stored = s.sessions.stored_state(plugin_id)
    if stored is None:
        return {"source_id": plugin_id, "state": s.sessions.state(plugin_id)}
    s.sessions.mark_checking(plugin_id)
    try:
        valid = await s.source_service.validate_candidate(plugin_id, stored)
    except PluginUnavailable as exc:
        s.sessions.confirm_connected(plugin_id)
        return error(409, "INVALID_SOURCE_STATE", str(exc))
    if valid is False:
        s.sessions.mark_needs_reconnect(plugin_id, "session validation failed")
    else:
        s.sessions.confirm_connected(plugin_id)
    return {"source_id": plugin_id, "state": s.sessions.state(plugin_id)}


@router.delete("/sources/{plugin_id}/session")
async def disconnect(request: Request, plugin_id: str):
    s = services(request)
    s.sessions.disconnect(plugin_id)
    return {"source_id": plugin_id, "state": s.sessions.state(plugin_id)}


@router.get("/sources/{plugin_id}/health")
async def health_signals(request: Request, plugin_id: str):
    signals = recent_signals(services(request).conn, plugin_id)
    return {"source_id": plugin_id, "signals": [
        {"capability": x.capability, "outcome": x.outcome, "category": x.category, "plugin_version": x.plugin_version,
         "at": x.created_at} for x in signals]}


@router.post("/sources/{plugin_id}/login")
async def start_login(request: Request, plugin_id: str):
    s = services(request)
    try:
        login = await s.logins.start(plugin_id)
    except PluginUnavailable as exc:
        return error(404, "SOURCE_NOT_FOUND", str(exc))
    except LoginError as exc:
        return error(409, "LOGIN_UNAVAILABLE", str(exc))
    return {"login_id": login.id, "status": login.status}


@router.get("/logins/{login_id}/frame")
async def login_frame(request: Request, login_id: str):
    try:
        frame = await services(request).logins.get(login_id).frame()
    except (LoginError, TimeoutError) as exc:
        return error(409, "LOGIN_UNAVAILABLE", str(exc))
    return Response(frame, media_type="image/jpeg", headers={"Cache-Control": "no-store"})


class LoginInput(BaseModel):
    type: Literal["click", "type", "key", "scroll"]
    x: float | None = None
    y: float | None = None
    text: str | None = Field(default=None, max_length=512)
    key: str | None = Field(default=None, max_length=32)
    dy: float | None = None


@router.post("/logins/{login_id}/input")
async def login_input(request: Request, login_id: str, body: LoginInput):
    try:
        login = services(request).logins.get(login_id)
        if body.type == "click" and body.x is not None and body.y is not None:
            await login.click(body.x, body.y)
        elif body.type == "type" and body.text is not None:
            await login.type_text(body.text)
        elif body.type == "key" and body.key:
            await login.press(body.key)
        elif body.type == "scroll" and body.dy is not None:
            await login.scroll(body.dy)
        else:
            return error(422, "INVALID_INPUT", "Incomplete input event.")
    except LoginError as exc:
        return error(409, "LOGIN_UNAVAILABLE", str(exc))
    return {"login_id": login_id, "status": login.status}


@router.post("/logins/{login_id}/complete")
async def complete_login(request: Request, login_id: str):
    try:
        login = services(request).logins.get(login_id)
        outcome = await login.complete()
    except LoginError as exc:
        return error(409, "LOGIN_UNAVAILABLE", str(exc))
    return {"login_id": login_id, "outcome": outcome, "status": login.status}


@router.delete("/logins/{login_id}")
async def cancel_login(request: Request, login_id: str):
    try:
        login = services(request).logins.get(login_id)
    except LoginError:
        return {"login_id": login_id, "status": "cancelled"}
    await login.cancel()
    return {"login_id": login_id, "status": login.status}


@router.get("/registry")
async def registry_listing(request: Request, refresh: bool = False):
    """One card per plugin: the Registry's newest version this build can run, set against what is installed.

    The comparison happens here, with the same version logic the manager uses, so the screen never has to
    guess. Reading the Registry changes nothing — it never installs, updates or enables anything.
    """
    s = services(request)
    registry = s.registry
    if registry is None:
        return {"configured": False, "plugins": []}
    if refresh and hasattr(registry, "invalidate"):
        registry.invalidate()
    try:
        entries = await registry.entries()
    except (RegistryError, OSError) as exc:
        return error(502, "REGISTRY_UNAVAILABLE", str(exc))
    except Exception as exc:  # network policy / transport failures
        return error(502, "REGISTRY_UNAVAILABLE", type(exc).__name__)
    by_id: dict[str, list] = {}
    for entry in entries:
        by_id.setdefault(entry.id, []).append(entry)
    plugins = []
    for plugin_id in sorted(by_id):
        versions = sorted(by_id[plugin_id], key=lambda e: _registry_vkey(e.version), reverse=True)
        runnable = [e for e in versions if api_supported(e.api)]
        entry = runnable[0] if runnable else versions[0]
        state, installed = s.plugins.install_state(plugin_id, entry.version)
        if not runnable and state in ("available", "update_available"):
            state = "incompatible"                                      # "Requires newer OneShelf"
        plugins.append({
            "id": entry.id, "name": entry.name, "version": entry.version,
            "trust_label": entry.trust_label, "signed": bool(entry.signature),
            "effective_trust": s.plugins.registry_trust(entry), "api": entry.api,
            "state": state, "installed_version": installed["installed_version"],
            "plugin_state": installed["plugin_state"], "channel": installed["channel"],
            "installed_trust": installed["trust_label"],
        })
    return {"configured": True, "location": registry.location, "plugins": plugins}


class RegistryReviewBody(BaseModel):
    plugin_id: str = Field(pattern=r"^[a-z0-9]+(?:[.-][a-z0-9]+)*$", max_length=64)
    version: str | None = Field(default=None, pattern=r"^\d+\.\d+\.\d+$")


@router.post("/registry/review-package")
async def registry_review(request: Request, body: RegistryReviewBody):
    """Download and check a package exactly as installing it would — and install nothing.

    The response carries the package's sha256; sending it back with the install binds the approval to
    these exact bytes.
    """
    s = services(request)
    if s.registry is None:
        return error(409, "REGISTRY_NOT_CONFIGURED", "No plugin registry is configured.")
    try:
        review = await s.plugins.review_from_registry(s.registry, body.plugin_id, version=body.version)
    except InstallRejected as exc:
        return error(422, "REVIEW_REJECTED", str(exc))
    return {
        "id": review.plugin_id, "name": review.name, "version": review.version, "publisher": review.publisher,
        "description": review.description, "capabilities": list(review.capabilities),
        "permissions": sorted(review.permissions), "added_permissions": sorted(review.added_permissions),
        "tests_passed": review.tests_passed, "test_cases": review.test_cases,
        "test_failures": list(review.test_failures), "effective_trust": review.effective_trust,
        "claimed_trust": review.claimed_trust, "signed": review.signed, "sha256": review.sha256,
        "state": review.state, "installed_version": review.installed_version, "plugin_state": review.plugin_state,
        "channel": review.channel,
    }


class RegistryInstallBody(BaseModel):
    plugin_id: str = Field(pattern=r"^[a-z0-9]+(?:[.-][a-z0-9]+)*$", max_length=64)
    version: str | None = Field(default=None, pattern=r"^\d+\.\d+\.\d+$")
    approved_permissions: list[str] = Field(default_factory=list, max_length=200)
    # From the review: the install is refused if the package is no longer these exact bytes.
    sha256: str | None = Field(default=None, pattern=r"^[0-9a-fA-F]{64}$")


@router.post("/registry/install")
async def registry_install(request: Request, body: RegistryInstallBody):
    s = services(request)
    if s.registry is None:
        return error(409, "REGISTRY_NOT_CONFIGURED", "No plugin registry is configured.")
    try:
        outcome = await s.plugins.install_from_registry(s.registry, body.plugin_id, version=body.version,
                                                        approved_permissions=body.approved_permissions,
                                                        expected_sha256=body.sha256)
    except InstallRejected as exc:
        return error(422, "INSTALL_REJECTED", str(exc))
    return _outcome(outcome)


def _registry_vkey(version: str) -> tuple[int, ...]:
    return tuple(int(part) for part in version.split("."))
