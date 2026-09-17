"""Master §11 / INV-15: allowlists + redirect and DNS revalidation + private-target blocking (HTTP path)."""
import asyncio
import socket

import pytest
from aiohttp import web

from oneshelf.net.http import BlockedDestination, DisallowedTarget, HttpClient, ResponseTooLarge, TooManyRedirects
from oneshelf.net.policy import EgressPolicy, PolicyConfigError, is_public_address, policy_for_plugin

PUBLIC = "93.184.216.34"


def h(fn):
    """Wrap a sync (request -> response) callable as an async aiohttp handler."""
    async def handler(request):
        return fn(request)
    return handler


def redirect(fn):
    async def handler(request):
        raise web.HTTPFound(fn(request))
    return handler


class FakeDNS:
    """Injectable resolver backend: hostname -> list of addresses; records every lookup."""

    def __init__(self, table):
        self.table = table
        self.lookups = []

    async def resolve(self, host, port=0, family=socket.AF_UNSPEC):
        self.lookups.append(host)
        if host not in self.table:
            raise OSError(f"NXDOMAIN {host}")
        return [{"hostname": host, "host": ip, "port": port, "family": socket.AF_INET6 if ":" in ip else socket.AF_INET,
                 "proto": 0, "flags": socket.AI_NUMERICHOST} for ip in self.table[host]]

    async def close(self):
        pass


def run(coro):
    return asyncio.run(coro)


@pytest.mark.parametrize("ip,public", [
    (PUBLIC, True), ("2606:4700:4700::1111", True),
    ("127.0.0.1", False), ("10.1.2.3", False), ("172.16.0.1", False), ("192.168.1.1", False),
    ("169.254.169.254", False), ("100.64.0.1", False), ("0.0.0.0", False), ("224.0.0.1", False),
    ("192.0.2.1", False), ("::1", False), ("fe80::1", False), ("fd00::1", False),
    ("::ffff:127.0.0.1", False), ("::ffff:10.0.0.1", False), ("64:ff9b::a00:1", False), ("2002:c0a8:0101::1", False),
    ("255.255.255.255", False),
])
def test_address_classification(ip, public):
    assert is_public_address(ip) is public


def policy(**kw):
    return EgressPolicy(domains=("books.example",), cdn_domains=("*.cdn.books.example",), **kw)


@pytest.mark.parametrize("url", [
    "ftp://books.example/x", "http://books.example/x", "https://user:pw@books.example/x", "https://evil.example/x",
    "https://books.example.evil.example/x", "https://127.0.0.1/x", "https://[::1]/x", "https://2130706433/x",
    "https://books.example:8443/x", "https://cdn.books.example/x", "javascript:alert(1)",
])
def test_url_checks_reject(url):
    with pytest.raises(DisallowedTarget):
        policy().check_url(url)


def test_url_checks_accept_allowlisted():
    assert policy().check_url("https://books.example/search?q=1").host == "books.example"
    assert policy().check_url("https://img1.cdn.books.example/p.jpg").host == "img1.cdn.books.example"
    assert policy(allow_http=True).check_url("http://books.example/x").port == 80


def test_dev_exception_requires_flag_and_test_source_identity():
    other = policy_for_plugin("example.books", domains=["books.example"], cdn_domains=[], allow_http=False,
                              dev_test_source_enabled=True)
    assert other.dev_loopback_exception is False  # the exception is never granted to other plugins
    with pytest.raises(PolicyConfigError):
        EgressPolicy(domains=(), dev_loopback_exception=False)
    p = policy_for_plugin("oneshelf.test-source", domains=["testsource.example"], cdn_domains=[], allow_http=True,
                          dev_test_source_enabled=False)
    assert p.dev_loopback_exception is False
    p = policy_for_plugin("oneshelf.test-source", domains=["testsource.example"], cdn_domains=[], allow_http=True,
                          dev_test_source_enabled=True)
    assert p.dev_loopback_exception is True


@pytest.fixture
def server_factory():
    """Start aiohttp apps on 127.0.0.1 inside the running loop; returns (base_port)."""
    async def start(routes):
        app = web.Application()
        app.add_routes(routes)
        runner = web.AppRunner(app)
        await runner.setup()
        site = web.TCPSite(runner, "127.0.0.1", 0)
        await site.start()
        port = site._server.sockets[0].getsockname()[1]
        return runner, port
    return start


def client_for(pol, dns):
    return HttpClient(pol, resolver_backend=dns)


def test_allowlisted_domain_resolving_to_loopback_is_blocked(server_factory):
    async def scenario():
        hits = []
        runner, port = await server_factory([web.get("/x", h(lambda r: hits.append(1) or web.Response(text="secret")))])
        dns = FakeDNS({"books.example": ["127.0.0.1"]})
        async with client_for(policy(allow_http=True, allowed_ports=(port,)), dns) as c:
            with pytest.raises(BlockedDestination):
                await c.fetch(f"http://books.example:{port}/x")
        await runner.cleanup()
        return hits, dns.lookups

    hits, lookups = run(scenario())
    assert hits == [] and lookups == ["books.example"]


