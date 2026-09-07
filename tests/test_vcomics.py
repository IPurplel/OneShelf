"""The vcomics/Astro platform adapter (azoramoon.com).

Fixtures are trimmed copies of real pages, keeping the site's own encoding: the
chapter list lives in an ``astro-island`` props attribute as HTML-escaped JSON
where every value is wrapped in Astro's ``[type, payload]`` pair. Rebuilding
that shape by hand is exactly how an adapter passes its tests and then fails on
the live site, so none of it is invented.
"""

from __future__ import annotations

import pytest

from app.adapters import registry
from app.adapters.base import AdapterError
from app.adapters.vcomics import VComicsAdapter, _relevant
from app.models import Chapter

from .conftest import FakeSessionManager, fixture

SITE = "https://azoramoon.com"
SLUG = "a-fortune-telling-princess"
SERIES = f"{SITE}/series/{SLUG}"


@pytest.fixture
def sessions():
    return FakeSessionManager(
        pages={
            SERIES: fixture("vcomics_series.html"),
            f"{SERIES}/chapter-0": fixture("vcomics_reader.html"),
            f"{SERIES}/chapter-164": fixture("vcomics_locked.html"),
        }
    )


# ------------------------------------------------------------- identification


def test_matches_its_known_hosts():
    assert VComicsAdapter.matches(SERIES)
    assert VComicsAdapter.matches("https://azorafly.com/series/x")
    assert not VComicsAdapter.matches("https://example.net/series/x")


def test_matches_an_unknown_install_by_its_markup():
    """The platform is recognisable, so a mirror on a new domain still works."""
    page = fixture("vcomics_series.html")
    assert VComicsAdapter.matches("https://newmirror.example/series/x", page)
    assert not VComicsAdapter.matches(
        "https://newmirror.example/series/x", "<html><body>nothing</body></html>")


def test_the_registry_picks_it_for_azoramoon():
    assert registry.select(SERIES) is VComicsAdapter


async def test_resolving_a_known_host_never_renders_the_page():
    """The site needs no browser — and on a filtered network cannot use one."""
    class Forbidden:
        async def fetch_html(self, url, **kwargs):
            raise AssertionError("resolving azoramoon rendered the page")

    assert isinstance(await registry.resolve(SERIES, Forbidden()), VComicsAdapter)


# -------------------------------------------------------------------- series


async def test_series_metadata_comes_from_the_island(sessions):
    series = await VComicsAdapter(sessions).fetch_series(SERIES)

    assert series.title == "A fortune-telling princess"
    assert series.cover_url.endswith(".jpg")
    assert "الأشباح" in (series.description or "")
    assert series.site_id == "1257"
    assert series.source == "vcomics"


async def test_a_chapter_url_still_resolves_the_series(sessions):
    series = await VComicsAdapter(sessions).fetch_series(f"{SERIES}/chapter-0")
    assert series.url == SERIES


async def test_pages_are_fetched_over_plain_http(sessions):
    """No browser: this platform server-renders everything it knows."""
    await VComicsAdapter(sessions).fetch_series(SERIES)
    assert sessions.direct == [SERIES]
    assert sessions.requested == []


async def test_a_page_without_an_island_is_explained(sessions):
    empty = FakeSessionManager(pages={SERIES: "<html><body>hi</body></html>"})
    with pytest.raises(AdapterError, match="no series data"):
        await VComicsAdapter(empty).fetch_series(SERIES)


# ------------------------------------------------------------------ chapters


async def test_every_chapter_is_listed_not_just_the_linked_ones(sessions):
    """The DOM links one chapter; the island holds the whole list."""
    adapter = VComicsAdapter(sessions)
    series = await adapter.fetch_series(SERIES)
    chapters = await adapter.fetch_chapters(series)

    assert [c.number for c in chapters] == ["0", "1", "160", "161"]
    assert [c.index for c in chapters] == [1, 2, 3, 4]
    assert chapters[0].url == f"{SERIES}/chapter-0"
    assert chapters[0].date.startswith("2023-")


async def test_locked_chapters_are_left_out(sessions):
    """Sold for coins: it serves a paywall, so queueing it only fails later."""
    adapter = VComicsAdapter(sessions)
    chapters = await adapter.fetch_chapters(await adapter.fetch_series(SERIES))
    assert all("chapter-164" not in c.url for c in chapters)


async def test_a_wholly_locked_series_says_so():
    page = fixture("vcomics_series.html").replace(
        "&quot;isAccessible&quot;: [0, true]", "&quot;isAccessible&quot;: [0, false]")
    sessions = FakeSessionManager(pages={SERIES: page})
    adapter = VComicsAdapter(sessions)
    series = await adapter.fetch_series(SERIES)
    with pytest.raises(AdapterError, match="locked"):
        await adapter.fetch_chapters(series)


