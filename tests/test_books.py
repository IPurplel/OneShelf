"""Book sites: link scanning, file naming, and the write-through pipeline.

Markup below follows the two sites this was built against — planetebook, which
offers one book in three formats, and 8ghrb, whose "book page" is a list of
seventy-two PDFs hosted on an entirely different domain.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.adapters import registry
from app.adapters.base import AdapterError
from app.adapters.books import (
    BooksAdapter, _canonical_kitaboka_url, _clean_title, _file_links)
from app.adapters.madara import MadaraAdapter
from app.models import Chapter, Series
from app.packager import (
    LIBRARY_EXTENSIONS,
    book_path,
    looks_like_document,
    verify_file,
    write_file,
)

from .conftest import FakeSessionManager, make_noise_png

BOOK_URL = "https://www.planetebook.com/agnes-grey/"

BOOK_HTML = """
<html><head>
  <title>Agnes Grey — Download Free at Planet eBook</title>
  <meta property="og:title" content="Agnes Grey">
  <meta property="og:image" content="/covers/agnes-grey.jpg">
  <meta property="og:description" content="Anne Bronte's first novel.">
</head><body>
  <h1>Agnes Grey</h1>
  <a href="/free-ebooks/agnes-grey.epub">ePUB</a>
  <a href="/free-ebooks/agnes-grey.pdf">PDF</a>
  <a href="/free-ebooks/agnes-grey.mobi">MOBI</a>
  <a href="https://helpx.adobe.com/reader/download.html">Download Adobe Reader</a>
  <a href="/about/">About</a>
</body></html>
"""

COLLECTION_URL = "https://8ghrb.com/thakafat/"
COLLECTION_HTML = """
<html><head><title>سلسلة من ثقافات الشعوب – قهوة 8 غرب</title></head><body>
  <h1>سلسلة من ثقافات الشعوب</h1>
  <a href="http://www.bookleaks.com/files/thakafat/1.pdf">للتحميل اضغط هنا</a>
  <a href="http://www.bookleaks.com/files/thakafat/2.pdf">للتحميل اضغط هنا</a>
</body></html>
"""


@pytest.fixture
def sessions():
    return FakeSessionManager(pages={BOOK_URL: BOOK_HTML,
                                     COLLECTION_URL: COLLECTION_HTML})


# ------------------------------------------------------------- identification


def test_matches_a_page_that_links_book_files():
    assert BooksAdapter.matches("https://any.example/book/", BOOK_HTML)
    assert BooksAdapter.matches(BOOK_URL)


def test_a_page_with_no_book_files_is_not_a_book_page():
    assert not BooksAdapter.matches(
        "https://any.example/x/", "<html><a href='/about'>About</a></html>")


def test_a_comic_page_is_never_read_as_a_book():
    """A manga page that happens to link a PDF is still a manga page."""
    madara = ('<html><body><div class="wp-manga">'
              '<li class="wp-manga-chapter"><a href="/manga/x/ch-1/">1</a></li>'
              '<a href="/files/guide.pdf">Reading guide</a>'
              "</div></body></html>")
    assert registry.select("https://x.net/manga/y/", madara) is MadaraAdapter


def test_the_registry_picks_it_for_a_book_page():
    assert registry.select(BOOK_URL, BOOK_HTML) is BooksAdapter


async def test_resolving_a_known_book_host_never_renders_the_page():
    """Static publisher pages: a browser adds seconds and nothing else."""
    class Forbidden:
        async def fetch_html(self, url, **kwargs):
            raise AssertionError("resolving a book page started a browser")

    assert isinstance(await registry.resolve(BOOK_URL, Forbidden()), BooksAdapter)


# -------------------------------------------------------------------- links


def test_only_the_extension_makes_a_link_a_book():
    """Filtering on the word "download" matched an Adobe help page."""
    links = _file_links(BOOK_HTML, BOOK_URL)

    assert [url for url, _ in links] == [
        "https://www.planetebook.com/free-ebooks/agnes-grey.epub",
        "https://www.planetebook.com/free-ebooks/agnes-grey.pdf",
        "https://www.planetebook.com/free-ebooks/agnes-grey.mobi",
    ]


def test_a_path_that_merely_contains_an_extension_is_not_a_file():
    html = '<html><a href="/report.pdf.html">Report</a></html>'
    assert _file_links(html, "https://x.net/") == []


def test_a_filename_with_a_semicolon_is_still_a_file():
    """`urlparse` cuts the last path segment at ';' as RFC 2396 params.

    Publishers name uploads after the book, and bettergutenberg serves
    "007_Frankenstein; or, the modern prometheus_pg84.epub" — whose extension
    lands in `params`, making every book on the site invisible.
    """
    href = ("/wp-content/uploads/library/classic-literature/"
            "007_Frankenstein; or, the modern prometheus_pg84.epub")
    html = f'<html><a href="{href}">⬇ Download EPUB</a></html>'

    links = _file_links(html, "https://bettergutenberg.org/x/")
    assert len(links) == 1
    assert links[0][0].endswith("_pg84.epub")


def test_a_file_url_is_encoded_before_it_is_fetched():
    """Spaces and semicolons are legal in a name and illegal in a request."""
    from app.adapters.books import _encoded

    encoded = _encoded("https://x.net/lib/007_Frankenstein; or, the modern.epub")
    assert " " not in encoded
    assert encoded.endswith("modern.epub")
    # Already-encoded URLs must not be double-encoded.
    assert _encoded("https://x.net/a%20b.epub") == "https://x.net/a%20b.epub"


@pytest.mark.parametrize(
    "given,expected",
    [
        ("Agnes Grey — Download Free at Planet eBook", "Agnes Grey"),
        ("سلسلة من ثقافات الشعوب – قهوة 8 غرب", "سلسلة من ثقافات الشعوب"),
        ("Plain Title", "Plain Title"),
    ],
)
def test_site_branding_is_trimmed_from_the_title(given, expected):
    assert _clean_title(given) == expected


# ------------------------------------------------------------------- series


async def test_series_metadata(sessions):
    series = await BooksAdapter(sessions).fetch_series(BOOK_URL)

    assert series.title == "Agnes Grey"
    assert series.cover_url == "https://www.planetebook.com/covers/agnes-grey.jpg"
    assert series.description == "Anne Bronte's first novel."
    assert series.source == "books"


async def test_each_format_is_its_own_item(sessions):
    """One book in three formats: named after the book, not the site's file."""
    adapter = BooksAdapter(sessions)
    chapters = await adapter.fetch_chapters(await adapter.fetch_series(BOOK_URL))

    assert [c.title for c in chapters] == [
        "Agnes Grey.epub", "Agnes Grey.pdf", "Agnes Grey.mobi"]
    assert [c.index for c in chapters] == [1, 2, 3]
    # The identity is the page plus a position, so it survives a restart.
    assert chapters[0].url == f"{BOOK_URL}#1"


