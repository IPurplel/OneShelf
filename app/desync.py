"""Built-in DPI-bypass proxy.

Some networks block sites by reading the hostname out of the plaintext TLS
ClientHello and injecting a TCP reset. The connection dies before any HTTP
response exists, so no amount of browser realism helps.

Such filters are passive: they inspect packets in flight rather than proxying
them, and most never reassemble a TCP stream. Splitting the ClientHello across
two segments therefore leaves them nothing to match, and the handshake completes
normally.

Measured against a live filter of this kind, the decisive factor was *where* the
split falls. Splitting inside the hostname still failed; making the very first
segment too small to parse as a TLS record succeeded every time. The filter
appears to parse a record header before deciding whether to track a flow, and
abandons flows whose opening bytes it cannot interpret.

This module implements a local SOCKS5 proxy that applies that split. It exists
as a proxy rather than as a transport wrapper because Chromium cannot be made to
fragment its own handshake, and the browser and the image downloader must egress
identically - a Cloudflare clearance cookie is bound to the IP that earned it.
"""

from __future__ import annotations

import asyncio
import logging
import socket
import struct

log = logging.getLogger(__name__)

SOCKS_VERSION = 5
CMD_CONNECT = 1

ATYP_IPV4 = 1
ATYP_DOMAIN = 3
ATYP_IPV6 = 4

# SOCKS5 reply codes
REP_SUCCESS = 0
REP_GENERAL_FAILURE = 1
REP_HOST_UNREACHABLE = 4
REP_CMD_NOT_SUPPORTED = 7

BUFFER = 65536


