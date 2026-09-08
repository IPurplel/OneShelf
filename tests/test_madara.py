"""Madara adapter parsing rules.

These lock down the behaviours that empirically break scrapers of this theme:
whitespace-padded lazy-load attributes, newest-first chapter ordering, decimal
chapter numbers, and theme chrome leaking into the page list.
"""

from __future__ import annotations

import pytest

from app.adapters.madara import MadaraAdapter, _extract_number
from app.models import (
    Chapter, Series, format_chapter_number, parse_chapter_number)

from .conftest import FakeSessionManager, fixture

# Async tests are collected automatically via `asyncio_mode = auto` in
# pytest.ini, so no module-level asyncio marker is needed here.


# ---------------------------------------------------------------- detection


def test_matches_by_dom_fingerprint():
    assert MadaraAdapter.matches("https://anything.example/x/", fixture("madara_series.html"))


def test_does_not_match_unrelated_html():
    assert not MadaraAdapter.matches(
        "https://example.net/manga/foo/", "<html><body><p>nothing here</p></body></html>"
    )


def test_matches_by_url_when_html_unavailable():
    assert MadaraAdapter.matches("https://example.net/manga/foo/")
    assert not MadaraAdapter.matches("https://example.net/novel/foo/")


# ------------------------------------------------------------------ series


async def test_fetch_series_extracts_metadata(madara_sessions, series_url):
    adapter = MadaraAdapter(madara_sessions)
    series = await adapter.fetch_series(series_url)

    # The theme leaves a "HOT" badge inside the title node.
    assert series.title == "Example Series"
    assert series.author == "Placeholder Author"
    assert series.site_id == "4821"
    assert series.source == "madara"
    assert "placeholder synopsis" in series.description.lower()


async def test_fetch_series_strips_cover_padding(madara_sessions, series_url):
    adapter = MadaraAdapter(madara_sessions)
    series = await adapter.fetch_series(series_url)

    assert series.cover_url is not None
    assert not series.cover_url.strip() != series.cover_url
    assert "\n" not in series.cover_url


# ---------------------------------------------------------------- chapters


async def test_chapters_via_ajax_are_sorted_ascending(madara_sessions, series_url):
    adapter = MadaraAdapter(madara_sessions)
    series = await adapter.fetch_series(series_url)
    chapters = await adapter.fetch_chapters(series)

    # Fixture lists 11, 10.5, 9, 10, 1 newest-first and out of order.
    assert [c.number for c in chapters] == ["1", "9", "10", "10.5", "11"]
    assert [c.index for c in chapters] == [1, 2, 3, 4, 5]


async def test_chapters_resolve_relative_hrefs(madara_sessions, series_url):
    adapter = MadaraAdapter(madara_sessions)
    series = await adapter.fetch_series(series_url)
    chapters = await adapter.fetch_chapters(series)

    assert chapters[0].url == "https://example.net/manga/example-series/chapter-1/"
    assert all(c.url.startswith("https://") for c in chapters)


async def test_chapters_fall_back_to_admin_ajax(series_url):
    """When the modern endpoint fails, the older admin-ajax route must work."""
    sessions = FakeSessionManager(
        pages={series_url: fixture("madara_series.html")},
        posts={
            # ajax/chapters/ deliberately unregistered -> raises -> fallback
            "https://example.net/wp-admin/admin-ajax.php": fixture("madara_chapters.html"),
        },
    )
    adapter = MadaraAdapter(sessions)
    series = await adapter.fetch_series(series_url)
    chapters = await adapter.fetch_chapters(series)

    assert len(chapters) == 5
    endpoint, payload = sessions.posted[-1]
    assert endpoint.endswith("/wp-admin/admin-ajax.php")
    assert payload == {"action": "manga_get_chapters", "manga": "4821"}


async def test_chapters_fall_back_to_inline_markup(series_url):
    """Sites with AJAX chapter loading disabled ship the list in the page."""
    combined = fixture("madara_series.html").replace(
        "</body>", fixture("madara_chapters.html") + "</body>"
    )
    sessions = FakeSessionManager(pages={series_url: combined}, posts={})

    adapter = MadaraAdapter(sessions)
    series = await adapter.fetch_series(series_url)
    chapters = await adapter.fetch_chapters(series)

    assert len(chapters) == 5


