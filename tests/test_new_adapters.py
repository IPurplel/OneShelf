"""Blogger and comix.to adapters.

The markup below mirrors what was captured from the rendered pages — the class
names, URL shapes and label text are the real ones. Both sites inject the parts
that matter with JavaScript, so these shapes only exist after render.
"""

from __future__ import annotations

import pytest

from app.adapters.base import AdapterError
from app.adapters.blogger import BloggerAdapter
from app.adapters.comix import ComixAdapter, _series_url
from app.models import Chapter

from .conftest import FakeSessionManager

BLOG = "https://arcomixverse.blogspot.com"
SERIES = f"{BLOG}/2024/10/absolute-batman.html"

# div.chapter-table / div.chapter-item, and the issue number only in the label.
BLOG_SERIES_HTML = f"""
<html><head><meta property="og:title" content="ABSOLUTE BATMAN">
<meta property="og:image" content="https://blogger.googleusercontent.com/img/a/AB/s1600/cover.jpg">
</head><body>
<h1 class="post-title">ABSOLUTE BATMAN</h1>
<div class="chapter-table">
  <div class="chapter-item"><a href="{BLOG}/2026/05/19_02077140790.html">العدد#19</a></div>
  <div class="chapter-item"><a href="{BLOG}/2026/04/18.html">العدد#18</a></div>
  <div class="chapter-item"><a href="{BLOG}/2025/12/16_16.html">العدد#16</a></div>
  <div class="chapter-item"><a href="{SERIES}">ABSOLUTE BATMAN</a></div>
  <div class="chapter-item"><a href="{BLOG}/p/marvel-series.html">MARVEL</a></div>
  <div class="chapter-item"><a href="https://elsewhere.example/2024/01/x.html">Other</a></div>
</div></body></html>
"""

BLOG_ISSUE_HTML = """
<html><body><div class="post-body">
  <img src="https://blogger.googleusercontent.com/img/a/AA/s1600/p1.jpg">
  <img src="https://blogger.googleusercontent.com/img/a/AB/s1600/p2.jpg">
  <img src="https://blogger.googleusercontent.com/img/b/icon/s35/avatar.png">
  <img src="data:image/gif;base64,R0lGOD">
</div></body></html>
"""


@pytest.fixture
def blog_sessions():
    return FakeSessionManager(
        pages={
            SERIES: BLOG_SERIES_HTML,
            f"{BLOG}/2026/04/18.html": BLOG_ISSUE_HTML,
        },
        posts={},
    )


# ------------------------------------------------------------------ blogger


def test_blogger_matches_blogspot_by_host():
    assert BloggerAdapter.matches(SERIES)
    assert not BloggerAdapter.matches("https://example.net/manga/x/")


def test_blogger_matches_a_custom_domain_by_dom():
    html = '<html><head><meta content="blogger" name="generator"></head></html>'
    assert BloggerAdapter.matches("https://comics.example.com/x.html", html)


def test_blogger_reads_western_comics_left_to_right():
    # The global default is right-to-left, which is wrong for Marvel/DC.
    assert BloggerAdapter.right_to_left is False


async def test_blogger_waits_for_the_injected_issue_list(blog_sessions):
    adapter = BloggerAdapter(blog_sessions)
    series = await adapter.fetch_series(SERIES)
    await adapter.fetch_chapters(series)
    # Without the wait the served HTML has no issue links at all.
    assert any(w and "chapter-item" in w for w in blog_sessions.waited)


async def test_blogger_numbers_issues_from_the_label(blog_sessions):
    """The number is in the link text, never the URL.

    Slugs like 19_02077140790 and 16_16 would parse as nonsense — the same
    failure that once misordered a whole series.
    """
    adapter = BloggerAdapter(blog_sessions)
    series = await adapter.fetch_series(SERIES)
    chapters = await adapter.fetch_chapters(series)

    assert [c.number for c in chapters] == ["16", "18", "19"]
    assert chapters[-1].url.endswith("19_02077140790.html")


async def test_blogger_drops_non_issue_links(blog_sessions):
    adapter = BloggerAdapter(blog_sessions)
    series = await adapter.fetch_series(SERIES)
    chapters = await adapter.fetch_chapters(series)
    urls = {c.url for c in chapters}

    assert SERIES not in urls                      # the series itself
    assert not any("/p/" in u for u in urls)       # a static index page
    assert all("arcomixverse" in u for u in urls)  # another blog entirely


async def test_blogger_extracts_only_real_page_images(blog_sessions):
    adapter = BloggerAdapter(blog_sessions)
    pages = await adapter.fetch_pages(
        Chapter(url=f"{BLOG}/2026/04/18.html", title="18", number="18")
    )

    assert [p.index for p in pages] == [1, 2]
    assert all("googleusercontent" in p.url for p in pages)
    assert not any("avatar" in p.url or p.url.startswith("data:") for p in pages)


async def test_blogger_explains_an_empty_issue_list():
    sessions = FakeSessionManager(
        pages={SERIES: "<html><body><h1>ABSOLUTE BATMAN</h1></body></html>"}, posts={})
    adapter = BloggerAdapter(sessions)
    series = await adapter.fetch_series(SERIES)

    with pytest.raises(AdapterError, match="No issue list"):
        await adapter.fetch_chapters(series)


