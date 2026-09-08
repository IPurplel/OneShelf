"""/api/search: the content type is required, and it decides which sites run.

Searching everything at once mixed novels into manga queries and manga into
book queries. These tests pin the two properties that fixes: a request without a
valid type is refused, and a request with one only ever touches sites serving
that kind.

No lifespan is started, so nothing here opens a browser, a database or a proxy —
the endpoint's collaborators are supplied directly.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app import main
from app.adapters import ADAPTERS, CONTENT_TYPES
from app.models import SearchResult

MANGA_SITE = "https://mangadex.org"
MANGA_SITE_2 = "https://azoramoon.com"
BOOK_SITE = "https://8ghrb.com"
COMICS_SITE = "https://comix.to"


class AdapterInterface:
    """The parts of ``Adapter`` that ``/api/search`` actually calls.

    Shared by every stub in this module. A test double has to carry the whole
    interface it stands in for: when ``content_type_for`` was added and these
    stubs did not have it, each one raised AttributeError inside the endpoint's
    broad per-site handler, which reported it as a site "error" — twenty tests
    failed in a way that looked like a routing bug rather than a missing stub
    method.
    """

    content_type: str = "manga"

    def content_type_for(self, url: str) -> str:
        """The kind *this site* serves; for a stub, always its own."""
        return self.content_type


class StubAdapter(AdapterInterface):
    """Answers any query with one hit, and records that it was asked."""

    def __init__(self, content_type: str, adapter_id: str) -> None:
        self.content_type = content_type
        self.id = adapter_id


    async def search(self, site, query, limit=12):
        return [SearchResult(title=f"{query} on {site}", url=f"{site}/x",
                             source=self.id, site=site.split("//")[-1])]


#: What each test site's adapter turns out to be once resolved.
RESOLVED = {
    MANGA_SITE: StubAdapter("manga", "mangadex"),
    MANGA_SITE_2: StubAdapter("manga", "vcomics"),
    BOOK_SITE: StubAdapter("book", "books"),
    COMICS_SITE: StubAdapter("comics", "comix"),
}


@pytest.fixture
def client(monkeypatch):
    asked: list[str] = []

    async def fake_resolve(site, sessions):
        asked.append(site)
        return RESOLVED[site]

    monkeypatch.setattr(main, "resolve_adapter", fake_resolve)
    monkeypatch.setattr(main.settings, "search_sites",
                        [MANGA_SITE, MANGA_SITE_2, BOOK_SITE, COMICS_SITE])
    main.state["sessions"] = object()   # never used: resolve is stubbed

    # Deliberately not entered as a context manager: that would run the app's
    # lifespan, which opens a database, a DPI-bypass proxy and eventually a
    # browser. None of that is needed to test a query parameter.
    test_client = TestClient(main.app)
    test_client.asked = asked
    return test_client


# ------------------------------------------------------------- the type gate


def test_a_search_without_a_type_is_refused(client):
    response = client.get("/api/search", params={"q": "berserk"})
    assert response.status_code == 400
    assert "content type is required" in response.json()["detail"]


def test_a_blank_type_is_refused(client):
    response = client.get("/api/search", params={"q": "berserk", "type": "  "})
    assert response.status_code == 400


def test_an_unknown_type_is_refused(client):
    response = client.get("/api/search", params={"q": "berserk", "type": "audio"})
    assert response.status_code == 400
    assert "audio" in response.json()["detail"]


def test_the_type_is_case_insensitive(client):
    response = client.get("/api/search", params={"q": "berserk", "type": "MANGA"})
    assert response.status_code == 200
    assert response.json()["type"] == "manga"


# ---------------------------------------------------------------- filtering


def test_a_manga_search_never_touches_book_or_comic_sites(client):
    response = client.get("/api/search", params={"q": "berserk", "type": "manga"})
    body = response.json()

    assert [s["site"] for s in body["sites"]] == [MANGA_SITE, MANGA_SITE_2]
    assert client.asked == [MANGA_SITE, MANGA_SITE_2]
    assert all(r["content_type"] == "manga" for r in body["results"])


def test_a_book_search_only_asks_book_sites(client):
    response = client.get("/api/search", params={"q": "agnes", "type": "book"})
    body = response.json()

    assert [s["site"] for s in body["sites"]] == [BOOK_SITE]
    assert client.asked == [BOOK_SITE]
    assert [r["content_type"] for r in body["results"]] == ["book"]


def test_a_comics_search_only_asks_comic_sites(client):
    response = client.get("/api/search", params={"q": "batman", "type": "comics"})
    body = response.json()

    assert [s["site"] for s in body["sites"]] == [COMICS_SITE]
    assert client.asked == [COMICS_SITE]
    assert [r["content_type"] for r in body["results"]] == ["comics"]


def test_a_site_that_turns_out_to_serve_something_else_is_dropped(client, monkeypatch):
    """The URL-only guess is a filter; the resolved page has the last word."""
    async def resolve_to_a_book(site, sessions):
        return RESOLVED[BOOK_SITE]

    monkeypatch.setattr(main, "resolve_adapter", resolve_to_a_book)
    body = client.get("/api/search",
                      params={"q": "berserk", "type": "manga"}).json()

    assert body["results"] == []


def test_a_short_query_still_reports_the_type(client):
    body = client.get("/api/search", params={"q": "a", "type": "book"}).json()
    # Every exit from the endpoint answers in the same shape, including the
    # cheap ones. A short query used to return a smaller dict than a real
    # search, so the fields the UI reads to *explain* an empty result were
    # missing in exactly the cases where it needed them.
    assert body == {
        "query": "a", "type": "book", "results": [], "sites": [],
        "kinds": [], "answered": 0, "searched": 0, "merged": 0,
    }


def test_results_carry_their_type_for_badging(client):
    body = client.get("/api/search", params={"q": "agnes", "type": "book"}).json()
    assert body["results"], "expected a hit"
    for result in body["results"]:
        assert result["content_type"] == "book"
        assert result["url"] and result["title"]


# --------------------------------------------------------- adapter metadata


def test_every_adapter_declares_what_it_serves():
    """A new adapter without one would be silently unreachable from search."""
    missing = [a.id for a in ADAPTERS if a.content_type not in CONTENT_TYPES]
    assert not missing, f"adapters missing a valid content_type: {missing}"


def test_the_known_adapters_are_filed_correctly():
    kinds = {a.id: a.content_type for a in ADAPTERS}
    assert kinds == {
        "mangadex": "manga",
        "aco": "book",
        "ao3": "book",
        "royalroad": "book",
        "scribblehub": "book",
        "rewayat": "book",
        "riwayatarab": "book",
        "sunovels": "book",
        "wuxiabox": "book",
        "webtoons": "comics",
        "gutenberg": "book",
        "vcomics": "manga",
        "mangathemesia": "manga",
        "madara": "manga",
        "comix": "comics",
        "blogger": "comics",
        "books": "book",
        "generic": "manga",
    }


def test_the_adapter_listing_exposes_the_type():
    from app.adapters import describe

    assert all(row["content_type"] in CONTENT_TYPES for row in describe())


# ---------------------------------------------------------------- relevance
# These sites match on descriptions and word stems, so their own answer to
# "berserk" contains a lot that is not Berserk. Measured live across the eight
# configured manga sites: 26 hits, the real series at positions 1, 7 and 20,
# with `Magic Emperor` and `The Hero Becomes Duke's Eldest Son` — not one word
# shared with the query — ranked above two of them.

from app.adapters.base import (  # noqa: E402
    SCORE_EXACT,
    SCORE_IRRELEVANT,
    SCORE_PREFIX,
    SCORE_SUBSTRING,
    SCORE_UNJUDGEABLE,
    SCORE_WORD,
    SCORE_WORD_PREFIX,
    relevance,
)


@pytest.mark.parametrize("title, expected", [
    ("Berserk", SCORE_EXACT),
    ("berserk", SCORE_EXACT),               # case is not a signal
    ("Berserk!", SCORE_EXACT),              # nor is trailing punctuation
    ("Berserk Gaiden", SCORE_PREFIX),
    ("Berserk of Gluttony", SCORE_PREFIX),
    ("Berserk: Shinen no Kami 2", SCORE_PREFIX),
    ("Berserk - GuideBook", SCORE_PREFIX),
    ("Boushoku no Berserk", SCORE_WORD),
    ("Her Ladyship's Going Berserk Again", SCORE_WORD),
    ("The Berserker's Second Playthrough", SCORE_WORD_PREFIX),
    ("Real Play: Berserker", SCORE_WORD_PREFIX),
    ("Magic Emperor", SCORE_IRRELEVANT),
    ("The Hero Becomes Duke's Eldest Son", SCORE_IRRELEVANT),
])
def test_hits_are_scored_by_how_well_the_title_answers_the_query(title, expected):
    assert relevance("berserk", title) == expected


def test_an_alternative_title_matches_but_ranks_just_below_the_real_one():
    """MangaDex indexes every translation and shows only one of them."""
    direct = relevance("berserk", "Berserk")
    via_alt = relevance("berserk", "Kentaro Miura Memorial Manga", "Berserk")

    assert via_alt < direct
    assert via_alt > relevance("berserk", "Boushoku no Berserk")


def test_a_query_in_another_script_is_never_judged_as_irrelevant():
    """The one case text cannot settle, and the one that must not be dropped.

    These sites index names in several writing systems and display one. An
    English query landing on a series shown under an Arabic title has nothing in
    common on the page, yet the site returned it because it matched a name we
    are not being shown.
    """
    assert relevance("berserk", "\u0647\u062c\u0648\u0645 \u0627\u0644\u0639\u0645\u0627\u0644\u0642\u0629") \
        == SCORE_UNJUDGEABLE
    # ...but a Latin title sharing no word with a Latin query *is* judged.
    assert relevance("berserk", "Magic Emperor") == SCORE_IRRELEVANT


def test_arabic_queries_are_scored_the_same_way():
    assert relevance("\u0627\u0644\u063a\u0631\u064a\u0628", "\u0627\u0644\u063a\u0631\u064a\u0628") == SCORE_EXACT
    # The alt title that actually matched, romanised display title.
    assert relevance(
        "\u0627\u0644\u063a\u0631\u064a\u0628", "JoJo's Bizarre Adventure",
        "\u0645\u063a\u0627\u0645\u0631\u0629 \u062c\u0648\u062c\u0648 \u0627\u0644\u063a\u0631\u064a\u0628\u0629",
    ) > SCORE_IRRELEVANT


def test_a_substring_buried_inside_a_word_still_counts_but_barely():
    assert relevance("serk", "Berserk") == SCORE_SUBSTRING


class RankingAdapter(AdapterInterface):
    """Returns a fixed set of hits regardless of the query."""

    content_type = "manga"
    id = "mangadex"

    def __init__(self, titles):
        self._titles = titles

    async def search(self, site, query, limit=12):
        host = site.split("//")[-1]
        return [SearchResult(title=t, url=f"{site}/{i}", source=self.id, site=host)
                for i, t in enumerate(self._titles)]


def test_the_exact_match_leads_and_noise_is_dropped(client, monkeypatch):
    """End to end: the ordering and the filtering the endpoint is there for."""
    hits = {
        MANGA_SITE: ["Magic Emperor", "Berserk of Gluttony", "Berserk"],
        MANGA_SITE_2: ["The Berserker's Second Playthrough", "Berserk"],
    }

    async def resolve(site, sessions):
        return RankingAdapter(hits[site])

    monkeypatch.setattr(main, "resolve_adapter", resolve)
    body = client.get("/api/search",
                      params={"q": "berserk", "type": "manga"}).json()

    titles = [r["title"] for r in body["results"]]

    assert "Magic Emperor" not in titles, "shares no word with the query"
    # Both sites' exact match leads — but as *one* card now, not two: the same
    # work from two sites is one work. The sources are kept on the record.
    assert titles[0] == "Berserk"
    assert titles.count("Berserk") == 1, "the duplicate should have merged"
    assert body["merged"] >= 1
    berserk = next(r for r in body["results"] if r["title"] == "Berserk")
    assert len(berserk["sources"]) == 2, "both sites must stay reachable"
    assert titles[1] == "Berserk of Gluttony"
    assert titles[-1] == "The Berserker's Second Playthrough"


def test_a_sites_count_reflects_what_survived_filtering(client, monkeypatch):
    """Otherwise the UI credits a site that contributed nothing usable."""
    async def resolve(site, sessions):
        return RankingAdapter(["Magic Emperor", "Berserk"])

    monkeypatch.setattr(main, "resolve_adapter", resolve)
    body = client.get("/api/search",
                      params={"q": "berserk", "type": "manga"}).json()

    assert all(s["count"] == 1 for s in body["sites"])
    # Each site is still credited with the hit it contributed, even though the
    # two identical hits render as a single merged card.
    assert len(body["results"]) == 1
    assert len(body["results"][0]["sources"]) == 2


# ------------------------------------------------------------- the limit


class LimitRecordingAdapter(AdapterInterface):
    """Records the limit it was asked for, and answers with nothing."""

    content_type = "manga"
    id = "mangadex"
    seen: list[int] = []

    async def search(self, site, query, limit=12):
        LimitRecordingAdapter.seen.append(limit)
        return []


@pytest.fixture
def limits(client, monkeypatch):
    LimitRecordingAdapter.seen = []

    async def resolve(site, sessions):
        return LimitRecordingAdapter()

    monkeypatch.setattr(main, "resolve_adapter", resolve)

    def ask(**params):
        client.get("/api/search", params={"q": "berserk", "type": "manga", **params})
        return LimitRecordingAdapter.seen

    return ask


@pytest.mark.parametrize("asked, expected", [
    (8, 8),                             # the default passes through
    (50, main.MAX_SEARCH_RESULTS),
    (100000, main.MAX_SEARCH_RESULTS),  # ...and no further
    (0, 1),
    (-5, 1),                            # a negative limit is not a page size
])
def test_the_search_limit_is_clamped_before_it_reaches_a_site(limits, asked, expected):
    """This number is handed to every adapter, several of which page to reach it.

    Unclamped, one query string sent each site — each behind a browser that may
    have to clear a bot check — off to walk its whole catalogue.
    """
    assert set(limits(limit=asked)) == {expected}


# ------------------------------------------------- abandoning a search
# Typing a six-letter query fires a search per pause -- measured on a real
# session: ten searches for one word. The UI drops the stale *responses*, but
# ASGI does not cancel a handler when the caller hangs up, so each abandoned
# search ran to its full 20s timeout. Everything here shares one rate limiter,
# so that time came straight out of the query the user was still waiting for.
# Measured against the live server: a request killed at 4s went on to fetch 16
# more book pages; with the fix, 1 (the one already in flight).

import asyncio  # noqa: E402


class FakeRequest:
    """Reports the client gone after `after` polls."""

    def __init__(self, after: int | None = None) -> None:
        self._after = after
        self.polls = 0

    async def is_disconnected(self) -> bool:
        self.polls += 1
        return self._after is not None and self.polls > self._after


async def test_a_completed_search_returns_its_results():
    async def work(value):
        await asyncio.sleep(0)
        return value

    request = FakeRequest()
    got = await main._gather_while_connected(request, [work(1), work(2)], poll=0.01)

    assert got == [1, 2]


async def test_a_disconnect_cancels_the_work_in_flight():
    started = asyncio.Event()
    cancelled = False

    async def slow():
        nonlocal cancelled
        started.set()
        try:
            await asyncio.sleep(30)     # the 20s-timeout site search
        except asyncio.CancelledError:
            cancelled = True
            raise

    request = FakeRequest(after=1)
    with pytest.raises(main.ClientGone):
        await main._gather_while_connected(request, [slow()], poll=0.01)

    assert started.is_set(), "the work did start"
    assert cancelled, "...and was cancelled rather than left running"


async def test_the_disconnect_watcher_does_not_outlive_the_request():
    """It polls forever by design, so leaking one leaks a task per search."""
    async def quick():
        return "done"

    before = len(asyncio.all_tasks())
    await main._gather_while_connected(FakeRequest(), [quick()], poll=0.01)
    await asyncio.sleep(0.05)

    assert len(asyncio.all_tasks()) <= before


def test_an_abandoned_search_answers_without_pretending_to_have_looked(client, monkeypatch):
    """The body goes nowhere, but it must not look like a real empty result."""
    async def gone(request, coroutines, poll=0.4):
        for coroutine in coroutines:
            coroutine.close()       # nothing ran; do not warn about it
        raise main.ClientGone

    monkeypatch.setattr(main, "_gather_while_connected", gone)
    body = client.get("/api/search",
                      params={"q": "berserk", "type": "manga"}).json()

    assert body == {
        "query": "berserk", "type": "manga", "results": [], "sites": [],
        "kinds": [], "answered": 0, "searched": 0, "merged": 0,
    }


# ------------------------------------------------------------ by author
# Scoring only the title made an author search impossible: ask for "Kentaro
# Miura" and the book you want is called Berserk, which shares no word with the
# query and was judged, and dropped, as noise. Measured before the change:
# /api/search?q=Kentaro+Miura&type=manga returned a memorial anthology and
# Berserk Gaiden -- not Berserk.

from app.adapters.base import SCORE_AUTHOR  # noqa: E402


def test_a_book_by_the_author_is_kept_rather_than_dropped():
    assert relevance("kentaro miura", "Berserk") == SCORE_IRRELEVANT
    assert relevance("kentaro miura", "Berserk", None, "Kentaro Miura") == SCORE_AUTHOR


@pytest.mark.parametrize("stored", [
    "Kentaro Miura",
    "Miura Kentarou",   # what MangaDex actually stores: reordered *and*
    "Miura Kentaro",    # transliterated differently
    "Kentarou Miura",
])
def test_the_name_does_not_have_to_be_spelled_our_way(stored):
    """The real case, and the one a graded score got wrong.

    Grading the author on how exactly the string matched put "Miura Kentarou"
    a band below an identical string, which dropped Berserk out of a search for
    its own author. One flat band; the site's own fuzzy name lookup already
    decided this is the person.
    """
    assert relevance("kentaro miura", "Berserk", None, stored) == SCORE_AUTHOR


def test_a_book_by_the_author_outranks_one_merely_named_after_them():
    """Typing a person's name is a request for their books."""
    by_them = relevance("kentaro miura", "Berserk", None, "Miura Kentarou")
    about_them = relevance("kentaro miura", "Kentaro Miura Memorial Manga")

    assert by_them > about_them            # 90 > 80
    # ...but a title that *is* the query still wins: same words, other meaning.
    assert by_them < relevance("kentaro miura", "Kentaro Miura")


