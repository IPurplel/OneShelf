"""Project Gutenberg: real search markup, and the download list's traps.

Fixtures are trimmed copies of the live pages. The download table is the point:
Gutenberg lists the same text as three EPUB variants, offers "send to Dropbox"
links that are an OAuth flow rather than a file, and names every download
``…epub3.images`` — an extension no reader opens.
"""

from __future__ import annotations

import pytest

from app.adapters import registry
from app.adapters.base import AdapterError
from app.adapters.gutenberg import GutenbergAdapter, _downloads
from app.models import Chapter

from .conftest import FakeSessionManager, fixture

SITE = "https://www.gutenberg.org"
BOOK = f"{SITE}/ebooks/84"
SEARCH = f"{SITE}/ebooks/search/?query=frankenstein"


def _fixture(name: str) -> str:
    return fixture(f"books/{name}")


@pytest.fixture
def sessions():
    return FakeSessionManager(pages={
        SEARCH: _fixture("gutenberg_search.html"),
        BOOK: _fixture("gutenberg_book.html"),
    })


# ------------------------------------------------------------- identification


def test_matches_its_host_only():
    assert GutenbergAdapter.matches(BOOK)
    assert GutenbergAdapter.matches("https://gutenberg.org/ebooks/1")
    assert not GutenbergAdapter.matches("https://example.net/ebooks/84")


def test_the_registry_picks_it_without_fetching():
    class Forbidden:
        async def fetch_html(self, url, **kwargs):
            raise AssertionError("resolving a Gutenberg URL fetched the page")

    assert registry.select(BOOK) is GutenbergAdapter


async def test_resolve_uses_the_host_alone():
    class Forbidden:
        async def fetch_html(self, url, **kwargs):
            raise AssertionError("resolving a Gutenberg URL fetched the page")

    adapter = await registry.resolve(BOOK, Forbidden())
    assert isinstance(adapter, GutenbergAdapter)


def test_it_is_a_book_source_that_writes_files():
    assert GutenbergAdapter.content_type == "book"
    assert GutenbergAdapter.packaging == "file"


def test_a_url_without_an_id_is_rejected_clearly():
    from app.adapters.gutenberg import _book_id

    with pytest.raises(AdapterError, match="not a Project Gutenberg book URL"):
        _book_id("https://www.gutenberg.org/browse/scores/top")


# -------------------------------------------------------------------- search


async def test_search_reads_the_booklink_list(sessions):
    results = await GutenbergAdapter(sessions).search(SITE, "frankenstein")

    assert len(results) == 3
    first = results[0]
    # The title is the title. The author used to be appended to it so that an
    # author query had something to score against, which made every displayed
    # title wrong; it now travels in its own field and relevance() reads that.
    assert first.title == "Frankenstein; or, the modern prometheus"
    # Still worth having: this catalogue is full of same-named editions.
    assert first.author == "Mary Wollstonecraft Shelley"
    assert first.url == BOOK
    assert first.site == "gutenberg.org"
    assert first.cover_url.startswith("https://www.gutenberg.org/cache/epub/84/")
    assert first.source == "gutenberg"


async def test_search_honours_the_limit(sessions):
    assert len(await GutenbergAdapter(sessions).search(SITE, "frankenstein", limit=1)) == 1


# -------------------------------------------------------------------- series


async def test_series_metadata(sessions):
    series = await GutenbergAdapter(sessions).fetch_series(BOOK)

    assert series.title == "Frankenstein; or, the modern prometheus"
    assert series.author.startswith("Shelley, Mary Wollstonecraft")
    assert series.cover_url.endswith("pg84.cover.medium.jpg")
    assert series.site_id == "84"


async def test_a_file_url_still_resolves_the_book(sessions):
    series = await GutenbergAdapter(sessions).fetch_series(f"{SITE}/ebooks/84.epub3.images")
    assert series.url == BOOK


# ----------------------------------------------------------------- downloads


def test_one_entry_per_real_format():
    """Three EPUB variants of one text are one choice, not three."""
    files = _downloads(_fixture("gutenberg_book.html"), BOOK)
    extensions = [ext for _url, ext in files]

    assert extensions == sorted(set(extensions), key=extensions.index)
    assert extensions.count(".epub") == 1
    assert extensions[0] == ".epub"   # the format most readers want, first


def test_the_best_epub_variant_wins():
    files = dict((ext, url) for url, ext in _downloads(_fixture("gutenberg_book.html"), BOOK))
    assert files[".epub"].endswith("/ebooks/84.epub3.images")


def test_cloud_transfer_links_are_not_downloads():
    """"Send to Dropbox" is an OAuth flow that returns HTML, not a book."""
    files = _downloads(_fixture("gutenberg_book.html"), BOOK)
    assert all("/ebooks/send/" not in url for url, _ in files)


async def test_chapters_are_named_after_the_book(sessions):
    """A download called "84.epub3.images" is a file nothing opens."""
    adapter = GutenbergAdapter(sessions)
    series = await adapter.fetch_series(BOOK)
    chapters = await adapter.fetch_chapters(series)

    assert chapters[0].title == "Frankenstein; or, the modern prometheus.epub"
    assert all(c.title.endswith((".epub", ".azw3", ".pdf")) for c in chapters)
    assert [c.index for c in chapters] == list(range(1, len(chapters) + 1))


async def test_pages_resolve_to_the_file_with_the_book_as_referer(sessions):
    adapter = GutenbergAdapter(sessions)
    series = await adapter.fetch_series(BOOK)
    chapters = await adapter.fetch_chapters(series)

    pages = await adapter.fetch_pages(chapters[0])
    assert len(pages) == 1
    assert pages[0].url == f"{SITE}/ebooks/84.epub3.images"
    assert pages[0].referer == BOOK


async def test_a_book_with_no_usable_format_says_so():
    page = "<html><body><table class='files'></table></body></html>"
    sessions = FakeSessionManager(pages={BOOK: page})
    adapter = GutenbergAdapter(sessions)
    series_page = ('<html><body><td itemprop="headline">X</td>'
                   "<table class='files'></table></body></html>")
    sessions.pages[BOOK] = series_page
    series = await adapter.fetch_series(BOOK)
    adapter._cache.clear()
    with pytest.raises(AdapterError, match="no EPUB"):
        await adapter.fetch_chapters(series)


async def test_a_stale_format_reference_is_reported(sessions):
    with pytest.raises(AdapterError, match="no longer offered"):
        await GutenbergAdapter(sessions).fetch_pages(
            Chapter(url=f"{BOOK}#9", title="x.epub", index=9))
