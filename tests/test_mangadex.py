"""MangaDex adapter.

The only supported site with a documented public API, so these tests pin the
payload shapes rather than markup. Shapes below match what the live API
returns; they were captured from it, not invented.
"""

from __future__ import annotations

import pytest

from app.adapters.base import AdapterError
from app.adapters.mangadex import MangaDexAdapter, _cover_url, _manga_id, _pick_title
from app.models import Chapter

MID = "801513ba-a712-498c-8f57-cae55b38cc92"


class FakeApi:
    """Stands in for SessionManager, answering by URL substring."""

    def __init__(self, routes, language="ar"):
        self.routes = routes
        self.calls: list[tuple[str, list]] = []

        class _S:
            pass
        self._settings = _S()
        self._settings.language = language

    async def fetch_json_direct(self, url, params=None):
        self.calls.append((url, list(params or [])))
        for key, payload in self.routes.items():
            if key in url:
                return payload
        raise AssertionError(f"no route for {url}")


def _manga(title=None):
    return {
        "id": MID,
        "attributes": {"title": title or {"ja-ro": "Berserk"},
                       "description": {"ar": "وصف", "en": "A dark fantasy."}},
        "relationships": [
            {"type": "author", "attributes": {}},
            {"type": "cover_art", "attributes": {"fileName": "abc.jpg"}},
        ],
    }


def _chapter(cid, number, **attrs):
    base = {"chapter": number, "title": "", "translatedLanguage": "ar",
            "publishAt": "2020-01-01T00:00:00+00:00", "pages": 20}
    base.update(attrs)
    return {"id": cid, "attributes": base}


# ------------------------------------------------------------ identification


def test_matches_only_mangadex():
    assert MangaDexAdapter.matches(f"https://mangadex.org/title/{MID}")
    assert MangaDexAdapter.matches(f"https://MangaDex.org/title/{MID}/berserk")
    assert not MangaDexAdapter.matches("https://example.net/title/x")


async def test_resolving_a_mangadex_url_never_touches_the_browser():
    """The API adapter must not need a browser render to be chosen.

    Fingerprinting is what lets one adapter serve unknown Madara sites, but
    nothing else can be at mangadex.org — and rendering its JavaScript site to
    confirm that made every job depend on a browser it never otherwise uses.
    """
    from app.adapters import resolve

    class Forbidden:
        async def fetch_html(self, url, **kwargs):
            raise AssertionError("resolving a mangadex.org URL rendered the site")

    adapter = await resolve(f"https://mangadex.org/title/{MID}", Forbidden())
    assert isinstance(adapter, MangaDexAdapter)


def test_id_is_read_from_any_url_shape():
    assert _manga_id(f"https://mangadex.org/title/{MID}") == MID
    assert _manga_id(f"https://mangadex.org/title/{MID}/berserk-slug") == MID
    assert _manga_id(f"https://mangadex.org/chapter/{MID}") == MID


def test_a_url_without_an_id_is_rejected_clearly():
    with pytest.raises(AdapterError, match="not a MangaDex title URL"):
        _manga_id("https://mangadex.org/titles")


# ------------------------------------------------------------------ metadata


def test_title_prefers_latin_script():
    """The title becomes a folder name, so a romanised form is preferable."""
    assert _pick_title(_manga({"ja": "ベルセルク", "ja-ro": "Berserk"})) == "Berserk"
    assert _pick_title(_manga({"en": "Berserk", "ja-ro": "Beruseruku"})) == "Berserk"
    # Anything is better than nothing when no preferred key exists.
    assert _pick_title(_manga({"de": "Berserk DE"})) == "Berserk DE"


def test_cover_is_built_from_the_relationship():
    assert _cover_url(_manga()) == \
        f"https://uploads.mangadex.org/covers/{MID}/abc.jpg.512.jpg"


def test_missing_cover_is_not_an_error():
    item = _manga()
    item["relationships"] = [{"type": "author", "attributes": {}}]
    assert _cover_url(item) is None


async def test_series_uses_the_configured_language_for_description():
    api = FakeApi({f"/manga/{MID}": {"data": _manga()}}, language="ar")
    series = await MangaDexAdapter(api).fetch_series(f"https://mangadex.org/title/{MID}")

    assert series.title == "Berserk"
    assert series.description == "وصف"
    assert series.site_id == MID


# ------------------------------------------------------------------ chapters


async def test_chapters_request_the_configured_language():
    api = FakeApi({"/feed": {"data": [_chapter("c1", "1")], "total": 1}}, language="ar")
    adapter = MangaDexAdapter(api)
    from app.models import Series
    await adapter.fetch_chapters(
        Series(url=f"https://mangadex.org/title/{MID}", title="B",
               source="mangadex", site_id=MID))

    _url, params = api.calls[0]
    assert ("translatedLanguage[]", "ar") in params