@pytest.mark.parametrize("author", [
    "Kaiser Wilhelm",      # 'ser' is buried inside a word
    "Musserati Tanaka",    # ...and inside a name
])
def test_a_fragment_buried_in_a_name_is_a_coincidence_not_a_match(author):
    """A title may score on a bare substring; a name may not.

    A title is prose and the site did think it matched. Half a name, starting
    nowhere, is nothing — the floor is a word *prefix*, which is exactly what
    lets "Kentaro" reach "Kentarou" while "ser" never reaches "Kaiser".
    """
    assert relevance("ser", "Some Unrelated Book", None, author) == SCORE_IRRELEVANT
    assert relevance("ser", "Berserk") == SCORE_SUBSTRING


def test_an_author_only_match_survives_the_endpoint(client, monkeypatch):
    """End to end: the filter must not eat the only hit worth having."""
    class ByAuthor(AdapterInterface):
        content_type = "manga"
        id = "mangadex"

        async def search(self, site, query, limit=12):
            return [
                SearchResult(title="Berserk", url=f"{site}/1", source=self.id,
                             site="mangadex.org", author="Kentaro Miura"),
                SearchResult(title="Magic Emperor", url=f"{site}/2", source=self.id,
                             site="mangadex.org", author="Yi Yi"),
            ]

    async def resolve(site, sessions):
        return ByAuthor()

    monkeypatch.setattr(main, "resolve_adapter", resolve)
    body = client.get("/api/search",
                      params={"q": "Kentaro Miura", "type": "manga"}).json()

    # Both configured manga sites answer, so the kept hit appears once each.
    assert {r["title"] for r in body["results"]} == {"Berserk"}
    assert "Magic Emperor" not in [r["title"] for r in body["results"]]
    assert body["results"][0]["author"] == "Kentaro Miura"