def test_mixed_public_and_private_answers_are_rejected_entirely():
    async def scenario():
        dns = FakeDNS({"books.example": [PUBLIC, "10.0.0.7"]})
        async with client_for(policy(), dns) as c:
            with pytest.raises(BlockedDestination):
                await c.fetch("https://books.example/x")
    run(scenario())


def test_dev_exception_allows_loopback_only(server_factory):
    async def scenario():
        runner, port = await server_factory([web.get("/ok", h(lambda r: web.Response(text="fine")))])
        pol = EgressPolicy(domains=("testsource.example",), allow_http=True, dev_loopback_exception=True)
        async with client_for(pol, FakeDNS({"testsource.example": ["127.0.0.1"]})) as c:
            result = await c.fetch(f"http://testsource.example:{port}/ok")
        async with client_for(pol, FakeDNS({"testsource.example": ["192.168.1.10"]})) as c:
            with pytest.raises(BlockedDestination):
                await c.fetch(f"http://testsource.example:{port}/ok")
        await runner.cleanup()
        return result
    result = run(scenario())
    assert result.status == 200 and result.body == b"fine"


def test_redirects_are_revalidated_each_hop(server_factory):
    async def scenario():
        visited = []
        routes = [
            web.get("/to-evil", redirect(lambda r: "http://evil.example/steal")),
            web.get("/to-metadata", redirect(lambda r: "http://169.254.169.254/latest/meta-data")),
            web.get("/to-private-alias", redirect(lambda r: f"http://inner.testsource.example:{r.url.port}/x")),
            web.get("/loop", redirect(lambda r: "/loop")),
            web.get("/x", h(lambda r: visited.append("x") or web.Response(text="internal"))),
        ]
        runner, port = await server_factory(routes)
        pol = EgressPolicy(domains=("testsource.example", "*.testsource.example"), allow_http=True, dev_loopback_exception=True)
        dns = FakeDNS({"testsource.example": ["127.0.0.1"], "inner.testsource.example": ["10.0.0.5"]})
        async with client_for(pol, dns) as c:
            base = f"http://testsource.example:{port}"
            with pytest.raises(DisallowedTarget):
                await c.fetch(base + "/to-evil")
            with pytest.raises(DisallowedTarget):
                await c.fetch(base + "/to-metadata")
            with pytest.raises(BlockedDestination):
                await c.fetch(base + "/to-private-alias")
            with pytest.raises(TooManyRedirects):
                await c.fetch(base + "/loop")
        await runner.cleanup()
        return visited, dns.lookups
    visited, lookups = run(scenario())
    assert visited == []
    assert "evil.example" not in lookups  # rejected before any DNS lookup


def test_response_size_is_bounded(server_factory):
    async def scenario():
        runner, port = await server_factory([web.get("/big", h(lambda r: web.Response(body=b"x" * 2_000_000)))])
        pol = EgressPolicy(domains=("testsource.example",), allow_http=True, dev_loopback_exception=True)
        async with client_for(pol, FakeDNS({"testsource.example": ["127.0.0.1"]})) as c:
            with pytest.raises(ResponseTooLarge):
                await c.fetch(f"http://testsource.example:{port}/big", max_bytes=1_000_000)
        await runner.cleanup()
    run(scenario())


def test_environment_proxy_variables_are_ignored(server_factory, monkeypatch):
    monkeypatch.setenv("HTTP_PROXY", "http://127.0.0.1:9")
    monkeypatch.setenv("HTTPS_PROXY", "http://127.0.0.1:9")
    monkeypatch.setenv("ALL_PROXY", "http://127.0.0.1:9")

    async def scenario():
        runner, port = await server_factory([web.get("/ok", h(lambda r: web.Response(text="direct")))])
        pol = EgressPolicy(domains=("testsource.example",), allow_http=True, dev_loopback_exception=True)
        async with client_for(pol, FakeDNS({"testsource.example": ["127.0.0.1"]})) as c:
            result = await c.fetch(f"http://testsource.example:{port}/ok")
        await runner.cleanup()
        return result
    assert run(scenario()).body == b"direct"


def test_client_never_stores_cookies_from_responses(server_factory):
    async def scenario():
        seen = []

        async def set_cookie(request):
            resp = web.Response(text="set")
            resp.set_cookie("sid", "abc")
            return resp

        async def echo(request):
            seen.append(request.headers.get("Cookie"))
            return web.Response(text="echo")

        runner, port = await server_factory([web.get("/set", set_cookie), web.get("/echo", echo)])
        pol = EgressPolicy(domains=("testsource.example",), allow_http=True, dev_loopback_exception=True)
        async with client_for(pol, FakeDNS({"testsource.example": ["127.0.0.1"]})) as c:
            first = await c.fetch(f"http://testsource.example:{port}/set")
            await c.fetch(f"http://testsource.example:{port}/echo")
        await runner.cleanup()
        return seen, first
    seen, first = run(scenario())
    assert seen == [None]
    assert "set-cookie" in {k.lower() for k in first.headers}  # visible to Core session capture, not auto-stored
