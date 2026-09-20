"""End-to-end C3 pipeline against the controlled OneShelf Test Source (Master §9–15, §21, §41.5)."""
import asyncio
import time
from contextlib import asynccontextmanager

import aiohttp
import pytest

from oneshelf.net.governor import Priority, TrafficGovernor
from oneshelf.net.policy import DisallowedTarget
from oneshelf.plugins.manager import PluginManager, PluginUnavailable
from oneshelf.plugins.package import load_package
from oneshelf.plugins.runtime import AuthRequired, RateLimited
from oneshelf.sessions.manager import SessionManager
from oneshelf.sessions.store import SecretsStore, SessionState, load_or_create_key
from oneshelf.sources.fetcher import DevHostsResolver
from oneshelf.sources.health import recent_signals
from oneshelf.sources.service import SourceService
from testsource.build import build_package
from testsource.server import CDN_HOST, HOST, SESSION_COOKIE, TestSourceServer

TS = "oneshelf.test-source"


@pytest.fixture
def installed(db, tmp_path):
    manager = PluginManager(db, store_dir=tmp_path / "app" / "plugins")
    path = build_package(tmp_path / "testsource.osp")
    outcome = asyncio.run(manager.install_file(path, approved_permissions=load_package(path).permissions))
    assert outcome.state == "active" and outcome.auth_available
    return manager


@asynccontextmanager
async def environment(db, tmp_path, manager, *, dev=True, hostile_dns=False):
    store = SecretsStore(tmp_path / "app" / "secrets.db", load_or_create_key(tmp_path / "keys" / "session.key"))
    sessions = SessionManager(db, store, events=None)
    governor = TrafficGovernor()
    async with TestSourceServer() as server:
        resolver = DevHostsResolver(server.hosts()) if hostile_dns else None  # DNS pointing at loopback
        async with SourceService(db, manager, governor, sessions, dev_test_source=dev, dev_hosts=server.hosts(),
                                 resolver_backend=resolver) as service:
            yield service, server, sessions, governor
    store.close()


async def control(server, **changes):
    async with aiohttp.ClientSession() as s:
        async with s.post(f"http://127.0.0.1:{server.port}/__control", json=changes) as r:
            assert r.status == 200


async def login(server) -> SessionState:
    async with aiohttp.ClientSession() as s:
        async with s.post(f"http://127.0.0.1:{server.port}/login", data={"username": "reader", "password": "correct horse"},
                          allow_redirects=False) as r:
            token = r.cookies[SESSION_COOKIE].value
    return SessionState(storage_state={"cookies": [{"name": SESSION_COOKIE, "value": token, "domain": HOST, "path": "/",
                                                    "secure": False, "httpOnly": True, "expires": -1, "sameSite": "Lax"}],
                                       "origins": []})


def run(coro):
    return asyncio.run(asyncio.wait_for(coro, timeout=30))


def test_search_including_arabic(db, tmp_path, installed):
    async def scenario():
        async with environment(db, tmp_path, installed) as (service, *_):
            english = await service.run(TS, "search", {"query": "chronicle"})
            arabic = await service.run(TS, "search", {"query": "القمر"})
            return english, arabic
    english, arabic = run(scenario())
    assert english.complete and english.items[0].listing_key == "irregular"
    assert english.items[0].cover_url == f"http://{CDN_HOST}/covers/irregular.png"
    assert arabic.items[0].title == "حكاية القمر" and arabic.items[0].language == "ar"


def test_irregular_catalog_preserves_source_order_types_and_numbers(db, tmp_path, installed):
    async def scenario():
        async with environment(db, tmp_path, installed) as (service, *_):
            return await service.run(TS, "catalog", {"listing_key": "irregular"})
    result = run(scenario())
    assert result.complete
    assert [u.unit_key for u in result.units] == ["irr-prologue", "irr-1", "irr-2", "irr-special", "irr-3-5", "irr-3",
                                                   "irr-10a", "irr-10b", "irr-extra"]
    assert [u.number for u in result.units][4:8] == ["3.5", "3", "10", "10"]
    assert [u.unit_type for u in result.units][:4] == ["prologue", "chapter", "chapter", "special"]