async def test_a_single_file_is_named_after_the_book():
    """These sites name files by database id ("2463.pdf"), which is no use."""
    html = ('<html><head><title>رواية الغريب – قهوة 8 غرب</title></head><body>'
            '<h1>رواية الغريب</h1>'
            '<a href="https://book-shadow.com/files/fhrst15/2463.pdf">تحميل</a>'
            "</body></html>")
    url = "https://8ghrb.com/gharib/"
    adapter = BooksAdapter(FakeSessionManager(pages={url: html}))
    chapters = await adapter.fetch_chapters(await adapter.fetch_series(url))

    assert [c.title for c in chapters] == ["رواية الغريب.pdf"]


async def test_a_collection_page_keeps_the_sites_numbering(sessions):
    """Twenty PDFs are volumes: the site's numbering is what separates them."""
    adapter = BooksAdapter(sessions)
    chapters = await adapter.fetch_chapters(await adapter.fetch_series(COLLECTION_URL))
    assert [c.title for c in chapters] == ["1.pdf", "2.pdf"]


async def test_a_page_with_no_files_is_explained(sessions):
    empty = FakeSessionManager(pages={BOOK_URL: "<html><h1>Nothing</h1></html>"})
    adapter = BooksAdapter(empty)
    with pytest.raises(AdapterError, match="No book files"):
        await adapter.fetch_chapters(await adapter.fetch_series(BOOK_URL))


# -------------------------------------------------------------------- pages


async def test_the_download_carries_the_book_page_as_referer(sessions):
    """The file host is often not the site host, and those hosts check."""
    pages = await BooksAdapter(sessions).fetch_pages(
        Chapter(url=f"{COLLECTION_URL}#2", title="2.pdf", index=2))

    assert len(pages) == 1
    assert pages[0].url == "http://www.bookleaks.com/files/thakafat/2.pdf"
    assert pages[0].referer == COLLECTION_URL


async def test_a_link_that_has_moved_is_reported_clearly(sessions):
    with pytest.raises(AdapterError, match="no longer linked"):
        await BooksAdapter(sessions).fetch_pages(
            Chapter(url=f"{BOOK_URL}#9", title="gone.pdf", index=9))


# ---------------------------------------------------------------- packaging


# ------------------------------------------------------------------- search

# planetebook's theme wraps each result in <article>; 8ghrb's wraps it in
# <li class="post-item post">. Both are WordPress ?s= pages, and both correctly
# return nothing for a query they do not have — which is what makes them safe
# to put in a multi-site search.
PLANET_SEARCH = """
<html><body><main>
  <article class="fusion-post-grid post post-12038 type-post">
    <h2><a href="https://www.planetebook.com/agnes-grey/">Agnes Grey</a></h2>
    <img src="https://www.planetebook.com/covers/agnes-390x220.jpg">
  </article>
</main></body></html>
"""

GHRB_SEARCH = """
<html><body><ul>
  <li class="post-item post-130212 post type-post has-post-thumbnail category-3348">
    <a aria-label="رواية مخطوط الغريب" href="https://8ghrb.com/makhtot/" class="post-thumb">
      <img src="https://8ghrb.com/wp-content/uploads/2026/08/22-12-390x220.jpg"></a>
    <div class="post-details"><h2 class="post-title">
      <a href="https://8ghrb.com/makhtot/">رواية مخطوط الغريب – عمرو يسري</a></h2></div>
  </li>
  <li class="post-item post-130206 post type-post">
    <h2 class="post-title">
      <a href="https://8ghrb.com/modon/">كتاب مدن الغريب – ابتسام عازم</a></h2>
  </li>
  <li class="post-item post">
    <h2><a href="https://8ghrb.com/category/novels/">روايات</a></h2>
  </li>
</ul></body></html>
"""


