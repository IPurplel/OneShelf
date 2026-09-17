"""Core-owned HTTP client for source traffic (Master §9.3, §11). Plugins never get a client.

- DNS goes through PolicyResolver: every answer is validated and the validated address is what the
  connection uses (no second lookup → no DNS rebinding window).
- Redirects are followed manually with full policy re-checks per hop.
- No environment proxies, no automatic cookie storage, bounded bodies.
"""
from __future__ import annotations

import socket
from collections.abc import Callable
from dataclasses import dataclass, field
from urllib.parse import urljoin

import aiohttp
from aiohttp.abc import AbstractResolver
from multidict import CIMultiDict

from oneshelf.net.policy import BlockedDestination, DisallowedTarget, EgressPolicy, Target

__all__ = ["BlockedDestination", "DisallowedTarget", "HttpClient", "HttpResponse", "ResponseTooLarge", "TooManyRedirects",
           "FetchFailed"]

DEFAULT_MAX_BYTES = 64 * 1024**2
DEFAULT_MAX_REDIRECTS = 5
USER_AGENT = "OneShelf/0.1 (+self-hosted personal library)"
REDIRECT_STATUSES = {301, 302, 303, 307, 308}


class TooManyRedirects(RuntimeError):
    pass


class ResponseTooLarge(RuntimeError):
    pass


class FetchFailed(RuntimeError):
    """Transport-level failure (timeout, reset, TLS, DNS failure)."""


@dataclass
class HttpResponse:
    url: str
    status: int
    headers: CIMultiDict
    body: bytes
    redirects: list[str] = field(default_factory=list)


class PolicyResolver(AbstractResolver):
    def __init__(self, policy: EgressPolicy, backend) -> None:
        self.policy = policy
        self.backend = backend

    async def resolve(self, host: str, port: int = 0, family: int = socket.AF_INET):
        results = await self.backend.resolve(host, port, family)
        self.policy.check_resolved(host, [r["host"] for r in results])
        return results

    async def close(self) -> None:
        await self.backend.close()


def _find_cause(exc: BaseException, kind: type) -> BaseException | None:
    seen = set()
    while exc is not None and id(exc) not in seen:
        if isinstance(exc, kind):
            return exc
        seen.add(id(exc))
        exc = exc.__cause__ or exc.__context__
    return None


CookieProvider = Callable[[Target], str | None]


class HttpClient:
    def __init__(self, policy: EgressPolicy, *, resolver_backend=None, connect_timeout: float = 10,
                 read_timeout: float = 30) -> None:
        self.policy = policy
        self._backend = resolver_backend
        self._timeout = aiohttp.ClientTimeout(total=None, connect=connect_timeout, sock_read=read_timeout)
        self._session: aiohttp.ClientSession | None = None

    async def __aenter__(self) -> HttpClient:
        backend = self._backend or aiohttp.ThreadedResolver()
        connector = aiohttp.TCPConnector(resolver=PolicyResolver(self.policy, backend), use_dns_cache=False, limit=16)
        self._session = aiohttp.ClientSession(
            connector=connector, trust_env=False, cookie_jar=aiohttp.DummyCookieJar(), timeout=self._timeout,
        )
        return self

    async def __aexit__(self, *exc) -> None:
        if self._session is not None:
            await self._session.close()
            self._session = None

    async def fetch(
        self,
        url: str,
        *,
        method: str = "GET",
        headers: dict[str, str] | None = None,
        data: dict[str, str] | None = None,
        max_bytes: int = DEFAULT_MAX_BYTES,
        max_redirects: int = DEFAULT_MAX_REDIRECTS,
        cookie_provider: CookieProvider | None = None,
    ) -> HttpResponse:
        if self._session is None:
            raise RuntimeError("HttpClient must be used as an async context manager")
        redirects: list[str] = []
        current, current_method, current_data = url, method, data
        for _hop in range(max_redirects + 1):
            target = self.policy.check_url(current)
            request_headers = {"User-Agent": USER_AGENT, **(headers or {})}
            cookie = cookie_provider(target) if cookie_provider else None
            if cookie:
                request_headers["Cookie"] = cookie
            try:
                async with self._session.request(
                    current_method, current, headers=request_headers, data=current_data, allow_redirects=False,
                ) as resp:
                    location = resp.headers.get("Location")
                    if resp.status in REDIRECT_STATUSES and location:
                        redirects.append(current)
                        current = urljoin(current, location)
                        if resp.status == 303 or (resp.status in (301, 302) and current_method == "POST"):
                            current_method, current_data = "GET", None
                        continue
                    body = bytearray()
                    async for chunk in resp.content.iter_chunked(64 * 1024):
                        body.extend(chunk)
                        if len(body) > max_bytes:
                            raise ResponseTooLarge(f"response exceeds {max_bytes} bytes")
                    return HttpResponse(url=current, status=resp.status, headers=CIMultiDict(resp.headers),
                                        body=bytes(body), redirects=redirects)
            except (ResponseTooLarge, DisallowedTarget):
                raise
            except Exception as exc:
                blocked = _find_cause(exc, BlockedDestination)
                if blocked is not None:
                    raise blocked from None
                if isinstance(exc, (aiohttp.ClientError, TimeoutError, OSError)):
                    raise FetchFailed(f"{type(exc).__name__}: {exc}") from exc
                raise
        raise TooManyRedirects(f"more than {max_redirects} redirects")
