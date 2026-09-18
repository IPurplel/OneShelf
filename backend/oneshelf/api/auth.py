"""Remote access endpoints (Master §28).

Every route here is reachable from a trusted LAN device. A remote client reaches them only with a valid
session cookie, except the two sign-in routes, which the access boundary lets through so a signed-out
remote browser can present its passkey.
"""
from __future__ import annotations

import json
from typing import Literal

from fastapi import APIRouter, Request, Response
from pydantic import BaseModel, Field

from oneshelf.api.access import AccessClass
from oneshelf.auth.passkeys import PasskeyError
from oneshelf.auth.policy import PolicyError
from oneshelf.auth.service import RemoteAuthError
from oneshelf.auth.sessions import COOKIE_NAME, LIFETIMES, SessionError, cookie_attributes

router = APIRouter(prefix="/api/auth")

# Routes a signed-out remote browser must be able to reach to present a passkey (§28.3).
PUBLIC_REMOTE_PATHS = ("/api/auth/sign-in/options", "/api/auth/sign-in")


def services(request: Request):
    return request.app.state.services


def access(request: Request) -> AccessClass:
    return request.scope["state"]["access"]


def error(status: int, code: str, message: str) -> Response:
    return Response(content=json.dumps({"error": {"code": code, "message": message}}), status_code=status,
                    media_type="application/json", headers={"Cache-Control": "no-store"})


def _is_https(request: Request) -> bool:
    forwarded = request.headers.get("x-forwarded-proto", "").split(",")[0].strip().lower()
    return request.url.scheme == "https" or forwarded == "https"


def _token(request: Request) -> str | None:
    return request.cookies.get(COOKIE_NAME)


class HostnameBody(BaseModel):
    hostname: str = Field(min_length=1, max_length=253)


class RegisterOptionsBody(BaseModel):
    label: str = Field(default="Passkey", max_length=100)
    recovery_code: str | None = Field(default=None, max_length=100)


class RegisterBody(BaseModel):
    ceremony_id: str = Field(min_length=1, max_length=64)
    label: str = Field(default="Passkey", max_length=100)
    response: dict


class SignInBody(BaseModel):
    ceremony_id: str = Field(min_length=1, max_length=64)
    response: dict
    label: str = Field(default="Remote device", max_length=100)
    lifetime: Literal["7d", "30d", "90d", "1y", "manual"] = "30d"


class NetworksBody(BaseModel):
    trusted_networks: list[str] | None = Field(default=None, max_length=50)
    trusted_proxies: list[str] | None = Field(default=None, max_length=50)


# -- state and configuration -----------------------------------------------------------------------

@router.get("/state")
async def state(request: Request):
    s = services(request)
    payload = s.remote_auth.state()
    current = s.remote_auth.sessions.validate(_token(request))
    for session in payload["sessions"]:
        session["current"] = bool(current and session["id"] == current.id)
    payload["access"] = access(request).kind
    payload["network"] = s.access_policy.describe()
    payload["session_lifetimes"] = list(LIFETIMES)
    return payload


@router.post("/hostname")
async def set_hostname(request: Request, body: HostnameBody):
    try:
        host = services(request).remote_auth.set_canonical_hostname(body.hostname)
    except RemoteAuthError as exc:
        return error(422, "INVALID_HOSTNAME", str(exc))
    return {"hostname": host}


@router.post("/networks")
async def set_networks(request: Request, body: NetworksBody):
    policy = services(request).access_policy
    try:
        if body.trusted_networks is not None:
            policy.set_trusted_networks(body.trusted_networks)
        if body.trusted_proxies is not None:
            policy.set_trusted_proxies(body.trusted_proxies)
    except PolicyError as exc:
        return error(422, "INVALID_NETWORK", str(exc))
    return policy.describe()


# -- passkeys --------------------------------------------------------------------------------------

@router.post("/passkeys/register/options")
async def register_options(request: Request, body: RegisterOptionsBody):
    s = services(request)
    try:
        ceremony = s.remote_auth.begin_registration(access=access(request).kind, label=body.label,
                                                    recovery_code=body.recovery_code, session_token=_token(request))
    except RemoteAuthError as exc:
        return error(403, "REGISTRATION_NOT_AUTHORIZED", str(exc))
    except PasskeyError as exc:
        return error(422, "PASSKEY_ERROR", str(exc))
    return {"ceremony_id": ceremony.id, "options": ceremony.options}


