"""Browser retrieval through the Core egress proxy (K2), isolation, and Use My Session login (Master §11, §13)."""
import asyncio
import shutil
from contextlib import asynccontextmanager
from pathlib import Path

import pytest
import yaml
from aiohttp import web
from playwright.async_api import async_playwright

from oneshelf.net.browser import BrowserManager
from oneshelf.net.governor import TrafficGovernor
from oneshelf.net.policy import EgressPolicy
from oneshelf.plugins.manager import PluginManager
from oneshelf.plugins.package import load_package
from oneshelf.sessions.login import LoginController
from oneshelf.sessions.manager import SessionManager
from oneshelf.sessions.store import SecretsStore, load_or_create_key
from oneshelf.sources.fetcher import DevHostsResolver
from oneshelf.sources.service import SourceService
from testsource import build as ts_build
from testsource.server import HOST, TestSourceServer

TS = "oneshelf.test-source"
pytestmark = pytest.mark.browser


def run(coro, timeout=90):
    return asyncio.run(asyncio.wait_for(coro, timeout))


async def secret_server():
    hits = []

    async def secret(request):
        hits.append(request.path_qs)
        return web.Response(text="INTERNAL SECRET", headers={"Access-Control-Allow-Origin": "*"})

    app = web.Application()
    app.add_routes([web.get("/{tail:.*}", secret)])
    runner = web.AppRunner(app, access_log=None)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", 0)
    await site.start()
    return runner, site._server.sockets[0].getsockname()[1], hits


def test_control_unprotected_browser_can_reach_local_services():
    """Proves the probe below would detect a leak if the protections were missing."""
    async def scenario():
        runner, port, hits = await secret_server()
        async with async_playwright() as p:
            browser = await p.chromium.launch()
            page = await browser.new_page()
            await page.goto(f"http://127.0.0.1:{port}/control")
            await browser.close()
        await runner.cleanup()
        return hits
    assert run(scenario()) == ["/control"]


def test_browser_context_cannot_reach_loopback_private_or_unapproved_targets():
    async def scenario():
        runner, secret_port, hits = await secret_server()
        async with TestSourceServer() as server:
            hosts = server.hosts() | {"unapproved.example": ("127.0.0.1", secret_port)}
            policy = EgressPolicy(domains=("testsource.example",), cdn_domains=("cdn.testsource.example",), allow_http=True,
                                  dev_loopback_exception=True)
            async with BrowserManager() as browser:
                async with browser.context(policy, resolver_backend=DevHostsResolver(hosts)) as handle:
                    page = await handle.context.new_page()
                    targets = [f"http://127.0.0.1:{secret_port}/fetch", f"http://localhost:{secret_port}/localhost",
                               f"http://[::1]:{secret_port}/v6", "http://169.254.169.254/latest/meta-data",
                               "http://unapproved.example/rebound", f"http://{HOST}/redirect-to?url=http://127.0.0.1:{secret_port}/redirected"]
                    query = "&".join(f"t={t}" for t in targets)
                    await page.goto(f"http://{HOST}/probe?{query}", wait_until="load")
                    await page.wait_for_timeout(1500)
                    probe_text = await page.inner_text("#done")
                    for direct in (f"http://127.0.0.1:{secret_port}/direct", f"http://{HOST}/redirect-to?url=http://unapproved.example/nav"):
                        try:
                            await page.goto(direct, timeout=5000)
                        except Exception:
                            pass
                    blocked = list(handle.proxy.blocked)
        await runner.cleanup()
        return probe_text, hits, blocked
    probe_text, hits, blocked = run(scenario())
    assert probe_text == "probe"  # the allowlisted page itself loaded through the proxy
    assert hits == []  # nothing reached the local "internal" service
    assert blocked


def test_browser_recipe_extracts_javascript_rendered_results(db, tmp_path):
    package_dir = tmp_path / "ts-browser"
    shutil.copytree(ts_build.PACKAGE_DIR, package_dir)
    manifest = yaml.safe_load((package_dir / "manifest.yaml").read_text())
    manifest["browser"] = {"capabilities": ["search"]}
    (package_dir / "manifest.yaml").write_text(yaml.safe_dump(manifest))
    search = yaml.safe_load((package_dir / "recipes" / "search.yaml").read_text())
    search["request"]["url"] = "{base_url}/js-search?q={query}&page={page}"
    search["request"]["fetch"] = "browser"
    search["pagination"] = {"mode": "none", "complete_when": "single_response"}
    (package_dir / "recipes" / "search.yaml").write_text(yaml.safe_dump(search))
    tests = yaml.safe_load((package_dir / "tests" / "tests.yaml").read_text())
    tests["cases"][0]["fixtures"][0]["url"] = "http://testsource.example/js-search?q=chronicle&page=1"
    tests["cases"][0]["fixtures"][0]["file"] = "fixtures/search.html"
    (package_dir / "tests" / "tests.yaml").write_text(yaml.safe_dump(tests))
    original = ts_build.PACKAGE_DIR
    ts_build.PACKAGE_DIR = package_dir
    try:
        path = ts_build.build_package(tmp_path / "ts-browser.osp")
    finally:
        ts_build.PACKAGE_DIR = original
    manager = PluginManager(db, store_dir=tmp_path / "plugins")
    assert run(manager.install_file(path, approved_permissions=load_package(path).permissions)).state == "active"

    async def scenario():
        async with TestSourceServer() as server, BrowserManager() as browser:
            async with SourceService(db, manager, TrafficGovernor(), None, dev_test_source=True, dev_hosts=server.hosts(),
                                     browser=browser) as service:
                return await service.run(TS, "search", {"query": "chronicle", "page": 1})
    result = run(scenario())
    assert result.complete and [i.listing_key for i in result.items] == ["irregular"]


