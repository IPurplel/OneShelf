"""WuxiaBox, against real captured markup.

See tests/fixtures/wuxiabox/PROVENANCE.md.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from app.adapters.base import AdapterError
from app.adapters.wuxiabox import WuxiaBoxAdapter, _chapter_number, _slug
from app.models import Series

from .conftest import FakeSessionManager

FIXTURES = Path(__file__).parent / "fixtures/wuxiabox"
SLUG = "absolute-resonance"
NOVEL = f"https://wuxiabox.com/novel/{SLUG}.html"
TAB = f"{NOVEL}?tab=chapters"
PAGE1 = f"https://wuxiabox.com/e/extend/fy.php?page=1&wjm={SLUG}"
CHAPTER1 = f"https://wuxiabox.com/novel/{SLUG}_1.html"


def _fixture(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


def sessions(**extra):
    pages = {
        NOVEL: _fixture("chapters-tab.html"),
        TAB: _fixture("chapters-tab.html"),
        PAGE1: _fixture("chapters-page1.html"),
        # Repeat the last saved page to end this shortened fixture catalogue;
        # an unregistered URL is a transport failure, not an empty last page.
        PAGE1.replace("page=1", "page=2"): _fixture("chapters-page1.html"),
        CHAPTER1: _fixture("chapter.html"),
    }
    pages.update(extra)
    return FakeSessionManager(pages=pages)


# ------------------------------------------------------------ identification


def test_the_host_is_claimed_and_nothing_else_is():
    assert WuxiaBoxAdapter.matches(NOVEL)
    assert WuxiaBoxAdapter.matches("https://www.wuxiabox.com/novel/x.html")
    assert not WuxiaBoxAdapter.matches("https://example.net/novel/x.html")


@pytest.mark.parametrize("url", [
    NOVEL, CHAPTER1, f"https://wuxiabox.com/novel/{SLUG}_0046.html", PAGE1,
])
def test_the_slug_is_read_from_every_url_shape(url):
    assert _slug(url) == SLUG


def test_a_url_that_names_no_novel_says_so():
    with pytest.raises(AdapterError, match="does not name a novel"):
        _slug("https://wuxiabox.com/browse")


@pytest.mark.parametrize("url, expected", [
    (CHAPTER1, "1"),
    (f"https://wuxiabox.com/novel/{SLUG}_0046.html", "0046"),
    (NOVEL, None),
])
def test_chapter_numbers_come_from_the_path(url, expected):
    assert _chapter_number(url) == expected


# -------------------------------------------------------------------- series


async def test_the_novel_page_gives_the_title():
    series = await WuxiaBoxAdapter(sessions()).fetch_series(NOVEL)
    assert series.title == "Absolute Resonance"
    assert series.site_id == SLUG
    assert series.url == NOVEL


# ------------------------------------------------------------------ chapters


async def test_a_chapter_published_under_two_urls_is_listed_once():
    """The bug this adapter's de-duplication exists for.

    The site publishes some chapters twice, once zero-padded: `…_46.html` and
    `…_0046.html` are the same chapter. De-duplicating on the URL — the obvious
    choice, and enough for the overlapping pages — left both, and measured on
    the live novel that meant **117 of 1,216 chapters downloaded and packaged
    twice**.
    """
    raw = _fixture("chapters-tab.html")
    assert f"/novel/{SLUG}_0046.html" in raw and f"/novel/{SLUG}_46.html" in raw

    series = Series(url=NOVEL, title="Absolute Resonance", source="wuxiabox")
    chapters = await WuxiaBoxAdapter(sessions()).fetch_chapters(series)

    numbers = [int(c.number) for c in chapters]
    assert len(numbers) == len(set(numbers)), "no chapter listed twice"
    assert numbers.count(46) == 1
    # The unpadded URL is the one kept, because it is listed first.
    assert any(c.url.endswith(f"{SLUG}_46.html") for c in chapters)
    assert not any(c.url.endswith(f"{SLUG}_0046.html") for c in chapters)


async def test_overlapping_listing_pages_do_not_duplicate_chapters():
    """`page=1` is chapters 91-190, not 101-200: zero-based, stride 90, page
    size 100. Consecutive pages share ten rows by design."""
    series = Series(url=NOVEL, title="Absolute Resonance", source="wuxiabox")
    chapters = await WuxiaBoxAdapter(sessions()).fetch_chapters(series)

    numbers = [int(c.number) for c in chapters]
    assert len(numbers) == len(set(numbers))
    # Both pages contributed: 1-100 from the tab, up to 190 from page=1.
    assert max(numbers) >= 190


async def test_chapters_come_back_in_reading_order_and_are_indexed_from_one():
    series = Series(url=NOVEL, title="Absolute Resonance", source="wuxiabox")
    chapters = await WuxiaBoxAdapter(sessions()).fetch_chapters(series)

    assert [c.index for c in chapters[:3]] == [1, 2, 3]
    assert [int(c.number) for c in chapters[:3]] == [1, 2, 3]


async def test_another_novels_chapter_in_a_recommendation_panel_is_ignored():
    """Listing pages carry recommendation panels, and another novel's chapter
    numbers would collide with this one's."""
    tab = _fixture("chapters-tab.html").replace(
        "</body>",
        '<a href="/novel/some-other-novel_5.html">Chapter 5</a></body>')
    series = Series(url=NOVEL, title="Absolute Resonance", source="wuxiabox")

    chapters = await WuxiaBoxAdapter(
        sessions(**{NOVEL: tab, TAB: tab})).fetch_chapters(series)

    assert all("some-other-novel" not in c.url for c in chapters)


# ---------------------------------------------------------------------- text


async def test_a_chapter_is_read_as_prose_split_on_its_line_breaks():
    """`div.chapter-content` is one `<p>` and 234 `<br>`. Reading `text()`
    would return 19,000 characters as a single run-on sentence."""
    from app.models import Chapter

    chapter = Chapter(url=CHAPTER1, title="Chapter 1", number="1", index=1)
    text = await WuxiaBoxAdapter(sessions()).fetch_text(chapter)

    assert len(text.blocks) > 50, "the line breaks must become separate blocks"
    assert text.characters > 5000
    assert "Chapter 1" in text.title


async def test_page_images_are_refused_with_a_reason():
    from app.models import Chapter

    chapter = Chapter(url=CHAPTER1, title="Chapter 1", number="1", index=1)
    with pytest.raises(AdapterError, match="serves prose"):
        await WuxiaBoxAdapter(sessions()).fetch_pages(chapter)


@pytest.mark.parametrize("error_type", [TimeoutError, ConnectionError])
async def test_a_failed_listing_request_is_not_a_successful_partial_preview(
    monkeypatch, error_type,
):
    manager = sessions()
    fetch = manager.fetch_text_direct
    cause = error_type("connection interrupted")

    async def interrupted(url, *, referer=None):
        if url == PAGE1:
            raise cause
        return await fetch(url, referer=referer)

    monkeypatch.setattr(manager, "fetch_text_direct", interrupted)
    series = Series(url=NOVEL, title="Absolute Resonance", source="wuxiabox")
    adapter = WuxiaBoxAdapter(manager)

    with pytest.raises(AdapterError) as caught:
        await adapter.fetch_chapters(series)

    assert PAGE1 in str(caught.value)
    # The first 100 links contain ten padded duplicates: 90 chapters.
    assert "90 chapters" in str(caught.value)
    assert caught.value.__cause__ is cause

    monkeypatch.setattr(manager, "fetch_text_direct", fetch)
    chapters = await adapter.fetch_chapters(series)
    assert len(chapters) == 190