async def test_search_returns_book_pages():
    sessions = FakeSessionManager(
        pages={"https://www.planetebook.com/?s=agnes": PLANET_SEARCH})
    results = await BooksAdapter(sessions).search(
        "https://www.planetebook.com", "agnes")

    assert [r.title for r in results] == ["Agnes Grey"]
    assert results[0].url == BOOK_URL
    assert results[0].source == "books"
    assert results[0].site == "www.planetebook.com"
    assert results[0].cover_url.endswith("agnes-390x220.jpg")


async def test_search_reads_a_theme_that_uses_list_items():
    sessions = FakeSessionManager(pages={
        "https://8ghrb.com/?s=%D8%A7%D9%84%D8%BA%D8%B1%D9%8A%D8%A8": GHRB_SEARCH,
        "https://8ghrb.com/makhtot/": '<a href="/files/makhtot.pdf">PDF</a>',
        "https://8ghrb.com/modon/": '<a href="/files/modon.pdf">PDF</a>',
    })
    results = await BooksAdapter(sessions).search("https://8ghrb.com", "الغريب")

    assert [r.url for r in results] == [
        "https://8ghrb.com/makhtot/", "https://8ghrb.com/modon/"]
    # The heading wins over the thumbnail's aria-label, which is truncated.
    assert results[0].title.startswith("رواية مخطوط الغريب")


async def test_category_listings_are_not_offered_as_books():
    """A search page links its own archives; those have nothing to download."""
    sessions = FakeSessionManager(
        pages={"https://8ghrb.com/?s=x": GHRB_SEARCH})
    results = await BooksAdapter(sessions).search("https://8ghrb.com", "x")
    assert all("/category/" not in r.url for r in results)


async def test_search_honours_the_limit():
    sessions = FakeSessionManager(pages={
        "https://8ghrb.com/?s=%D8%A7%D9%84%D8%BA%D8%B1%D9%8A%D8%A8": GHRB_SEARCH,
        "https://8ghrb.com/makhtot/": '<a href="/files/makhtot.pdf">PDF</a>',
        "https://8ghrb.com/modon/": '<a href="/files/modon.pdf">PDF</a>',
    })
    results = await BooksAdapter(sessions).search(
        "https://8ghrb.com", "الغريب", limit=1)
    assert len(results) == 1


async def test_a_widget_of_recent_titles_is_not_mistaken_for_results():
    """Search pages render "latest books" in the same markup as a hit.

    arabic-book.net does exactly this: a query it cannot answer comes back
    carrying ten recent titles and no way to tell them from real results.
    """
    sessions = FakeSessionManager(
        pages={"https://8ghrb.com/?s=zzzqqq": GHRB_SEARCH})
    assert await BooksAdapter(sessions).search("https://8ghrb.com", "zzzqqq") == []


# bettergutenberg builds its sections and its books as the same kind of
# WordPress page, so only the depth of the URL separates "Novels" from a novel.
BG_SEARCH = """
<html><body>
  <article class="post-218 page type-page status-publish hentry">
    <h2><a rel="bookmark"
      href="https://bettergutenberg.org/classic-literature/frankenstein-or-the-modern-prometheus/"
      >Frankenstein; or, the Modern Prometheus</a></h2>
  </article>
  <article class="post-1425 page type-page status-publish hentry">
    <h2><a rel="bookmark" href="https://bettergutenberg.org/novels/">Novels</a></h2>
  </article>
</body></html>
"""


# arabic-book.net: titles live in an h4, and the file is base64 in a data
# attribute rather than an anchor.
AB_SEARCH = """
<html><body>
  <article class="uagb-post__inner-wrap">
    <div class="uagb-post__image">
      <a href="https://arabic-book.net/313"><img src="/uploads/cover.jpg"></a>
    </div>
    <h4 class="uagb-post__title">
      <a href="https://arabic-book.net/313">“أمواج أكما – قواعد جارتين 3” عمرو عبد الحميد</a>
    </h4>
  </article>
</body></html>
"""

AB_BOOK = """
<html><head><title>“أمواج أكما” – Arabic-Book.net</title></head><body>
  <h1>“أمواج أكما – قواعد جارتين 3” عمرو عبد الحميد</h1>
  <span class="dl" data-href="aHR0cHM6Ly9hcmFiaWMtYm9vay5uZXQvd3AtY29udGVudC91cGxvYWRzLzIwMjUvMDIvXzIzNzU3X2ZvdWxhYm9vay5jb21fLnBkZg==">تحميل</span>
</body></html>
"""


async def test_a_title_in_an_h4_is_still_found():
    sessions = FakeSessionManager(
        pages={"https://arabic-book.net/?s=%D8%A3%D9%85%D9%88%D8%A7%D8%AC":
               AB_SEARCH})
    results = await BooksAdapter(sessions).search("https://arabic-book.net", "أمواج")

    assert len(results) == 1
    assert results[0].url == "https://arabic-book.net/313"
    # The cover anchor comes first in the DOM and has no text; the heading wins.
    assert results[0].title.startswith("“أمواج أكما")
    assert results[0].cover_url.endswith("/uploads/cover.jpg")


async def test_a_dash_inside_a_books_own_title_survives():
    """Trimming site branding must not cut a title at its own punctuation."""
    sessions = FakeSessionManager(
        pages={"https://arabic-book.net/?s=%D8%A3%D9%85%D9%88%D8%A7%D8%AC":
               AB_SEARCH})
    results = await BooksAdapter(sessions).search("https://arabic-book.net", "أمواج")
    assert "قواعد جارتين 3" in results[0].title