async def test_chapter_numbers_read_as_labels(sessions):
    """JSON gives numbers; a filename wants "161", never "161.0"."""
    adapter = VComicsAdapter(sessions)
    chapters = await adapter.fetch_chapters(await adapter.fetch_series(SERIES))
    assert all(c.number and "." not in c.number for c in chapters)


# --------------------------------------------------------------------- pages


async def test_reader_pages_are_read_in_order(sessions):
    pages = await VComicsAdapter(sessions).fetch_pages(
        Chapter(url=f"{SERIES}/chapter-0", title="c", number="0"))

    assert [p.index for p in pages] == [1, 2, 3]
    assert all(p.url.startswith("https://storage.azorafly.com/") for p in pages)
    assert len({p.url for p in pages}) == 3
    assert all(p.referer == f"{SERIES}/chapter-0" for p in pages)


async def test_a_locked_chapter_is_reported_as_locked(sessions):
    with pytest.raises(AdapterError, match="locked"):
        await VComicsAdapter(sessions).fetch_pages(
            Chapter(url=f"{SERIES}/chapter-164", title="c", number="164"))


async def test_an_empty_reader_is_not_silently_accepted():
    sessions = FakeSessionManager(pages={
        f"{SERIES}/chapter-2": '<html><body><div class="comic-images-wrapper">'
                               "</div></body></html>"})
    with pytest.raises(AdapterError, match="No page images"):
        await VComicsAdapter(sessions).fetch_pages(
            Chapter(url=f"{SERIES}/chapter-2", title="c", number="2"))


# -------------------------------------------------------------------- search

HOME = ('<html><body><script>const RUNTIME_ENV={"PUBLIC_API_URL":'
        '"https://api.azorafly.com","PUBLIC_SITE_LANGUAGE":"ar"};</script>'
        '<astro-island props="{}"></astro-island></body></html>')


def _search_sessions(posts):
    return FakeSessionManager(
        pages={f"{SITE}/": HOME},
        json_routes={"/api/query": {"posts": posts, "totalCount": len(posts)}},
    )


def _post(id_, slug, title, series_type="MANHWA"):
    return {"id": id_, "slug": slug, "postTitle": title,
            "featuredImage": f"https://storage.azorafly.com/{slug}.webp",
            "seriesType": series_type, "seriesStatus": "ONGOING"}


async def test_search_returns_matching_series():
    sessions = _search_sessions([
        _post(1257, SLUG, "A fortune-telling princess"),
        _post(2635, "the-princess-goes-to-the-gym", "The Princess Goes to the Gym"),
    ])
    results = await VComicsAdapter(sessions).search(SITE, "princess")

    assert [r.title for r in results] == [
        "A fortune-telling princess", "The Princess Goes to the Gym"]
    assert results[0].url == SERIES
    assert results[0].site == "azoramoon.com"
    assert results[0].cover_url.endswith(".webp")


async def test_a_query_the_api_cannot_match_returns_nothing():
    """Its search indexes Latin titles only — and does not say so.

    An Arabic term is not rejected but *ignored*: the API answers with the whole
    catalogue, newest first, which looks exactly like a page of results. Every
    site in a multi-site search doing that is how search became noise.
    """
    sessions = _search_sessions([
        _post(2709, "the-villain-wants-to-live1", "The Villain Wants to Live"),
        _post(2708, "myst-might-mayhem1", "Myst, Might, Mayhem"),
    ])
    assert await VComicsAdapter(sessions).search(SITE, "الغريب") == []


async def test_novels_are_not_offered():
    """Prose, not pages: it would parse and then produce an empty archive."""
    sessions = _search_sessions([
        _post(2218, "story-of-banwoldang", "Banwoldang tales", "NOVEL"),
        _post(1, "banwoldang-comic", "Banwoldang comic"),
    ])
    results = await VComicsAdapter(sessions).search(SITE, "banwoldang")
    assert [r.url for r in results] == [f"{SITE}/series/banwoldang-comic"]


async def test_a_site_without_an_api_root_searches_nothing():
    sessions = FakeSessionManager(pages={f"{SITE}/": "<html><body>x</body></html>"})
    assert await VComicsAdapter(sessions).search(SITE, "princess") == []


@pytest.mark.parametrize(
    "query,title,expected",
    [
        ("princess", "A fortune-telling princess", True),
        ("PRINCESS", "A fortune-telling princess", True),
        # Punctuation in the title must not defeat a plain-words query.
        ("fortune telling", "A fortune-telling princess", True),
        ("dragon", "A fortune-telling princess", False),
        ("الغريب", "A fortune-telling princess", False),
        ("", "A fortune-telling princess", False),
    ],
)
def test_relevance_filter(query, title, expected):
    assert _relevant(query, title, "a-fortune-telling-princess") is expected
