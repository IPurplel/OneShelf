"""Core-owned egress proxy for browser traffic (Master §11 browser path; ledger K2).

Chromium resolves DNS itself, so request interception cannot stop DNS rebinding. All browser traffic is
forced through this proxy instead: every CONNECT / absolute-form request is checked against the plugin's
EgressPolicy, the destination is resolved and validated here, and the connection goes to the validated
address. One request per connection prevents a pipelined request from skipping validation.
"""
from __future__ import annotations

import asyncio
import base64
import hmac
import secrets
from urllib.parse import urlsplit

import aiohttp

from oneshelf.diagnostics.redact import redact_url
from oneshelf.net.policy import BlockedDestination, DisallowedTarget, EgressPolicy

MAX_HEAD_BYTES = 16 * 1024
MAX_BODY_BYTES = 16 * 1024 * 1024
HEAD_TIMEOUT = 15.0
CONNECT_TIMEOUT = 10.0
IDLE_TIMEOUT = 60.0
HOP_BY_HOP = {"connection", "keep-alive", "proxy-connection", "proxy-authorization", "proxy-authenticate", "te",
              "trailer", "upgrade"}


class EgressProxy:
    def __init__(self, policy: EgressPolicy, *, resolver_backend=None) -> None:
        self.policy = policy
        self.backend = resolver_backend
        self.username = "oneshelf"
        self.password = secrets.token_urlsafe(24)
        self.port: int | None = None
        self.blocked: list[str] = []
        self._server: asyncio.base_events.Server | None = None
        self._tasks: set[asyncio.Task] = set()

    @property
    def server_url(self) -> str:
        return f"http://127.0.0.1:{self.port}"

    async def start(self) -> EgressProxy:
        if self.backend is None:
            self.backend = aiohttp.ThreadedResolver()
        self._server = await asyncio.start_server(self._track, "127.0.0.1", 0, limit=MAX_HEAD_BYTES)
        self.port = self._server.sockets[0].getsockname()[1]
        return self

    async def stop(self) -> None:
        if self._server is not None:
            self._server.close()
            await self._server.wait_closed()
        for task in list(self._tasks):
            task.cancel()
        await asyncio.gather(*self._tasks, return_exceptions=True)

    async def _track(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        task = asyncio.current_task()
        self._tasks.add(task)
        try:
            await self._handle(reader, writer)
        except (ConnectionError, asyncio.IncompleteReadError, TimeoutError):
            pass
        finally:
            self._tasks.discard(task)
            writer.close()

    # -- protocol ---------------------------------------------------------------------------------

    @staticmethod
    async def _reply(writer: asyncio.StreamWriter, status: str, extra: str = "") -> None:
        writer.write(f"HTTP/1.1 {status}\r\nContent-Length: 0\r\nConnection: close\r\n{extra}\r\n".encode())
        await writer.drain()

    def _authorized(self, headers: dict[str, str]) -> bool:
        expected = "Basic " + base64.b64encode(f"{self.username}:{self.password}".encode()).decode()
        return hmac.compare_digest(headers.get("proxy-authorization", ""), expected)

    async def _handle(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        try:
            head = await asyncio.wait_for(reader.readuntil(b"\r\n\r\n"), HEAD_TIMEOUT)
        except (asyncio.LimitOverrunError, ValueError):
            await self._reply(writer, "431 Request Header Fields Too Large")
            return
        lines = head.decode("latin-1").split("\r\n")
        try:
            method, target, _version = lines[0].split(" ", 2)
        except ValueError:
            await self._reply(writer, "400 Bad Request")
            return
        header_lines = [line for line in lines[1:] if line]
        headers = {}
        for line in header_lines:
            name, _, value = line.partition(":")
            headers[name.strip().lower()] = value.strip()
        if not self._authorized(headers):
            await self._reply(writer, "407 Proxy Authentication Required", 'Proxy-Authenticate: Basic realm="OneShelf"\r\n')
            return
        try:
            if method.upper() == "CONNECT":
                await self._connect(target, reader, writer)
            else:
                await self._forward(method, target, header_lines, headers, reader, writer)
        except (DisallowedTarget, BlockedDestination) as exc:
            self.blocked.append(f"{method.upper()} {redact_url(target) if '://' in target else target}: {exc}")
            await self._reply(writer, "403 Forbidden")
        except OSError:
            await self._reply(writer, "502 Bad Gateway")

    async def _open(self, host: str, port: int):
        results = await self.backend.resolve(host, port)
        self.policy.check_resolved(host, [r["host"] for r in results])
        chosen = results[0]
        return await asyncio.wait_for(asyncio.open_connection(chosen["host"], chosen["port"]), CONNECT_TIMEOUT)

    async def _connect(self, authority: str, reader, writer) -> None:
        target = self.policy.check_url(f"https://{authority}/")
        upstream_reader, upstream_writer = await self._open(target.host, target.port)
        writer.write(b"HTTP/1.1 200 Connection Established\r\n\r\n")
        await writer.drain()
        await self._relay_both(reader, writer, upstream_reader, upstream_writer)

    async def _forward(self, method: str, url: str, header_lines: list[str], headers: dict[str, str], reader, writer) -> None:
        if not url.lower().startswith("http://"):
            raise DisallowedTarget("proxy accepts absolute http:// URLs and CONNECT only")
        target = self.policy.check_url(url)
        if "chunked" in headers.get("transfer-encoding", "").lower():
            await self._reply(writer, "411 Length Required")
            return
        length = int(headers.get("content-length", "0") or 0)
        if length < 0 or length > MAX_BODY_BYTES:
            await self._reply(writer, "413 Payload Too Large")
            return
        body = await reader.readexactly(length) if length else b""
        parts = urlsplit(url)
        path = parts.path or "/"
        if parts.query:
            path += "?" + parts.query
        forwarded = [f"{method} {path} HTTP/1.1"]
        for line in header_lines:
            name = line.partition(":")[0].strip().lower()
            if name not in HOP_BY_HOP:
                forwarded.append(line)
        if "host" not in headers:
            forwarded.append(f"Host: {parts.netloc}")
        forwarded.append("Connection: close")
        upstream_reader, upstream_writer = await self._open(target.host, target.port)
        try:
            upstream_writer.write(("\r\n".join(forwarded) + "\r\n\r\n").encode("latin-1") + body)
            await upstream_writer.drain()
            await self._relay(upstream_reader, writer)
        finally:
            upstream_writer.close()

    @staticmethod
    async def _relay(source: asyncio.StreamReader, sink: asyncio.StreamWriter) -> None:
        while True:
            chunk = await asyncio.wait_for(source.read(64 * 1024), IDLE_TIMEOUT)
            if not chunk:
                return
            sink.write(chunk)
            await sink.drain()

    async def _relay_both(self, client_reader, client_writer, upstream_reader, upstream_writer) -> None:
        tasks = [asyncio.create_task(self._relay(client_reader, upstream_writer)),
                 asyncio.create_task(self._relay(upstream_reader, client_writer))]
        try:
            await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
        finally:
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            upstream_writer.close()