# -------------------------------------------------------------------- comix

COMIX = "https://comix.to"
TITLE = f"{COMIX}/title/qqwrm-full-time-awakening"

COMIX_TITLE_HTML = f"""
<html><head><meta property="og:title" content="Full-Time Awakening | Comix">
<meta property="og:image" content="{COMIX}/images/cover.webp"></head><body>
<a href="/title/qqwrm-full-time-awakening/11088588-chapter-144">Chapter 144</a>
<a href="/title/qqwrm-full-time-awakening/11088611-chapter-145">Chapter 145</a>
<a href="/title/qqwrm-full-time-awakening/11173862-chapter-154">Chapter 154</a>
<a href="/title/939g0-killing-stalking">Another title</a>
</body></html>
"""

COMIX_READER_HTML = """
<html><body>
<img src="https://j24n.wowpic1.store/i5/bEqPbYfoPT0GmxHlQi6foD5AjS5FIHyEz7">
<img src="https://j24n.wowpic1.store/i5/bEqPbYfoPT0GmxHlQi6foD5AgS5FIHyEz7">
<img src="https://comix.to/images/avatars/364/364056.webp">
</body></html>
"""


@pytest.fixture
def comix_sessions():
    return FakeSessionManager(
        pages={
            TITLE: COMIX_TITLE_HTML,
            f"{TITLE}?page=2": COMIX_TITLE_HTML,
            f"{TITLE}/11173862-chapter-154": COMIX_READER_HTML,
        },
        posts={},
    )


def test_comix_matches_its_host():
    assert ComixAdapter.matches(TITLE)
    assert not ComixAdapter.matches("https://example.net/title/x")


@pytest.mark.parametrize(
    "given",
    [
        f"{TITLE}/11173862-chapter-154",   # a chapter someone is reading
        f"{TITLE}/",
        f"{TITLE}?x=1",
        TITLE,
    ],
)
def test_comix_trims_any_url_to_the_series(given):
    assert _series_url(given) == TITLE


def test_comix_rejects_an_unrelated_url():
    with pytest.raises(AdapterError, match="not a comix.to series"):
        _series_url("https://comix.to/browse")


async def test_comix_lists_and_orders_chapters(comix_sessions):
    adapter = ComixAdapter(comix_sessions)
    series = await adapter.fetch_series(f"{TITLE}/11173862-chapter-154")
    chapters = await adapter.fetch_chapters(series)

    assert series.url == TITLE
    assert series.site_id == "qqwrm"
    assert [c.number for c in chapters] == ["144", "145", "154"]
    # A link to a different title must not become a chapter of this one.
    assert all("qqwrm" in c.url for c in chapters)


async def test_comix_strips_site_branding_from_the_title(comix_sessions):
    adapter = ComixAdapter(comix_sessions)
    series = await adapter.fetch_series(TITLE)
    assert series.title == "Full-Time Awakening"


async def test_comix_takes_pages_from_the_rendered_reader(comix_sessions):
    adapter = ComixAdapter(comix_sessions)
    pages = await adapter.fetch_pages(
        Chapter(url=f"{TITLE}/11173862-chapter-154", title="Chapter 154", number="154")
    )

    assert [p.index for p in pages] == [1, 2]
    assert all(".store/" in p.url for p in pages)
    # Site furniture must never be mistaken for a comic page.
    assert not any("avatars" in p.url for p in pages)
    assert all(p.referer.endswith("chapter-154") for p in pages)


async def test_comix_waits_for_the_reader_images(comix_sessions):
    adapter = ComixAdapter(comix_sessions)
    await adapter.fetch_pages(
        Chapter(url=f"{TITLE}/11173862-chapter-154", title="c", number="154")
    )
    assert any(w and "/i5/" in w for w in comix_sessions.waited)


async def test_blogger_strips_the_blog_name_from_the_title():
    """The title becomes a folder name, so branding must not leak into paths."""
    html = (
        '<html><head><meta property="og:site_name" content="Comicverse">'
        '<meta property="og:title" content="ABSOLUTE BATMAN  - Comicverse">'
        '</head><body><div class="chapter-table"><div class="chapter-item">'
        f'<a href="{BLOG}/2026/04/18.html">18</a></div></div></body></html>'
    )
    adapter = BloggerAdapter(FakeSessionManager(pages={SERIES: html}, posts={}))
    series = await adapter.fetch_series(SERIES)
    assert series.title == "ABSOLUTE BATMAN"


async def test_comix_takes_the_cover_from_the_hydration_payload():
    """The page has no og:image; the poster is in the query cache."""
    html = (
        '<html><head><meta property="og:title" content="X | Comix"></head><body>'
        '<a href="/title/qqwrm-full-time-awakening/1-chapter-1">1</a>'
        '<script type="application/json">{"queries":{"a":{"hid":"qqwrm",'
        '"poster":"https://comix.to/images/covers/abc.webp"}}}</script>'
        "</body></html>"
    )
    adapter = ComixAdapter(FakeSessionManager(pages={TITLE: html}, posts={}))
    series = await adapter.fetch_series(TITLE)
    assert series.cover_url == "https://comix.to/images/covers/abc.webp"