async def test_chapter_failure_reports_all_attempts(series_url):
    sessions = FakeSessionManager(
        pages={series_url: "<html><body><div class='wp-manga'></div></body></html>"},
        posts={},
    )
    adapter = MadaraAdapter(sessions)
    series = await adapter.fetch_series(series_url)

    with pytest.raises(Exception) as exc:
        await adapter.fetch_chapters(series)
    message = str(exc.value)
    assert "_chapters_via_ajax_path" in message
    assert "_chapters_via_admin_ajax" in message


# ------------------------------------------------------------------- pages


async def test_pages_prefer_data_src_over_placeholder_src(madara_sessions):
    from app.models import Chapter

    adapter = MadaraAdapter(madara_sessions)
    pages = await adapter.fetch_pages(
        Chapter(url="https://example.net/manga/example-series/chapter-1/", title="Chapter 1")
    )

    urls = [p.url for p in pages]
    assert urls[0] == "https://cdn.example.net/uploads/example-series/ch-1/001.jpg"
    # The loading.gif placeholder in src must never win.
    assert not any("loading.gif" in u for u in urls)


async def test_pages_strip_attribute_whitespace(madara_sessions):
    from app.models import Chapter

    adapter = MadaraAdapter(madara_sessions)
    pages = await adapter.fetch_pages(
        Chapter(url="https://example.net/manga/example-series/chapter-1/", title="Chapter 1")
    )

    for page in pages:
        assert page.url == page.url.strip()
        assert "\n" not in page.url and "\t" not in page.url


async def test_pages_pick_widest_srcset_entry(madara_sessions):
    from app.models import Chapter

    adapter = MadaraAdapter(madara_sessions)
    pages = await adapter.fetch_pages(
        Chapter(url="https://example.net/manga/example-series/chapter-1/", title="Chapter 1")
    )

    # 1600w is listed second, not last - the widest must still be chosen.
    assert pages[2].url.endswith("003-1600.jpg")


async def test_pages_exclude_theme_chrome_and_resolve_scheme(madara_sessions):
    from app.models import Chapter

    adapter = MadaraAdapter(madara_sessions)
    pages = await adapter.fetch_pages(
        Chapter(url="https://example.net/manga/example-series/chapter-1/", title="Chapter 1")
    )

    assert len(pages) == 4
    assert not any("themes/madara" in p.url or "spinner" in p.url for p in pages)
    # Protocol-relative URL must gain the page's scheme.
    assert pages[3].url.startswith("https://cdn.example.net/")
    assert [p.index for p in pages] == [1, 2, 3, 4]


async def test_pages_carry_referer(madara_sessions):
    from app.models import Chapter

    chapter_url = "https://example.net/manga/example-series/chapter-1/"
    adapter = MadaraAdapter(madara_sessions)
    pages = await adapter.fetch_pages(Chapter(url=chapter_url, title="Chapter 1"))

    assert all(p.referer == chapter_url for p in pages)


# ------------------------------------------------------- number extraction


@pytest.mark.parametrize(
    "title,url,expected",
    [
        ("Chapter 12", "https://e.net/m/s/chapter-12/", "12"),
        ("Chapter 12.5", "https://e.net/m/s/chapter-12-5/", "12.5"),
        ("Ch. 7", "https://e.net/m/s/chapter-7/", "7"),
        ("الفصل 344", "https://e.net/m/s/chapter-344/", "344"),
        ("", "https://e.net/m/s/chapter-88/", "88"),
        ("Prologue", "https://e.net/m/s/prologue/", None),
        # Bare numeric labels: the common Madara case.
        ("386", "https://e.net/m/s/386/", "386"),
        ("0", "https://e.net/m/s/n-a/", "0"),
    ],
)
def test_extract_number(title, url, expected):
    assert _extract_number(title, url) == expected


