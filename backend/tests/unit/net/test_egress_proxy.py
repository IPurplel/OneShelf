"""Ledger K2: browser egress goes through a Core proxy enforcing the same policy as the HTTP client."""
import asyncio
import base64
import socket

import pytest
from aiohttp import web

from oneshelf.net.egress_proxy import EgressProxy
from oneshelf.net.policy import EgressPolicy


class Hosts:
    def __init__(self, table):
        self.table = table

    async def resolve(self, host, port=0, family=socket.AF_INET):
        if host not in self.table:
            raise OSError("NXDOMAIN")
        ip, real_port = self.table[host]
        return [{"hostname": host, "host": ip, "port": real_port, "family": socket.AF_INET, "proto": 0, "flags": 0}]

    async def close(self):
        pass


async def start_origin():
    seen = []

    async def any_path(request):
        seen.append({"host": request.headers.get("Host"), "path": request.path_qs,
                     "proxy_auth": request.headers.get("Proxy-Authorization")})
        return web.Response(text=f"origin:{request.path_qs}")

    app = web.Application()
    app.add_routes([web.route("*", "/{tail:.*}", any_path)])
    runner = web.AppRunner(app, access_log=None)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", 0)
    await site.start()
    return runner, site._server.sockets[0].getsockname()[1], seen


def auth_header(proxy):
    token = base64.b64encode(f"{proxy.username}:{proxy.password}".encode()).decode()
    return f"Proxy-Authorization: Basic {token}\r\n"


async def raw(proxy, request: bytes) -> bytes:
    reader, writer = await asyncio.open_connection("127.0.0.1", proxy.port)
    writer.write(request)
    await writer.drain()
    data = await asyncio.wait_for(reader.read(65536), 5)
    writer.close()
    return data


def run(coro):
    return asyncio.run(asyncio.wait_for(coro, 20))


def dev_policy(**kw):
    return EgressPolicy(domains=("testsource.example",), cdn_domains=("cdn.testsource.example",), allow_http=True,
                        dev_loopback_exception=True, **kw)


def test_http_absolute_form_is_forwarded_with_host_preserved_and_proxy_auth_stripped():
    async def scenario():
        runner, port, seen = await start_origin()
        proxy = EgressProxy(dev_policy(), resolver_backend=Hosts({"testsource.example": ("127.0.0.1", port)}))
        await proxy.start()
        data = await raw(proxy, (f"GET http://testsource.example/page?x=1 HTTP/1.1\r\nHost: testsource.example\r\n"
                                 f"{auth_header(proxy)}\r\n").encode())
        await proxy.stop()
        await runner.cleanup()
        return data, seen
    data, seen = run(scenario())
    assert b"200" in data.split(b"\r\n")[0] and b"origin:/page?x=1" in data
    assert seen == [{"host": "testsource.example", "path": "/page?x=1", "proxy_auth": None}]


def test_connect_tunnel_to_allowlisted_host():
    async def scenario():
        runner, port, seen = await start_origin()
        proxy = EgressProxy(dev_policy(), resolver_backend=Hosts({"cdn.testsource.example": ("127.0.0.1", port)}))
        await proxy.start()
        reader, writer = await asyncio.open_connection("127.0.0.1", proxy.port)
        writer.write(f"CONNECT cdn.testsource.example:443 HTTP/1.1\r\nHost: cdn.testsource.example:443\r\n{auth_header(proxy)}\r\n".encode())
        await writer.drain()
        established = await asyncio.wait_for(reader.readuntil(b"\r\n\r\n"), 5)
        writer.write(b"GET /img.png HTTP/1.1\r\nHost: cdn.testsource.example\r\nConnection: close\r\n\r\n")
        await writer.drain()
        body = await asyncio.wait_for(reader.read(65536), 5)
        writer.close()
        await proxy.stop()
        await runner.cleanup()
        return established, body, seen
    established, body, seen = run(scenario())
    assert b" 200 " in established and b"origin:/img.png" in body and len(seen) == 1