async def test_a_file_hidden_as_base64_is_found():
    """The page offers no anchor at all — the PDF is in a data attribute."""
    url = "https://arabic-book.net/313"
    sessions = FakeSessionManager(pages={url: AB_BOOK})
    adapter = BooksAdapter(sessions)
    chapters = await adapter.fetch_chapters(await adapter.fetch_series(url))

    assert len(chapters) == 1
    pages = await adapter.fetch_pages(chapters[0])
    assert pages[0].url == ("https://arabic-book.net/wp-content/uploads/2025/02/"
                            "_23757_foulabook.com_.pdf")
    assert pages[0].referer == url


def test_base64_that_is_not_a_book_url_is_ignored():
    """The decoder must not turn arbitrary encoded data into a download."""
    import base64

    for payload in ("hello there, this is not a url at all",
                    "https://tracker.example/pixel.gif?u=12345678"):
        encoded = base64.b64encode(payload.encode()).decode()
        html = f'<html><body><span data-x="{encoded}">x</span></body></html>'
        assert _file_links(html, "https://arabic-book.net/1") == []


async def test_section_listings_are_dropped_where_only_depth_tells():
    sessions = FakeSessionManager(
        pages={"https://bettergutenberg.org/?s=frankenstein": BG_SEARCH})
    results = await BooksAdapter(sessions).search(
        "https://bettergutenberg.org", "frankenstein")

    assert [r.title for r in results] == ["Frankenstein; or, the Modern Prometheus"]


async def test_the_depth_rule_does_not_apply_to_other_sites():
    """planetebook's books live at the root, so depth must stay site-specific."""
    sessions = FakeSessionManager(
        pages={"https://www.planetebook.com/?s=agnes": PLANET_SEARCH})
    results = await BooksAdapter(sessions).search(
        "https://www.planetebook.com", "agnes")
    assert [r.url for r in results] == [BOOK_URL]


async def test_a_search_with_no_hits_returns_nothing():
    sessions = FakeSessionManager(
        pages={"https://8ghrb.com/?s=zzz": "<html><body><main></main></body></html>"})
    assert await BooksAdapter(sessions).search("https://8ghrb.com", "zzz") == []


def test_the_book_sites_are_searched():
    from app.config import Settings

    sites = Settings(config_dir=Path(".")).search_sites
    assert "https://8ghrb.com" in sites
    assert "https://www.noor-book.com" in sites
    assert "https://kitaboka.com" in sites
    assert "https://www.planetebook.com" in sites


# ---------------------------------------------------------------- packaging


def test_books_are_stored_under_their_own_filename(tmp_path):
    series = Series(url=BOOK_URL, title="Agnes Grey", source="books")
    path = book_path(tmp_path, series, Chapter(url="x", title="agnes-grey.epub"))

    assert path == tmp_path / "Agnes Grey" / "agnes-grey.epub"


def test_three_formats_do_not_collide(tmp_path):
    series = Series(url=BOOK_URL, title="Agnes Grey", source="books")
    paths = {book_path(tmp_path, series, Chapter(url="x", title=name))
             for name in ("agnes-grey.epub", "agnes-grey.pdf", "agnes-grey.mobi")}
    assert len(paths) == 3


@pytest.mark.parametrize(
    "data,extension,expected",
    [
        (b"%PDF-1.7\n...", ".pdf", True),
        (b"PK\x03\x04....", ".epub", True),
        (b"<!DOCTYPE html><html>Access denied", ".pdf", False),
        (b"<html>Please log in</html>", ".epub", False),
        (b"", ".pdf", False),
    ],
)
def test_a_download_is_checked_against_its_extension(data, extension, expected):
    """An HTML login wall served as a .pdf must not become a "book"."""
    assert looks_like_document(data, extension) is expected


def test_verify_file_rejects_a_stub(tmp_path):
    path = tmp_path / "book.pdf"
    path.write_bytes(b"%PDF-" + b"0" * 10)   # right magic, far too small
    assert not verify_file(path)

    path.write_bytes(b"%PDF-" + b"0" * 4096)
    assert verify_file(path)


def test_write_file_is_atomic(tmp_path):
    destination = tmp_path / "sub" / "book.pdf"
    write_file(destination, b"%PDF-" + b"0" * 2048)

    assert destination.is_file()
    assert not list(tmp_path.rglob("*.tmp"))


def test_the_library_owns_book_formats():
    assert {".epub", ".pdf", ".mobi", ".cbz"} <= LIBRARY_EXTENSIONS
    # Never .txt: the same set is the delete path's allow-list.
    assert ".txt" not in LIBRARY_EXTENSIONS


GHRB_FILTER_SEARCH = """
<html><body><ul>
  <li class="post"><h2><a href="https://8ghrb.com/no-file/">
    رواية الغريب بلا ملف
  </a></h2></li>
  <li class="post"><h2><a href="https://8ghrb.com/with-file/">
    رواية الغريب المتاحة
  </a></h2></li>
  <li class="post"><h2><a href="https://8ghrb.com/second-file/">
    رواية الغريب الثانية
  </a></h2></li>
</ul></body></html>
"""


