"""Master §6.1 / §7 / INV-27: local-first search with progressive live enrichment."""
import asyncio
import time
from types import SimpleNamespace

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


def add_typed_local_work(db, title, content_type, language):
    work_id = new_id()
    db.execute("INSERT INTO works (id, display_title, content_type, created_at, updated_at) VALUES (?,?,?,?,?)",
               (work_id, title, content_type, NOW, NOW))
    db.execute("INSERT INTO source_tracks (id, work_id, source_id, language, kind, created_at)"
               " VALUES (?,?,?,?,?,?)", (new_id(), work_id, "local", language, "local", NOW))
    index_work(db, work_id)
    return work_id


def labelled_sources(behaviours, labels):
    sources = FakeSources(behaviours)
    sources.plugins = SimpleNamespace(get=lambda source_id: SimpleNamespace(
        category=labels[source_id][0], languages=labels[source_id][1]))
    return sources


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


def test_plain_title_matches_come_first_whichever_source_answered_first(db, cache):
    """Searching "الغريب" used to show unrelated manga first, because that source happened to answer first."""
    async def late_exact(inputs):
        await asyncio.sleep(0.05)
        return listing_result("Something Else", "الغريب", "الغريب وقصص أخرى", source="books")

    sources = FakeSources({"manga": listing_result("JoJo no Kimyou na Bouken", "Akaya Akashiya", source="manga"),
                           "books": late_exact})
    for _ in range(2):        # the order is the same on every run, not a race between sources
        final = asyncio.run(collect(SearchService(db, sources, cache), "الغريب", refresh=True))[-1]
        assert [r.title for r in final.results][:2] == ["الغريب", "الغريب وقصص أخرى"]
        assert {r.title for r in final.results[2:]} == {"Something Else", "JoJo no Kimyou na Bouken", "Akaya Akashiya"}


def test_a_result_with_nothing_to_open_is_not_shown(db, cache):
    empty = Listing(listing_key="promo", title="A Promo With No Translation", content_type="manga",
                    language="ja", available_languages=[])
    sources = FakeSources({"s": ListResult("search", [empty, *listing_result("A Real One").entries], True,
                                           Evidence(pages=1, stop_reason="single_response"))})
    final = asyncio.run(collect(SearchService(db, sources, cache), "one"))[-1]
    assert [r.title for r in final.results] == ["A Real One"]


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


def test_an_unfetchable_page_is_a_failure_and_is_not_cached(db, cache):
    from oneshelf.plugins.results import Issue

    calls = {"n": 0}

    async def unreachable(inputs):
        calls["n"] += 1
        if calls["n"] == 1:
            return ListResult("search", [], False, Evidence(pages=0, issues=[Issue("transport", "reset", 1)]))
        return listing_result("Found", source="net")

    sources = FakeSources({"net": unreachable})
    first = asyncio.run(collect(SearchService(db, sources, cache), "found"))[-1]
    assert first.source_status["net"] == {"state": "failed", "category": "transport"}
    second = asyncio.run(collect(SearchService(db, sources, cache), "found"))[-1]
    assert {r.title for r in second.results} == {"Found"} and calls["n"] == 2


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


def test_cancelled_search_cancels_and_awaits_source_tasks(db, cache):
    async def scenario():
        started, stopped = asyncio.Event(), asyncio.Event()
        async def slow(_inputs):
            started.set()
            try:
                await asyncio.Event().wait()
            finally:
                stopped.set()
        service = SearchService(db, FakeSources({'slow': slow}), cache)
        stream = service.search('cancel me')
        await anext(stream)
        request = asyncio.create_task(anext(stream))
        await started.wait()
        request.cancel()
        with pytest.raises(asyncio.CancelledError):
            await request
        assert stopped.is_set()
    asyncio.run(scenario())


def test_retry_state_is_bounded_and_expires_without_persisting_queries(db, cache):
    clock = [0.0]
    service = SearchService(db, FakeSources({}), cache, max_states=2, state_ttl_seconds=10,
                            clock=lambda: clock[0])
    async def scenario():
        for query in ('first', 'second', 'third'):
            await collect(service, query)
        assert set(service._states) == {'second', 'third'}
        clock[0] = 11
        await collect(service, 'fourth')
        assert set(service._states) == {'fourth'}
    asyncio.run(scenario())


def test_translation_choices_survive_search_cache_and_retry(db, cache):
    result = ListResult('search', [Listing('series', 'Bilingual', available_languages=['en', 'ar'])],
                        True, Evidence())
    source = FakeSources({'source': result})
    service = SearchService(db, source, cache)
    async def scenario():
        for _ in range(2):
            final = (await collect(service, 'bilingual'))[-1]
            assert final.results[0].availability == {'en': 1, 'ar': 1}
        retried = [update async for update in service.retry_source('bilingual', 'source')]
        assert retried[-1].results[0].availability == {'en': 1, 'ar': 1}
    asyncio.run(scenario())


def test_scoped_search_runs_only_matching_sources_and_reports_scoped_total(db, cache):
    sources = labelled_sources({name: listing_result(name, source=name) for name in
                                ("manga_en", "manga_ar", "books_en", "unknown", "multi")},
                               {"manga_en": ("Manga", ("EN",)), "manga_ar": ("Manga", ("AR",)),
                                "books_en": ("Books", ("EN",)), "unknown": (None, ("EN",)),
                                "multi": ("Manga", ("Multi",))})
    updates = asyncio.run(collect(SearchService(db, sources, cache), "scope",
                                  categories={"Manga"}, languages={"en"}))
    assert updates[0].sources_total == 2
    assert updates[0].sources_available == 5
    assert set(updates[0].source_status) == {"manga_en", "multi"}
    assert {source for source, _ in sources.calls} == {"manga_en", "multi"}
    assert updates[-1].sources_done == 2
    assert updates[-1].sources_available == 5