# ------------------------------------------------------- searching every kind
#
# `type` stays required, because guessing is what mixed novels into a manga
# query. `all` is an explicit request for everything, and the results are
# *grouped* by kind rather than interleaved — which is what made the old
# untyped search unusable.


def test_all_reaches_every_kind_of_site(client):
    body = client.get("/api/search", params={"q": "berserk", "type": "all"}).json()
    assert sorted(client.asked) == sorted(
        [MANGA_SITE, MANGA_SITE_2, BOOK_SITE, COMICS_SITE]
    )
    assert {r["content_type"] for r in body["results"]} == {"manga", "book", "comics"}


def test_all_reports_a_count_per_kind_for_grouping(client):
    body = client.get("/api/search", params={"q": "berserk", "type": "all"}).json()
    counts = {k["type"]: k["count"] for k in body["kinds"]}
    assert counts == {"manga": 2, "comics": 1, "book": 1}
    # Labelled by the server, so the browser cannot drift from what it serves.
    assert {k["label"] for k in body["kinds"]} == {"Manga", "Comics", "Books"}


def test_a_kind_that_returned_nothing_is_not_listed(client):
    body = client.get("/api/search", params={"q": "berserk", "type": "manga"}).json()
    assert [k["type"] for k in body["kinds"]] == ["manga"]