async def test_8ghrb_search_hides_posts_that_only_link_to_facebook():
    search_url = "https://8ghrb.com/?s=%D8%A7%D9%84%D8%BA%D8%B1%D9%8A%D8%A8"
    sessions = FakeSessionManager(pages={
        search_url: GHRB_FILTER_SEARCH,
        "https://8ghrb.com/no-file/":
            '<a href="https://facebook.com/groups/books">Facebook</a>',
        "https://8ghrb.com/with-file/":
            '<a href="https://files.example/book.pdf">PDF</a>',
        "https://8ghrb.com/second-file/":
            '<a href="https://files.example/second.epub">EPUB</a>',
    })

    results = await BooksAdapter(sessions).search(
        "https://8ghrb.com", "الغريب")

    assert [result.url for result in results] == [
        "https://8ghrb.com/with-file/",
        "https://8ghrb.com/second-file/",
    ]


async def test_8ghrb_search_limit_applies_after_unavailable_posts_are_filtered():
    search_url = "https://8ghrb.com/?s=%D8%A7%D9%84%D8%BA%D8%B1%D9%8A%D8%A8"
    sessions = FakeSessionManager(pages={
        search_url: GHRB_FILTER_SEARCH,
        "https://8ghrb.com/no-file/": '<a href="https://facebook.com/x">x</a>',
        "https://8ghrb.com/with-file/": '<a href="/files/one.pdf">PDF</a>',
        "https://8ghrb.com/second-file/": '<a href="/files/two.pdf">PDF</a>',
    })

    results = await BooksAdapter(sessions).search(
        "https://8ghrb.com", "الغريب", limit=1)

    assert [result.url for result in results] == [
        "https://8ghrb.com/with-file/"
    ]


KTOBATI_BOOK_URL = "https://www.ktobati.com/book/example"


def test_ktobati_is_not_claimed_as_a_book_source():
    """Excluded, not broken: reaching a Ktobati book requires an account.

    The adapter used to own this host and, when no file turned up, told the
    user to sign in to Ktobati in the app's browser profile. Instructing
    someone to authenticate is not a download path, so the host is no longer
    claimed by hostname at all. A page that genuinely links a file is still
    matched on that evidence, like any unknown site.
    """
    assert not BooksAdapter.matches(KTOBATI_BOOK_URL)
    assert not BooksAdapter.matches(KTOBATI_BOOK_URL, "<html><h1>Book</h1></html>")


NOOR_ROOT = "https://www.noor-book.com"
NOOR_SEARCH_URL = f"{NOOR_ROOT}/en/tag/white%20nights"
NOOR_BOOK_URL = (
    f"{NOOR_ROOT}/en/ebook-White-Nights-and-Other-Stories-pdf"
)
NOOR_SECOND_BOOK_URL = f"{NOOR_ROOT}/en/ebook-White-Nights-Study-pdf"
NOOR_PDF_URL = "https://files.noor-book.com/white-nights.pdf"

NOOR_SEARCH_HTML = """
<html><body>
  <a href="/en/book/review/123">
    <img src="/covers/restricted.jpg" alt="White Nights restricted">
    Unavailable White Nights restricted
  </a>
  <a href="/en/ebook-White-Nights-and-Other-Stories-pdf">
    <img src="/covers/white-nights.jpg">
    White Nights and Other Stories
  </a>
  <a href="/en/ebook-Restricted-White-Nights-pdf-123">
    Unavailable Restricted White Nights
  </a>
  <a href="/en/ebook-White-Nights-Study-pdf">
    White Nights Study
  </a>
  <a href="/en/ebook-Unrelated-pdf">Unrelated title</a>
</body></html>
"""


def test_noor_is_recognised_as_a_book_source():
    assert BooksAdapter.matches(NOOR_BOOK_URL)


async def test_noor_search_hides_catalog_only_books_and_keeps_covers():
    sessions = FakeSessionManager(pages={NOOR_SEARCH_URL: NOOR_SEARCH_HTML})

    results = await BooksAdapter(sessions).search(NOOR_ROOT, "white nights")

    assert [result.url for result in results] == [
        NOOR_BOOK_URL,
        NOOR_SECOND_BOOK_URL,
    ]
    assert results[0].cover_url == (
        "https://www.noor-book.com/covers/white-nights.jpg"
    )
    assert sessions.direct == [NOOR_SEARCH_URL]
    assert sessions.requested == []


async def test_noor_search_limit_applies_after_unavailable_results_are_filtered():
    sessions = FakeSessionManager(pages={NOOR_SEARCH_URL: NOOR_SEARCH_HTML})

    results = await BooksAdapter(sessions).search(
        NOOR_ROOT, "white nights", limit=1
    )

    assert [result.url for result in results] == [NOOR_BOOK_URL]


# ---------------------------------------------------------------- Noor's reader
#
# Noor's Download control is account-gated: measured on a live book, clicking it
# produced zero PDF anchors while the same book read fine. Its reader is not
# gated, and serves each page as an SVG wrapping a base64 PNG. The shapes below
# are the ones observed on www.noor-book.com/en/ebook-...-1613751028:
#
#   curr_reading_pages = 124
#   book_hash          = 8f820c79a5d825f38c798494f068bf69
#   page URL           /book/read_book_image/0/<book>/<n>/<session token>.svg

NOOR_BOOK_HASH = "8f820c79a5d825f38c798494f068bf69"
NOOR_TOKEN = "3051a7c42e030d11667f04d9f9c6fa89"