@pytest.mark.parametrize("request_line", [
    "GET http://unapproved.example/steal HTTP/1.1",
    "GET http://127.0.0.1:{port}/secret HTTP/1.1",
    "GET http://169.254.169.254/latest/meta-data HTTP/1.1",
    "CONNECT unapproved.example:443 HTTP/1.1",
    "CONNECT 127.0.0.1:{port} HTTP/1.1",
    "CONNECT [::1]:443 HTTP/1.1",
    "GET file:///etc/passwd HTTP/1.1",
])
def test_policy_violations_are_refused_without_reaching_the_origin(request_line):
    async def scenario():
        runner, port, seen = await start_origin()
        proxy = EgressProxy(dev_policy(), resolver_backend=Hosts({"unapproved.example": ("127.0.0.1", port)}))
        await proxy.start()
        line = request_line.format(port=port)
        data = await raw(proxy, f"{line}\r\nHost: x\r\n{auth_header(proxy)}\r\n".encode())
        await proxy.stop()
        await runner.cleanup()
        return data, seen, proxy.blocked
    data, seen, blocked = run(scenario())
    assert data.startswith(b"HTTP/1.1 403") and seen == [] and blocked


def test_allowlisted_name_resolving_to_private_address_is_refused_without_dev_exception():
    async def scenario():
        runner, port, seen = await start_origin()
        policy = EgressPolicy(domains=("testsource.example",), allow_http=True, allowed_ports=(port,))
        proxy = EgressProxy(policy, resolver_backend=Hosts({"testsource.example": ("127.0.0.1", port)}))
        await proxy.start()
        data = await raw(proxy, f"GET http://testsource.example:{port}/x HTTP/1.1\r\nHost: t\r\n{auth_header(proxy)}\r\n".encode())
        await proxy.stop()
        await runner.cleanup()
        return data, seen
    data, seen = run(scenario())
    assert data.startswith(b"HTTP/1.1 403") and seen == []


def test_missing_or_wrong_proxy_credentials_are_rejected():
    async def scenario():
        runner, port, seen = await start_origin()
        proxy = EgressProxy(dev_policy(), resolver_backend=Hosts({"testsource.example": ("127.0.0.1", port)}))
        await proxy.start()
        missing = await raw(proxy, b"GET http://testsource.example/ HTTP/1.1\r\nHost: t\r\n\r\n")
        wrong = await raw(proxy, b"GET http://testsource.example/ HTTP/1.1\r\nHost: t\r\nProxy-Authorization: Basic Zm9vOmJhcg==\r\n\r\n")
        await proxy.stop()
        await runner.cleanup()
        return missing, wrong, seen
    missing, wrong, seen = run(scenario())
    assert missing.startswith(b"HTTP/1.1 407") and wrong.startswith(b"HTTP/1.1 407") and seen == []


def test_pipelined_second_request_is_not_forwarded_unchecked():
    async def scenario():
        runner, port, seen = await start_origin()
        proxy = EgressProxy(dev_policy(), resolver_backend=Hosts({"testsource.example": ("127.0.0.1", port)}))
        await proxy.start()
        first = f"GET http://testsource.example/one HTTP/1.1\r\nHost: testsource.example\r\n{auth_header(proxy)}\r\n"
        smuggled = "GET http://unapproved.example/two HTTP/1.1\r\nHost: unapproved.example\r\n\r\n"
        await raw(proxy, (first + smuggled).encode())
        await asyncio.sleep(0.1)
        await proxy.stop()
        await runner.cleanup()
        return seen
    seen = run(scenario())
    assert [s["path"] for s in seen] == ["/one"]


def test_oversized_request_head_is_rejected():
    async def scenario():
        runner, port, seen = await start_origin()
        proxy = EgressProxy(dev_policy(), resolver_backend=Hosts({"testsource.example": ("127.0.0.1", port)}))
        await proxy.start()
        data = await raw(proxy, b"GET http://testsource.example/ HTTP/1.1\r\nX-Big: " + b"a" * 100_000 + b"\r\n\r\n")
        await proxy.stop()
        await runner.cleanup()
        return data, seen
    data, seen = run(scenario())
    assert data.startswith(b"HTTP/1.1 431") and seen == []
