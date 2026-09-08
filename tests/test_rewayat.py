"""Rewayat Club, against real captured markup.

See tests/fixtures/rewayat/PROVENANCE.md.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from app.adapters.base import AdapterError
from app.adapters.rewayat import (
    RewayatAdapter, _all_chapter_numbers, _clean, _newest_chapter, _slug)
from app.models import Chapter, Series

from .conftest import FakeSessionManager

FIXTURES = Path(__file__).parent / "fixtures/rewayat"
SLUG = "cleaver-of-sin"
NOVEL = f"https://rewayat.club/novel/{SLUG}"
CHAPTER1 = f"{NOVEL}/1"


def _fixture(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


NEWEST = f"{NOVEL}/955"


def sessions():
    return FakeSessionManager(pages={
        NOVEL: _fixture("novel.html"),
        CHAPTER1: _fixture("chapter1.html"),
        # The chapter the adapter actually opens: the newest one linked from
        # the novel page.
        NEWEST: _fixture("chapter-newest.html"),
    })


# ------------------------------------------------------------ identification


def test_the_host_is_claimed_and_nothing_else_is():
    assert RewayatAdapter.matches(NOVEL)
    assert RewayatAdapter.matches(f"https://www.rewayat.club/novel/{SLUG}/5")
    assert not RewayatAdapter.matches("https://example.net/novel/x")


@pytest.mark.parametrize("url", [NOVEL, CHAPTER1, f"{NOVEL}/955/"])
def test_the_slug_is_read_from_a_novel_or_a_chapter(url):
    assert _slug(url) == SLUG


def test_a_url_that_names_no_novel_says_so():
    with pytest.raises(AdapterError, match="does not name a novel"):
        _slug("https://rewayat.club/store")


def test_an_attribution_tag_does_not_make_a_second_chapter():
    """Chapter links carry `?username=…`; keeping it would split one chapter
    into two."""
    assert _clean(f"{NOVEL}/932?username=ZEUS") == f"{NOVEL}/932"


# ------------------------------------------------------ the payload it needs


def test_the_novel_page_lists_only_the_newest_chapters():
    """Why the adapter opens a chapter at all: the novel page is not the list."""
    novel = _fixture("novel.html")
    assert "allChapters:[" not in novel
    newest = _newest_chapter(novel, SLUG)
    assert newest and newest > 900


def test_every_chapter_is_read_from_one_chapters_payload():
    numbers = _all_chapter_numbers(_fixture("chapter1.html"))
    assert len(numbers) == 954, "954 literal entries in allChapters"
    assert min(numbers) == 2 and max(numbers) == 955
    assert numbers[2].strip().endswith("2")


@pytest.mark.parametrize("fixture, missing", [
    ("chapter1.html", 1),
    ("chapter-newest.html", 955),
])
def test_the_current_chapter_has_no_literal_entry_of_its_own(fixture, missing):
    """It is built by assignment (`i.text=e`), so a regex over `text:"…"`
    returns every chapter except the one being read — whichever that is."""
    numbers = _all_chapter_numbers(_fixture(fixture))
    assert missing not in numbers
    assert len(numbers) == 954


def test_a_payload_without_the_array_yields_nothing_rather_than_guessing():
    assert _all_chapter_numbers("<html>no payload here</html>") == {}
    assert _all_chapter_numbers("allChapters:[unterminated") == {}


def test_the_array_is_scoped_so_menu_labels_do_not_become_chapters():
    """The same `text:"…"` shape appears elsewhere in the hydration state."""
    html = ('x={menu:[{text:"الصفحة 7"}],allChapters:[{value:a,text:"الفصل 3"}],'
            'footer:[{text:"سياسة 9"}]}')
    assert _all_chapter_numbers(html) == {3: "الفصل 3"}


# ------------------------------------------------------------------ reading


async def test_the_series_title_comes_from_the_novel_page():
    series = await RewayatAdapter(sessions()).fetch_series(NOVEL)
    assert series.title.startswith("رواية")
    assert series.site_id == SLUG


async def test_the_chapter_list_is_contiguous_and_includes_the_one_fetched():
    """Chapter 955's payload lists 1-954 and omits itself, so the fetched
    chapter has to be added back to reach a complete 1-955."""
    assert 955 not in _all_chapter_numbers(_fixture("chapter-newest.html"))

    series = Series(url=NOVEL, title="رواية", source="rewayat")
    chapters = await RewayatAdapter(sessions()).fetch_chapters(series)

    numbers = sorted(int(c.number) for c in chapters)
    assert numbers == list(range(1, 956)), "1-955, no gaps and no duplicates"
    assert chapters[0].url == f"{NOVEL}/1"
    assert [c.index for c in chapters[:3]] == [1, 2, 3]


async def test_a_chapter_is_read_as_prose():
    chapter = Chapter(url=CHAPTER1, title="الفصل 1", number="1", index=1)
    text = await RewayatAdapter(sessions()).fetch_text(chapter)

    assert len(text.blocks) > 20
    assert text.characters > 2000


async def test_page_images_are_refused_with_a_reason():
    chapter = Chapter(url=CHAPTER1, title="الفصل 1", number="1", index=1)
    with pytest.raises(AdapterError, match="serves prose"):
        await RewayatAdapter(sessions()).fetch_pages(chapter)


# -------------------------------------------------------------------- search


SEARCH_URL = "https://rewayat.club/library?search=%D8%B3%D8%A7%D8%B7%D9%88%D8%B1"
SENTINEL = "zzqvoneshelfnonexistent987654321"
SENTINEL_URL = f"https://rewayat.club/library?search={SENTINEL}"


async def test_search_returns_the_novel_under_its_own_name():
    """The result card wraps the title *and* its genre tags in one anchor.

    Reading the anchor's text gave "ساطور الخطيئة مترجمة أكشن فانتازيا" — a
    title no reader would recognise and one nothing else would match.
    """
    manager = FakeSessionManager(pages={SEARCH_URL: _fixture("search.html")})

    results = await RewayatAdapter(manager).search(
        "https://rewayat.club", "ساطور")

    assert [r.title for r in results] == ["ساطور الخطيئة"]
    assert results[0].url == f"{NOVEL}"


async def test_search_answers_an_unanswerable_query_with_nothing():
    manager = FakeSessionManager(pages={SENTINEL_URL: _fixture("search-empty.html")})

    assert await RewayatAdapter(manager).search(
        "https://rewayat.club", SENTINEL) == []


async def test_an_authors_note_length_chapter_is_read_rather_than_rejected():
    """A 24-character chapter is short, not broken markup.

    Container selection used to ask `looks_like_prose`, which answers "prose or
    pictures?" and carries a length floor with it. `riwayatarab`, which takes
    its container directly, read the same input fine — so the two adapters
    disagreed about the same chapter.
    """
    url = f"{NOVEL}/8"
    note = "ملاحظة المترجم: عدت غدا."
    page = f"<html><body><div class='v-card v-card--flat'><p>{note}</p></div></body></html>"
    manager = FakeSessionManager(pages={url: page})
    chapter = Chapter(url=url, title="الفصل 8", number="8", index=8)

    text = await RewayatAdapter(manager).fetch_text(chapter)

    assert [b.text for b in text.blocks] == [note]


async def test_a_short_chapter_is_read_rather_than_rejected():
    """A short chapter is short, not broken markup.

    `fetch_text` used `looks_like_prose` to pick its container, so a chapter
    under that threshold failed with "No chapter text ... the reader's markup
    has changed" — wrong twice over: the markup was fine and the chapter was
    readable. `looks_like_prose` answers "prose or pictures?", which is not the
    question being asked here.
    """
    url = f"{NOVEL}/9"
    short = "قصيرة " * 60
    page = (f"<html><body><div class='v-card v-card--flat'>"
            f"<p>{short}</p><p>{short}</p></div></body></html>")
    manager = FakeSessionManager(pages={url: page})
    chapter = Chapter(url=url, title="الفصل 9", number="9", index=9)

    text = await RewayatAdapter(manager).fetch_text(chapter)

    assert text.blocks
    assert text.characters > 300


async def test_a_reader_with_no_readable_text_still_fails():
    """The guard that has to survive the fix."""
    url = f"{NOVEL}/10"
    page = "<html><body><div class='v-card v-card--flat'></div></body></html>"
    manager = FakeSessionManager(pages={url: page})
    chapter = Chapter(url=url, title="الفصل 10", number="10", index=10)

    with pytest.raises(AdapterError):
        await RewayatAdapter(manager).fetch_text(chapter)
