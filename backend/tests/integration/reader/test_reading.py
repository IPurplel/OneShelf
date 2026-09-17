"""Master §19, §26.11–26.23, §42; INV-07, INV-08, INV-16: online reading, cache, progress, auto-download."""
import asyncio
from contextlib import asynccontextmanager
from pathlib import Path

import pytest

from oneshelf.downloads.contract import Settings
from oneshelf.downloads.engine import DownloadEngine
from oneshelf.net.governor import TrafficGovernor
from oneshelf.plugins.manager import PluginManager
from oneshelf.plugins.package import load_package
from oneshelf.reader.cache import ReaderCache
from oneshelf.reader.service import ReaderService, StaleProgress
from oneshelf.sessions.manager import SessionManager
from oneshelf.sessions.store import SecretsStore, load_or_create_key
from oneshelf.sources.service import SourceService
from oneshelf.storage.roots import register_root
from testsource.build import build_package
from testsource.server import TestSourceServer
from tests.integration.downloads.conftest import Environment, TS, run


@pytest.fixture
def reading(db, tmp_path):
    @asynccontextmanager
    async def factory(**cache_kwargs):
        manager = PluginManager(db, store_dir=tmp_path / "app" / "plugins")
        path = build_package(tmp_path / "ts.osp")
        await manager.install_file(path, approved_permissions=load_package(path).permissions)
        (tmp_path / "library").mkdir(exist_ok=True)
        root = register_root(db, "Library", tmp_path / "library")
        store = SecretsStore(tmp_path / "app" / "secrets.db", load_or_create_key(tmp_path / "keys" / "session.key"))
        sessions = SessionManager(db, store, events=None)
        governor = TrafficGovernor()
        cache = ReaderCache(tmp_path / "app" / "reader-cache", tmp_path / "app" / "cache.db", **cache_kwargs)
        async with TestSourceServer() as server:
            async with SourceService(db, manager, governor, sessions, dev_test_source=True,
                                     dev_hosts=server.hosts()) as service:
                engine = DownloadEngine(db, service, manager, governor, backoff_base_seconds=1.05)
                env = Environment(db, service, engine, server, sessions, governor, root)
                reader = ReaderService(db, service, cache, engine, settings=Settings(db))
                yield env, reader, cache
        cache.close()
        store.close()

    return factory


def image_requests(env, unit_key):
    return [r for r in env.server.scenario.request_log if f"/img/{unit_key}/" in r]


def test_reading_online_never_downloads_permanently(reading):
    async def scenario():
        async with reading() as (env, reader, cache):
            await env.add_work("irregular", "The Irregular Chronicle")
            unit = env.unit_id("irr-1")
            pages = await reader.pages(unit)
            first = await reader.page(unit, 1)
            return env, pages, first, cache.count()

    env, pages, first, cached = run(scenario())
    assert len(pages) == 3 and first.origin == "online" and first.data[:8] == b"\x89PNG\r\n\x1a\n"
    assert env.assets() == [] and env.files() == []   # INV-07: reading is not downloading
    assert cached == 1


def test_cached_pages_are_not_refetched_and_are_keyed_by_resource_identity(reading):
    async def scenario():
        async with reading() as (env, reader, cache):
            await env.add_work("irregular", "The Irregular Chronicle")
            unit = env.unit_id("irr-1")
            await reader.page(unit, 1)
            after_first = len(image_requests(env, "irr-1"))
            second = await reader.page(unit, 1)
            other = await reader.page(unit, 2)
            keys = cache.keys()
            return after_first, len(image_requests(env, "irr-1")), second.origin, other.origin, keys

    after_first, after_second, origin, other_origin, keys = run(scenario())
    assert after_first == 1 and after_second == 2  # page 1 served from cache, page 2 fetched once
    assert origin == "cache" and other_origin == "online"
    assert all(TS in key and "irr-1" in key for key in keys)
    assert not any("Chapter" in key or key.endswith("/1") for key in keys)  # never keyed by title or number


def test_cache_eviction_protects_the_current_unit_and_permanent_files(reading):
    async def scenario():
        async with reading(cap_bytes=300) as (env, reader, cache):
            await env.add_work("irregular", "The Irregular Chronicle")
            current, other = env.unit_id("irr-1"), env.unit_id("irr-2")
            for index in (1, 2, 3):
                await reader.page(other, index)
            reader.set_open_units([current])
            for index in (1, 2, 3):
                await reader.page(current, index)
            cache.evict()
            protected = [k for k in cache.keys() if "irr-1" in k]
            evicted = [k for k in cache.keys() if "irr-2" in k]
            return protected, evicted, cache.total_bytes()

    protected, evicted, total = run(scenario())
    # the open unit's pages survive even though that keeps the cache above its cap (§42)
    assert len(protected) == 3 and evicted == []
    assert total > 0


def test_downloaded_units_are_read_locally_without_network(reading):
    async def scenario():
        async with reading() as (env, reader, cache):
            await env.add_work("irregular", "The Irregular Chronicle")
            unit = env.unit_id("irr-1")
            env.engine.enqueue([unit])
            await env.engine.run_until_idle()
            before = len(env.server.scenario.request_log)
            pages = await reader.pages(unit)
            page = await reader.page(unit, 2)
            return pages, page, before, len(env.server.scenario.request_log), cache.count()

    pages, page, before, after, cached = run(scenario())
    assert len(pages) == 3 and page.origin == "local" and page.data[:8] == b"\x89PNG\r\n\x1a\n"
    assert before == after and cached == 0  # no network, no cache entries for permanent content