async def test_unavailable_and_external_chapters_are_skipped():
    """They carry no pages here, so queueing them only creates failures."""
    api = FakeApi({"/feed": {"data": [
        _chapter("c1", "1"),
        _chapter("c2", "2", externalUrl="https://elsewhere.example/read"),
        _chapter("c3", "3", isUnavailable=True),
    ], "total": 3}})
    from app.models import Series
    chapters = await MangaDexAdapter(api).fetch_chapters(
        Series(url=f"https://mangadex.org/title/{MID}", title="B",
               source="mangadex", site_id=MID))

    assert [c.number for c in chapters] == ["1"]


async def test_chapters_are_ordered_and_indexed():
    api = FakeApi({"/feed": {"data": [
        _chapter("c10", "10"), _chapter("c2", "2"), _chapter("c1", "1"),
    ], "total": 3}})
    from app.models import Series
    chapters = await MangaDexAdapter(api).fetch_chapters(
        Series(url=f"https://mangadex.org/title/{MID}", title="B",
               source="mangadex", site_id=MID))

    # 10 must not sort between 1 and 2.
    assert [c.number for c in chapters] == ["1", "2", "10"]
    assert [c.index for c in chapters] == [1, 2, 3]


async def test_no_chapters_in_that_language_says_so():
    api = FakeApi({"/feed": {"data": [], "total": 0}}, language="ar")
    from app.models import Series
    with pytest.raises(AdapterError, match="No chapters in 'ar'"):
        await MangaDexAdapter(api).fetch_chapters(
            Series(url=f"https://mangadex.org/title/{MID}", title="B",
                   source="mangadex", site_id=MID))


# --------------------------------------------------------------------- pages


async def test_pages_are_built_from_the_at_home_payload():
    api = FakeApi({"/at-home/server/": {
        "baseUrl": "https://cdn.mangadex.network",
        "chapter": {"hash": "HASH", "data": ["1.jpg", "2.jpg"],
                    "dataSaver": ["s1.jpg", "s2.jpg"]},
    }})
    pages = await MangaDexAdapter(api).fetch_pages(
        Chapter(url=f"https://mangadex.org/chapter/{MID}", title="c", number="1"))

    assert [p.url for p in pages] == [
        "https://cdn.mangadex.network/data/HASH/1.jpg",
        "https://cdn.mangadex.network/data/HASH/2.jpg",
    ]
    # dataSaver is a recompressed copy; using it would undo lossless storage.
    assert not any("s1.jpg" in p.url for p in pages)
    assert [p.index for p in pages] == [1, 2]


async def test_page_urls_are_declared_perishable_and_can_be_relisted():
    """Each URL names one MangaDex@Home node and carries a short-lived token.

    So a failed page is worth asking about again — the queue only does that
    for adapters that say their URLs expire.
    """
    api = FakeApi({"/at-home/server/": {
        "baseUrl": "https://node1.mangadex.network",
        "chapter": {"hash": "HASH", "data": ["1.jpg"]},
    }})
    adapter = MangaDexAdapter(api)
    chapter = Chapter(url=f"https://mangadex.org/chapter/{MID}", title="c", number="1")

    assert adapter.pages_expire is True

    await adapter.fetch_pages(chapter)
    await adapter.refresh_pages(chapter)

    # A fresh at-home request, not a replay of the list we already had.
    requested = [url for url, _ in api.calls]
    assert requested == [f"https://api.mangadex.org/at-home/server/{MID}"] * 2


async def test_an_empty_at_home_response_is_an_error():
    api = FakeApi({"/at-home/server/": {"baseUrl": "", "chapter": {}}})
    with pytest.raises(AdapterError, match="no pages"):
        await MangaDexAdapter(api).fetch_pages(
            Chapter(url=f"https://mangadex.org/chapter/{MID}", title="c", number="1"))


# -------------------------------------------------------------------- search


async def test_search_returns_titles_and_covers():
    api = FakeApi({"/manga": {"data": [_manga()]}})
    results = await MangaDexAdapter(api).search("https://mangadex.org", "berserk")

    assert results[0].title == "Berserk"
    assert results[0].url == f"https://mangadex.org/title/{MID}"
    assert results[0].site == "mangadex.org"
    assert results[0].cover_url.endswith(".512.jpg")
    # Nothing to explain: the displayed title is the one that matched.
    assert results[0].alt_title is None