@router.post("/passkeys/register")
async def register(request: Request, body: RegisterBody):
    s = services(request)
    try:
        enrolment = s.remote_auth.complete_registration(body.ceremony_id, body.response, label=body.label)
    except (PasskeyError, RemoteAuthError) as exc:
        return error(422, "PASSKEY_ERROR", str(exc))
    return {"credential": {"credential_id": enrolment.credential.credential_id, "label": enrolment.credential.label,
                           "created_at": enrolment.credential.created_at},
            "recovery_code": enrolment.recovery_code}


@router.delete("/passkeys/{credential_id}")
async def remove_passkey(request: Request, credential_id: str):
    s = services(request)
    try:
        removed = s.remote_auth.passkeys.delete_credential(credential_id)
    except RemoteAuthError as exc:
        return error(422, "PASSKEY_ERROR", str(exc))
    return {"removed": removed}


# -- sign in and out -------------------------------------------------------------------------------

@router.post("/sign-in/options")
async def sign_in_options(request: Request):
    try:
        ceremony = services(request).remote_auth.begin_authentication()
    except (PasskeyError, RemoteAuthError) as exc:
        return error(409, "NO_PASSKEY", str(exc))
    return {"ceremony_id": ceremony.id, "options": ceremony.options}


@router.post("/sign-in")
async def sign_in(request: Request, body: SignInBody):
    s = services(request)
    try:
        issued = s.remote_auth.complete_authentication(body.ceremony_id, body.response, label=body.label,
                                                       lifetime=body.lifetime)
    except (PasskeyError, RemoteAuthError) as exc:
        return error(401, "SIGN_IN_FAILED", str(exc))
    except SessionError as exc:
        return error(422, "INVALID_LIFETIME", str(exc))
    response = Response(content=json.dumps({"session_id": issued.session_id, "expires_at": issued.expires_at}),
                        media_type="application/json", headers={"Cache-Control": "no-store"})
    response.set_cookie(COOKIE_NAME, issued.token, **cookie_attributes(secure=_is_https(request)))
    return response


@router.post("/sign-out")
async def sign_out(request: Request):
    services(request).remote_auth.sign_out(_token(request))
    response = Response(content=json.dumps({"signed_out": True}), media_type="application/json",
                        headers={"Cache-Control": "no-store"})
    response.delete_cookie(COOKIE_NAME, path="/")
    return response


# -- sessions --------------------------------------------------------------------------------------

@router.get("/sessions")
async def list_sessions(request: Request):
    sessions = services(request).remote_auth.sessions.list_sessions(current_token=_token(request))
    return {"sessions": [{"id": s.id, "label": s.label, "created_at": s.created_at,
                          "last_active_at": s.last_active_at, "expires_at": s.expires_at, "current": s.current}
                         for s in sessions]}


@router.delete("/sessions/{session_id}")
async def revoke_session(request: Request, session_id: str):
    return {"revoked": services(request).remote_auth.sessions.revoke(session_id)}


@router.post("/sessions/revoke-others")
async def revoke_other_sessions(request: Request):
    return {"revoked": services(request).remote_auth.sessions.revoke_others(current_token=_token(request))}


# -- recovery --------------------------------------------------------------------------------------

@router.post("/recovery/regenerate")
async def regenerate_recovery(request: Request):
    return {"recovery_code": services(request).remote_auth.regenerate_recovery_code()}


@router.post("/lan-recovery")
async def lan_recovery(request: Request):
    """§28.5: available to genuine LAN devices; affects remote Web UI authentication only."""
    try:
        report = services(request).remote_auth.lan_recovery_reset(access=access(request).kind)
    except RemoteAuthError as exc:
        return error(403, "LAN_RECOVERY_UNAVAILABLE", str(exc))
    return {"passkeys_removed": report.passkeys_removed, "sessions_revoked": report.sessions_revoked,
            "message": report.message}