def test_all_is_still_not_an_adapter_content_type():
    """It is a request shape. An adapter must never be filed under it."""
    assert main.ANY_TYPE not in CONTENT_TYPES


# ------------------------------------------------------------- per-site status


def test_a_site_that_answered_is_marked_ok(client):
    body = client.get("/api/search", params={"q": "berserk", "type": "book"}).json()
    assert [(s["host"], s["status"], s["count"]) for s in body["sites"]] == [
        ("8ghrb.com", "ok", 1)
    ]


def test_a_site_that_timed_out_says_so_rather_than_looking_empty(client, monkeypatch):
    """Every failure used to arrive as an empty list.

    A timeout, an exception and a genuine no-match were indistinguishable, so
    the only thing the UI could say was "nothing found" — which blames the
    query for the site's problem.
    """
    import asyncio

    class Slow(StubAdapter):
        async def search(self, site, query, limit=12):
            raise asyncio.TimeoutError

    monkeypatch.setitem(RESOLVED, BOOK_SITE, Slow("book", "books"))
    try:
        body = client.get("/api/search",
                          params={"q": "berserk", "type": "book"}).json()
    finally:
        monkeypatch.setitem(RESOLVED, BOOK_SITE, StubAdapter("book", "books"))
    assert [s["status"] for s in body["sites"]] == ["timeout"]
    assert body["answered"] == 0 and body["searched"] == 1