def test_large_catalog_and_collapse_are_both_reported_with_evidence(db, tmp_path, installed):
    async def scenario():
        async with environment(db, tmp_path, installed) as (service, server, *_):
            full = await service.run(TS, "catalog", {"listing_key": "big"})
            await control(server, big_collapsed=True)
            collapsed = await service.run(TS, "catalog", {"listing_key": "big"})
            return full, collapsed
    full, collapsed = run(scenario())
    assert len(full.units) == 300 and full.complete and full.evidence.pages == 6
    assert len(collapsed.units) == 7 and collapsed.complete  # suspicion is decided by catalog trust (C4)


@pytest.mark.parametrize("mode,reason", [("fail_page_3", "page_failed"), ("repeat_page_2", "repeated_page"),
                                         ("short", "total_not_reached")])
def test_incomplete_pagination_is_never_complete(db, tmp_path, installed, mode, reason):
    async def scenario():
        async with environment(db, tmp_path, installed) as (service, server, *_):
            await control(server, paged_mode=mode)
            return await service.run(TS, "catalog", {"listing_key": "paged"})
    result = run(scenario())
    assert not result.complete and result.evidence.stop_reason == reason


def test_malformed_metadata_stays_unknown_and_invalidates_catalog(db, tmp_path, installed):
    async def scenario():
        async with environment(db, tmp_path, installed) as (service, *_):
            work = await service.run(TS, "work", {"listing_key": "malformed"})
            catalog = await service.run(TS, "catalog", {"listing_key": "malformed"})
            return work, catalog
    work, catalog = run(scenario())
    assert work.title == "Weird   Metadata" and work.content_type is None and work.language is None
    assert not catalog.complete and catalog.units[0].unit_type == "unknown" and catalog.units[0].raw_title is None


def test_use_my_session_flow_with_scoped_cookies(db, tmp_path, installed):
    async def scenario():
        async with environment(db, tmp_path, installed) as (service, server, sessions, _):
            with pytest.raises(AuthRequired):
                await service.run(TS, "catalog", {"listing_key": "private"})
            assert sessions.state(TS) == "not_connected"
            assert (await service.run(TS, "check_session", {})).logged_in is False

            sessions.connect(TS, await login(server))
            private = await service.run(TS, "catalog", {"listing_key": "private"})
            assert (await service.run(TS, "check_session", {})).logged_in is True
            cover = await service.fetch_resource(TS, f"http://{CDN_HOST}/covers/private.png", capability="catalog")
            assert cover.status == 200

            await control(server, expire_sessions=True)
            with pytest.raises(AuthRequired):
                await service.run(TS, "catalog", {"listing_key": "private"})
            assert sessions.state(TS) == "needs_reconnect"
            waiter = asyncio.create_task(sessions.wait_until_connected(TS))
            await asyncio.sleep(0.01)
            assert not waiter.done()
            sessions.connect(TS, await login(server))
            await asyncio.wait_for(waiter, 1)
            again = await service.run(TS, "catalog", {"listing_key": "private"})
            sessions.disconnect(TS)
            return private, again, dict(server.scenario.cookie_log)
    private, again, cookie_log = run(scenario())
    assert private.complete and again.complete
    assert any(c and SESSION_COOKIE in c for c in cookie_log[HOST])
    assert all(c is None for c in cookie_log[CDN_HOST])  # session never leaks to the CDN


def test_rate_limit_feeds_the_governor(db, tmp_path, installed):
    async def scenario():
        async with environment(db, tmp_path, installed) as (service, server, _, governor):
            await control(server, rate_limit_remaining=1, retry_after=1)
            with pytest.raises(RateLimited) as info:
                await service.fetch_resource(TS, f"http://{HOST}/limited", capability="search")
            started = time.monotonic()
            ok = await service.fetch_resource(TS, f"http://{HOST}/limited", capability="search", priority=Priority.READER)
            return info.value.retry_after, time.monotonic() - started, ok.status
    retry_after, waited, status = run(scenario())
    assert retry_after == 1 and waited >= 0.9 and status == 200


