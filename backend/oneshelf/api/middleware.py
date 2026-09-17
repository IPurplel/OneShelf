"""ASGI boundary: classify every request; deny unauthenticated remote access (Master §28, ledger K4)."""
from __future__ import annotations

import json
from collections.abc import Callable

from oneshelf.api.access import AccessConfig, classify

RemoteAuthenticator = Callable[[dict], bool]


def _deny_all_remote(_scope: dict) -> bool:
    return False  # built-in passkey sessions arrive in C8


class AccessBoundaryMiddleware:
    def __init__(self, app, config: AccessConfig, remote_authenticator: RemoteAuthenticator = _deny_all_remote):
        self.app = app
        self.config = config
        self.remote_authenticator = remote_authenticator

    async def __call__(self, scope, receive, send):
        if scope["type"] not in ("http", "websocket"):
            return await self.app(scope, receive, send)
        headers = {k.decode("latin-1").lower(): v.decode("latin-1") for k, v in scope.get("headers", [])}
        client = scope.get("client")
        access = classify(client[0] if client else None, headers, self.config)
        scope.setdefault("state", {})["access"] = access
        if access.kind != "remote" or self.remote_authenticator(scope):
            return await self.app(scope, receive, send)
        if scope["type"] == "websocket":
            await send({"type": "websocket.close", "code": 4401})
            return
        body = json.dumps({"error": {"code": "REMOTE_AUTH_REQUIRED",
                                     "message": "Remote access requires signing in with a passkey."}}).encode()
        await send({"type": "http.response.start", "status": 401,
                    "headers": [(b"content-type", b"application/json"), (b"cache-control", b"no-store")]})
        await send({"type": "http.response.body", "body": body})
