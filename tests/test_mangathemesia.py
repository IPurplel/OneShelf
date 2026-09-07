"""MangaThemesia / TS theme adapter.

The theme behind a large share of Arabic and Indonesian scanlation sites, and
the second most deployed manga theme after Madara. Markup below follows the
theme's stable structure: eplister chapter lists, a readerarea, and the
ts_reader.run() payload the reader is driven from.
"""

from __future__ import annotations

import pytest

from app.adapters import registry
from app.adapters.base import AdapterError
from app.adapters.madara import MadaraAdapter
from app.adapters.mangathemesia import (
    MangaThemesiaAdapter,
    _images_from_ts_reader,
    _normalise_series_url,
)
from app.models import Chapter

from .conftest import FakeSessionManager

SITE = "https://example-ts.net"
SERIES = f"{SITE}/manga/one-piece/"

SERIES_HTML = f"""
<html><body>
<h1 class="entry-title">One Piece</h1>
<div class="thumb"><img src="{SITE}/cover.jpg"></div>
<div class="entry-content"><p>A pirate story.</p></div>
<div class="eplister"><ul>
  <li><a href="{SITE}/one-piece-chapter-3/">
      <span class="chapternum">Chapter 3</span>
      <span class="chapterdate">March 3, 2026</span></a></li>
  <li><a href="{SITE}/one-piece-chapter-10/">
      <span class="chapternum">Chapter 10</span></a></li>
  <li><a href="{SITE}/one-piece-chapter-2/">
      <span class="chapternum">Chapter 2</span></a></li>
  <li><a href="{SERIES}"><span class="chapternum">One Piece</span></a></li>
</ul></div></body></html>
"""

# The reader ships placeholders in src and the real URLs in its JSON payload.
CHAPTER_HTML = """
<html><body><div id="readerarea">
  <img src="https://example-ts.net/wp-content/themes/ts/spinner.gif">
</div>
<script>
ts_reader.run({"post_id":1,"sources":[{"source":"Main","images":[
  "https://cdn.example-ts.net/op/3/001.jpg",
  "https://cdn.example-ts.net/op/3/002.jpg",
  "https://cdn.example-ts.net/op/3/003.jpg"]}]});
</script></body></html>
"""

# A build with no ts_reader payload: the real URLs sit in data-src.
CHAPTER_DOM_ONLY = """
<html><body><div id="readerarea">
  <img src="/wp-content/themes/ts/loading.gif"
       data-src="  https://cdn.example-ts.net/op/4/001.jpg  ">
  <img data-src="https://cdn.example-ts.net/op/4/002.jpg">
  <img src="https://example-ts.net/logo.png">
</div></body></html>
"""


@pytest.fixture
def sessions():
    return FakeSessionManager(
        pages={
            SERIES: SERIES_HTML,
            f"{SITE}/one-piece-chapter-3/": CHAPTER_HTML,
            f"{SITE}/one-piece-chapter-4/": CHAPTER_DOM_ONLY,
        },
        posts={},
    )


# ------------------------------------------------------------- identification


def test_matches_on_theme_fingerprints():
    assert MangaThemesiaAdapter.matches(SERIES, SERIES_HTML)
    assert MangaThemesiaAdapter.matches(SERIES, CHAPTER_HTML)


def test_does_not_claim_a_madara_page():
    """Both themes use /manga/ URLs; only the DOM separates them."""
    madara = '<html><body><div class="wp-manga"><li class="wp-manga-chapter"></li></div></body></html>'
    assert not MangaThemesiaAdapter.matches("https://x.net/manga/y/", madara)


def test_registry_prefers_ts_over_madara_for_a_ts_page():
    assert registry.select(SERIES, SERIES_HTML) is MangaThemesiaAdapter
    madara = '<html><body><div class="wp-manga"></div></body></html>'
    assert registry.select("https://x.net/manga/y/", madara) is MadaraAdapter


def test_url_alone_claims_nothing():
    # /manga/ is shared with Madara, so guessing from the URL would misroute.
    assert not MangaThemesiaAdapter.matches(SERIES)


# -------------------------------------------------------------------- series


async def test_series_metadata(sessions):
    adapter = MangaThemesiaAdapter(sessions)
    series = await adapter.fetch_series(SERIES)

    assert series.title == "One Piece"
    assert series.cover_url == f"{SITE}/cover.jpg"
    assert "pirate" in (series.description or "")
    assert series.source == "mangathemesia"


@pytest.mark.parametrize(
    "given,expected",
    [
        (f"{SITE}/manga/one-piece/", f"{SITE}/manga/one-piece/"),
        (f"{SITE}/manga/one-piece", f"{SITE}/manga/one-piece/"),
        (f"{SITE}/manga/one-piece/?x=1", f"{SITE}/manga/one-piece/"),
        # TS puts chapters on their own top-level slug, so this must be left
        # alone rather than mangled into a series URL.
        (f"{SITE}/one-piece-chapter-3/", f"{SITE}/one-piece-chapter-3/"),
    ],
)
def test_series_url_normalisation(given, expected):
    assert _normalise_series_url(given) == expected