# Real labels and slugs taken from a live Madara site, where the chapter title
# is Arabic and the slug is therefore percent-encoded. Every one of these
# parsed to a wrong number (or None) before the leading-number rule existed.
@pytest.mark.parametrize(
    "title,slug,expected",
    [
        ("373 - أغلال مكبلة من حديد صدئ", "373-أغلال-مكبلة-من-حديد-صدئ", "373"),
        ("372 - الغراب الأحمر النائم في قفص العصافير",
         "372-الغراب-الأحمر-النائم-في-قفص-العصافير", "372"),
        ("371 - ضوءٌ يخبو في ظلام الليل الحالك", "371-ضوءٌ-يخبو-في-ظلام-الليل-الحالك", "371"),
        ("370 - لاجئون على البحر الغربي", "370-لاجئون-على-البحر-الغربي", "370"),
        ("155 - خيطُ العنكبوت", "155-خيطُ-العنكبوت", "155"),
    ],
)
def test_extract_number_from_non_latin_titles(title, slug, expected):
    from urllib.parse import quote

    url = f"https://e.net/manga/berserk/{quote(slug)}/"
    assert _extract_number(title, url) == expected


def test_percent_encoded_slug_is_not_read_as_a_number():
    # "%d8%a7%d9%84" is hex, and scanning it raw finds digits that look like a
    # chapter number. Chapter 372 was parsed as chapter 1 this way.
    from urllib.parse import quote

    url = f"https://e.net/manga/berserk/{quote('372-الغراب')}/"
    assert _extract_number("", url) == "372"


def test_leading_number_beats_a_number_inside_the_title():
    # Reading from the end first would return 3 here.
    assert _extract_number("12 - The Tale of 3 Kings", "https://e.net/m/s/x/") == "12"


@pytest.mark.parametrize(
    "raw,index,expected",
    [
        ("12", 0, "012"),
        ("12.5", 0, "012.5"),
        ("344", 0, "344"),
        ("1", 0, "001"),
        (None, 7, "007"),
    ],
)
def test_format_chapter_number_pads_for_lexical_sorting(raw, index, expected):
    assert format_chapter_number(raw, index) == expected


def test_parse_chapter_number_handles_non_numeric():
    assert parse_chapter_number("Prologue") is None
    assert parse_chapter_number(None) is None
    assert parse_chapter_number("الفصل 42") == 42.0


# ------------------------------------------------- series URL normalisation


@pytest.mark.parametrize(
    "given,expected",
    [
        # The reported bug: a chapter URL was taken as a series URL, producing
        # a one-chapter "series" pointing at the site index.
        ("https://e.net/manga/berserk/n-a/", "https://e.net/manga/berserk/"),
        ("https://e.net/manga/berserk/386/", "https://e.net/manga/berserk/"),
        ("https://e.net/manga/berserk/386/?style=list", "https://e.net/manga/berserk/"),
        ("https://e.net/manga/berserk/386#top", "https://e.net/manga/berserk/"),
        # Already a series URL: unchanged.
        ("https://e.net/manga/berserk/", "https://e.net/manga/berserk/"),
        ("https://e.net/manga/berserk", "https://e.net/manga/berserk/"),
        # Other Madara post-type slugs.
        ("https://e.net/series/berserk/12/", "https://e.net/series/berserk/"),
        ("https://e.net/webtoon/x/ch-3/", "https://e.net/webtoon/x/"),
        ("https://e.net/read/x/3/", "https://e.net/read/x/"),
    ],
)
def test_normalise_series_url(given, expected):
    from app.adapters.madara import _normalise_series_url

    assert _normalise_series_url(given) == expected


def test_unknown_post_type_is_left_alone():
    # Unrecognised installs must keep working; fetch_series verifies the page
    # shape and can still recover from there.
    from app.adapters.madara import _normalise_series_url

    assert _normalise_series_url("https://e.net/weird/x/3/") == "https://e.net/weird/x/3/"


@pytest.mark.parametrize("url", ["https://e.net/manga/", "https://e.net/manga"])
def test_a_listing_page_is_rejected(url):
    from app.adapters.base import AdapterError
    from app.adapters.madara import _normalise_series_url

    with pytest.raises(AdapterError, match="listing page"):
        _normalise_series_url(url)


# --------------------------------------------------- bogus chapter filtering


@pytest.mark.parametrize(
    "href,is_junk",
    [
        ("https://e.net/manga/", True),                 # the site index
        ("https://e.net/manga/berserk/", True),         # the series itself
        ("https://e.net/manga/berserk/386/", False),    # a real chapter
        ("https://e.net/manga/berserk/n-a/", False),
    ],
)
def test_ancestor_links_are_not_chapters(href, is_junk):
    """Breadcrumb and nav links are never chapters.

    This alone would have caught the reported bug: the fabricated chapter
    pointed at /manga/, the site index.
    """
    from app.adapters.madara import _is_ancestor_or_same

    assert _is_ancestor_or_same(href, "https://e.net/manga/berserk/") is is_junk


