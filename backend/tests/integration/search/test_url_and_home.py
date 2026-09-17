"""Master §8 (direct URL entry) and §31 (Home discovery semantics)."""
import asyncio

import pytest

from oneshelf.discovery.home import HomeService
from oneshelf.domain.clock import utcnow_iso
from oneshelf.domain.ids import new_id
from oneshelf.plugins.manager import PluginManager
from oneshelf.plugins.package import load_package
from oneshelf.plugins.results import Evidence, ListResult, Listing, WorkDetails
from oneshelf.search.cache import DiscoveryCache
from oneshelf.search.index import index_work
from oneshelf.search.url_resolve import UnsupportedUrl, resolve_url
from testsource.build import build_package

NOW = utcnow_iso()
TS = "oneshelf.test-source"


@pytest.fixture
def plugins(db, tmp_path):
    manager = PluginManager(db, store_dir=tmp_path / "plugins")
    path = build_package(tmp_path / "ts.osp")
    asyncio.run(manager.install_file(path, approved_permissions=load_package(path).permissions))
    return manager


@pytest.fixture
def cache(tmp_path):
    c = DiscoveryCache(tmp_path / "cache.db")
    yield c
    c.close()


class FakeSources:
    def __init__(self, responses=None, capabilities=None):
        self.responses = responses or {}
        self.capabilities = capabilities or {}
        self.calls = []

    def sources_with_capability(self, capability):
        return [(s, "1.0.0") for s, caps in self.capabilities.items() if capability in caps]

    async def run(self, plugin_id, capability, inputs, *, priority=None):
        self.calls.append((plugin_id, capability))
        value = self.responses.get((plugin_id, capability))
        if value is None:
            raise AssertionError(f"unexpected call {plugin_id}/{capability}")
        return value


# -- §8 direct URL entry ---------------------------------------------------------------------------

def test_supported_url_resolves_to_plugin_capability_and_identifier(plugins):
    resolved = resolve_url(plugins, "http://testsource.example/work/irregular")
    assert (resolved.plugin_id, resolved.capability, resolved.identifier) == (TS, "work", "irregular")


@pytest.mark.parametrize("url", [
    "http://testsource.example/search?q=x",        # no pattern matches
    "http://unrelated.example/work/irregular",     # host not allowlisted for this plugin
    "javascript:alert(1)", "file:///etc/passwd", "not a url",
])
def test_unsupported_urls_are_rejected(plugins, url):
    with pytest.raises(UnsupportedUrl):
        resolve_url(plugins, url)


def test_disabled_plugin_does_not_resolve_urls(plugins):
    plugins.disable(TS)
    with pytest.raises(UnsupportedUrl):
        resolve_url(plugins, "http://testsource.example/work/irregular")


def test_resolved_url_preview_uses_the_normal_matching_flow(db, plugins, cache):
    work_id = new_id()
    db.execute("INSERT INTO works (id, display_title, content_type, created_at, updated_at) VALUES (?,?,?,?,?)",
               (work_id, "The Irregular Chronicle", "manga", NOW, NOW))
    index_work(db, work_id)
    sources = FakeSources({(TS, "work"): WorkDetails(title="The Irregular Chronicle", content_type="manga", language="en")})
    from oneshelf.search.url_resolve import UrlResolver

    preview = asyncio.run(UrlResolver(db, plugins, sources).preview("http://testsource.example/work/irregular"))
    assert preview.result.work_id == work_id and preview.result.soft is True
    assert preview.result.provenance[0].source_id == TS
    assert db.execute("SELECT count(*) FROM source_listings").fetchone()[0] == 0  # preview persists nothing


# -- §31 Home discovery semantics -------------------------------------------------------------------

def trending_result(*titles):
    return ListResult("trending", [Listing(listing_key=t, title=t, content_type="manga", language="en") for t in titles],
                      True, Evidence(pages=1, stop_reason="single_response"))


def test_trending_is_hidden_without_source_data(db, cache):
    home = HomeService(db, FakeSources(capabilities={"s": {"search"}}), cache)
    sections = asyncio.run(home.sections())
    assert sections.trending == [] and sections.latest == []


