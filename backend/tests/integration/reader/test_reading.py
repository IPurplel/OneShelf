"""Master §19, §26.11–26.23, §42; INV-07, INV-08, INV-16: online reading, cache, progress, auto-download."""
import asyncio
import io
import time
import zipfile
from contextlib import asynccontextmanager
from pathlib import Path

import pytest
from multidict import CIMultiDict

from oneshelf.downloads.contract import Settings
from oneshelf.downloads.engine import DownloadEngine
from oneshelf.net.governor import Priority, TrafficGovernor
from oneshelf.net.http import HttpResponse
from oneshelf.plugins.manager import PluginManager
from oneshelf.plugins.package import load_package
from oneshelf.reader.cache import ReaderCache
from oneshelf.reader.service import ReaderService, StaleProgress
from oneshelf.sessions.manager import SessionManager
from oneshelf.sessions.store import SecretsStore, load_or_create_key
from oneshelf.sources.service import SourceService
from oneshelf.storage.roots import register_root
from oneshelf.integrity.validators import validate
from testsource.build import build_package
from testsource.server import TestSourceServer
from tests.integration.downloads.conftest import Environment, TS, run
from tests.fixtures.builders import png_bytes
from tests.fixtures.library import library  # noqa: F401


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


@pytest.mark.parametrize("count", [1, 2])
def test_i73_local_cbz_rejects_indices_outside_one_based_pages(library, count):
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w") as archive:
        for index in range(1, count + 1):
            archive.writestr(f"{index}.png", f"page-{index}".encode())
    work = library.add_work(f"Local {count}", source="local", content=stream.getvalue())
    reader = ReaderService(library.conn, None, None)
    unit = work["unit_id"]
    for index in range(1, count + 1):
        assert run(reader.page(unit, index)).data == f"page-{index}".encode()
    for index in (0, -1, -8, count + 1):
        with pytest.raises(IndexError):
            run(reader.page(unit, index))


def test_i83_local_cbz_duplicate_member_names_keep_distinct_page_content(library):
    import warnings

    first_page = png_bytes(color=(255, 0, 0))
    second_page = png_bytes(color=(0, 0, 255))
    stream = io.BytesIO()
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", UserWarning)
        with zipfile.ZipFile(stream, "w") as archive:
            archive.writestr("same.png", first_page)
            archive.writestr("same.png", second_page)
    work = library.add_work("Duplicate member pages", source="local", content=stream.getvalue())
    reader = ReaderService(library.conn, None, None)

    assert validate(library.root_path / work["relative"]).ok
    assert len(run(reader.pages(work["unit_id"]))) == 2
    assert run(reader.page(work["unit_id"], 1)).data == first_page
    assert run(reader.page(work["unit_id"], 2)).data == second_page


def test_i90_reader_ignores_archive_entries_excluded_by_cbz_validation(library):
    stream = io.BytesIO()
    first_page = png_bytes()
    with zipfile.ZipFile(stream, "w") as archive:
        archive.writestr("001.png", first_page)
        archive.writestr(".hidden.png", b"invalid hidden image")
        archive.writestr("__MACOSX/ghost.png", b"invalid metadata image")
    work = library.add_work("Archive metadata", source="local", content=stream.getvalue())
    reader = ReaderService(library.conn, None, None)

    assert validate(library.root_path / work["relative"]).page_count == 1
    assert len(run(reader.pages(work["unit_id"]))) == 1
    assert run(reader.page(work["unit_id"], 1)).data == first_page
    with pytest.raises(IndexError):
        run(reader.page(work["unit_id"], 2))


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


def test_visible_page_overtakes_queued_preloads_on_a_slow_source(reading, monkeypatch):
    async def scenario():
        async with reading() as (env, reader, cache):
            await env.add_work("irregular", "The Irregular Chronicle")
            unit = env.unit_id("irr-1")
            await reader.pages(unit)  # measure image scheduling after the descriptor request
            governor = TrafficGovernor(http_capacity=2, reserved_for_foreground=0)
            governor.configure_source(TS, concurrency=1, requests_per_minute=None)
            acquired = asyncio.Event()
            release_first = asyncio.Event()
            order = []

            async def slow_image(source_id, url, *, capability, priority):
                async with governor.acquire(source_id, priority):
                    number = int(url.rsplit("/", 1)[-1].split(".")[0])
                    order.append(number)
                    if number == 1:
                        acquired.set()
                        await release_first.wait()
                    await asyncio.sleep(0.12)
                    return HttpResponse(url, 200, CIMultiDict(), png_bytes())

            monkeypatch.setattr(env.service, "fetch_resource", slow_image)

            async def run_window(*, demote_preloads):
                order.clear()
                acquired.clear()
                release_first.clear()
                first = asyncio.create_task(reader.page(unit, 1, **({"prefetch": True} if demote_preloads else {})))
                await acquired.wait()
                second = asyncio.create_task(reader.page(unit, 2, **({"prefetch": True} if demote_preloads else {})))
                while governor.snapshot()["waiting"] < 1:
                    await asyncio.sleep(0)
                started = time.monotonic()
                visible = asyncio.create_task(reader.page(unit, 3))
                while governor.snapshot()["waiting"] < 2:
                    await asyncio.sleep(0)
                release_first.set()
                await visible
                latency = time.monotonic() - started
                await asyncio.gather(first, second)
                cache.clear()
                return list(order), latency

            baseline_order, baseline_latency = await run_window(demote_preloads=False)
            priority_order, priority_latency = await run_window(demote_preloads=True)
            return baseline_order, baseline_latency, priority_order, priority_latency

    baseline_order, baseline_latency, priority_order, priority_latency = run(scenario())
    print(f"reader visible page, controlled 120 ms source: baseline={baseline_latency:.3f}s "
          f"prioritized={priority_latency:.3f}s")
    assert baseline_order == [1, 2, 3]
    assert priority_order == [1, 3, 2]