class DesyncProxy:
    """Local SOCKS5 proxy that fragments the first client payload.

    Only the opening write of each connection is split — that is the ClientHello
    — after which bytes are relayed untouched. The cost is one extra local hop
    and a single short delay per connection.
    """

    def __init__(
        self,
        host: str = "127.0.0.1",
        port: int = 0,
        split_at: int = 1,
        delay: float = 0.05,
    ) -> None:
        self.host = host
        self.port = port
        self.split_at = max(1, split_at)
        self.delay = max(0.0, delay)

        self._server: asyncio.AbstractServer | None = None
        self._clients: set[asyncio.Task] = set()
        """In-flight client handlers, so shutdown can cancel them.

        asyncio.start_server spawns one task per connection and holds no
        reference we can reach; without tracking them, tearing the proxy down
        mid-transfer logs "Task was destroyed but it is pending!" at ERROR
        level, which buries real errors in noise.
        """
        self.connections = 0
        self.failures = 0

    # ------------------------------------------------------------- lifecycle

    async def start(self) -> str:
        """Start listening. Returns the proxy URL to hand to clients."""
        self._server = await asyncio.start_server(
            self._handle_client, self.host, self.port
        )
        self.port = self._server.sockets[0].getsockname()[1]
        log.info(
            "DPI-bypass proxy listening on %s (split at %d byte(s), %.0f ms delay)",
            self.url, self.split_at, self.delay * 1000,
        )
        return self.url

    async def stop(self) -> None:
        if self._server is None:
            return

        # Stop accepting first, then cancel what is still in flight, and only
        # then wait: wait_closed() blocks on live handlers, so cancelling after
        # it would be the wrong order.
        self._server.close()

        for task in list(self._clients):
            task.cancel()
        if self._clients:
            await asyncio.gather(*self._clients, return_exceptions=True)
            self._clients.clear()

        try:
            await self._server.wait_closed()
        except Exception:  # pragma: no cover - shutdown races
            log.debug("Error closing desync proxy", exc_info=True)
        self._server = None

    @property
    def url(self) -> str:
        return f"socks5://{self.host}:{self.port}"

    @property
    def running(self) -> bool:
        return self._server is not None

    def status(self) -> dict:
        return {
            "running": self.running,
            "url": self.url if self.running else None,
            "split_at": self.split_at,
            "delay": self.delay,
            "connections": self.connections,
            "failures": self.failures,
        }

    # ---------------------------------------------------------- socks5 setup

    async def _handle_client(
        self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> None:
        task = asyncio.current_task()
        if task is not None:
            self._clients.add(task)
            task.add_done_callback(self._clients.discard)

        remote_writer: asyncio.StreamWriter | None = None
        try:
            if not await self._negotiate(reader, writer):
                return

            target = await self._read_request(reader, writer)
            if target is None:
                return
            host, port = target

            try:
                remote_reader, remote_writer = await asyncio.wait_for(
                    asyncio.open_connection(host, port), timeout=20
                )
            except Exception as exc:
                self.failures += 1
                log.debug("Upstream connect failed for %s:%s - %s", host, port, exc)
                await self._reply(writer, REP_HOST_UNREACHABLE)
                return

            await self._reply(writer, REP_SUCCESS)
            self.connections += 1

            # Disable Nagle so the fragments leave as separate segments rather
            # than being coalesced back into one - coalescing would undo the
            # entire point of splitting.
            _set_nodelay(remote_writer)

            await asyncio.gather(
                self._pump_first_split(reader, remote_writer),
                self._pump(remote_reader, writer),
                return_exceptions=True,
            )
        except (asyncio.IncompleteReadError, ConnectionError):
            pass
        except Exception:  # pragma: no cover - defensive
            log.debug("Unhandled error in desync proxy connection", exc_info=True)
        finally:
            _close(writer)
            if remote_writer is not None:
                _close(remote_writer)

    async def _negotiate(
        self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> bool:
        """Greeting exchange. No authentication - it binds to localhost only."""
        version, count = await reader.readexactly(2)
        await reader.readexactly(count)
        if version != SOCKS_VERSION:
            writer.write(b"\xff")
            await writer.drain()
            return False
        writer.write(bytes([SOCKS_VERSION, 0]))
        await writer.drain()
        return True

    async def _read_request(
        self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> tuple[str, int] | None:
        version, command, _, address_type = await reader.readexactly(4)
        if version != SOCKS_VERSION:
            return None
        if command != CMD_CONNECT:
            await self._reply(writer, REP_CMD_NOT_SUPPORTED)
            return None

        if address_type == ATYP_IPV4:
            host = socket.inet_ntoa(await reader.readexactly(4))
        elif address_type == ATYP_DOMAIN:
            length = (await reader.readexactly(1))[0]
            # Hostname forwarded verbatim: resolution happens here rather than
            # in the client, keeping the name out of any local DNS query.
            #
            # Decoded as plain ASCII, not via the "idna" codec: SOCKS5 carries
            # the name already punycode-encoded, and Python's idna codec rejects
            # every error handler except "strict" - passing one raises
            # unconditionally, which would break every hostname request.
            host = (await reader.readexactly(length)).decode("ascii", "replace")
        elif address_type == ATYP_IPV6:
            host = socket.inet_ntop(socket.AF_INET6, await reader.readexactly(16))
        else:
            await self._reply(writer, REP_GENERAL_FAILURE)
            return None

        port = struct.unpack("!H", await reader.readexactly(2))[0]
        return host, port

    async def _reply(self, writer: asyncio.StreamWriter, code: int) -> None:
        # Bound address is ignored by every client that matters; zeros are fine.
        writer.write(bytes([SOCKS_VERSION, code, 0, ATYP_IPV4]) + b"\x00" * 6)
        await writer.drain()

    # ------------------------------------------------------------- relaying

    async def _pump_first_split(
        self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> None:
        """Relay client -> upstream, splitting only the opening payload."""
        first = await reader.read(BUFFER)
        if not first:
            return

        if len(first) > self.split_at:
            head, tail = first[: self.split_at], first[self.split_at :]
            writer.write(head)
            await writer.drain()
            if self.delay:
                # Gives the filter a chance to evaluate - and discard - a first
                # segment it cannot parse, before the rest arrives.
                await asyncio.sleep(self.delay)
            writer.write(tail)
            await writer.drain()
        else:
            writer.write(first)
            await writer.drain()

        await self._pump(reader, writer)

    @staticmethod
    async def _pump(
        reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> None:
        try:
            while True:
                chunk = await reader.read(BUFFER)
                if not chunk:
                    break
                writer.write(chunk)
                await writer.drain()
        except (ConnectionError, asyncio.CancelledError):
            pass
        finally:
            try:
                if writer.can_write_eof():
                    writer.write_eof()
            except Exception:
                pass


def _set_nodelay(writer: asyncio.StreamWriter) -> None:
    try:
        sock = writer.get_extra_info("socket")
        if sock is not None:
            sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
    except Exception:  # pragma: no cover - platform dependent
        log.debug("Could not set TCP_NODELAY", exc_info=True)


def _close(writer: asyncio.StreamWriter) -> None:
    try:
        writer.close()
    except Exception:  # pragma: no cover
        pass