def test_trending_and_latest_come_from_their_own_capabilities(db, cache):
    sources = FakeSources(responses={("s", "trending"): trending_result("Hot One"),
                                     ("s", "latest"): trending_result("Fresh Chapter")},
                          capabilities={"s": {"trending", "latest"}})
    sections = asyncio.run(HomeService(db, sources, cache).sections())
    assert [r.title for r in sections.trending] == ["Hot One"]
    assert [r.title for r in sections.latest] == ["Fresh Chapter"]
    assert sorted(c[1] for c in sources.calls) == ["latest", "trending"]


def test_recently_added_means_recently_added_to_my_shelf(db, cache):
    ids = []
    for index, title in enumerate(["First", "Second", "Third"]):
        work_id = new_id()
        db.execute("INSERT INTO works (id, display_title, created_at, updated_at) VALUES (?,?,?,?)",
                   (work_id, title, NOW, NOW))
        db.execute("INSERT INTO shelf_entries (work_id, added_at) VALUES (?, ?)",
                   (work_id, f"2026-09-1{index}T00:00:00+00:00"))
        ids.append(work_id)
    sections = asyncio.run(HomeService(db, FakeSources(), cache).sections())
    assert [w.work_id for w in sections.recently_added] == list(reversed(ids))


def test_hero_prefers_continue_reading_then_pinned_and_never_calls_a_source(db, cache):
    sources = FakeSources(capabilities={"s": {"trending"}}, responses={("s", "trending"): trending_result("Hot")})
    pinned, reading = new_id(), new_id()
    for work_id, title in ((pinned, "Pinned Work"), (reading, "Reading Work")):
        db.execute("INSERT INTO works (id, display_title, created_at, updated_at) VALUES (?,?,?,?)", (work_id, title, NOW, NOW))
        db.execute("INSERT INTO shelf_entries (work_id, added_at, is_pinned) VALUES (?, ?, ?)",
                   (work_id, NOW, 1 if work_id == pinned else 0))
    track = new_id()
    db.execute("INSERT INTO source_tracks (id, work_id, source_id, language, kind, created_at) VALUES (?,?,?,?,?,?)",
               (track, reading, "local", "en", "local", NOW))
    unit = new_id()
    db.execute("INSERT INTO reading_units (id, track_id, source_unit_key, unit_type, source_order, first_seen_at)"
               " VALUES (?,?,?,?,?,?)", (unit, track, "u1", "chapter", 1, NOW))
    db.execute("INSERT INTO reading_state (reading_unit_id, read_state, fraction, updated_at) VALUES (?, 'partial', 0.4, ?)",
               (unit, NOW))
    home = HomeService(db, sources, cache)
    hero = asyncio.run(home.hero())
    assert hero.reason == "continue_reading" and hero.work_id == reading
    assert sources.calls == []
    db.execute("UPDATE reading_state SET read_state = 'read', fraction = 1.0 WHERE reading_unit_id = ?", (unit,))
    hero = asyncio.run(home.hero())
    assert hero.reason == "pinned" and hero.work_id == pinned
    assert sources.calls == []


def test_hero_falls_back_to_cached_discovery_without_network(db, cache):
    sources = FakeSources(capabilities={"s": {"trending"}}, responses={("s", "trending"): trending_result("Cached Hot")})
    asyncio.run(HomeService(db, sources, cache).sections())  # fills the discovery cache
    calls_before = len(sources.calls)
    hero = asyncio.run(HomeService(db, sources, cache).hero())
    assert hero.reason == "cached_discovery" and hero.title == "Cached Hot"
    assert len(sources.calls) == calls_before


def test_home_sections_are_empty_without_fabricated_data(db, cache):
    sections = asyncio.run(HomeService(db, FakeSources(), cache).sections())
    assert sections.trending == [] and sections.latest == [] and sections.recently_added == []
    assert sections.continue_reading == []
    assert asyncio.run(HomeService(db, FakeSources(), cache).hero()) is None