def test_visible_page_shares_an_already_started_preload_after_browser_disconnect(reading, monkeypatch):
    async def scenario():
        async with reading() as (env, reader, cache):
            await env.add_work("irregular", "The Irregular Chronicle")
            unit = env.unit_id("irr-1")
            await reader.pages(unit)
            started = asyncio.Event()
            release = asyncio.Event()
            calls = []

            async def slow_image(source_id, url, *, capability, priority):
                calls.append((url, priority))
                started.set()
                await release.wait()
                return HttpResponse(url, 200, CIMultiDict(), png_bytes())

            monkeypatch.setattr(env.service, "fetch_resource", slow_image)
            preload = asyncio.create_task(reader.page(unit, 1, prefetch=True))
            await started.wait()
            preload.cancel()  # the browser discarded its preload request
            with pytest.raises(asyncio.CancelledError):
                await preload
            visible = asyncio.create_task(reader.page(unit, 1))
            await asyncio.sleep(0)
            release.set()
            page = await visible
            return page, len(calls), cache.count()

    page, calls, cached = run(scenario())
    assert page.origin == "online" and page.data == png_bytes()
    assert calls == 1 and cached == 1


def test_abandoned_preload_cancels_source_fetch_after_handoff_window(reading, monkeypatch):
    async def scenario():
        async with reading() as (env, reader, cache):
            await env.add_work("irregular", "The Irregular Chronicle")
            unit = env.unit_id("irr-1")
            await reader.pages(unit)
            started = asyncio.Event()
            cancelled = asyncio.Event()

            async def slow_image(source_id, url, *, capability, priority):
                started.set()
                try:
                    await asyncio.Event().wait()
                except asyncio.CancelledError:
                    cancelled.set()
                    raise

            monkeypatch.setattr(env.service, "fetch_resource", slow_image)
            preload = asyncio.create_task(reader.page(unit, 1, prefetch=True))
            await started.wait()
            preload.cancel()
            with pytest.raises(asyncio.CancelledError):
                await preload
            await asyncio.wait_for(cancelled.wait(), timeout=1)
            await asyncio.sleep(0)
            return len(reader._page_fetches), cache.count()

    active, cached = run(scenario())
    assert active == 0 and cached == 0


def test_foreground_arriving_as_orphan_is_cancelled_starts_fresh_fetch(reading, monkeypatch):
    async def scenario():
        async with reading() as (env, reader, cache):
            await env.add_work("irregular", "The Irregular Chronicle")
            unit = env.unit_id("irr-1")
            await reader.pages(unit)
            started = asyncio.Event()
            calls = 0

            async def slow_then_fast(source_id, url, *, capability, priority):
                nonlocal calls
                calls += 1
                if calls == 1:
                    started.set()
                    await asyncio.Event().wait()
                return HttpResponse(url, 200, CIMultiDict(), png_bytes())

            monkeypatch.setattr(env.service, "fetch_resource", slow_then_fast)
            preload = asyncio.create_task(reader.page(unit, 1, prefetch=True))
            await started.wait()
            preload.cancel()
            with pytest.raises(asyncio.CancelledError):
                await preload
            key, flight = next(iter(reader._page_fetches.items()))
            flight.orphan_timer.cancel()
            reader._cancel_orphan_page(key, flight)
            visible = await reader.page(unit, 1)
            return visible, calls, cache.count()

    visible, calls, cached = run(scenario())
    assert visible.data == png_bytes() and calls == 2 and cached == 1