async def test_navigation_links_are_dropped_from_the_chapter_list(series_url):
    html = (
        "<html><body>"
        f"<li class='wp-manga-chapter'><a href='{series_url}'>Series</a></li>"
        "<li class='wp-manga-chapter'><a href='https://example.net/manga/'>All</a></li>"
        f"<li class='wp-manga-chapter'><a href='{series_url}5/'>5</a></li>"
        "</body></html>"
    )
    adapter = MadaraAdapter(FakeSessionManager(pages={}, posts={}))
    chapters = adapter._parse_chapter_nodes(html, series_url)

    assert [c.number for c in chapters] == ["5"]


# ------------------------------------------- recovering a series from a page


async def test_a_chapter_page_resolves_back_to_its_series():
    """Pasting a chapter URL should give the whole series, not one chapter.

    The reader-page fixture is trimmed from real markup off the live site.
    """
    chapter_url = "https://manga-starz.net/manga/berserk/386/"
    series_url = "https://manga-starz.net/manga/berserk/"
    sessions = FakeSessionManager(
        pages={
            # Normalisation turns the chapter URL into the series URL before
            # any request, so only the series page is ever fetched.
            series_url: fixture("madara_series.html"),
        },
        posts={},
    )
    adapter = MadaraAdapter(sessions)
    series = await adapter.fetch_series(chapter_url)

    assert series.url == series_url
    assert sessions.direct == [series_url]
    assert sessions.requested == []


async def test_a_reader_page_on_an_unknown_install_is_followed():
    # No recognised post-type slug, so the URL cannot be trimmed; the
    # breadcrumb on the page is what gets us to the series.
    reader_url = "https://manga-starz.net/weird/berserk/386/"
    series_url = "https://manga-starz.net/manga/berserk/"
    sessions = FakeSessionManager(
        pages={
            reader_url: fixture("madara_chapter_page.html"),
            series_url: fixture("madara_series.html"),
        },
        posts={},
    )
    adapter = MadaraAdapter(sessions)
    series = await adapter.fetch_series(reader_url)

    assert series.url == series_url
    assert sessions.direct == [reader_url, series_url]
    assert sessions.requested == [reader_url]  # incomplete static breadcrumb page


async def test_a_page_that_is_neither_is_rejected_clearly():
    from app.adapters.base import AdapterError

    url = "https://manga-starz.net/weird/nothing/here/"
    sessions = FakeSessionManager(
        pages={url: "<html><body><p>nothing useful</p></body></html>"}, posts={})
    adapter = MadaraAdapter(sessions)

    with pytest.raises(AdapterError, match="does not look like a series page"):
        await adapter.fetch_series(url)


# -------------------------------------------------------------------- search


async def test_madara_search_parses_results():
    html = """
    <html><body>
      <div class="c-tabs-item__content">
        <div class="tab-thumb"><img src="https://e.net/c/berserk.jpg"></div>
        <div class="post-title"><h3><a href="https://e.net/manga/berserk/">Berserk</a></h3></div>
      </div>
      <div class="c-tabs-item__content">
        <div class="post-title"><h3><a href="https://e.net/manga/berserk-gaiden/">Berserk Gaiden</a></h3></div>
      </div>
    </body></html>
    """
    sessions = FakeSessionManager(
        pages={"https://e.net/?s=berserk&post_type=wp-manga": html}, posts={})
    results = await MadaraAdapter(sessions).search("https://e.net", "berserk")

    assert [r.title for r in results] == ["Berserk", "Berserk Gaiden"]
    assert results[0].cover_url == "https://e.net/c/berserk.jpg"
    assert results[0].site == "e.net"
    # A result with no cover must still be listed, not dropped.
    assert results[1].cover_url is None


async def test_madara_search_survives_an_empty_page():
    sessions = FakeSessionManager(
        pages={"https://e.net/?s=nothing&post_type=wp-manga": "<html></html>"}, posts={})
    assert await MadaraAdapter(sessions).search("https://e.net", "nothing") == []


