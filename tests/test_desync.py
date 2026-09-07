"""Built-in DPI-bypass proxy.

Verifies the SOCKS5 implementation is correct and, critically, that the opening
payload really does arrive as separate TCP segments — the whole mechanism
depends on that, and it is easy to break by coalescing writes.
"""

from __future__ import annotations

import asyncio
import socket
import struct

import pytest

from app.config import Settings
from app.desync import DesyncProxy


class SegmentRecorder:
    """Upstream server that records how the client's bytes were segmented."""

    def __init__(self) -> None:
        self.port = 0
        self.segments: list[bytes] = []
        self._server: asyncio.AbstractServer | None = None
        self._done = asyncio.Event()

    async def start(self) -> None:
        self._server = await asyncio.start_server(self._handle, "127.0.0.1", 0)
        self.port = self._server.sockets[0].getsockname()[1]

    async def stop(self) -> None:
        if self._server:
            self._server.close()
            await self._server.wait_closed()

    async def _handle(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
        try:
            # Read whatever arrives, recording each delivery separately. With
            # TCP_NODELAY and a delay between writes these stay distinct.
            while len(b"".join(self.segments)) < 64:
                chunk = await asyncio.wait_for(reader.read(4096), timeout=3)
                if not chunk:
                    break
                self.segments.append(chunk)
                self._done.set()
        except (asyncio.TimeoutError, ConnectionError):
            pass
        finally:
            writer.close()

    async def wait(self, timeout: float = 3.0) -> None:
        try:
            await asyncio.wait_for(self._done.wait(), timeout)
            await asyncio.sleep(0.25)  # let the second segment land
        except asyncio.TimeoutError:
            pass


async def socks5_connect(proxy_port: int, host: str, port: int):
    """Perform a SOCKS5 CONNECT and return the open streams."""
    reader, writer = await asyncio.open_connection("127.0.0.1", proxy_port)

    writer.write(b"\x05\x01\x00")  # version 5, 1 method, no auth
    await writer.drain()
    assert await reader.readexactly(2) == b"\x05\x00"

    encoded = host.encode()
    writer.write(
        b"\x05\x01\x00\x03" + bytes([len(encoded)]) + encoded + struct.pack("!H", port)
    )
    await writer.drain()

    reply = await reader.readexactly(10)
    assert reply[0] == 5, "bad SOCKS version in reply"
    return reader, writer, reply[1]


@pytest.fixture
async def proxy():
    server = DesyncProxy(split_at=1, delay=0.05)
    await server.start()
    yield server
    await server.stop()


# ------------------------------------------------------------------- basics


async def test_proxy_reports_its_url(proxy):
    assert proxy.running
    assert proxy.url.startswith("socks5://127.0.0.1:")
    assert proxy.port > 0
    assert proxy.status()["running"] is True


async def test_connect_succeeds_and_relays(proxy):
    upstream = SegmentRecorder()
    await upstream.start()
    try:
        reader, writer, code = await socks5_connect(proxy.port, "127.0.0.1", upstream.port)
        assert code == 0  # success
        writer.write(b"x" * 40)
        await writer.drain()
        await upstream.wait()
        writer.close()

        assert b"".join(upstream.segments) == b"x" * 40
    finally:
        await upstream.stop()


async def test_first_payload_is_split_into_separate_segments(proxy):
    """The core mechanism: opening bytes must not arrive as one segment."""
    upstream = SegmentRecorder()
    await upstream.start()
    try:
        _, writer, _ = await socks5_connect(proxy.port, "127.0.0.1", upstream.port)
        writer.write(b"A" + b"B" * 39)  # stands in for a ClientHello
        await writer.drain()
        await upstream.wait()
        writer.close()

        assert len(upstream.segments) >= 2, (
            f"expected a split, got one segment of {len(upstream.segments[0])} bytes"
        )
        assert upstream.segments[0] == b"A"          # split_at=1
        assert b"".join(upstream.segments) == b"A" + b"B" * 39  # nothing lost
    finally:
        await upstream.stop()


async def test_split_point_is_configurable():
    server = DesyncProxy(split_at=5, delay=0.05)
    await server.start()
    upstream = SegmentRecorder()
    await upstream.start()
    try:
        _, writer, _ = await socks5_connect(server.port, "127.0.0.1", upstream.port)
        writer.write(b"HELLO" + b"rest" * 8)
        await writer.drain()
        await upstream.wait()
        writer.close()

        assert upstream.segments[0] == b"HELLO"
    finally:
        await upstream.stop()
        await server.stop()


async def test_payload_shorter_than_split_is_sent_whole(proxy):
    upstream = SegmentRecorder()
    await upstream.start()
    try:
        server = DesyncProxy(split_at=100, delay=0.0)
        await server.start()
        try:
            _, writer, _ = await socks5_connect(server.port, "127.0.0.1", upstream.port)
            writer.write(b"short")
            await writer.drain()
            await upstream.wait()
            writer.close()
            assert b"".join(upstream.segments) == b"short"
        finally:
            await server.stop()
    finally:
        await upstream.stop()


# -------------------------------------------------------------- error paths


async def test_unreachable_upstream_reports_failure(proxy):
    # Port 1 on localhost: reliably closed.
    _, writer, code = await socks5_connect(proxy.port, "127.0.0.1", 1)
    assert code != 0
    writer.close()
    assert proxy.failures >= 1


async def test_non_socks5_greeting_is_rejected(proxy):
    reader, writer = await asyncio.open_connection("127.0.0.1", proxy.port)
    writer.write(b"\x04\x01\x00")  # SOCKS4
    await writer.drain()
    assert await reader.readexactly(1) == b"\xff"
    writer.close()


async def test_bind_command_is_refused(proxy):
    reader, writer = await asyncio.open_connection("127.0.0.1", proxy.port)
    writer.write(b"\x05\x01\x00")
    await writer.drain()
    await reader.readexactly(2)

    writer.write(b"\x05\x02\x00\x01" + socket.inet_aton("127.0.0.1") + struct.pack("!H", 80))
    await writer.drain()
    reply = await reader.readexactly(10)
    assert reply[1] == 7  # command not supported
    writer.close()


# --------------------------------------------------------- settings wiring


def test_desync_off_by_default(tmp_path):
    assert Settings(config_dir=tmp_path).desync_enabled is False


def test_runtime_proxy_is_used_when_no_explicit_proxy(tmp_path):
    settings = Settings(config_dir=tmp_path, desync_enabled=True)
    settings._runtime_proxy = "socks5://127.0.0.1:9999"

    assert settings.effective_proxy == "socks5://127.0.0.1:9999"
    assert settings.proxy_config.port == 9999


def test_explicit_proxy_overrides_the_builtin_bypass(tmp_path):
    """An operator who named a route must not be silently rerouted."""
    settings = Settings(
        config_dir=tmp_path, proxy="socks5://10.0.0.9:1080", desync_enabled=True
    )
    settings._runtime_proxy = "socks5://127.0.0.1:9999"

    assert settings.effective_proxy == "socks5://10.0.0.9:1080"


def test_runtime_proxy_is_not_persisted(tmp_path):
    """It is a per-run detail - the port is chosen at bind time."""
    settings = Settings(config_dir=tmp_path)
    settings._runtime_proxy = "socks5://127.0.0.1:9999"

    assert "9999" not in settings.model_dump_json()