def test_queued_preload_is_promoted_without_refetching_when_page_turns(reading, monkeypatch):
    async def scenario():
        async with reading() as (env, reader, cache):
            await env.add_work("irregular", "The Irregular Chronicle")
            unit = env.unit_id("irr-1")
            await reader.pages(unit)
            governor = env.governor
            governor.configure_source(TS, concurrency=1, requests_per_minute=None)
            held = asyncio.Event()
            release = asyncio.Event()
            order = []
            calls = []

            async def blocker():
                async with governor.acquire(TS, Priority.MANUAL):
                    held.set()
                    await release.wait()

            async def other_background():
                async with governor.acquire(TS, Priority.READ_AHEAD):
                    order.append("other")

            async def slow_image(source_id, url, *, capability, priority):
                calls.append((url, priority))
                async with governor.acquire(source_id, priority):
                    order.append("page")
                    return HttpResponse(url, 200, CIMultiDict(), png_bytes())

            monkeypatch.setattr(env.service, "fetch_resource", slow_image)
            holding = asyncio.create_task(blocker())
            await held.wait()
            other = asyncio.create_task(other_background())
            while governor.snapshot()["waiting"] < 1:
                await asyncio.sleep(0)
            preload = asyncio.create_task(reader.page(unit, 1, prefetch=True))
            while governor.snapshot()["waiting"] < 2:
                await asyncio.sleep(0)
            preload.cancel()
            with pytest.raises(asyncio.CancelledError):
                await preload
            visible = asyncio.create_task(reader.page(unit, 1))
            await asyncio.sleep(0)
            release.set()
            page = await visible
            await asyncio.gather(holding, other)
            return order, len(calls), page.origin, cache.count()

    order, calls, origin, cached = run(scenario())
    assert order == ["page", "other"]
    assert calls == 1 and origin == "online" and cached == 1


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


# -- I-107 (BE-017): honest page failures, a bounded page-list cache, and offline cached pages ---------------

from oneshelf.plugins.results import Evidence, ListResult
from oneshelf.plugins.runtime import CapabilityError
from oneshelf.reader import service as reader_module
from oneshelf.reader.service import SourceUnavailable


def page_list_requests(env, unit_key):
    return [r for r in env.server.scenario.request_log if f"/api/units/{unit_key}/pages" in r]


def test_i107_a_page_the_source_lost_is_reported_with_its_status(reading):
    async def scenario():
        async with reading() as (env, reader, cache):
            await env.add_work("irregular", "The Irregular Chronicle")
            unit = env.unit_id("irr-1")
            await env.control(missing_pages=True)
            with pytest.raises(CapabilityError) as raised:
                await reader.page(unit, 1)
            signals = env.db.execute("SELECT capability, outcome, category FROM source_health_signals"
                                     " WHERE capability = 'reader' ORDER BY rowid").fetchall()
            return raised.value, [tuple(s) for s in signals]

    error, signals = run(scenario())
    assert error.category == "not_found" and "404" in str(error)
    assert ("reader", "content_missing", "not_found") in signals          # one lost page is not a broken source
    assert not any(outcome == "failure" for _, outcome, _ in signals)


def test_i107_an_expired_page_link_is_refreshed_once_and_read(reading):
    async def scenario():
        async with reading() as (env, reader, cache):
            await env.add_work("irregular", "The Irregular Chronicle")
            unit = env.unit_id("irr-1")
            await env.control(expiring_pages=True)
            await reader.pages(unit)                                        # links carry token 1
            await env.control(page_token=2)                                 # ... which then expires
            page = await reader.page(unit, 1)
            return page.origin, len(page_list_requests(env, "irr-1"))

    origin, listings = run(scenario())
    assert origin == "online" and listings == 2                             # one refresh, then the page


def test_i107_a_failed_page_list_is_not_remembered(reading, monkeypatch):
    async def scenario():
        async with reading() as (env, reader, cache):
            await env.add_work("irregular", "The Irregular Chronicle")
            unit = env.unit_id("irr-1")
            real_run, calls = env.service.run, []

            async def flaky(source_id, capability, inputs, **kwargs):
                calls.append(capability)
                if capability == "reader" and len(calls) == 1:
                    return ListResult("reader", [], False, Evidence(stop_reason="page_failed"))
                return await real_run(source_id, capability, inputs, **kwargs)

            monkeypatch.setattr(env.service, "run", flaky)
            with pytest.raises(CapabilityError):
                await reader.pages(unit)
            return len(await reader.pages(unit))

    assert run(scenario()) == 3


def test_i107_the_page_list_cache_is_bounded(reading, monkeypatch):
    monkeypatch.setattr(reader_module, "DESCRIPTOR_CACHE_UNITS", 2)

    async def scenario():
        async with reading() as (env, reader, cache):
            await env.add_work("irregular", "The Irregular Chronicle")
            for key in ("irr-1", "irr-2", "irr-3"):
                await reader.pages(env.unit_id(key))
            return len(reader._descriptors)

    assert run(scenario()) == 2


def test_i107_a_disabled_source_says_so_and_its_cached_pages_stay_readable(reading):
    async def scenario():
        async with reading() as (env, reader, cache):
            await env.add_work("irregular", "The Irregular Chronicle")
            unit = env.unit_id("irr-1")
            await reader.page(unit, 1)                                     # read once, so page 1 is cached
            env.service.plugins.disable(TS)
            fresh = ReaderService(env.db, env.service, cache, env.engine, settings=Settings(env.db))  # a restart
            listed = await fresh.pages(unit)
            cached = await fresh.page(unit, 1)
            with pytest.raises(SourceUnavailable):
                await fresh.page(unit, 2)                                  # never fetched: needs the source
            context = fresh.context(unit)
            return len(listed), cached.origin, context["kind"]

    listed, origin, kind = run(scenario())
    assert listed == 3 and origin == "cache" and kind == "images"