def test_auto_download_is_off_by_default(reading):
    async def scenario():
        async with reading() as (env, reader, cache):
            await env.add_work("irregular", "The Irregular Chronicle")
            unit = env.unit_id("irr-1")
            queued = await reader.record_engagement(unit, fraction=0.9, interacted=True)
            return queued, env.db.execute("SELECT count(*) FROM download_jobs").fetchone()[0]

    queued, jobs = run(scenario())
    assert queued == [] and jobs == 0   # INV-08


def test_engagement_threshold_and_genuine_interaction(reading):
    async def scenario():
        async with reading() as (env, reader, cache):
            await env.add_work("irregular", "The Irregular Chronicle")
            reader.settings.set("global", None, "reader.auto_download.enabled", True)
            unit = env.unit_id("irr-1")
            below = await reader.record_engagement(unit, fraction=0.05, interacted=True)
            without_interaction = await reader.record_engagement(unit, fraction=0.5, interacted=False)
            triggered = await reader.record_engagement(unit, fraction=0.12, interacted=True)
            again = await reader.record_engagement(unit, fraction=0.5, interacted=True)
            return below, without_interaction, triggered, again, env.db.execute(
                "SELECT count(*) FROM download_jobs").fetchone()[0]

    below, without_interaction, triggered, again, jobs = run(scenario())
    assert below == [] and without_interaction == []
    assert len(triggered) == 1 and again == []   # already queued, not queued twice
    assert jobs == 1


def test_read_ahead_is_bounded_and_follows_track_order(reading):
    async def scenario():
        async with reading() as (env, reader, cache):
            await env.add_work("irregular", "The Irregular Chronicle")
            reader.settings.set("global", None, "reader.auto_download.enabled", True)
            reader.settings.set("global", None, "reader.auto_download.mode", "current_plus_read_ahead")
            queued = await reader.record_engagement(env.unit_id("irr-prologue"), fraction=0.2, interacted=True)
            keys = [env.db.execute("SELECT source_unit_key FROM reading_units WHERE id = ?", (u,)).fetchone()[0]
                    for u in queued]
            return keys

    keys = run(scenario())
    assert keys == ["irr-prologue", "irr-1", "irr-2", "irr-special", "irr-3-5", "irr-3"]  # current + next 5 in source order


def test_leaving_the_work_cancels_unstarted_read_ahead_only(reading):
    async def scenario():
        async with reading() as (env, reader, cache):
            binding = await env.add_work("irregular", "The Irregular Chronicle")
            reader.settings.set("global", None, "reader.auto_download.enabled", True)
            reader.settings.set("global", None, "reader.auto_download.mode", "current_plus_read_ahead")
            queued = await reader.record_engagement(env.unit_id("irr-prologue"), fraction=0.2, interacted=True)
            jobs = env.db.execute("SELECT id, reading_unit_id FROM download_jobs ORDER BY queue_position").fetchall()
            env.db.execute("UPDATE download_jobs SET state = 'DOWNLOADING' WHERE id = ?", (jobs[1]["id"],))
            canceled = await reader.leaving_work(binding.work_id)
            states = {r["state"] for r in env.db.execute("SELECT state FROM download_jobs")}
            current_state = env.db.execute("SELECT state FROM download_jobs WHERE reading_unit_id = ?",
                                           (queued[0],)).fetchone()[0]
            return canceled, states, current_state

    canceled, states, current_state = run(scenario())
    assert canceled == 4 and states == {"QUEUED", "DOWNLOADING", "CANCELED"}
    assert current_state == "QUEUED"  # the unit being read may finish


def test_progress_writes_reject_stale_tabs_but_allow_explicit_changes(reading):
    async def scenario():
        async with reading() as (env, reader, cache):
            await env.add_work("irregular", "The Irregular Chronicle")
            unit = env.unit_id("irr-1")
            first = reader.set_progress(unit, locator={"page": 2}, fraction=0.2)
            second = reader.set_progress(unit, locator={"page": 6}, fraction=0.6, revision=first.revision)
            stale = None
            try:
                reader.set_progress(unit, locator={"page": 3}, fraction=0.3, revision=first.revision)
            except StaleProgress as exc:
                stale = exc
            state = reader.progress(unit)
            reader.mark_unread(unit)
            after_unread = reader.progress(unit)
            auto = reader.set_progress(unit, locator={"page": 10}, fraction=0.98, revision=after_unread.revision)
            return second, stale, state, after_unread, auto

    second, stale, state, after_unread, auto = run(scenario())
    assert second.revision == 2 and state.fraction == pytest.approx(0.6) and state.read_state == "partial"
    assert stale is not None
    assert after_unread.read_state == "unread" and after_unread.fraction is None
    assert auto.read_state == "read"   # auto mark read at 97% (§26.14)


def test_reader_stays_responsive_while_downloads_saturate_the_governor(reading):
    async def scenario():
        async with reading() as (env, reader, cache):
            await env.add_work("irregular", "The Irregular Chronicle")
            await env.add_work("paged", "Paged Archive", content_type="comic")
            units = [r[0] for r in env.db.execute(
                "SELECT id FROM reading_units WHERE source_unit_key LIKE 'pg-%' ORDER BY source_order LIMIT 40")]
            env.engine.enqueue(units)
            downloads = asyncio.create_task(env.engine.run_until_idle(max_seconds=10))
            await asyncio.sleep(0.2)
            import time
            started = time.monotonic()
            page = await reader.page(env.unit_id("irr-1"), 1, timeout=10)
            latency = time.monotonic() - started
            env.engine.pause(env.db.execute("SELECT id FROM download_batches").fetchone()[0])
            await downloads
            return page, latency

    page, latency = run(scenario(), timeout=90)
    assert page.origin == "online" and latency < 3.0   # INV-26