def test_a_site_that_raised_is_marked_error(client, monkeypatch):
    class Broken(StubAdapter):
        async def search(self, site, query, limit=12):
            raise RuntimeError("boom")

    monkeypatch.setitem(RESOLVED, BOOK_SITE, Broken("book", "books"))
    try:
        body = client.get("/api/search",
                          params={"q": "berserk", "type": "book"}).json()
    finally:
        monkeypatch.setitem(RESOLVED, BOOK_SITE, StubAdapter("book", "books"))
    assert [s["status"] for s in body["sites"]] == ["error"]


def test_a_site_whose_hits_were_all_noise_reads_as_empty_not_ok(client, monkeypatch):
    """It answered — just not with anything worth showing."""
    class Noise(StubAdapter):
        async def search(self, site, query, limit=12):
            return [SearchResult(title="Something Else Entirely",
                                 url=f"{site}/x", source=self.id, site="8ghrb.com")]

    monkeypatch.setitem(RESOLVED, BOOK_SITE, Noise("book", "books"))
    try:
        body = client.get("/api/search",
                          params={"q": "berserk", "type": "book"}).json()
    finally:
        monkeypatch.setitem(RESOLVED, BOOK_SITE, StubAdapter("book", "books"))
    assert [s["status"] for s in body["sites"]] == ["empty"]
    assert body["results"] == []


