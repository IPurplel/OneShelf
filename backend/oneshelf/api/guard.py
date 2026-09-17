"""Request guard: Host allowlist and same-origin checks for state-changing requests (ledger D-C3-13).

LAN trust (Master §28.1) covers genuine devices, not arbitrary websites running in their browsers:
- A Host allowlist (IP literals, localhost, configured names) defeats DNS-rebinding attacks.
- Browser requests that change state must be same-origin (Origin / Sec-Fetch-Site), which stops
  cross-site request forgery against an unauthenticated LAN instance. Non-browser clients are unaffected.
"""
from __future__ import annotations

import ipaddress
import json

UNSAFE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}


def _split_host(value: str) -> tuple[str, str | None]:
    value = value.strip().lower()
    if value.startswith("["):
        host, _, rest = value[1:].partition("]")
        return host, rest.lstrip(":") or None
    host, sep, port = value.rpartition(":")
    if sep and port.isdigit():
        return host, port
    return value, None


def _is_ip(host: str) -> bool:
    try:
        ipaddress.ip_address(host)
        return True
    except ValueError:
        return False


class RequestGuardMiddleware:
    def __init__(self, app, allowed_hosts: tuple[str, ...] | list[str] = ()) -> None:
        self.app = app
        self.allowed = {h.strip().lower().rstrip(".") for h in allowed_hosts if h.strip()} | {"localhost"}

    async def _deny(self, send, status: int, code: str, message: str) -> None:
        body = json.dumps({"error": {"code": code, "message": message}}).encode()
        await send({"type": "http.response.start", "status": status,
                    "headers": [(b"content-type", b"application/json"), (b"cache-control", b"no-store")]})
        await send({"type": "http.response.body", "body": body})

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        headers = {k.decode("latin-1").lower(): v.decode("latin-1") for k, v in scope.get("headers", [])}
        host_header = headers.get("host", "")
        host, _port = _split_host(host_header)
        if not host or not (_is_ip(host) or host.rstrip(".") in self.allowed):
            return await self._deny(send, 421, "HOST_NOT_ALLOWED", "This OneShelf address is not configured.")
        if scope["method"] in UNSAFE_METHODS:
            if headers.get("sec-fetch-site") == "cross-site":
                return await self._deny(send, 403, "CROSS_ORIGIN_REQUEST", "Cross-site requests are not allowed.")
            origin = headers.get("origin")
            if origin is not None:
                origin_netloc = origin.split("://", 1)[-1].rstrip("/").lower() if "://" in origin else None
                if origin_netloc != host_header.strip().lower():
                    return await self._deny(send, 403, "CROSS_ORIGIN_REQUEST", "Cross-site requests are not allowed.")
        return await self.app(scope, receive, send)
