"""Master §6.1 / §7 / INV-27: local-first search with progressive live enrichment."""
import asyncio
import time

import pytest

from oneshelf.domain.clock import utcnow_iso
from oneshelf.domain.ids import new_id
from oneshelf.plugins.results import Evidence, ListResult, Listing
from oneshelf.plugins.runtime import CapabilityError, RateLimited
from oneshelf.search.cache import DiscoveryCache
from oneshelf.search.index import index_work
from oneshelf.search.service import SearchService

NOW = utcnow_iso()


def listing_result(*titles, source="s"):
    entries = [Listing(listing_key=f"{source}-{t}", title=t, url=f"https://{source}/{t}", content_type="manga",
                       language="en") for t in titles]
    return ListResult("search", entries, True, Evidence(pages=1, stop_reason="single_response"))


class FakeSources:
    """Stands in for SourceService: per-source behaviour and call counting."""

    def __init__(self, behaviours):
        self.behaviours = behaviours
        self.calls = []

    def searchable_sources(self):
        return [(source, "1.0.0") for source in self.behaviours]

    async def run(self, plugin_id, capability, inputs, *, priority=None):
        self.calls.append((plugin_id, inputs.get("query")))
        behaviour = self.behaviours[plugin_id]
        if callable(behaviour):
            return await behaviour(inputs)
        return behaviour


@pytest.fixture
def cache(tmp_path):
    c = DiscoveryCache(tmp_path / "cache.db")
    yield c
    c.close()


def add_local_work(db, title):
    work_id = new_id()
    db.execute("INSERT INTO works (id, display_title, content_type, created_at, updated_at) VALUES (?,?,?,?,?)",
               (work_id, title, "manga", NOW, NOW))
    db.execute("INSERT INTO shelf_entries (work_id, added_at) VALUES (?, ?)", (work_id, NOW))
    index_work(db, work_id)
    return work_id


async def collect(service, query, **kw):
    return [update async for update in service.search(query, **kw)]


def test_local_results_come_first_and_live_sources_enrich_them(db, cache):
    work = add_local_work(db, "Solo Leveling")
    sources = FakeSources({"mangadex": listing_result("Solo Leveling", source="mangadex"),
                           "3asq": listing_result("Solo Leveling: Ragnarok", source="3asq")})
    updates = asyncio.run(collect(SearchService(db, sources, cache), "Solo Leveling"))
    assert updates[0].stage == "local"
    assert [r.work_id for r in updates[0].results] == [work]
    assert updates[0].sources_total == 2 and updates[0].sources_done == 0
    final = updates[-1]
    assert final.stage == "complete" and final.sources_done == 2
    titles = {r.title for r in final.results}
    assert titles == {"Solo Leveling", "Solo Leveling: Ragnarok"}
    solo = next(r for r in final.results if r.title == "Solo Leveling")
    assert solo.work_id == work and {p.source_id for p in solo.provenance} == {"mangadex"}


def test_a_slow_source_does_not_block_results(db, cache):
    async def slow(inputs):
        await asyncio.sleep(0.4)
        return listing_result("Slow Result", source="slow")

    sources = FakeSources({"fast": listing_result("Fast Result", source="fast"), "slow": slow})

    async def scenario():
        started = time.monotonic()
        seen = []
        async for update in SearchService(db, sources, cache).search("result"):
            seen.append((update.stage, time.monotonic() - started, {r.title for r in update.results}))
        return seen

    seen = asyncio.run(scenario())
    fast_update = next(s for s in seen if "Fast Result" in s[2])
    assert fast_update[1] < 0.3
    assert seen[-1][2] == {"Fast Result", "Slow Result"} and seen[-1][1] >= 0.4


def test_failing_source_never_clears_other_results(db, cache):
    add_local_work(db, "Berserk")

    async def broken(inputs):
        raise CapabilityError("parser_failure", "selectors changed")

    sources = FakeSources({"good": listing_result("Berserk", source="good"), "broken": broken})
    updates = asyncio.run(collect(SearchService(db, sources, cache), "Berserk"))
    final = updates[-1]
    assert {r.title for r in final.results} == {"Berserk"}
    assert final.source_status["broken"]["state"] == "failed"
    assert final.source_status["broken"]["category"] == "parser_failure"
    assert final.source_status["good"]["state"] == "done"
    assert final.sources_done == 1 and final.sources_failed == 1


def test_rate_limited_source_is_reported_as_retryable(db, cache):
    async def limited(inputs):
        raise RateLimited(30)

    sources = FakeSources({"limited": limited})
    final = asyncio.run(collect(SearchService(db, sources, cache), "x"))[-1]
    assert final.source_status["limited"] == {"state": "failed", "category": "rate_limit", "retry_after": 30}


def test_retry_source_returns_its_results(db, cache):
    attempts = {"n": 0}

    async def flaky(inputs):
        attempts["n"] += 1
        if attempts["n"] == 1:
            raise CapabilityError("timeout", "too slow")
        return listing_result("Recovered", source="flaky")

    service = SearchService(db, FakeSources({"flaky": flaky}), cache)

    async def scenario():
        await collect(service, "recovered")
        return [u async for u in service.retry_source("recovered", "flaky")]

    updates = asyncio.run(scenario())
    assert {r.title for r in updates[-1].results} == {"Recovered"}
    assert updates[-1].source_status["flaky"]["state"] == "done"


def test_cached_results_are_reused_and_invalidated_by_plugin_version(db, cache):
    sources = FakeSources({"mangadex": listing_result("Cached Work", source="mangadex")})
    service = SearchService(db, sources, cache)
    asyncio.run(collect(service, "cached work"))
    assert len(sources.calls) == 1
    final = asyncio.run(collect(service, "cached work"))[-1]
    assert len(sources.calls) == 1 and final.source_status["mangadex"]["state"] == "cached"
    assert {r.title for r in final.results} == {"Cached Work"}
    sources.behaviours = {"mangadex": listing_result("Fresh Work", source="mangadex")}
    sources.searchable_sources = lambda: [("mangadex", "2.0.0")]
    final = asyncio.run(collect(service, "cached work"))[-1]
    assert len(sources.calls) == 2 and {r.title for r in final.results} == {"Fresh Work"}


def test_cached_and_live_copies_of_one_listing_stay_one_record(db, cache):
    sources = FakeSources({"mangadex": listing_result("Same Listing", source="mangadex")})
    service = SearchService(db, sources, cache)
    asyncio.run(collect(service, "same listing"))
    final = asyncio.run(collect(service, "same listing", refresh=True))[-1]
    result = final.results[0]
    assert len(result.provenance) == 1 and len(sources.calls) == 2


def test_search_writes_nothing_durable_about_the_query(db, cache):
    sources = FakeSources({"mangadex": listing_result("Private Thing", source="mangadex")})
    asyncio.run(collect(SearchService(db, sources, cache), "private phrase"))
    assert db.execute("SELECT count(*) FROM source_listings").fetchone()[0] == 0
    assert db.execute("SELECT count(*) FROM works").fetchone()[0] == 0