# ------------------------------------------------------------------ chapters


async def test_chapters_are_ordered_numerically(sessions):
    adapter = MangaThemesiaAdapter(sessions)
    series = await adapter.fetch_series(SERIES)
    chapters = await adapter.fetch_chapters(series)

    # Listed 3, 10, 2 — and 10 must not sort between 1 and 2.
    assert [c.number for c in chapters] == ["2", "3", "10"]
    assert [c.index for c in chapters] == [1, 2, 3]


async def test_the_series_link_is_not_a_chapter(sessions):
    adapter = MangaThemesiaAdapter(sessions)
    series = await adapter.fetch_series(SERIES)
    chapters = await adapter.fetch_chapters(series)
    assert all(c.url.rstrip("/") != SERIES.rstrip("/") for c in chapters)


async def test_chapter_dates_are_kept(sessions):
    adapter = MangaThemesiaAdapter(sessions)
    series = await adapter.fetch_series(SERIES)
    chapters = await adapter.fetch_chapters(series)
    assert any(c.date for c in chapters)


async def test_missing_chapter_list_is_explained():
    sessions = FakeSessionManager(
        pages={SERIES: "<html><body><div class='eplister'></div></body></html>"},
        posts={})
    adapter = MangaThemesiaAdapter(sessions)
    series = await adapter.fetch_series(SERIES)
    with pytest.raises(AdapterError, match="No chapter list"):
        await adapter.fetch_chapters(series)


# --------------------------------------------------------------------- pages


def test_ts_reader_payload_is_parsed():
    assert _images_from_ts_reader(CHAPTER_HTML) == [
        "https://cdn.example-ts.net/op/3/001.jpg",
        "https://cdn.example-ts.net/op/3/002.jpg",
        "https://cdn.example-ts.net/op/3/003.jpg",
    ]


def test_absent_payload_yields_nothing():
    assert _images_from_ts_reader("<html><body>no reader here</body></html>") == []


async def test_pages_prefer_the_payload_over_placeholder_markup(sessions):
    """The DOM holds a spinner; reading it would produce a chapter of spinners."""
    adapter = MangaThemesiaAdapter(sessions)
    pages = await adapter.fetch_pages(
        Chapter(url=f"{SITE}/one-piece-chapter-3/", title="Chapter 3", number="3")
    )

    assert len(pages) == 3
    assert not any("spinner" in p.url for p in pages)
    assert [p.index for p in pages] == [1, 2, 3]
    assert all(p.referer.endswith("chapter-3/") for p in pages)


async def test_pages_fall_back_to_the_dom(sessions):
    adapter = MangaThemesiaAdapter(sessions)
    pages = await adapter.fetch_pages(
        Chapter(url=f"{SITE}/one-piece-chapter-4/", title="Chapter 4", number="4")
    )

    assert [p.url for p in pages] == [
        "https://cdn.example-ts.net/op/4/001.jpg",
        "https://cdn.example-ts.net/op/4/002.jpg",
    ]
    # Whitespace-padded lazy attributes and theme chrome must both be handled.
    assert all(p.url == p.url.strip() for p in pages)


# -------------------------------------------------------------------- search

SEARCH_HTML = """
<html><body><div class="listupd">
  <div class="bs"><a href="https://example-ts.net/manga/one-piece/" title="One Piece">
     <img src="https://example-ts.net/c/op.jpg"><div class="tt">One Pie...</div></a></div>
  <div class="bs"><a href="https://example-ts.net/manga/one-punch/" title="One Punch Man">
     <img data-src="https://example-ts.net/c/opm.jpg"><div class="tt">One Punch</div></a></div>
</div></body></html>
"""


async def test_search_returns_titles_covers_and_site():
    sessions = FakeSessionManager(
        pages={"https://example-ts.net/?s=one+piece": SEARCH_HTML}, posts={})
    results = await MangaThemesiaAdapter(sessions).search(
        "https://example-ts.net", "one piece")

    assert [r.title for r in results] == ["One Piece", "One Punch Man"]
    assert results[0].url == "https://example-ts.net/manga/one-piece/"
    assert results[0].cover_url == "https://example-ts.net/c/op.jpg"
    # Lazy-loaded covers must be found too, or half the grid shows blanks.
    assert results[1].cover_url == "https://example-ts.net/c/opm.jpg"
    assert results[0].site == "example-ts.net"
    assert results[0].source == "mangathemesia"


async def test_search_prefers_the_full_title_over_the_truncated_one():
    """The card shows "One Pie..."; the anchor carries the real title."""
    sessions = FakeSessionManager(
        pages={"https://example-ts.net/?s=one+piece": SEARCH_HTML}, posts={})
    results = await MangaThemesiaAdapter(sessions).search(
        "https://example-ts.net", "one piece")
    assert "..." not in results[0].title