def test_unknown_category_is_included_when_only_language_is_scoped(db, cache):
    sources = labelled_sources({"unknown": listing_result("Unknown", source="unknown")},
                               {"unknown": (None, ("EN",))})
    final = asyncio.run(collect(SearchService(db, sources, cache), "unknown", languages={"en"}))[-1]
    assert final.sources_total == 1 and final.source_status["unknown"]["state"] == "done"


def test_per_source_cache_is_reused_between_scopes(db, cache):
    sources = labelled_sources({"multi": listing_result("Shared", source="multi")},
                               {"multi": ("Manga", ("Multi",))})
    service = SearchService(db, sources, cache)
    asyncio.run(collect(service, "shared", categories={"Manga"}, languages={"EN"}))
    second = asyncio.run(collect(service, "shared", categories={"Manga"}, languages={"AR"}))[-1]
    assert second.source_status["multi"]["state"] == "cached"
    assert len(sources.calls) == 1


def test_multilingual_source_only_shows_requested_listing_languages(db, cache):
    result = ListResult("search", [
        Listing("arabic", "Arabic Work", language="ar", content_type="manga"),
        Listing("english", "English Work", language="en", content_type="manga"),
        Listing("translations", "Translated Work", available_languages=["en", "ar"], content_type="manga"),
    ], True, Evidence())
    sources = labelled_sources({"multi": result}, {"multi": ("Manga", ("Multi",))})
    final = asyncio.run(collect(SearchService(db, sources, cache), "work", languages={"EN"}))[-1]
    assert {work.title for work in final.results} == {"English Work", "Translated Work"}
    translated = next(work for work in final.results if work.title == "Translated Work")
    assert translated.availability == {"en": 1}


def test_local_results_follow_category_content_type_and_track_language(db, cache):
    manga = add_typed_local_work(db, "Scope Manga", "manga", "en")
    comic = add_typed_local_work(db, "Scope Comic", "manhwa", "en")
    book = add_typed_local_work(db, "Scope Book", "novel", "ar")
    paper = add_typed_local_work(db, "Scope Paper", "paper", "en")
    service = SearchService(db, FakeSources({}), cache)
    async def result_ids(**scope):
        return {result.work_id for result in (await collect(service, "scope", **scope))[0].results}
    assert asyncio.run(result_ids(categories={"Manga"}, languages={"en"})) == {manga}
    assert asyncio.run(result_ids(categories={"Comics", "Webtoons"}, languages={"en"})) == {comic}
    assert asyncio.run(result_ids(categories={"Books"}, languages={"ar"})) == {book}
    assert asyncio.run(result_ids(categories={"Reports"}, languages={"en"})) == {paper}
    assert asyncio.run(result_ids(categories={"Manuscripts"})) == {manga, comic, book, paper}


def test_local_scope_finds_matching_work_after_unscoped_result_limit(db, cache):
    for index in range(4):
        add_typed_local_work(db, f"Scope A Manga {index}", "manga", "en")
    book = add_typed_local_work(db, "Scope Z Book", "book", "en")
    service = SearchService(db, FakeSources({}), cache, limit=2)
    updates = asyncio.run(collect(service, "scope", categories={"Books"}))
    assert [result.work_id for result in updates[0].results] == [book]


def test_local_primary_language_matches_a_regional_track(db, cache):
    regional = add_typed_local_work(db, "Regional Story", "book", "en-US")
    service = SearchService(db, FakeSources({}), cache)
    updates = asyncio.run(collect(service, "regional", languages={"EN"}))
    assert [result.work_id for result in updates[0].results] == [regional]


def test_arabic_scope_keeps_egyptian_arabic_local_and_live_results(db, cache):
    local = add_typed_local_work(db, "Habiba Story", "book", "arz")
    result = ListResult("search", [
        Listing("egyptian", "Habiba Story", language="arz", content_type="book"),
        Listing("regional", "Egyptian Edition", language="arz-EG", content_type="book"),
    ], True, Evidence())
    sources = labelled_sources({"habiba": result}, {"habiba": ("Books", ("AR",))})
    updates = asyncio.run(collect(SearchService(db, sources, cache), "habiba",
                                  categories={"Books"}, languages={"AR"}))
    assert [item.work_id for item in updates[0].results] == [local]
    assert {item.title for item in updates[-1].results} == {"Habiba Story", "Egyptian Edition"}
    assert len(sources.calls) == 1


def test_retry_uses_the_same_scope_and_never_retries_an_excluded_source(db, cache):
    attempts = {"english": 0}
    async def english(_inputs):
        attempts["english"] += 1
        if attempts["english"] == 1:
            raise CapabilityError("timeout", "try again")
        return listing_result("Recovered", source="english")
    sources = labelled_sources({"english": english, "arabic": listing_result("Arabic", source="arabic")},
                               {"english": ("Manga", ("EN",)), "arabic": ("Manga", ("AR",))})
    service = SearchService(db, sources, cache)
    async def scenario():
        await collect(service, "scope", categories={"Manga"}, languages={"en"})
        await collect(service, "scope", categories={"Manga"}, languages={"ar"})
        excluded = [u async for u in service.retry_source("scope", "arabic", categories={"Manga"}, languages={"en"})]
        retried = [u async for u in service.retry_source("scope", "english", categories={"Manga"}, languages={"en"})]
        return excluded[-1], retried[-1]
    excluded, retried = asyncio.run(scenario())
    assert set(excluded.source_status) == {"english"}
    assert excluded.sources_total == 1 and retried.sources_total == 1
    assert retried.source_status["english"]["state"] == "done"
    assert [source for source, _ in sources.calls] == ["english", "arabic", "english"]