def _noor_reader_html(pages=124, loaded=5, title="White Nights and Other Stories"):
    """The book page with its reader open, as the browser leaves it.

    Only the first few pages are in the DOM -- the reader lazy-loads -- which is
    exactly why the count has to come from the script variable rather than from
    counting <img> tags.
    """
    imgs = "".join(
        f'<img src="/book/read_book_image/0/{NOOR_BOOK_HASH}/{n}/{NOOR_TOKEN}.svg">'
        for n in range(1, loaded + 1)
    )
    return f"""
    <html><head><meta property="og:image" content="/covers/white-nights.jpg">
    </head><body>
      <h1>{title}</h1>
      <script>var book_hash = '{NOOR_BOOK_HASH}';
              curr_reading_pages = {pages};</script>
      <div id="readModal">{imgs}</div>
    </body></html>
    """


async def test_noor_reads_the_book_instead_of_asking_for_the_download():
    sessions = FakeSessionManager(pages={NOOR_BOOK_URL: _noor_reader_html()})
    adapter = BooksAdapter(sessions)

    series = await adapter.fetch_series(NOOR_BOOK_URL)
    chapters = await adapter.fetch_chapters(series)

    assert sessions.clicked == [(NOOR_BOOK_URL, ("Read", "اقرأ", "قراءة"))]
    assert sessions.waited == ['img[src*="read_book_image"]']
    assert [c.title for c in chapters] == ["White Nights and Other Stories.pdf"]


async def test_the_whole_book_is_one_artifact_bound_from_its_pages():
    sessions = FakeSessionManager(pages={NOOR_BOOK_URL: _noor_reader_html()})
    adapter = BooksAdapter(sessions)

    chapters = await adapter.fetch_chapters(
        await adapter.fetch_series(NOOR_BOOK_URL))
    pages = await adapter.fetch_pages(chapters[0])

    assert len(chapters) == 1, "a book is not a list of chapters"
    assert adapter.packaging_for(chapters[0]) == "pdf"
    # Every page, not only the handful the reader had lazy-loaded.
    assert len(pages) == 124
    assert pages[0].url == (
        f"https://www.noor-book.com/book/read_book_image/0/{NOOR_BOOK_HASH}"
        f"/1/{NOOR_TOKEN}.svg"
    )
    assert pages[-1].url.endswith(f"/124/{NOOR_TOKEN}.svg")
    assert {p.referer for p in pages} == {NOOR_BOOK_URL}
    assert [p.index for p in pages] == list(range(1, 125))


async def test_every_other_book_site_still_downloads_its_file():
    """The reader is Noor's alone; nothing else changes shape."""
    html = '''<html><body><h1>Agnes Grey</h1>
        <a href="/free-ebooks/agnes-grey.pdf">PDF</a></body></html>'''
    sessions = FakeSessionManager(pages={BOOK_URL: html})
    adapter = BooksAdapter(sessions)

    chapters = await adapter.fetch_chapters(await adapter.fetch_series(BOOK_URL))

    assert adapter.packaging_for(chapters[0]) == "file"


async def test_a_reader_that_will_not_open_says_only_that():
    """The old message blamed licensing for what was usually a failed click.

    It decided a book was "not licensed for distribution" by finding the word
    "unavailable" in the page — but every Noor book page carries a sidebar of
    *other* titles each labelled Unavailable, so it fired on a perfectly
    readable book whose Read click an ad interstitial had swallowed. Seen live,
    on the book this feature was built against.
    """
    html = """
    <html><body><h1>Restricted Book</h1>
      <p>Download is not available</p>
      <aside><a href="/en/book/review/1">Unavailable</a>
             <a href="/en/book/review/2">Unavailable</a></aside>
    </body></html>
    """
    url = f"{NOOR_ROOT}/en/ebook-restricted-pdf-1"
    adapter = BooksAdapter(FakeSessionManager(pages={url: html}))

    with pytest.raises(AdapterError) as raised:
        await adapter.fetch_chapters(await adapter.fetch_series(url))

    assert "did not open" in str(raised.value)
    assert "licen" not in str(raised.value).lower(), \
        "claims to know why, and it does not"


async def test_the_read_click_is_retried_when_an_ad_swallows_it():
    """Observed live: the page came back with #google_vignette and no reader."""
    url = f"{NOOR_ROOT}/en/ebook-flaky-pdf-9"
    blocked = "<html><body><h1>Flaky Book</h1><p>ad interstitial</p></body></html>"

    sessions = FakeSessionManager(pages={url: blocked})
    adapter = BooksAdapter(sessions)

    # The reader opens only on the third attempt.
    attempts = {"n": 0}
    original = sessions.fetch_html_after_click

    async def flaky(target, **kwargs):
        attempts["n"] += 1
        await original(target, **kwargs)
        return blocked if attempts["n"] < 3 else _noor_reader_html(pages=7)

    sessions.fetch_html_after_click = flaky

    chapters = await adapter.fetch_chapters(await adapter.fetch_series(url))

    assert attempts["n"] == 3
    assert len(chapters) == 1


@pytest.mark.parametrize("pages", [0, 99999])
async def test_an_implausible_page_count_is_not_believed(pages):
    url = f"{NOOR_ROOT}/en/ebook-odd-pdf-3"
    adapter = BooksAdapter(
        FakeSessionManager(pages={url: _noor_reader_html(pages=pages)}))

    with pytest.raises(AdapterError):
        await adapter.fetch_chapters(await adapter.fetch_series(url))