async def test_search_honours_the_limit():
    sessions = FakeSessionManager(
        pages={"https://example-ts.net/?s=one+piece": SEARCH_HTML}, posts={})
    results = await MangaThemesiaAdapter(sessions).search(
        "https://example-ts.net", "one piece", limit=1)
    assert len(results) == 1


# ------------------------------------------------------- live-search installs

# A build that keeps the theme's markup but answers search from JSON. Captured
# from rizzfables.com: its ``?s=`` URL returns 200 with the *homepage*, whose
# grid is unrelated to the query — which is exactly why this is dangerous.
LIVE_SITE = "https://example-live.net"
LIVE_HOMEPAGE = f"""
<html><body>
<form id="livesearch-pc" method="POST"><input name="ls-pc-search"></form>
<div class="listupd">
  <div class="bs"><a href="{LIVE_SITE}/series/r2311170-leveling-up-with-the-gods"
      title="Leveling Up with the Gods"><img src="{LIVE_SITE}/a.webp"></a></div>
  <div class="bs"><a href="{LIVE_SITE}/series/r2311170-mercenary-enrollment"
      title="Mercenary Enrollment"><img src="{LIVE_SITE}/b.webp"></a></div>
</div>
<div class="eplister"></div>
<script>
$('#ls-pc-search').keyup(function (e) {{
  $.ajax({{ type: "post", url: "{LIVE_SITE}/Index/live_search",
           data: {{ search_value: $(this).val() }}, dataType: "json" }});
}});
</script></body></html>
"""

LIVE_RESPONSE = (
    '[{"id":"71649","title":"Leveling Up with the Gods","image_url":"lwg.webp"},'
    '{"id":"40260","title":"The Seventh Prince","image_url":"7pp.webp"}]'
)


async def test_a_live_search_install_is_not_scraped_from_its_homepage():
    """``?s=`` on these builds answers 200 with the homepage.

    Its grid parses perfectly, so unnoticed, every query returns the same
    handful of front-page series — an answer that looks real and is not.
    """
    sessions = FakeSessionManager(
        pages={f"{LIVE_SITE}/?s=leveling": LIVE_HOMEPAGE},
        posts={f"{LIVE_SITE}/Index/live_search": LIVE_RESPONSE},
    )
    results = await MangaThemesiaAdapter(sessions).search(LIVE_SITE, "leveling")

    assert sessions.posted == [
        (f"{LIVE_SITE}/Index/live_search", {"search_value": "leveling"})
    ]
    assert [r.title for r in results] == [
        "Leveling Up with the Gods", "The Seventh Prince"
    ]
    # The endpoint returns no URL, so links are rebuilt the way the site does.
    assert results[0].url == f"{LIVE_SITE}/series/r2311170-leveling-up-with-the-gods"
    assert results[1].url == f"{LIVE_SITE}/series/r2311170-the-seventh-prince"
    assert results[0].cover_url == f"{LIVE_SITE}/assets/images/lwg.webp"
    assert results[0].site == "example-live.net"


async def test_a_live_search_install_returns_nothing_when_it_answers_nothing():
    """Empty is the honest result; the homepage grid would be a lie."""
    sessions = FakeSessionManager(
        pages={f"{LIVE_SITE}/?s=%D8%A7%D9%84%D8%BA%D8%B1%D9%8A%D8%A8": LIVE_HOMEPAGE},
        posts={f"{LIVE_SITE}/Index/live_search": "[]"},
    )
    assert await MangaThemesiaAdapter(sessions).search(LIVE_SITE, "الغريب") == []


async def test_a_live_search_install_with_no_series_prefix_yields_nothing():
    without_prefix = LIVE_HOMEPAGE.replace("/series/r2311170-", "/series/")
    sessions = FakeSessionManager(
        pages={f"{LIVE_SITE}/?s=leveling": without_prefix},
        posts={f"{LIVE_SITE}/Index/live_search": LIVE_RESPONSE},
    )
    assert await MangaThemesiaAdapter(sessions).search(LIVE_SITE, "leveling") == []


async def test_a_broken_live_search_never_falls_back_to_the_homepage():
    sessions = FakeSessionManager(
        pages={f"{LIVE_SITE}/?s=leveling": LIVE_HOMEPAGE},
        posts={},  # the endpoint is unregistered, so post_form raises
    )
    assert await MangaThemesiaAdapter(sessions).search(LIVE_SITE, "leveling") == []


@pytest.mark.parametrize(
    "title,slug",
    [
        ("Leveling Up with the Gods", "leveling-up-with-the-gods"),
        ("The Seventh Prince", "the-seventh-prince"),
        # The site's own fix-ups for contractions, first match only.
        ("The Devil's Boy", "the-devils-boy"),
        ("I'll Be the Tyrant", "ill-be-the-tyrant"),
    ],
)
def test_live_search_slug_matches_the_sites_own(title, slug):
    from app.adapters.mangathemesia import _live_slug

    assert _live_slug(title) == slug