# --------------------------------------------------------------- site filter


def test_a_site_filter_narrows_what_is_asked(client):
    client.get("/api/search",
               params={"q": "berserk", "type": "manga", "sites": "mangadex.org"})
    assert client.asked == [MANGA_SITE], "only the named site should be woken"


def test_the_site_filter_accepts_a_full_url_too(client):
    client.get("/api/search",
               params={"q": "berserk", "type": "manga", "sites": MANGA_SITE})
    assert client.asked == [MANGA_SITE]


def test_an_unknown_site_in_the_filter_searches_nothing(client):
    body = client.get("/api/search",
                      params={"q": "berserk", "type": "manga",
                              "sites": "nowhere.example"}).json()
    assert client.asked == [] and body["results"] == [] and body["searched"] == 0


def test_a_blank_site_filter_is_ignored_rather_than_matching_nothing(client):
    client.get("/api/search",
               params={"q": "berserk", "type": "manga", "sites": " , "})
    assert sorted(client.asked) == sorted([MANGA_SITE, MANGA_SITE_2])


# ------------------------------------------------------------ why it matched


def test_every_hit_explains_why_it_is_in_the_list(client):
    body = client.get("/api/search", params={"q": "agnes", "type": "book"}).json()
    assert all(r["match"] for r in body["results"])


@pytest.mark.parametrize("score, expected", [
    (main.SCORE_EXACT, "exact title"),
    (main.SCORE_AUTHOR, "by this author"),
    (main.SCORE_PREFIX, "title starts with"),
    (main.SCORE_WORD, "title contains"),
    (main.SCORE_WORD_PREFIX, "partial word"),
    (main.SCORE_SUBSTRING, "loose match"),
    (5, "matched another title"),
])
def test_each_relevance_band_has_an_honest_explanation(score, expected):
    assert main._match_reason(score) == expected


# ---------------------------------------------------------------- /api/sources


def test_sources_lists_the_searchable_sites_by_kind(client):
    body = client.get("/api/sources").json()
    by_kind = {k["type"]: k for k in body["kinds"]}
    assert [s["host"] for s in by_kind["manga"]["sites"]] == [
        "mangadex.org", "azoramoon.com",
    ]
    assert by_kind["book"]["count"] == 1
    assert body["total"] == 4


def test_sources_orders_the_kinds_for_the_interface(client):
    body = client.get("/api/sources").json()
    assert [k["type"] for k in body["kinds"]] == ["manga", "comics", "book"]