# ------------------------------------------------------- unwrapping a page


def _svg_wrapping(payload: bytes, mime="png") -> bytes:
    import base64 as _b64
    encoded = _b64.b64encode(payload).decode()
    return (
        b'<svg width="686" height="967" xmlns="http://www.w3.org/2000/svg">'
        b'<image id="b" width="2144" height="3024" xlink:href="data:image/'
        + mime.encode() + b";base64," + encoded.encode()
        + b'"/></svg>'
    )


def test_a_reader_page_is_unwrapped_to_the_image_inside_it():
    from app.adapters.books import _noor_unwrap

    png = make_noise_png()
    assert _noor_unwrap(_svg_wrapping(png)) == png


def test_unwrapping_leaves_an_ordinary_image_alone():
    """It runs over every book site's pages, so it must be a no-op elsewhere."""
    from app.adapters.books import _noor_unwrap

    png = make_noise_png()
    assert _noor_unwrap(png) == png


def test_an_svg_that_wraps_nothing_is_passed_through_rather_than_emptied():
    """Returning b'' would fail validation with a confusing message."""
    from app.adapters.books import _noor_unwrap

    svg = b'<svg xmlns="http://www.w3.org/2000/svg"><text>no image</text></svg>'
    assert _noor_unwrap(svg) == svg


def test_base64_split_across_lines_still_decodes():
    from app.adapters.books import _noor_unwrap
    import base64 as _b64

    png = make_noise_png()
    encoded = _b64.b64encode(png).decode()
    chunked = "\n".join(encoded[i:i + 76] for i in range(0, len(encoded), 76))
    svg = (b'<svg xmlns="http://www.w3.org/2000/svg"><image xlink:href="data:image/png;base64,'
           + chunked.encode() + b'"/></svg>')
    assert _noor_unwrap(svg) == png


class _AnyBookPage(dict):
    """The captured pages, plus one stand-in for every book page requested.

    Kitaboka's search opens each candidate to confirm it links a real file.
    Registering all 37 by hand would be fixture-writing by another name, so
    the one page actually captured answers for each of them.
    """

    def __init__(self, known: dict, book_html: str):
        super().__init__(known)
        self._book = book_html

    def __contains__(self, url: object) -> bool:
        return super().__contains__(url) or self._is_book(url)

    def __getitem__(self, url):
        if super().__contains__(url):
            return super().__getitem__(url)
        if self._is_book(url):
            return self._book
        raise KeyError(url)

    @staticmethod
    def _is_book(url: object) -> bool:
        return isinstance(url, str) and "kitaboka.com/books/" in url


# Real markup, captured from kitaboka.com 2026-09-08. The previous fixtures
# here were written by hand and encoded the alias backwards -- see
# tests/fixtures/kitaboka/PROVENANCE.md.
KITABOKA_FIXTURES = Path(__file__).parent / "fixtures/kitaboka"
KITABOKA_ROOT = "https://kitaboka.com"
KITABOKA_QUERY = "\u0631\u0648\u0627\u064a\u0629"  # رواية
KITABOKA_SEARCH_URL = f"{KITABOKA_ROOT}/books?search=%D8%B1%D9%88%D8%A7%D9%8A%D8%A9"
KITABOKA_SENTINEL = "zzqvoneshelfnonexistent987654321"
KITABOKA_SENTINEL_URL = f"{KITABOKA_ROOT}/books?search={KITABOKA_SENTINEL}"
KITABOKA_BOOK_URL = f"{KITABOKA_ROOT}/books/hky-zhr"
NORKITAB_BOOK_URL = "https://norkitab.com/books/hky-zhr"
KITABOKA_MASKED_URL = "https://www.kitaboka.com/books/books/hky-zhr"


def _kitaboka(name: str) -> str:
    return (KITABOKA_FIXTURES / name).read_text(encoding="utf-8")


def test_kitaboka_and_its_mask_are_recognised():
    assert BooksAdapter.matches(KITABOKA_BOOK_URL)
    assert BooksAdapter.matches(NORKITAB_BOOK_URL)


def test_norkitab_is_the_mask_and_kitaboka_is_where_the_books_are():
    """The alias resolves towards the host that actually serves content.

    norkitab.com answers a 976-byte HTML 4 frameset whose only content is a
    frame pointing back at kitaboka.com/books. Resolving the other way -- what
    this adapter did until 2026-09-08 -- meant every search fetched an empty
    document and every query returned nothing.
    """
    assert _canonical_kitaboka_url(NORKITAB_BOOK_URL) == KITABOKA_BOOK_URL
    assert _canonical_kitaboka_url(KITABOKA_MASKED_URL) == KITABOKA_BOOK_URL
    # The mask doubles its own prefix on storage links too.
    assert _canonical_kitaboka_url(
        "https://norkitab.com/books/storage/book_files/x.pdf"
    ) == f"{KITABOKA_ROOT}/storage/book_files/x.pdf"
    # Any other host is left exactly as it was.
    assert _canonical_kitaboka_url("https://example.net/books/x") == (
        "https://example.net/books/x")