def test_redirect_to_unapproved_domain_is_blocked(db, tmp_path, installed):
    async def scenario():
        async with environment(db, tmp_path, installed) as (service, *_):
            with pytest.raises(DisallowedTarget):
                await service.fetch_resource(TS, f"http://{HOST}/redirect-out", capability="search")
    run(scenario())


def test_without_dev_flag_the_loopback_test_source_is_unreachable(db, tmp_path, installed):
    async def scenario():
        async with environment(db, tmp_path, installed, dev=False, hostile_dns=True) as (service, server, *_):
            result = await service.run(TS, "search", {"query": "chronicle"})
            return result, list(server.scenario.request_log)
    result, requests = run(scenario())
    assert not result.complete and result.evidence.issues[0].category == "blocked" and requests == []


def test_health_signals_are_recorded_passively_with_plugin_version(db, tmp_path, installed):
    async def scenario():
        async with environment(db, tmp_path, installed) as (service, server, *_):
            assert (await service.run(TS, "health", {})).ok is True
            await control(server, paged_mode="fail_page_3")
            await service.run(TS, "catalog", {"listing_key": "paged"})
    run(scenario())
    signals = recent_signals(db, TS)
    assert {(s.capability, s.outcome, s.category) for s in signals} >= {("health", "success", None),
                                                                        ("catalog", "failure", "server_error")}
    assert {s.plugin_version for s in signals} == {"1.0.0"}


def test_disabled_or_uninstalled_plugin_is_unavailable(db, tmp_path, installed):
    async def scenario():
        async with environment(db, tmp_path, installed) as (service, *_):
            installed.disable(TS)
            with pytest.raises(PluginUnavailable):
                await service.run(TS, "search", {"query": "x"})
    run(scenario())


def test_a_source_failure_becomes_a_local_diagnostic(db, tmp_path, installed):
    """§43: what goes wrong with a source is recorded locally — identifiers and a category, no content."""
    import logging

    from oneshelf.diagnostics.store import DiagnosticsHandler, DiagnosticsStore

    store = DiagnosticsStore(tmp_path / "diagnostics")
    handler = DiagnosticsHandler(store)
    logging.getLogger("oneshelf").addHandler(handler)

    async def scenario():
        async with environment(db, tmp_path, installed) as (service, server, _, governor):
            # A private catalog with no session: the source refuses, and that is worth recording.
            with pytest.raises(AuthRequired):
                await service.run(TS, "catalog", {"listing_key": "private"})

    try:
        run(scenario())
    finally:
        logging.getLogger("oneshelf").removeHandler(handler)

    entries = store.recent()
    assert entries, "a source failure left no diagnostic at all"
    entry = entries[-1]
    assert entry["category"] == "network"
    assert "auth_failure" in entry["message"] and TS in entry["message"]
    assert "cookie" not in entry["message"].lower()      # the refusal, never what was sent


def test_a_recipe_can_say_which_headers_its_resources_need(db, tmp_path, installed, monkeypatch):
    """A CDN that refuses an image without a Referer is answered by declaration, not by a branch in Core."""
    package = installed.load_active(TS)
    import dataclasses

    recipes = dict(package.recipes)
    recipes["catalog"] = recipes["catalog"].model_copy(update={"resource_headers": {"Referer": f"http://{HOST}/"}})
    package = dataclasses.replace(package, recipes=recipes)
    sent = {}

    async def scenario():
        async with environment(db, tmp_path, installed) as (service, server, *_):
            original = service._fetcher

            async def capture(plugin_id, priority):
                pkg, fetcher = await original(plugin_id, priority)
                real = fetcher.request

                async def request(url, **kwargs):
                    sent.update(kwargs.get("headers") or {})
                    return await real(url, **kwargs)

                fetcher.request = request
                return pkg, fetcher

            monkeypatch.setattr(service, "_fetcher", capture)
            monkeypatch.setattr(service.plugins, "load_active", lambda _id: package)
            await service.fetch_resource(TS, f"http://{CDN_HOST}/covers/irregular.png", capability="catalog")

    run(scenario())
    assert sent.get("Referer") == f"http://{HOST}/"