def test_sources_names_the_adapter_behind_each_site(client):
    body = client.get("/api/sources").json()
    manga = next(k for k in body["kinds"] if k["type"] == "manga")
    assert {s["adapter"] for s in manga["sites"]} == {"mangadex", "vcomics"}


# ------------------------------------------------------------- source cache
#
# The cache stores what a *source* answered, keyed on what was sent to it. The
# property that matters most is not the speed-up: it is that a failure is never
# remembered as an answer.


def test_a_repeated_query_is_served_from_the_cache(client, monkeypatch):
    """Counted on `search()`, not on `resolve_adapter()`.

    The cache wraps the request to the *site*, which is the expensive half; the
    adapter is still resolved each time. Asserting on `client.asked` would
    therefore measure something the cache never claimed to prevent.
    """
    from app.main import search_cache

    searched: list[str] = []

    class Counted(StubAdapter):
        async def search(self, site, query, limit=12):
            searched.append(site)
            return await StubAdapter.search(self, site, query, limit)

    monkeypatch.setitem(RESOLVED, MANGA_SITE, Counted("manga", "mangadex"))
    try:
        client.get("/api/search", params={"q": "berserk", "type": "manga"})
        first = len(searched)
        before = search_cache.hits

        client.get("/api/search", params={"q": "berserk", "type": "manga"})

        assert search_cache.hits > before, "the second search should have hit the cache"
        assert len(searched) == first, "the site must not be queried twice"
    finally:
        monkeypatch.setitem(RESOLVED, MANGA_SITE, StubAdapter("manga", "mangadex"))


def test_refresh_bypasses_the_cache_and_repopulates_it(client):
    client.get("/api/search", params={"q": "berserk", "type": "manga"})
    asked_once = len(client.asked)

    client.get("/api/search",
               params={"q": "berserk", "type": "manga", "refresh": "true"})

    assert len(client.asked) > asked_once, "refresh must re-ask the sites"


def test_a_timeout_is_never_cached_so_the_site_stays_retryable(client, monkeypatch):
    """The property this cache exists to get right.

    Remembering "nothing found" because a site was briefly slow would turn one
    bad moment into two minutes of lying, and the site would not be retried
    inside that window.
    """
    import asyncio

    from app.main import search_cache

    class Slow(StubAdapter):
        async def search(self, site, query, limit=12):
            raise asyncio.TimeoutError

    monkeypatch.setitem(RESOLVED, BOOK_SITE, Slow("book", "books"))
    try:
        client.get("/api/search", params={"q": "berserk", "type": "book"})
        cached, _ = search_cache.peek((BOOK_SITE, "berserk", 8))
        assert not cached, "a timeout must not be stored as an answer"

        # Restore a healthy adapter: the very next search must reach it.
        monkeypatch.setitem(RESOLVED, BOOK_SITE, StubAdapter("book", "books"))
        body = client.get("/api/search",
                          params={"q": "berserk", "type": "book"}).json()
        assert [s["status"] for s in body["sites"]] == ["ok"]
    finally:
        monkeypatch.setitem(RESOLVED, BOOK_SITE, StubAdapter("book", "books"))


def test_an_error_is_never_cached_either(client, monkeypatch):
    from app.main import search_cache

    class Broken(StubAdapter):
        async def search(self, site, query, limit=12):
            raise RuntimeError("boom")

    monkeypatch.setitem(RESOLVED, BOOK_SITE, Broken("book", "books"))
    try:
        client.get("/api/search", params={"q": "berserk", "type": "book"})
        cached, _ = search_cache.peek((BOOK_SITE, "berserk", 8))
        assert not cached
    finally:
        monkeypatch.setitem(RESOLVED, BOOK_SITE, StubAdapter("book", "books"))


def test_a_genuine_empty_answer_is_cached(client, monkeypatch):
    """A site that answered "I have nothing" gave a real answer."""
    from app.main import search_cache

    class Nothing(StubAdapter):
        async def search(self, site, query, limit=12):
            return []

    monkeypatch.setitem(RESOLVED, BOOK_SITE, Nothing("book", "books"))
    try:
        client.get("/api/search", params={"q": "berserk", "type": "book"})
        cached, value = search_cache.peek((BOOK_SITE, "berserk", 8))
        assert cached and value == []
    finally:
        monkeypatch.setitem(RESOLVED, BOOK_SITE, StubAdapter("book", "books"))


def test_an_abandoned_search_does_not_populate_the_cache(client, monkeypatch):
    from app.main import search_cache

    async def gone(request, coroutines, poll=0.4):
        for coroutine in coroutines:
            coroutine.close()
        raise main.ClientGone

    monkeypatch.setattr(main, "_gather_while_connected", gone)
    client.get("/api/search", params={"q": "berserk", "type": "manga"})

    assert search_cache.stats()["entries"] == 0