async def test_kitaboka_book_page_yields_its_pdf():
    sessions = FakeSessionManager(pages={KITABOKA_BOOK_URL: _kitaboka("book.html")})
    adapter = BooksAdapter(sessions)

    series = await adapter.fetch_series(KITABOKA_BOOK_URL)
    chapters = await adapter.fetch_chapters(series)
    pages = await adapter.fetch_pages(chapters[0])

    assert len(chapters) == 1
    assert chapters[0].title.endswith(".pdf")
    assert pages[0].url == (
        f"{KITABOKA_ROOT}/storage/book_files/"
        "01M00NDG35TDV35A6BTSMBYJH0.pdf")
    assert pages[0].referer == KITABOKA_BOOK_URL


async def test_kitaboka_search_returns_books_that_match_the_query():
    sessions = FakeSessionManager(pages={
        KITABOKA_SEARCH_URL: _kitaboka("search.html"),
    })

    # Every candidate page is fetched to confirm it links a real file; serve
    # the one captured book page for all of them.
    sessions.pages = _AnyBookPage(sessions.pages, _kitaboka("book.html"))
    results = await BooksAdapter(sessions).search(KITABOKA_ROOT, KITABOKA_QUERY)

    assert results, "the live listing holds 37 books whose titles carry رواية"
    assert all(KITABOKA_QUERY in result.title for result in results)
    assert all(result.site == "kitaboka.com" for result in results)
    assert all(result.url.startswith(f"{KITABOKA_ROOT}/books/")
               for result in results)


async def test_kitaboka_answers_an_unanswerable_query_with_its_catalogue():
    """The sixth site to do this, and the reason query_matches exists.

    Measured 2026-09-08: the sentinel below returns 27 real book links,
    overlapping the ones a genuine query returns. Nothing structural separates
    them from a hit -- only the text can, so the gate is what keeps this site
    out of every unrelated search.
    """
    raw = _kitaboka("negative.html")
    assert 'href="https://kitaboka.com/books/' in raw

    sessions = FakeSessionManager(pages={KITABOKA_SENTINEL_URL: raw})
    sessions.pages = _AnyBookPage(sessions.pages, _kitaboka("book.html"))

    results = await BooksAdapter(sessions).search(KITABOKA_ROOT, KITABOKA_SENTINEL)

    assert results == []


async def test_a_dead_reader_token_is_replaced_not_reused():
    """Measured on a 124-page book: pages 1-90 worked, 91 answered 114 bytes
    of text/html. The token is minted per reading session, so recovery means
    opening the reader again -- and that means dropping the cached page, or
    the refresh hands back the same dead token it was called to replace.
    """
    url = f"{NOOR_ROOT}/en/ebook-long-pdf-4"
    tokens = iter(["a" * 32, "b" * 32])
    opened = {"n": 0}

    sessions = FakeSessionManager(pages={url: _noor_reader_html()})

    async def reopen(target, **kwargs):
        opened["n"] += 1
        html = _noor_reader_html().replace(NOOR_TOKEN, next(tokens))
        return html

    sessions.fetch_html_after_click = reopen
    adapter = BooksAdapter(sessions)

    chapters = await adapter.fetch_chapters(await adapter.fetch_series(url))
    first = await adapter.fetch_pages(chapters[0])
    again = await adapter.refresh_pages(chapters[0])

    assert opened["n"] == 2, "the reader was not opened a second time"
    assert "a" * 32 in first[0].url
    assert "b" * 32 in again[0].url, "the refresh reused the dead token"
    assert len(again) == len(first)


async def test_refreshing_an_ordinary_book_page_still_works():
    """pages_expire is set for the whole adapter, so the file sites use it too."""
    html = '''<html><body><h1>Agnes Grey</h1>
        <a href="/free-ebooks/agnes-grey.pdf">PDF</a></body></html>'''
    adapter = BooksAdapter(FakeSessionManager(pages={BOOK_URL: html}))

    chapters = await adapter.fetch_chapters(await adapter.fetch_series(BOOK_URL))
    assert await adapter.refresh_pages(chapters[0]) \
        == await adapter.fetch_pages(chapters[0])


# --------------------------------------------------------- Hindawi / Safahat
#
# hindawi.org/books redirects to safahat.org. Every book page links an official
# EPUB and PDF on downloads.hindawi.org, served anonymously; verified
# 2026-09-07 against /books/25868315/ (a 2.45 MB EPUB, 44 entries).

SAFAHAT = "https://www.safahat.org/books/25868315/"

SAFAHAT_HTML = """
<html><head>
<meta property="og:title" content="الحرير | أليساندرو باريكو | مؤسسة هنداوي">
<meta property="og:image" content="https://downloads.hindawi.org/covers/304x406/25868315.jpg">
<meta property="og:description" content="وصف الكتاب.">
</head><body>
<h1>الكتب</h1>
<h2>الحرير</h2>
<a href="https://downloads.hindawi.org/books/25868315.epub">EPUB</a>
<a href="https://downloads.hindawi.org/books/25868315.pdf">PDF</a>
</body></html>
"""


@pytest.mark.asyncio
async def test_safahat_takes_the_title_from_og_not_the_h1():
    """Every Hindawi book page is headed "الكتب" ("Books").

    Taking the <h1> — which is right on every other book site here — named
    every book the same, so each download collided with the last.
    """
    from app.adapters.books import BooksAdapter

    adapter = BooksAdapter(FakeSessionManager(pages={SAFAHAT: SAFAHAT_HTML}))
    series = await adapter.fetch_series(SAFAHAT)
    assert series.title == "الحرير"

    chapters = await adapter.fetch_chapters(series)
    assert [c.title for c in chapters] == ["الحرير.epub", "الحرير.pdf"]
