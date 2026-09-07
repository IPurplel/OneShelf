"""Proxy parsing, plus an end-to-end fetch through a real SOCKS5 server.

The parsing tests are cheap. The integration test matters more: it stands up an
actual SOCKS5 proxy and pulls an image through it with the real Fetcher, which
is the only way to know the wiring works rather than merely type-checks.
"""

from __future__ import annotations

import asyncio
import socket
import struct
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from app.config import Settings
from app.fetcher import Fetcher
from app.proxy import ProxyError, parse_proxy

from .conftest import make_noise_png


# ------------------------------------------------------------------ parsing


def test_unset_proxy_is_none():
    assert parse_proxy(None) is None
    assert parse_proxy("") is None
    assert parse_proxy("   ") is None


def test_socks5_url():
    proxy = parse_proxy("socks5://127.0.0.1:1080")
    assert (proxy.scheme, proxy.host, proxy.port) == ("socks5", "127.0.0.1", 1080)
    assert proxy.is_socks
    assert proxy.for_browser() == {"server": "socks5://127.0.0.1:1080"}
    assert proxy.for_httpx() == "socks5://127.0.0.1:1080"


def test_bare_host_port_defaults_to_http():
    proxy = parse_proxy("192.168.1.5:3128")
    assert proxy.scheme == "http"
    assert proxy.port == 3128


def test_missing_port_gets_scheme_default():
    assert parse_proxy("socks5://10.0.0.1").port == 1080
    assert parse_proxy("http://10.0.0.1").port == 8080


def test_credentials_are_split_for_playwright():
    proxy = parse_proxy("http://bob:s3cret@proxy.lan:8080")
    assert proxy.for_browser() == {
        "server": "http://proxy.lan:8080",
        "username": "bob",
        "password": "s3cret",
    }
    assert proxy.for_httpx() == "http://bob:s3cret@proxy.lan:8080"


def test_special_characters_in_credentials_round_trip():
    proxy = parse_proxy("http://user%40corp:p%40ss%3Aword@proxy.lan:8080")
    assert proxy.username == "user@corp"
    assert proxy.password == "p@ss:word"
    # Must be re-encoded, or httpx mis-parses the authority section.
    assert "%40" in proxy.for_httpx()


def test_password_is_never_exposed_in_description():
    proxy = parse_proxy("http://bob:s3cret@proxy.lan:8080")
    described = proxy.describe()
    assert "s3cret" not in described
    assert "bob" in described


def test_socks5h_is_normalised_for_chromium():
    """Chromium rejects the socks5h spelling but already resolves remotely."""
    proxy = parse_proxy("socks5h://127.0.0.1:1080")
    assert proxy.scheme == "socks5h"
    assert proxy.for_browser()["server"] == "socks5://127.0.0.1:1080"
    assert proxy.for_httpx() == "socks5://127.0.0.1:1080"


@pytest.mark.parametrize("bad", ["ftp://h:1", "gopher://h", "socks5://:1080", "http://h:99999"])
def test_malformed_urls_are_rejected(bad):
    with pytest.raises(ProxyError):
        parse_proxy(bad)


# ----------------------------------------------------- settings integration


def test_settings_reject_bad_proxy(tmp_path):
    with pytest.raises(Exception):
        Settings(config_dir=tmp_path, proxy="ftp://nope:21")


def test_settings_treat_blank_as_unset(tmp_path):
    assert Settings(config_dir=tmp_path, proxy="   ").proxy is None
    assert Settings(config_dir=tmp_path, proxy="").proxy_config is None


def test_settings_expose_parsed_proxy(tmp_path):
    settings = Settings(config_dir=tmp_path, proxy="socks5://127.0.0.1:1080")
    assert settings.proxy_config.port == 1080


# --------------------------------------------------- real SOCKS5 round trip


class _ImageHandler(BaseHTTPRequestHandler):
    def do_GET(self):  # noqa: N802
        body = make_noise_png(80, 120)
        self.send_response(200)
        self.send_header("Content-Type", "image/png")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


