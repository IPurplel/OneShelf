"""Master §7: Discovery Cache — namespaced by source and plugin version, TTL + cap, no query history."""
from datetime import timedelta

import pytest

from oneshelf.search.cache import DiscoveryCache


@pytest.fixture
def cache(tmp_path):
    clock = {"now": 0.0}
    c = DiscoveryCache(tmp_path / "cache.db", clock=lambda: clock["now"])
    yield c, clock
    c.close()


def test_hit_miss_and_ttl(cache):
    c, clock = cache
    c.put("mangadex", "1.0.0", "search", "solo leveling", {"items": [1, 2]})
    assert c.get("mangadex", "1.0.0", "search", "solo leveling") == {"items": [1, 2]}
    clock["now"] += timedelta(days=8).total_seconds()
    assert c.get("mangadex", "1.0.0", "search", "solo leveling") is None


def test_plugin_version_change_invalidates_cached_parses(cache):
    c, _ = cache
    c.put("mangadex", "1.0.0", "search", "q", {"items": [1]})
    assert c.get("mangadex", "1.1.0", "search", "q") is None
    assert c.get("mangadex", "1.0.0", "search", "q") == {"items": [1]}


def test_single_record_per_source_listing(cache):
    c, _ = cache
    c.put("mangadex", "1.0.0", "listing", "abc", {"title": "Old", "cover": None})
    c.put("mangadex", "1.0.0", "listing", "abc", {"title": "New", "cover": "x.png"})
    assert c.get("mangadex", "1.0.0", "listing", "abc") == {"title": "New", "cover": "x.png"}
    assert c.count() == 1


def test_lru_eviction_respects_the_cap(tmp_path):
    clock = {"now": 0.0}
    c = DiscoveryCache(tmp_path / "cache.db", cap_bytes=4000, clock=lambda: clock["now"])
    for i in range(20):
        clock["now"] += 1
        c.put("s", "1.0.0", "search", f"q{i}", {"payload": "x" * 400})
    assert c.total_bytes() <= 4000 and c.count() < 20
    assert c.get("s", "1.0.0", "search", "q19") is not None  # newest kept
    assert c.get("s", "1.0.0", "search", "q0") is None       # oldest evicted
    c.close()


def test_clear_source_and_clear_all(cache):
    c, _ = cache
    c.put("a", "1.0.0", "search", "q", {"x": 1})
    c.put("b", "1.0.0", "search", "q", {"x": 1})
    c.clear_source("a")
    assert c.get("a", "1.0.0", "search", "q") is None and c.get("b", "1.0.0", "search", "q") == {"x": 1}
    c.clear()
    assert c.count() == 0


def test_query_text_is_not_stored(tmp_path):
    c = DiscoveryCache(tmp_path / "cache.db")
    c.put("mangadex", "1.0.0", "search", "my private search phrase", {"items": []})
    c.close()
    raw = (tmp_path / "cache.db").read_bytes()
    assert b"my private search phrase" not in raw
