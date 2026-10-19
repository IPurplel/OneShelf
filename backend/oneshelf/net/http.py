"""Core-owned HTTP client for source traffic (Master §9.3, §11). Plugins never get a client.

- DNS goes through PolicyResolver: every answer is validated and the validated address is what the
  connection uses (no second lookup → no DNS rebinding window).
- Redirects are followed manually with full policy re-checks per hop.
- No environment proxies, no automatic cookie storage, bounded bodies.
"""
from __future__ import annotations

import socket
from collections.abc import Callable
from contextlib import asynccontextmanager, contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urljoin

import aiohttp
from aiohttp.abc import AbstractResolver
from multidict import CIMultiDict

from oneshelf.net.policy import BlockedDestination, DisallowedTarget, EgressPolicy, Target

__all__ = ["BlockedDestination", "DisallowedTarget", "HttpClient", "HttpResponse", "ResponseTooLarge", "TooManyRedirects",
           "FetchFailed", "StreamedResponse"]

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


@dataclass
class StreamedResponse:
    """A response whose body went to a file: what was written, and whether it continued the file."""
    url: str
    status: int
    headers: CIMultiDict
    redirects: list[str]
    bytes_written: int
    resumed: bool
    total: int | None


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

    @asynccontextmanager
    async def _final_response(self, url: str, *, method: str, headers: dict[str, str] | None,
                              data: dict[str, str] | None, max_redirects: int,
                              cookie_provider: CookieProvider | None):
        """The response at the end of the redirect chain, every hop re-checked against the policy.

        The connection is released when the caller is done, and closed outright if anything went wrong while
        it was in use, so an abandoned read never leaks a socket (I-109).
        """
        if self._session is None:
            raise RuntimeError("HttpClient must be used as an async context manager")
        redirects: list[str] = []
        current, current_method, current_data = url, method, data
        with _transport_errors():
            for _hop in range(max_redirects + 1):
                target = self.policy.check_url(current)
                request_headers = {"User-Agent": USER_AGENT, **(headers or {})}
                cookie = cookie_provider(target) if cookie_provider else None
                if cookie:
                    request_headers["Cookie"] = cookie
                resp = await self._session.request(current_method, current, headers=request_headers,
                                                   data=current_data, allow_redirects=False)
                location = resp.headers.get("Location")
                if resp.status in REDIRECT_STATUSES and location:
                    resp.release()
                    redirects.append(current)
                    current = urljoin(current, location)
                    if resp.status == 303 or (resp.status in (301, 302) and current_method == "POST"):
                        current_method, current_data = "GET", None
                    continue
                try:
                    yield resp, current, redirects
                except BaseException:
                    resp.close()
                    raise
                else:
                    resp.release()
                return
        raise TooManyRedirects(f"more than {max_redirects} redirects")

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
        """A small response held in memory (pages, recipes, covers). Large files use `stream_to`."""
        async with self._final_response(url, method=method, headers=headers, data=data,
                                        max_redirects=max_redirects, cookie_provider=cookie_provider) as (resp, final,
                                                                                                         redirects):
            with _transport_errors():
                body = bytearray()
                async for chunk in resp.content.iter_chunked(64 * 1024):
                    body.extend(chunk)
                    if len(body) > max_bytes:
                        raise ResponseTooLarge(f"response exceeds {max_bytes} bytes")
            return HttpResponse(url=final, status=resp.status, headers=CIMultiDict(resp.headers), body=bytes(body),
                                redirects=redirects)

    async def stream_to(
        self,
        url: str,
        path: str | Path,
        *,
        resume_from: int = 0,
        validator: str | None = None,
        headers: dict[str, str] | None = None,
        max_bytes: int = DEFAULT_MAX_BYTES,
        max_redirects: int = DEFAULT_MAX_REDIRECTS,
        cookie_provider: CookieProvider | None = None,
    ) -> StreamedResponse:
        """Write a response body to `path` in chunks, never holding it in memory (Master §16, §56; I-101).

        With `resume_from` and the stored `validator`, asks for the rest with Range/If-Range and appends only
        when the server answers 206 for exactly that offset and the same version. A changed version, a full
        answer or "range not satisfiable" starts the file over, so two versions are never spliced (§16.4,
        I-97). Only a 200 or a matching 206 writes anything.
        """
        path = Path(path)
        resume = bool(resume_from and validator and path.is_file() and path.stat().st_size == resume_from)
        for asking_for_rest in ((True, False) if resume else (False,)):
            request_headers = dict(headers or {})
            if asking_for_rest:
                request_headers.update({"Range": f"bytes={resume_from}-", "If-Range": validator})
            async with self._final_response(url, method="GET", headers=request_headers, data=None,
                                            max_redirects=max_redirects,
                                            cookie_provider=cookie_provider) as (resp, final, redirects):
                response_validator = resp.headers.get("ETag") or resp.headers.get("Last-Modified")
                appending = (asking_for_rest and resp.status == 206
                             and _range_start(resp.headers.get("Content-Range")) == resume_from
                             and response_validator in (None, validator))
                if asking_for_rest and not appending and resp.status in (206, 416):
                    continue            # not the continuation we asked for: start the file over
                written = 0
                if resp.status == 200 or appending:
                    offset = resume_from if appending else 0
                    with _transport_errors(), open(path, "ab" if appending else "wb") as handle:
                        async for chunk in resp.content.iter_chunked(64 * 1024):
                            written += len(chunk)
                            if offset + written > max_bytes:
                                raise ResponseTooLarge(f"response exceeds {max_bytes} bytes")
                            handle.write(chunk)
                return StreamedResponse(url=final, status=resp.status, headers=CIMultiDict(resp.headers),
                                        redirects=redirects, bytes_written=written, resumed=appending,
                                        total=_total_length(resp.headers, resume_from if appending else 0))
        raise AssertionError("unreachable")  # pragma: no cover


def _range_start(content_range: str | None) -> int | None:
    try:
        return int(content_range.split(" ", 1)[1].split("-", 1)[0]) if content_range else None
    except (IndexError, ValueError):
        return None


def _total_length(headers, offset: int) -> int | None:
    content_range = headers.get("Content-Range")
    if content_range and "/" in content_range:
        total = content_range.rsplit("/", 1)[1]
        return int(total) if total.isdigit() else None
    length = headers.get("Content-Length")
    return offset + int(length) if length and length.isdigit() else None


@contextmanager
def _transport_errors():
    """Policy refusals pass through as themselves; every transport failure becomes FetchFailed."""
    try:
        yield
    except (ResponseTooLarge, DisallowedTarget, TooManyRedirects):
        raise
    except Exception as exc:
        blocked = _find_cause(exc, BlockedDestination)
        if blocked is not None:
            raise blocked from None
        if isinstance(exc, (aiohttp.ClientError, TimeoutError, OSError)):
            raise FetchFailed(f"{type(exc).__name__}: {exc}") from exc
        raise