async def test_search_shows_the_alternative_title_that_matched():
    """An Arabic query legitimately hits a series shown under a romanised name.

    MangaDex indexes every name a series is known by, so "الغريب" matches
    "مغامرة جوجو الغريبة" — and displaying only "JoJo no Kimyou na Bouken"
    makes a correct hit look like the query was ignored.
    """
    item = _manga({"ja-ro": "JoJo no Kimyou na Bouken: Part 1 - Phantom Blood"})
    item["attributes"]["altTitles"] = [
        {"en": "JoJo's Bizarre Adventure Part 1"},
        {"ar": "مغامرة جوجو الغريبة الجزء 1: دماء الشبح"},
    ]
    api = FakeApi({"/manga": {"data": [item]}})

    results = await MangaDexAdapter(api).search("https://mangadex.org", "الغريب")

    assert results[0].title.startswith("JoJo no Kimyou na Bouken")
    assert results[0].alt_title == "مغامرة جوجو الغريبة الجزء 1: دماء الشبح"
    assert results[0].to_dict()["alt_title"] == results[0].alt_title


async def test_a_matching_shown_title_needs_no_explanation():
    item = _manga({"en": "Berserk"})
    item["attributes"]["altTitles"] = [{"ar": "بيرسيرك"}]
    api = FakeApi({"/manga": {"data": [item]}})

    results = await MangaDexAdapter(api).search("https://mangadex.org", "berserk")
    assert results[0].alt_title is None


# ----------------------------------------------------------- author search
# /manga?title= matches titles only, so a query that is a person's name finds
# nothing they wrote. Measured live before the change: "Kentaro Miura" returned
# a memorial anthology and Berserk Gaiden, and not Berserk. Authors need their
# own lookup, and it takes two hops because the manga endpoint filters on
# author *ids* and has no free-text author parameter.

AUTHOR_ID = "5863578d-4e4f-4b57-b64d-1dd45a893cb0"


def _authored(manga_id, title, author="Miura Kentarou"):
    return {
        "id": manga_id,
        "attributes": {"title": {"en": title}, "description": {}},
        "relationships": [
            {"type": "author", "attributes": {"name": author}},
            {"type": "cover_art", "attributes": {"fileName": "abc.jpg"}},
        ],
    }


class RoutingApi(FakeApi):
    """Answers /author and /manga separately, and records the manga params."""

    def __init__(self, authors, by_author, by_title):
        super().__init__({})
        self._authors = authors
        self._by_author = by_author
        self._by_title = by_title

    async def fetch_json_direct(self, url, params=None):
        params = list(params or [])
        self.calls.append((url, params))
        if "/author" in url:
            return {"data": self._authors}
        keys = {k for k, _ in params}
        return {"data": self._by_author if "authors[]" in keys else self._by_title}


async def test_search_finds_what_the_author_wrote():
    api = RoutingApi(
        authors=[{"id": AUTHOR_ID}],
        by_author=[_authored("m1", "Berserk")],
        by_title=[],
    )
    results = await MangaDexAdapter(api).search("https://mangadex.org", "Kentaro Miura")

    assert [r.title for r in results] == ["Berserk"]
    assert results[0].author == "Miura Kentarou"
    # The name lookup is fuzzy at MangaDex's end -- "Kentaro Miura" finds
    # "Miura Kentarou" -- which is why it cannot be done by matching ourselves.
    ids = [dict(p).get("authors[]") for u, p in api.calls if "authors[]" in dict(p)]
    assert ids == [AUTHOR_ID]


async def test_a_manga_matching_both_ways_is_returned_once():
    api = RoutingApi(
        authors=[{"id": AUTHOR_ID}],
        by_author=[_authored("m1", "Berserk"), _authored("m2", "DUR-AN-KI")],
        by_title=[_authored("m1", "Berserk")],
    )
    results = await MangaDexAdapter(api).search("https://mangadex.org", "berserk")

    assert [r.title for r in results] == ["Berserk", "DUR-AN-KI"]


async def test_no_author_of_that_name_skips_the_second_hop():
    api = RoutingApi(authors=[], by_author=[], by_title=[_authored("m1", "Berserk")])
    await MangaDexAdapter(api).search("https://mangadex.org", "berserk")

    assert not any("authors[]" in dict(p) for _, p in api.calls), \
        "asking for manga by nobody would return the whole catalogue"


async def test_a_broken_author_lookup_does_not_lose_the_title_results():
    """One half failing is not a failed search; the author half is the optional one."""
    class HalfBroken(RoutingApi):
        async def fetch_json_direct(self, url, params=None):
            if "/author" in url:
                raise RuntimeError("502 from the author endpoint")
            return await super().fetch_json_direct(url, params)

    api = HalfBroken(authors=[], by_author=[], by_title=[_authored("m1", "Berserk")])
    results = await MangaDexAdapter(api).search("https://mangadex.org", "berserk")

    assert [r.title for r in results] == ["Berserk"]


async def test_the_limit_covers_both_halves_together():
    api = RoutingApi(
        authors=[{"id": AUTHOR_ID}],
        by_author=[_authored(f"a{i}", f"By {i}") for i in range(5)],
        by_title=[_authored(f"t{i}", f"Titled {i}") for i in range(5)],
    )
    results = await MangaDexAdapter(api).search("https://mangadex.org", "x", limit=3)

    assert len(results) == 3
