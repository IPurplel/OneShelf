"""RiwayatArab, against real captured markup.

See tests/fixtures/riwayatarab/PROVENANCE.md.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from app.adapters.base import AdapterError
from app.adapters.riwayatarab import (
    RiwayatArabAdapter, _advertised_count, _slug)
from app.models import Chapter, Series

from .conftest import FakeSessionManager

FIXTURES = Path(__file__).parent / "fixtures/riwayatarab"
SLUG = "demonic-emperor"
NOVEL = f"https://riwayatarab.com/novel/{SLUG}"
CHAPTERS = f"{NOVEL}/chapters"
CHAPTER1 = f"{NOVEL}/chapter/1"
SEARCH = "https://riwayatarab.com/search?q=%D8%A7%D9%84%D8%B4%D9%8A%D8%B7%D8%A7%D9%86%D9%8A"
SENTINEL = "zzqvoneshelfnonexistent987654321"
SENTINEL_URL = f"https://riwayatarab.com/search?q={SENTINEL}"


def _fixture(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


def sessions(**extra):
    pages = {
        NOVEL: _fixture("novel.html"),
        CHAPTERS: _fixture("chapters-page1.html"),
        # Explicit end of this shortened fixture catalogue. A missing fixture
        # raises a transport error and must not stand in for end-of-list.
        f"{CHAPTERS}?page=2": _fixture("chapters-page1.html"),
        CHAPTER1: _fixture("chapter1.html"),
        SEARCH: _fixture("search.html"),
        SENTINEL_URL: _fixture("search-empty.html"),
    }
    pages.update(extra)
    return FakeSessionManager(pages=pages)


# ------------------------------------------------------------ identification


def test_the_host_is_claimed_and_nothing_else_is():
    assert RiwayatArabAdapter.matches(NOVEL)
    assert not RiwayatArabAdapter.matches("https://example.net/novel/x")


@pytest.mark.parametrize("url", [NOVEL, CHAPTERS, CHAPTER1, f"{NOVEL}/"])
def test_the_slug_is_read_from_every_url_shape(url):
    assert _slug(url) == SLUG


def test_a_url_that_names_no_novel_says_so():
    with pytest.raises(AdapterError, match="does not name a novel"):
        _slug("https://riwayatarab.com/latest")


# -------------------------------------------------------------------- series


async def test_the_novel_page_gives_the_title():
    series = await RiwayatArabAdapter(sessions()).fetch_series(NOVEL)
    assert series.title == "الإمبراطور الشيطاني"
    assert series.site_id == SLUG


async def test_a_missing_novel_is_reported_as_gone_not_as_a_broken_adapter():
    """The site answers **200** for a novel it does not have, rendering a
    16 KB shell titled "رواية غير موجودة" with zero anchors. That looks exactly
    like a client-rendered page that has not finished, so the difference has to
    be stated rather than guessed at.
    """
    dead = "<html><head><title>رواية غير موجودة</title></head><body></body></html>"
    manager = sessions(**{NOVEL: dead})

    with pytest.raises(AdapterError, match="probably gone"):
        await RiwayatArabAdapter(manager).fetch_series(NOVEL)


def test_the_site_advertises_its_own_chapter_count():
    """Used as a cross-check: a listing that walks short of this is a hole
    that would otherwise survive a preview."""
    assert _advertised_count(_fixture("novel.html")) == 1344
    assert _advertised_count("<html>nothing here</html>") is None


# ------------------------------------------------------------------ chapters


async def test_chapters_are_listed_in_order_from_the_listing_page():
    series = Series(url=NOVEL, title="الإمبراطور الشيطاني", source="riwayatarab")
    chapters = await RiwayatArabAdapter(sessions()).fetch_chapters(series)

    numbers = [int(c.number) for c in chapters]
    assert numbers == sorted(numbers), "reading order"
    assert numbers[:3] == [1, 2, 3]
    assert len(numbers) == len(set(numbers)), "no chapter listed twice"
    assert [c.index for c in chapters[:3]] == [1, 2, 3]


async def test_another_novels_chapters_are_not_collected():
    listing = _fixture("chapters-page1.html").replace(
        "</body>",
        '<a href="/novel/some-other/chapter/7">الفصل 7</a></body>')
    series = Series(url=NOVEL, title="x", source="riwayatarab")

    chapters = await RiwayatArabAdapter(
        sessions(**{CHAPTERS: listing})).fetch_chapters(series)

    assert all("some-other" not in c.url for c in chapters)


# ---------------------------------------------------------------------- text


async def test_a_chapter_is_read_as_prose_split_on_its_line_breaks():
    chapter = Chapter(url=CHAPTER1, title="الفصل 1", number="1", index=1)
    text = await RiwayatArabAdapter(sessions()).fetch_text(chapter)

    assert len(text.blocks) > 50, "232 <br> must become separate blocks"
    assert text.characters > 3000


async def test_page_images_are_refused_with_a_reason():
    chapter = Chapter(url=CHAPTER1, title="الفصل 1", number="1", index=1)
    with pytest.raises(AdapterError, match="serves prose"):
        await RiwayatArabAdapter(sessions()).fetch_pages(chapter)


# -------------------------------------------------------------------- search


async def test_search_reads_the_rendered_page():
    """Over plain HTTP `/search?q=` returns a page that *names* the query and
    links nothing. A page containing the query string is not a page that
    answered it."""
    results = await RiwayatArabAdapter(sessions()).search(
        "https://riwayatarab.com", "الشيطاني")

    assert results
    assert all(r.url.startswith("https://riwayatarab.com/novel/") for r in results)
    assert all("/chapter/" not in r.url for r in results)
    assert all(r.title for r in results)


async def test_search_answers_an_unanswerable_query_with_nothing():
    assert await RiwayatArabAdapter(sessions()).search(
        "https://riwayatarab.com", SENTINEL) == []


def test_a_missing_count_is_not_a_passing_check():
    """`None` means the cross-check was *skipped*, not that it passed.

    The first version of `_advertised_count` looked for the number inside the
    "عرض جميع الفصول (…)" link. React's server rendering splits it from its own
    parentheses — the markup is literally `(<!-- -->1344<!-- -->)` — so it
    returned `None` on every real page and the walk was never checked against
    anything.
    """
    assert _advertised_count("<a>عرض جميع الفصول (<!-- -->1344<!-- -->) ←</a>") is None
    assert _advertised_count('"numberOfPages":1344,') == 1344


async def test_a_short_walk_is_reported_against_the_advertised_count(caplog):
    """The gap this cross-check exists to surface would otherwise be invisible:
    a preview of a truncated list looks exactly like a preview of a short novel.
    """
    import logging

    series = Series(url=NOVEL, title="x", source="riwayatarab")
    with caplog.at_level(logging.WARNING):
        chapters = await RiwayatArabAdapter(sessions()).fetch_chapters(series)

    # The fixture holds only the first listing page, so the walk stops at 50
    # against an advertised 1344 — and says so.
    assert len(chapters) == 50
    assert any("advertises" in record.message for record in caplog.records)


@pytest.mark.parametrize("failed_page, collected", [(1, 0), (2, 50)])
@pytest.mark.parametrize("error_type", [TimeoutError, ConnectionError])
async def test_a_failed_listing_request_is_not_a_successful_partial_preview(
    monkeypatch, failed_page, collected, error_type,
):
    manager = sessions()
    fetch = manager.fetch_text_direct
    failed_url = CHAPTERS + (f"?page={failed_page}" if failed_page > 1 else "")
    cause = error_type("connection interrupted")

    async def interrupted(url, *, referer=None):
        if url == failed_url:
            raise cause
        return await fetch(url, referer=referer)

    monkeypatch.setattr(manager, "fetch_text_direct", interrupted)
    series = Series(url=NOVEL, title="x", source="riwayatarab")
    adapter = RiwayatArabAdapter(manager)

    with pytest.raises(AdapterError) as caught:
        await adapter.fetch_chapters(series)

    assert failed_url in str(caught.value)
    assert f"{collected} chapters" in str(caught.value)
    assert caught.value.__cause__ is cause

    # Retrying the same adapter after the connection recovers can finish.
    monkeypatch.setattr(manager, "fetch_text_direct", fetch)
    chapters = await adapter.fetch_chapters(series)
    assert len(chapters) == 50


async def test_search_bounds_its_own_wait_well_below_the_configured_one():
    """An empty result set is an answer, not a fault.

    The results selector legitimately never appears when a query has no
    matches, so waiting the configured 10s was paid on **every** unsuccessful
    search. Measured live: 12.2s for an unanswerable query against 2.8s for one
    that matched, and in a thirteen-site book fan-out this site alone pushed
    the whole search to its 20s ceiling.
    """
    from app.config import settings

    manager = sessions()
    await RiwayatArabAdapter(manager).search("https://riwayatarab.com", "الشيطاني")

    assert manager.wait_timeouts == [RiwayatArabAdapter.SEARCH_WAIT]
    assert RiwayatArabAdapter.SEARCH_WAIT < settings.wait_timeout


async def test_reading_a_chapter_keeps_the_configured_wait():
    """The bound is for the one page whose selector may honestly be missing."""
    chapter = Chapter(url=CHAPTER1, title="الفصل 1", number="1", index=1)
    manager = sessions()

    await RiwayatArabAdapter(manager).fetch_text(chapter)

    assert manager.wait_timeouts == [], "chapters are read over plain HTTP"