def test_browser_contexts_are_isolated():
    async def scenario():
        async with TestSourceServer() as server:
            server.scenario.valid_sessions.add("tok")
            policy = EgressPolicy(domains=("testsource.example",), allow_http=True, dev_loopback_exception=True)
            resolver = DevHostsResolver(server.hosts())
            state = {"cookies": [{"name": "ts_session", "value": "tok", "domain": HOST, "path": "/", "expires": -1,
                                  "httpOnly": True, "secure": False, "sameSite": "Lax"}], "origins": []}
            async with BrowserManager() as browser:
                async with browser.context(policy, resolver_backend=resolver, storage_state=state) as a, \
                        browser.context(policy, resolver_backend=resolver) as b:
                    pa, pb = await a.context.new_page(), await b.context.new_page()
                    await pa.goto(f"http://{HOST}/account")
                    await pb.goto(f"http://{HOST}/account")
                    return await pa.content(), await pb.content()
    logged_in_page, anonymous_page = run(scenario())
    assert "logout" in logged_in_page and "logout" not in anonymous_page


@asynccontextmanager
async def login_env(db, tmp_path, server):
    manager = PluginManager(db, store_dir=tmp_path / "plugins")
    path = ts_build.build_package(tmp_path / "ts.osp")
    await manager.install_file(path, approved_permissions=load_package(path).permissions)
    store = SecretsStore(tmp_path / "app" / "secrets.db", load_or_create_key(tmp_path / "keys" / "session.key"))
    sessions = SessionManager(db, store, events=None)
    governor = TrafficGovernor()
    async with BrowserManager() as browser:
        async with SourceService(db, manager, governor, sessions, dev_test_source=True, dev_hosts=server.hosts(),
                                 browser=browser) as service:
            yield LoginController(service, browser, sessions, governor), service, sessions, store
    store.close()


async def fill_login(login, username, password):
    page = login.page  # tests locate fields; the real UI sends coordinates from the screencast
    for selector, text in (("input[name=username]", username), ("input[name=password]", password)):
        box = await page.locator(selector).bounding_box()
        await login.click(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)
        await login.type_text(text)
    await login.press("Enter")
    try:
        await page.wait_for_url(lambda url: not url.endswith("/login"), timeout=5000)
    except Exception:
        pass  # failed logins stay on the form


def test_use_my_session_login_flow_captures_encrypted_scoped_state(db, tmp_path):
    async def scenario():
        async with TestSourceServer() as server:
            async with login_env(db, tmp_path, server) as (controller, service, sessions, store):
                login = await controller.start(TS)
                frame = await login.frame(timeout=10)
                await fill_login(login, "reader", "correct horse")
                outcome = await login.complete()
                private = await service.run(TS, "catalog", {"listing_key": "private"})
                state = store.get(TS)
                return frame, outcome, sessions.state(TS), private, state, (tmp_path / "app" / "secrets.db").read_bytes()
    frame, outcome, state_name, private, state, raw = run(scenario())
    assert frame[:2] == b"\xff\xd8"  # JPEG screencast frame for the remote login UI
    assert outcome == "connected" and state_name == "connected" and private.complete
    assert {c["domain"].lstrip(".") for c in state.storage_state["cookies"]} == {HOST}
    assert state.session_storage == {f"http://{HOST}": {"ts_tab": "library"}}
    assert any(o["origin"] == f"http://{HOST}" for o in state.storage_state["origins"])
    assert b"correct horse" not in raw and b"ts_tab" not in raw


def test_failed_login_does_not_replace_existing_session_and_cancel_discards(db, tmp_path):
    async def scenario():
        async with TestSourceServer() as server:
            async with login_env(db, tmp_path, server) as (controller, service, sessions, store):
                login = await controller.start(TS)
                await fill_login(login, "reader", "wrong password")
                outcome = await login.complete()
                still_open = login.status
                await login.cancel()
                return outcome, still_open, login.status, sessions.state(TS), store.get(TS)
    outcome, still_open, final_status, state_name, stored = run(scenario())
    assert outcome == "not_logged_in" and still_open == "open"
    assert final_status == "cancelled" and state_name == "not_connected" and stored is None