def test_the_cache_is_bounded_and_evicts_the_oldest():
    """A cache with no size limit is a memory leak with good intentions."""
    import asyncio

    from app.searchcache import SourceCache

    cache = SourceCache(ttl=60.0, max_entries=3)

    async def fill():
        for index in range(5):
            await cache.get_or_fetch(("site", f"q{index}", 8),
                                     lambda i=index: _answer([f"hit{i}"]))

    asyncio.run(fill())
    assert cache.stats()["entries"] == 3
    assert not cache.peek(("site", "q0", 8))[0], "oldest should have been evicted"
    assert cache.peek(("site", "q4", 8))[0], "newest should still be live"


def test_an_expired_entry_is_not_served():
    import asyncio

    from app.searchcache import SourceCache

    cache = SourceCache(ttl=-1.0)   # already expired the moment it is stored

    async def go():
        await cache.get_or_fetch(("site", "q", 8), lambda: _answer(["a"]))
        return cache.peek(("site", "q", 8))

    assert not asyncio.run(go())[0]


def test_identical_concurrent_searches_are_coalesced():
    """A debounced input can overlap; each must not fan out independently."""
    import asyncio

    from app.searchcache import SourceCache

    cache = SourceCache()
    calls = 0

    async def slow():
        nonlocal calls
        calls += 1
        await asyncio.sleep(0.05)
        return ["hit"], "ok"

    async def go():
        await asyncio.gather(*[
            cache.get_or_fetch(("site", "q", 8), slow) for _ in range(4)
        ])

    asyncio.run(go())
    assert calls == 1, "four identical in-flight requests should share one fetch"
    assert cache.stats()["coalesced"] == 3


async def _answer(rows):
    return rows, "ok"


# ------------------------------------------- the kind belongs to the site


def test_a_site_can_serve_a_different_kind_from_its_adapter():
    """One platform, two kinds.

    A manga theme is WordPress markup and web-novel sites run it. kolnovel.com
    fingerprints as MangaThemesia and cenele.com as Madara, and both serve
    prose — so reading the kind off the adapter class filed novels under Manga,
    where a Books search could never reach them.
    """
    from app.adapters.madara import MadaraAdapter
    from app.adapters.mangathemesia import MangaThemesiaAdapter

    assert MangaThemesiaAdapter.content_type_for("https://kolnovel.com") == "book"
    assert MadaraAdapter.content_type_for("https://cenele.com") == "book"

    # Every other site on those adapters is unaffected.
    assert MangaThemesiaAdapter.content_type_for("https://rizzfables.com") == "manga"
    assert MadaraAdapter.content_type_for("https://3asq.online") == "manga"


def test_the_site_kind_holds_even_when_the_adapter_is_only_a_url_guess():
    """The caller that matters cannot fingerprint.

    `/api/sources` groups every configured site on every page load, so it must
    not fetch — and without a fetch these two resolve to `generic`. Holding the
    override on the MangaThemesia and Madara classes therefore did nothing at
    all for the one place the user sees.
    """
    from app.adapters import select
    from app.adapters.generic import GenericAdapter

    assert select("https://kolnovel.com") is GenericAdapter
    assert select("https://kolnovel.com").content_type_for(
        "https://kolnovel.com") == "book"


def test_the_site_kind_ignores_a_www_prefix_and_a_path():
    from app.adapters.madara import MadaraAdapter

    assert MadaraAdapter.content_type_for(
        "https://www.cenele.com/cont/a-series/") == "book"


def test_an_adapter_without_overrides_answers_its_own_kind():
    """The hook must be free for the adapters that do not need it."""
    from app.adapters.gutenberg import GutenbergAdapter
    from app.adapters.mangadex import MangaDexAdapter

    assert GutenbergAdapter.content_type_for("https://www.gutenberg.org") == "book"
    assert MangaDexAdapter.content_type_for("https://mangadex.org") == "manga"


def test_the_sources_listing_files_a_novel_site_under_books(client, monkeypatch):
    """What the user actually sees: the chip a site is counted under."""
    monkeypatch.setattr(main.settings, "search_sites",
                        ["https://kolnovel.com", "https://cenele.com",
                         "https://3asq.online"])

    body = client.get("/api/sources").json()
    by_kind = {k["type"]: {s["host"] for s in k["sites"]} for k in body["kinds"]}

    assert by_kind["book"] == {"kolnovel.com", "cenele.com"}
    assert by_kind["manga"] == {"3asq.online"}
