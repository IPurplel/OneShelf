"""First Run (Master §29).

Short on purpose: welcome, storage, access mode, remote setup only if the user picked Remote, optional
sources, finish. Nothing in the application is gated on completing it — Home works from the first request
— so the flow can be left and resumed.
"""
from __future__ import annotations

import json
from typing import Literal

from fastapi import APIRouter, Request, Response
from pydantic import BaseModel, Field

from oneshelf.auth.policy import PolicyError
from oneshelf.auth.service import RemoteAuthError
from oneshelf.db.connection import transaction
from oneshelf.domain.clock import utcnow_iso
from oneshelf.storage.roots import RootError, list_roots, register_root, set_default_root

router = APIRouter(prefix="/api/first-run")

STEPS = [
    {"id": "welcome", "optional": False},
    {"id": "storage", "optional": False},
    {"id": "access_mode", "optional": False},
    {"id": "remote", "optional": True},      # only when Access Mode is Remote
    {"id": "sources", "optional": True},
    {"id": "finish", "optional": False},
]


def services(request: Request):
    return request.app.state.services


def error(status: int, code: str, message: str) -> Response:
    return Response(content=json.dumps({"error": {"code": code, "message": message}}), status_code=status,
                    media_type="application/json", headers={"Cache-Control": "no-store"})


class StorageBody(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    path: str = Field(min_length=1, max_length=4096)


class AccessModeBody(BaseModel):
    mode: Literal["local", "lan", "remote"]
    trusted_networks: list[str] | None = Field(default=None, max_length=50)
    trusted_proxies: list[str] | None = Field(default=None, max_length=50)
    canonical_hostname: str | None = Field(default=None, max_length=253)


def _row(conn):
    row = conn.execute("SELECT * FROM first_run WHERE id = 1").fetchone()
    if row is None:
        with transaction(conn):
            conn.execute("INSERT INTO first_run (id, state, started_at) VALUES (1, 'pending', ?)", (utcnow_iso(),))
        row = conn.execute("SELECT * FROM first_run WHERE id = 1").fetchone()
    return row


def _update(conn, **fields) -> None:
    _row(conn)
    assignments = ", ".join(f"{key} = ?" for key in fields)
    with transaction(conn):
        conn.execute(f"UPDATE first_run SET {assignments} WHERE id = 1", tuple(fields.values()))


def _state(request: Request) -> dict:
    s = services(request)
    row = _row(s.conn)
    roots = list_roots(s.conn)
    remote_state = s.remote_auth.state()
    return {
        "state": row["state"],
        "access_mode": row["access_mode"],
        "steps": STEPS,
        "storage": [{"id": r.id, "name": r.name, "path": r.path, "default": r.is_default} for r in roots],
        "remote": {"canonical_hostname": remote_state["canonical_hostname"],
                   "passkey_registered": bool(remote_state["passkeys"])},
        "network": s.access_policy.describe(),
        "sources_installed": s.conn.execute("SELECT count(*) FROM plugins").fetchone()[0],
        "completed_at": row["completed_at"],
    }


@router.get("")
async def first_run_state(request: Request):
    return _state(request)


@router.post("/storage")
async def choose_storage(request: Request, body: StorageBody):
    s = services(request)
    try:
        created = register_root(s.conn, body.name, body.path)
        if len(list_roots(s.conn)) == 1:
            set_default_root(s.conn, created.id)
    except RootError as exc:
        return error(422, "STORAGE_REJECTED", str(exc))
    root = next(r for r in list_roots(s.conn) if r.id == created.id)
    return {"id": root.id, "name": root.name, "path": root.path, "default": root.is_default}


@router.post("/access-mode")
async def choose_access_mode(request: Request, body: AccessModeBody):
    s = services(request)
    try:
        if body.mode == "local":
            s.access_policy.set_trusted_networks([])        # loopback only
        elif body.trusted_networks is not None:
            s.access_policy.set_trusted_networks(body.trusted_networks)
        if body.trusted_proxies is not None:
            s.access_policy.set_trusted_proxies(body.trusted_proxies)
        if body.mode == "remote" and body.canonical_hostname:
            s.remote_auth.set_canonical_hostname(body.canonical_hostname)
    except PolicyError as exc:
        return error(422, "INVALID_NETWORK", str(exc))
    except RemoteAuthError as exc:
        return error(422, "INVALID_HOSTNAME", str(exc))
    _update(s.conn, access_mode=body.mode)
    return _state(request)


@router.post("/finish")
async def finish(request: Request):
    s = services(request)
    row = _row(s.conn)
    if row["access_mode"] == "remote":
        remote = s.remote_auth.state()
        if not remote["canonical_hostname"] or not remote["passkeys"]:
            return error(409, "REMOTE_SETUP_INCOMPLETE",
                         "Remote access needs the canonical hostname and one passkey before you finish.")
    _update(s.conn, state="completed", completed_at=utcnow_iso())
    return _state(request)
