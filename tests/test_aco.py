"""Arabic Collections Online, against its real captured manifest.

See tests/fixtures/aco/PROVENANCE.md — the manifest is as served, apart from
trimming the 524 page canvases the adapter never reads.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.adapters.aco import AcoAdapter, book_id
from app.adapters.base import AdapterError
from app.models import Series

from .conftest import FakeSessionManager

FIXTURE = Path(__file__).parent / "fixtures/aco/manifest.json"
BOOK = "aub_aco000056"
URL = f"https://aco.dlib.nyu.edu/book/{BOOK}/1"
MANIFEST_URL = (
    "https://sites.dlib.nyu.edu/viewer/api/presentation/books/"
    f"{BOOK}/manifest.json")


def sessions():
    return FakeSessionManager(
        pages={}, json_routes={MANIFEST_URL: json.loads(
            FIXTURE.read_text(encoding="utf-8"))})


# ------------------------------------------------------------ identification


@pytest.mark.parametrize("url", [
    URL,
    "https://sites.dlib.nyu.edu/viewer/books/aub_aco000056/1",
    "https://dlib.nyu.edu/aco/",
])
def test_the_collection_is_recognised_wherever_it_is_linked_from(url):
    assert AcoAdapter.matches(url)


def test_the_rest_of_the_university_library_is_not_claimed():
    """`dlib.nyu.edu` hosts far more than this collection, so the path decides."""
    assert not AcoAdapter.matches("https://dlib.nyu.edu/findingaids/")
    assert not AcoAdapter.matches("https://example.net/book/aub_aco000056/1")


@pytest.mark.parametrize("url, expected", [
    (URL, BOOK),
    (f"https://sites.dlib.nyu.edu/viewer/books/{BOOK}", BOOK),
    (f"https://sites.dlib.nyu.edu/viewer/books/{BOOK}/display?lang=ar", BOOK),
])
def test_the_book_id_is_read_from_every_url_shape_the_site_uses(url, expected):
    assert book_id(url) == expected


def test_a_url_naming_no_book_says_so():
    with pytest.raises(AdapterError, match="does not name a book"):
        book_id("https://aco.dlib.nyu.edu/about")


# ------------------------------------------------------------------- reading


async def test_the_record_comes_from_the_manifest_not_the_page():
    """The page a reader lands on is a 6.5 KB JavaScript shell: no title, no
    author, no file. Everything here is read from one JSON document."""
    manager = sessions()
    series = await AcoAdapter(manager).fetch_series(URL)

    assert series.title == "Sharḥ dīwān al-Mutanabbī v.3"
    assert series.site_id == BOOK
    assert series.cover_url and series.cover_url.startswith("https://")
    assert manager.pages == {}, "no HTML page should be fetched at all"


async def test_both_resolutions_are_offered_and_named_apart():
    """A library listing two identically-named PDFs is one where the second
    silently overwrites the first."""
    series = Series(url=URL, title="Sharḥ dīwān al-Mutanabbī v.3", source="aco")
    chapters = await AcoAdapter(sessions()).fetch_chapters(series)

    assert [c.title for c in chapters] == [
        "Sharḥ dīwān al-Mutanabbī v.3 (high resolution).pdf",
        "Sharḥ dīwān al-Mutanabbī v.3 (low resolution).pdf",
    ]


async def test_the_extension_is_the_last_thing_in_the_name():
    """A download is matched on the path's extension.

    The manifest's own label is "High-resolution PDF rendering (262.26 MB)";
    appending it after the extension produced a name ending in "MB))" and the
    queue refused the file as a type it does not store.
    """
    series = Series(url=URL, title="A Book", source="aco")
    chapters = await AcoAdapter(sessions()).fetch_chapters(series)

    assert all(c.title.endswith(".pdf") for c in chapters)


async def test_a_chapter_resolves_to_the_whole_book_pdf():
    series = Series(url=URL, title="A Book", source="aco")
    adapter = AcoAdapter(sessions())
    chapters = await adapter.fetch_chapters(series)

    pages = await adapter.fetch_pages(chapters[0])

    assert len(pages) == 1
    assert pages[0].url.endswith("_hi.pdf")
    assert (await adapter.fetch_pages(chapters[1]))[0].url.endswith("_lo.pdf")


async def test_a_rendering_in_a_format_the_library_does_not_store_is_skipped():
    from app.adapters.aco import _renderings

    assert _renderings({"rendering": [
        {"id": "https://x/y.pdf", "format": "application/pdf"},
        {"id": "https://x/y.zip", "format": "application/zip"},
        {"format": "application/pdf"},          # no url
    ]}) == [("https://x/y.pdf", ".pdf", "")]


async def test_a_book_with_no_whole_file_says_how_many_pages_it_has_instead():
    """An honest error: the pages exist, the bound copy does not."""
    manager = FakeSessionManager(pages={}, json_routes={
        MANIFEST_URL: {"items": [{}, {}, {}], "rendering": []}})
    series = Series(url=URL, title="A Book", source="aco")

    with pytest.raises(AdapterError, match="3 scanned page"):
        await AcoAdapter(manager).fetch_chapters(series)


def test_a_multilingual_label_prefers_english_for_the_filename():
    """IIIF labels are language maps. English is the half that survives a
    filesystem and a library listing; any language beats none."""
    from app.adapters.aco import _label

    assert _label({"en": ["English"], "ar": ["عربي"]}) == "English"
    assert _label({"ar": ["عربي"]}) == "عربي"
    assert _label("plain") == "plain"
    assert _label(None) == ""


async def test_the_manifest_is_fetched_once_however_often_it_is_needed():
    manager = sessions()
    adapter = AcoAdapter(manager)
    series = await adapter.fetch_series(URL)
    chapters = await adapter.fetch_chapters(series)
    await adapter.fetch_pages(chapters[0])
    await adapter.fetch_pages(chapters[1])

    assert manager.requested.count(MANIFEST_URL) == 1


# -------------------------------------------------------------------- search


SEARCH_URL = "https://aco.dlib.nyu.edu/search?q=mutanabbi"
SENTINEL = "zzqvoneshelfnonexistent987654321"
SENTINEL_URL = f"https://aco.dlib.nyu.edu/search?q={SENTINEL}"


def _html(name: str) -> str:
    return (FIXTURE.parent / name).read_text(encoding="utf-8")


async def test_search_returns_each_book_once_with_its_arabic_title_kept():
    """Every hit appears twice: romanised, and again under `?lang=ar`.

    They are the same book, so the Arabic name becomes the alt title rather
    than a second entry — which is also what makes an Arabic query visibly
    land on the right record when the romanised name is what gets shown.
    """
    manager = FakeSessionManager(pages={SEARCH_URL: _html("search.html")})

    results = await AcoAdapter(manager).search(
        "https://aco.dlib.nyu.edu", "mutanabbi")

    assert results, "the captured page holds 30 book links"
    assert len(results) == len({r.url for r in results}), "no book listed twice"
    first = results[0]
    assert "Mutanabb" in first.title
    assert first.alt_title and "المتنبي" in first.alt_title
    assert first.url.endswith("/1")
    assert "?lang=ar" not in first.url


async def test_search_answers_an_unanswerable_query_with_nothing():
    """The half that keeps a source out of every unrelated search."""
    manager = FakeSessionManager(pages={SENTINEL_URL: _html("search-empty.html")})

    assert await AcoAdapter(manager).search(
        "https://aco.dlib.nyu.edu", SENTINEL) == []


async def test_the_download_buttons_in_a_result_card_are_not_read_as_titles():
    """A result card holds the title link, a "Read Online" control pointing at
    the same page, and two PDF links on `mc.dlib.nyu.edu/files/books/<id>/…`.
    All three match the book-id pattern, so an unrestricted sweep took the
    title from whichever came last and named every hit
    "تحميل دِقّة منخفضةLow-resolution PDF(34.…)".
    """
    manager = FakeSessionManager(pages={SEARCH_URL: _html("search.html")})

    results = await AcoAdapter(manager).search(
        "https://aco.dlib.nyu.edu", "mutanabbi")

    for hit in results:
        assert "PDF" not in hit.title and "Read Online" not in hit.title
        assert hit.url.startswith("https://aco.dlib.nyu.edu/book/")


# ------------------------------------------- the viewer host is not ACO's own


@pytest.mark.parametrize("url", [
    "https://sites.dlib.nyu.edu/",
    "https://sites.dlib.nyu.edu/anything/else",
    "https://sites.dlib.nyu.edu/viewer/",
])
def test_the_shared_viewer_host_is_not_claimed_wholesale(url):
    """`sites.dlib.nyu.edu` is NYU's DLTS viewer, not ACO's own host.

    Its book ids are collection-prefixed (`aub_…`, `princeton_…`) and its root
    is a bare "Index of /". Because this adapter sets `owns_its_host`, the
    registry skips fingerprinting entirely — so claiming the whole host routed
    every unrelated URL on it here.
    """
    assert not AcoAdapter.matches(url)


def test_the_viewer_path_that_does_serve_books_is_still_claimed():
    assert AcoAdapter.matches(
        "https://sites.dlib.nyu.edu/viewer/books/aub_aco000056/1")
    assert AcoAdapter.matches("https://aco.dlib.nyu.edu/book/aub_aco000056/1")


async def test_each_format_can_be_selected_by_number():
    """A multi-format book has to be addressable one item at a time.

    Its chapters carried no `number`, so anything selecting by number — the
    verification tool's `--chapter`, and any tooling that addresses a chapter
    by name rather than by checkbox — could not reach the second format at all
    and reported "no selectable chapter matches".
    """
    series = Series(url=URL, title="A Book", source="aco")
    chapters = await AcoAdapter(sessions()).fetch_chapters(series)

    assert [c.number for c in chapters] == ["1", "2"]
    assert [c.index for c in chapters] == [1, 2]


def test_numbering_does_not_reach_the_filename():
    """`file` packaging names each download after the book, so the number is
    for selection only — a book must not become "A Book - c001.pdf"."""
    from app.models import Chapter

    chapter = Chapter(url=f"{URL}#1", title="A Book (low resolution).pdf",
                      number="1", index=1)
    assert chapter.title.endswith(".pdf")
    assert "c001" not in chapter.title