class MiniSocks5Server:
    """A minimal no-auth SOCKS5 server, enough to prove the path works.

    Records the address type of each request so the test can assert that a
    hostname was sent to the proxy rather than resolved locally — the property
    that actually matters when the local resolver or DPI is the problem.
    """

    def __init__(self) -> None:
        self.port = 0
        self.requests: list[tuple[str, int]] = []
        self.address_types: list[int] = []
        self._server: asyncio.AbstractServer | None = None

    async def start(self) -> None:
        self._server = await asyncio.start_server(self._handle, "127.0.0.1", 0)
        self.port = self._server.sockets[0].getsockname()[1]

    async def stop(self) -> None:
        if self._server is not None:
            self._server.close()
            await self._server.wait_closed()

    async def _handle(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
        try:
            # Greeting: version, number of methods, methods
            header = await reader.readexactly(2)
            await reader.readexactly(header[1])
            writer.write(b"\x05\x00")  # no authentication required
            await writer.drain()

            # Request: ver, cmd, reserved, address type
            ver, cmd, _, atyp = await reader.readexactly(4)
            self.address_types.append(atyp)

            if atyp == 1:  # IPv4
                host = socket.inet_ntoa(await reader.readexactly(4))
            elif atyp == 3:  # domain name
                length = (await reader.readexactly(1))[0]
                host = (await reader.readexactly(length)).decode()
            else:  # IPv6
                host = socket.inet_ntop(socket.AF_INET6, await reader.readexactly(16))

            port = struct.unpack("!H", await reader.readexactly(2))[0]
            self.requests.append((host, port))

            if cmd != 1:  # CONNECT only
                writer.write(b"\x05\x07\x00\x01" + b"\x00" * 6)
                await writer.drain()
                return

            try:
                remote_r, remote_w = await asyncio.open_connection(host, port)
            except Exception:
                writer.write(b"\x05\x05\x00\x01" + b"\x00" * 6)
                await writer.drain()
                return

            writer.write(b"\x05\x00\x00\x01" + b"\x00" * 6)  # success
            await writer.drain()

            await asyncio.gather(
                self._pipe(reader, remote_w),
                self._pipe(remote_r, writer),
                return_exceptions=True,
            )
        except Exception:
            pass
        finally:
            writer.close()

    @staticmethod
    async def _pipe(reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
        try:
            while chunk := await reader.read(65536):
                writer.write(chunk)
                await writer.drain()
        finally:
            writer.close()


# -------------------------------------------------- connect-error classifying


def test_reset_is_detected_through_a_wrapped_chain():
    """httpx buries the real cause and its own str() is empty.

    Regression guard: an earlier version matched on the message text and so
    misreported the exact case this diagnostic exists for.
    """
    import httpx as _httpx

    from app.main import _describe_exception, _is_connection_reset

    root = ConnectionResetError(22, "[WinError 64] network name no longer available")
    middle = _httpx.ConnectError("")
    middle.__cause__ = root
    outer = _httpx.ConnectError("")
    outer.__cause__ = middle

    assert str(outer) == ""          # the trap: nothing to string-match on
    assert _is_connection_reset(outer)
    assert "ConnectionResetError" in _describe_exception(outer)


def test_ordinary_connect_failure_is_not_called_a_reset():
    import httpx as _httpx

    from app.main import _is_connection_reset

    exc = _httpx.ConnectError("nodename nor servname provided")
    exc.__cause__ = OSError(11001, "getaddrinfo failed")

    assert not _is_connection_reset(exc)


def test_cause_walk_survives_a_cycle():
    from app.main import _walk_causes

    a = ValueError("a")
    b = ValueError("b")
    a.__cause__ = b
    b.__cause__ = a  # self-referential chain must not hang

    assert len(list(_walk_causes(a))) <= 8


@pytest.fixture
def image_server():
    server = ThreadingHTTPServer(("127.0.0.1", 0), _ImageHandler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{server.server_port}"
    server.shutdown()
    server.server_close()


class _StubSessions:
    def __init__(self):
        self.user_agent = "pytest-agent"

    async def get_session(self, url, *, force=False):
        from app.session import HostSession

        return HostSession(host="x", cookies={}, user_agent="pytest-agent")

    async def peek_session(self, url):
        return await self.get_session(url)

    async def refresh(self, url):
        return await self.get_session(url)


async def test_image_is_fetched_through_socks5_proxy(tmp_path, image_server):
    pytest.importorskip("socksio", reason="httpx[socks] not installed")

    proxy = MiniSocks5Server()
    await proxy.start()
    try:
        settings = Settings(
            config_dir=tmp_path,
            output_dir=tmp_path / "out",
            proxy=f"socks5://127.0.0.1:{proxy.port}",
            requests_per_second=100.0,
        )
        fetcher = Fetcher(settings, _StubSessions())
        await fetcher.start()
        try:
            result = await fetcher.fetch_image(f"{image_server}/page.png")
        finally:
            await fetcher.close()

        assert result.content.startswith(b"\x89PNG")
        assert len(result.content) > 1000
        # The request really did traverse the proxy.
        assert proxy.requests, "proxy saw no CONNECT request"
        assert proxy.requests[0][1] == int(image_server.rsplit(":", 1)[1])
    finally:
        await proxy.stop()


async def test_hostname_is_resolved_at_the_proxy(tmp_path, image_server):
    """SOCKS5 must forward the hostname, not a locally-resolved IP.

    This is the whole point when the local network is what's filtering: the
    name must never appear in a local DNS query.
    """
    pytest.importorskip("socksio", reason="httpx[socks] not installed")

    proxy = MiniSocks5Server()
    await proxy.start()
    try:
        port = int(image_server.rsplit(":", 1)[1])
        settings = Settings(
            config_dir=tmp_path,
            proxy=f"socks5://127.0.0.1:{proxy.port}",
            requests_per_second=100.0,
            max_retries=1,
        )
        fetcher = Fetcher(settings, _StubSessions())
        await fetcher.start()
        try:
            await fetcher.fetch_image(f"http://localhost:{port}/page.png")
        finally:
            await fetcher.close()

        # Address type 3 == domain name, forwarded verbatim to the proxy.
        assert 3 in proxy.address_types
        assert proxy.requests[0][0] == "localhost"
    finally:
        await proxy.stop()


# --------------------------------------------- browser vs downloader routing


def test_desync_skips_the_browser_by_default(tmp_path):
    """A fragmented handshake makes Cloudflare re-challenge forever.

    Chromium encrypts the ClientHello and resolves over DoH, so it clears the
    same hostname filter unaided. Sending it through the bypass anyway is what
    turns a solvable check into an endless verify loop.
    """
    from app.config import Settings

    settings = Settings(config_dir=tmp_path, desync_enabled=True)
    settings._runtime_proxy = "socks5://127.0.0.1:8081"

    assert settings.effective_proxy == "socks5://127.0.0.1:8081"  # downloader
    assert settings.browser_proxy is None                          # browser
    assert settings.browser_proxy_config is None


def test_desync_can_include_the_browser_when_asked(tmp_path):
    from app.config import Settings

    settings = Settings(config_dir=tmp_path, desync_enabled=True, desync_browser=True)
    settings._runtime_proxy = "socks5://127.0.0.1:8081"

    assert settings.browser_proxy == "socks5://127.0.0.1:8081"


def test_an_explicit_proxy_always_covers_both(tmp_path):
    """Clearance is IP-bound, so a split exit would void it."""
    from app.config import Settings

    settings = Settings(config_dir=tmp_path, proxy="socks5://10.0.0.2:1080")
    settings._runtime_proxy = "socks5://127.0.0.1:8081"

    assert settings.effective_proxy == "socks5://10.0.0.2:1080"
    assert settings.browser_proxy == "socks5://10.0.0.2:1080"


def test_no_proxy_anywhere_by_default(tmp_path):
    from app.config import Settings

    settings = Settings(config_dir=tmp_path)
    assert settings.effective_proxy is None
    assert settings.browser_proxy is None