async def test_madara_search_deduplicates_repeated_hits():
    """Themes list the same series in a carousel and the results grid."""
    row = ('<div class="c-tabs-item__content"><div class="post-title"><h3>'
           '<a href="https://e.net/manga/berserk/">Berserk</a></h3></div></div>')
    sessions = FakeSessionManager(
        pages={"https://e.net/?s=berserk&post_type=wp-manga":
               f"<html><body>{row}{row}</body></html>"}, posts={})
    results = await MadaraAdapter(sessions).search("https://e.net", "berserk")
    assert len(results) == 1


# ------------------------------------- installs that are not comics, or not /manga/


async def test_a_configurable_post_type_slug_still_yields_chapters():
    """Madara's post-type slug is configurable, and not every site uses /manga/.

    Measured 2026-09-08: cenele.com serves `/cont/<series>/<chapter>/`. The
    parser required `/manga/` in every chapter path, so all eight marked
    chapters were discarded and the series reported "could not read the
    chapter list" against a page whose list had parsed perfectly. The guard
    belongs to the *fallback* scan, where "every <li> holding a link" really is
    a guess; a link the site marked `li.wp-manga-chapter` needs no such check.
    """
    series_url = "https://example.net/cont/a-series/"
    html = """
    <html><body><div class="listing-chapters_wrap"><ul>
      <li class="wp-manga-chapter"><a href="/cont/a-series/chapter-1/">Chapter 1</a></li>
      <li class="wp-manga-chapter"><a href="/cont/a-series/chapter-2/">Chapter 2</a></li>
    </ul></div></body></html>
    """
    sessions = FakeSessionManager(pages={series_url: html})
    adapter = MadaraAdapter(sessions)
    series = Series(url=series_url, title="A Series", source="madara")

    chapters = await adapter.fetch_chapters(series)

    assert [c.number for c in chapters] == ["1", "2"]


async def test_the_fallback_scan_still_refuses_navigation_links():
    """The guard has to stay where it was actually earning its keep."""
    series_url = "https://example.net/manga/a-series/"
    html = """
    <html><body><ul>
      <li><a href="/about/">About us</a></li>
      <li><a href="/manga/a-series/chapter-1/">Chapter 1</a></li>
    </ul></body></html>
    """
    sessions = FakeSessionManager(pages={series_url: html})
    adapter = MadaraAdapter(sessions)
    series = Series(url=series_url, title="A Series", source="madara")

    chapters = await adapter.fetch_chapters(series)

    assert [c.url for c in chapters] == [
        "https://example.net/manga/a-series/chapter-1/"]


PROSE_HTML = "<html><body><div class='reading-content'><p>%s</p><p>%s</p></div></body></html>" % (
    "الفصل " * 400, "قال " * 400)

COMIC_HTML = """
<html><body><div class="reading-content">
  <img class="wp-manga-chapter-img" src="https://cdn.example.net/1.jpg">
  <img class="wp-manga-chapter-img" src="https://cdn.example.net/2.jpg">
  <p>A translator's note that goes on for a while. %s</p>
</div></body></html>
""" % ("word " * 500)


async def test_a_madara_chapter_of_prose_is_packaged_as_text():
    """cenele.com serves Arabic novels through this theme."""
    url = "https://example.net/cont/a-series/chapter-1/"
    sessions = FakeSessionManager(pages={url: PROSE_HTML})
    adapter = MadaraAdapter(sessions)
    chapter = Chapter(url=url, title="Chapter 1", number="1", index=1)

    assert await adapter.packaging_for(chapter) == "text"
    assert (await adapter.fetch_text(chapter)).blocks


async def test_a_chapter_with_images_stays_a_comic_however_much_text_it_carries():
    """An image anywhere in the reader settles it.

    Treating a comic chapter as prose would silently drop every page, which is
    the worst outcome available here -- so a long translator's note must never
    tip the decision.
    """
    url = "https://example.net/manga/a-series/chapter-1/"
    sessions = FakeSessionManager(pages={url: COMIC_HTML})
    adapter = MadaraAdapter(sessions)
    chapter = Chapter(url=url, title="Chapter 1", number="1", index=1)

    assert await adapter.packaging_for(chapter) == "cbz"
    assert len(await adapter.fetch_pages(chapter)) == 2
