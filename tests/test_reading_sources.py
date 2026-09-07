"""The reading sources added after the 2026-09-07 source survey.

Every fixture below reproduces the *structure* captured from the live page on
that date — the class names, id names, attribute names, URL shapes and nesting
are the real ones, because that is what the adapters key on. The prose and the
titles inside them are written for the test.

Each test names the trap it guards. All of them are traps that were actually
hit while building these adapters, or that the live markup makes easy to hit.
"""

from __future__ import annotations

import pytest

from app.adapters.ao3 import AO3Adapter
from app.adapters.base import AdapterError
from app.adapters.royalroad import RoyalRoadAdapter, _fiction_url
from app.adapters.scribblehub import ScribbleHubAdapter, _series_url, _with_toc
from app.adapters.sunovels import SunovelsAdapter, _with_page
from app.adapters.webtoons import WebtoonsAdapter, _list_url
from app.models import Chapter

from .conftest import FakeSessionManager


def sessions(pages):
    return FakeSessionManager(pages=pages)


# ------------------------------------------------------------------ Royal Road

RR_FICTION = "https://www.royalroad.com/fiction/117332/a-serial"

RR_FICTION_HTML = """
<html><head>
<meta property="og:image" content="https://www.royalroadcdn.com/public/covers-large/117332-a-serial.jpg">
<script type="application/ld+json">
{"@type":"Book","name":"A Serial","description":"A blurb.",
 "author":{"@type":"Person","name":"An Author"}}
</script>
</head><body>
<h1>A Serial</h1>
<script>
window.chapters = [
 {"id":3,"title":"Chapter 3: Third","url":"/fiction/117332/a-serial/chapter/3/third","order":2,"date":"2026-03-01T00:00:00Z","visible":true,"isUnlocked":true},
 {"id":1,"title":"Chapter 1: First","url":"/fiction/117332/a-serial/chapter/1/first","order":0,"date":"2026-01-01T00:00:00Z","visible":true,"isUnlocked":true},
 {"id":2,"title":"Chapter 2: Second","url":"/fiction/117332/a-serial/chapter/2/second","order":1,"date":"2026-02-01T00:00:00Z","visible":true,"isUnlocked":true},
 {"id":4,"title":"Chapter 4: Paid","url":"/fiction/117332/a-serial/chapter/4/paid","order":3,"date":"2026-04-01T00:00:00Z","visible":true,"isUnlocked":false},
 {"id":5,"title":"Chapter 5: Hidden","url":"/fiction/117332/a-serial/chapter/5/hidden","order":4,"date":"2026-05-01T00:00:00Z","visible":false,"isUnlocked":true}
];
</script>
</body></html>
"""

RR_CHAPTER_HTML = """
<html><body>
<h1>Chapter 1: First</h1>
<div class="chapter-inner chapter-content">
  <p>Opening line.</p>
  <p>Second line.<br>Third line.</p>
  <div class="comment-section"><p>a reader comment</p></div>
</div>
</body></html>
"""


@pytest.fixture
def rr():
    return RoyalRoadAdapter(sessions({
        RR_FICTION: RR_FICTION_HTML,
        "https://www.royalroad.com/fiction/117332/a-serial/chapter/1/first": RR_CHAPTER_HTML,
    }))


@pytest.mark.asyncio
async def test_royalroad_reads_metadata_from_the_page_and_its_ld_json(rr):
    series = await rr.fetch_series(RR_FICTION)
    assert series.title == "A Serial"
    assert series.author == "An Author"
    assert series.description == "A blurb."
    assert series.cover_url and series.site_id == "117332"


@pytest.mark.asyncio
async def test_royalroad_orders_by_the_sites_own_order_field(rr):
    """The trap: `window.chapters` is not emitted in reading order."""
    series = await rr.fetch_series(RR_FICTION)
    chapters = await rr.fetch_chapters(series)
    assert [c.title for c in chapters] == [
        "Chapter 1: First", "Chapter 2: Second", "Chapter 3: Third",
    ]
    assert [c.index for c in chapters] == [1, 2, 3]


@pytest.mark.asyncio
async def test_royalroad_drops_paid_and_hidden_chapters(rr):
    """Listing them would queue work that can only fail, and blame us for it."""
    series = await rr.fetch_series(RR_FICTION)
    titles = [c.title for c in await rr.fetch_chapters(series)]
    assert "Chapter 4: Paid" not in titles
    assert "Chapter 5: Hidden" not in titles


@pytest.mark.asyncio
async def test_royalroad_numbers_come_from_the_label(rr):
    series = await rr.fetch_series(RR_FICTION)
    assert [c.number for c in await rr.fetch_chapters(series)] == ["1", "2", "3"]


@pytest.mark.asyncio
async def test_royalroad_extracts_prose_and_ignores_comments(rr):
    text = await rr.fetch_text(Chapter(
        url="https://www.royalroad.com/fiction/117332/a-serial/chapter/1/first",
        title="Chapter 1", index=1,
    ))
    assert [b.text for b in text.blocks] == [
        "Opening line.", "Second line.", "Third line.",
    ]
    assert text.title == "Chapter 1: First"


def test_royalroad_normalises_a_chapter_url_to_its_fiction():
    """Pasting the chapter you are reading is the natural thing to do."""
    assert _fiction_url(
        "https://www.royalroad.com/fiction/117332/a-serial/chapter/3/third"
    ) == RR_FICTION


@pytest.mark.asyncio
async def test_royalroad_says_so_when_a_page_carries_no_chapter_list():
    adapter = RoyalRoadAdapter(sessions({RR_FICTION: "<html><h1>A Serial</h1></html>"}))
    series = await adapter.fetch_series(RR_FICTION)
    with pytest.raises(AdapterError, match="window.chapters"):
        await adapter.fetch_chapters(series)


@pytest.mark.asyncio
async def test_royalroad_rejects_being_asked_for_page_images(rr):
    with pytest.raises(AdapterError, match="text, not images"):
        await rr.fetch_pages(Chapter(url="x", title="x", index=1))


# ------------------------------------------------------------------ Scribble Hub

SH_SERIES = "https://www.scribblehub.com/series/1730819/a-serial/"

SH_SERIES_HTML = """
<html><head><meta property="og:image" content="https://cdn.scribblehub.com/images/86/a-serial.jpg"></head>
<body>
<div class="fic_title">A Serial</div>
<span class="auth_name_fic">An Author</span>
<div class="wi_fic_desc">A blurb.</div>
<ol>
 <li title="Bookmark Chapter" class="toc_w" order="3">
   <a class="toc_a" href="https://www.scribblehub.com/read/1730819-a-serial/chapter/300/">Chapter 2 &#8211; Second</a>
   <span class="fic_date_pub" title="Feb 2, 2026 01:00 PM">Feb 2, 2026</span></li>
 <li title="Bookmark Chapter" class="toc_w" order="2">
   <a class="toc_a" href="https://www.scribblehub.com/read/1730819-a-serial/chapter/200/">Chapter 1 &#8211; First</a>
   <span class="fic_date_pub" title="Jan 1, 2026 01:00 PM">Jan 1, 2026</span></li>
</ol>
<ul id="pagination-mesh-toc">
  <li class="active"><a class="current" href="./?toc=1#content1">1</a></li>
  <li><a href="?toc=2#content1" class="page-link">2</a></li>
</ul>
</body></html>
"""

SH_TOC2_HTML = """
<html><body><ol>
 <li class="toc_w" order="1">
   <a class="toc_a" href="https://www.scribblehub.com/read/1730819-a-serial/chapter/100/">Prologue</a>
   <span class="fic_date_pub" title="Dec 1, 2025 01:00 PM">Dec 1, 2025</span></li>
</ol></body></html>
"""

SH_CHAPTER_HTML = """
<html><body>
<div class="chapter-title">Chapter 1 &#8211; First</div>
<div id="chp_raw"><p>Opening line.</p><p>Closing line.</p></div>
</body></html>
"""


@pytest.fixture
def sh():
    return ScribbleHubAdapter(sessions({
        SH_SERIES: SH_SERIES_HTML,
        _with_toc(SH_SERIES, 2): SH_TOC2_HTML,
        "https://www.scribblehub.com/read/1730819-a-serial/chapter/200/": SH_CHAPTER_HTML,
    }))


@pytest.mark.asyncio
async def test_scribblehub_walks_every_toc_page(sh):
    series = await sh.fetch_series(SH_SERIES)
    chapters = await sh.fetch_chapters(series)
    assert [c.title for c in chapters] == [
        "Prologue", "Chapter 1 – First", "Chapter 2 – Second",
    ]


@pytest.mark.asyncio
async def test_scribblehub_sorts_on_order_but_numbers_from_the_label(sh):
    """The two disagree — measured, `order` 289 is the row labelled 288.

    Sorting on the label would scramble a serial whose labels restart per arc;
    numbering from `order` would put the wrong number on every filename.
    """
    series = await sh.fetch_series(SH_SERIES)
    chapters = await sh.fetch_chapters(series)
    assert [c.number for c in chapters] == ["1", "1", "2"]
    assert [c.index for c in chapters] == [1, 2, 3]


@pytest.mark.asyncio
async def test_scribblehub_keeps_a_partial_list_when_a_toc_page_fails():
    """A rate-limited page must not lose the chapters already read."""
    adapter = ScribbleHubAdapter(sessions({SH_SERIES: SH_SERIES_HTML}))
    series = await adapter.fetch_series(SH_SERIES)
    chapters = await adapter.fetch_chapters(series)
    assert [c.title for c in chapters] == ["Chapter 1 – First", "Chapter 2 – Second"]


@pytest.mark.asyncio
async def test_scribblehub_extracts_prose(sh):
    text = await sh.fetch_text(Chapter(
        url="https://www.scribblehub.com/read/1730819-a-serial/chapter/200/",
        title="Chapter 1", index=1,
    ))
    assert [b.text for b in text.blocks] == ["Opening line.", "Closing line."]


def test_scribblehub_normalises_a_reader_url_to_its_series():
    assert _series_url(
        "https://www.scribblehub.com/read/1730819-a-serial/chapter/300/"
    ) == SH_SERIES


# --------------------------------------------------------------------- Sunovels

SN_NOVEL = "https://sunovels.com/novel/a-serial"
SN_CHAPTERS = f"{SN_NOVEL}?activeTab=chapters"

SN_PAGE0 = """
<html><head><meta property="og:image" content="https://sunovels.com/uploads/cover.jpg"></head>
<body>
<h1>شمس الروايات</h1><h1>A Serial</h1>
<a href="/novel/a-serial/1">أقرء الفصل الأول</a>
<a href="/novel/a-serial/120">أقرء الفصل الأخير</a>
<a title="1 الفصل" href="/novel/a-serial/1"><li class="list-item">
  <strong class="chapter-title">1 الفصل</strong>
  <div class="meta"><time class="chapter-update" datetime="2021-09-08T19:35:47.024Z">4 سنة</time></div></li></a>
<a title="2 الفصل" href="/novel/a-serial/2"><li class="list-item">
  <strong class="chapter-title">2 الفصل</strong></li></a>
</body></html>
"""

SN_PAGE1 = """
<html><body>
<a title="51 الفصل" href="/novel/a-serial/51"><li class="list-item">
  <strong class="chapter-title">51 الفصل</strong></li></a>
</body></html>
"""

SN_CHAPTER = """
<html><body><h2>1 الفصل</h2>
<div class="chapter-content"><p>سطر أول.</p><p>سطر ثانٍ.</p></div>
</body></html>
"""


@pytest.fixture
def sn():
    return SunovelsAdapter(sessions({
        SN_NOVEL: SN_PAGE0,
        SN_CHAPTERS: SN_PAGE0,
        _with_page(SN_CHAPTERS, 1): SN_PAGE1,
        f"{SN_NOVEL}/1": SN_CHAPTER,
    }))


@pytest.mark.asyncio
async def test_sunovels_skips_the_site_name_when_reading_the_title(sn):
    """Every page opens with the site's own name in an <h1>."""
    series = await sn.fetch_series(SN_NOVEL)
    assert series.title == "A Serial"
    assert series.cover_url


@pytest.mark.asyncio
async def test_sunovels_pagination_is_zero_based(sn):
    """The trap. `page=1` is the *second* fifty, not the first.

    Reading it as one-based silently skips chapters 51-100 — a hole that
    survives a preview and surfaces months later as a missing chapter.
    """
    series = await sn.fetch_series(SN_NOVEL)
    chapters = await sn.fetch_chapters(series)
    numbers = [int(c.number) for c in chapters]
    assert 51 in numbers, "the second listing page was never requested"
    assert numbers == sorted(numbers)
    assert numbers[:2] == [1, 2]


@pytest.mark.asyncio
async def test_sunovels_keeps_the_last_chapter_shortcut_as_a_real_chapter(sn):
    """It carries no row markup, so a label has to be synthesised for it."""
    series = await sn.fetch_series(SN_NOVEL)
    chapters = await sn.fetch_chapters(series)
    assert chapters[-1].number == "120"
    assert chapters[-1].title


@pytest.mark.asyncio
async def test_sunovels_extracts_arabic_prose_in_order(sn):
    text = await sn.fetch_text(Chapter(url=f"{SN_NOVEL}/1", title="1", index=1))
    assert [b.text for b in text.blocks] == ["سطر أول.", "سطر ثانٍ."]
    assert text.language == "ar"


# -------------------------------------------------------------------------- AO3

AO3_WORK = "https://archiveofourown.org/works/19368172"

AO3_HTML = """
<html><body>
<h2 class="title heading">A Work</h2>
<h3 class="byline heading"><a rel="author" href="/users/someone">Someone</a></h3>
<div class="summary"><blockquote><p>A blurb.</p></blockquote></div>
<li class="download"><ul>
  <li><a href="/downloads/19368172/A_Work.azw3?updated_at=1">AZW3</a></li>
  <li><a href="/downloads/19368172/A_Work.epub?updated_at=1">EPUB</a></li>
  <li><a href="/downloads/19368172/A_Work.mobi?updated_at=1">MOBI</a></li>
  <li><a href="/downloads/19368172/A_Work.pdf?updated_at=1">PDF</a></li>
  <li><a href="/downloads/19368172/A_Work.html?updated_at=1">HTML</a></li>
</ul></li>
</body></html>
"""


@pytest.fixture
def ao3():
    return AO3Adapter(sessions({AO3_WORK: AO3_HTML}))


@pytest.mark.asyncio
async def test_ao3_offers_each_storable_format_and_skips_html(ao3):
    series = await ao3.fetch_series(AO3_WORK)
    chapters = await ao3.fetch_chapters(series)
    assert [c.title for c in chapters] == [
        "A Work.epub", "A Work.azw3", "A Work.mobi", "A Work.pdf",
    ]


@pytest.mark.asyncio
async def test_ao3_chapter_identity_excludes_the_updated_at_stamp(ao3):
    """The stamp changes whenever the author edits.

    Keying on the file URL would make every edit look like a new chapter and
    re-download the whole work.
    """
    series = await ao3.fetch_series(AO3_WORK)
    chapters = await ao3.fetch_chapters(series)
    assert all("updated_at" not in c.url for c in chapters)
    assert chapters[0].url == f"{AO3_WORK}#epub"


@pytest.mark.asyncio
async def test_ao3_resolves_a_format_to_its_current_download_url(ao3):
    series = await ao3.fetch_series(AO3_WORK)
    chapters = await ao3.fetch_chapters(series)
    pages = await ao3.fetch_pages(chapters[0])
    assert pages[0].url.endswith("A_Work.epub?updated_at=1")
    assert pages[0].referer == AO3_WORK


@pytest.mark.asyncio
async def test_ao3_reports_the_two_access_screens_as_what_they_are():
    """Both render an ordinary page with no download links on it."""
    restricted = AO3Adapter(sessions({
        AO3_WORK: "<html>This work is only available to registered users</html>"
    }))
    with pytest.raises(AdapterError, match="restricted to logged-in"):
        await restricted.fetch_series(AO3_WORK)

    adult = AO3Adapter(sessions({
        AO3_WORK: "<html>This work could have adult content</html>"
    }))
    with pytest.raises(AdapterError, match="adult-content confirmation"):
        await adult.fetch_series(AO3_WORK)


# --------------------------------------------------------------------- WEBTOON

WT_LIST = "https://www.webtoons.com/en/action/a-toon/list?title_no=1571"

WT_LIST_HTML = """
<html><head><meta property="og:image" content="https://swebtoon-phinf.pstatic.net/1571.jpg"></head>
<body>
<h1 class="subj">A Toon</h1>
<div class="author_area">An Artist author info</div>
<div class="detail_lst"><ul id="_listUl">
 <li class="_episodeItem detail_list_item" id="episode_3" data-episode-no="3">
   <a href="https://www.webtoons.com/en/action/a-toon/episode-3/viewer?title_no=1571&amp;episode_no=3">
   <span class="subj">Episode 3</span><span class="date">Mar 1, 2026</span></a></li>
 <li class="_episodeItem detail_list_item" id="episode_2" data-episode-no="2">
   <a href="https://www.webtoons.com/en/action/a-toon/episode-2/viewer?title_no=1571&amp;episode_no=2">
   <span class="subj">Episode 2</span><span class="date">Feb 1, 2026</span></a></li>
 <li class="_episodeItem detail_list_item" id="episode_4" data-episode-no="4">
   <a href="https://www.webtoons.com/en/action/a-toon/episode-4/viewer?title_no=1571&amp;episode_no=4">
   <span class="subj">Episode 4</span><span class="ico_lock"></span></a></li>
</ul></div>
<div class="author_area">Somebody Else</div>
</body></html>
"""

WT_VIEWER_HTML = """
<html><body><div id="_imageList">
 <img src="https://webtoons-static.pstatic.net/image/bg_transparency.png"
      data-url="https://webtoon-phinf.pstatic.net/a/p1.jpg?type=q90" class="_images">
 <img src="https://webtoons-static.pstatic.net/image/bg_transparency.png"
      data-url="https://webtoon-phinf.pstatic.net/a/p2.jpg?type=q90" class="_images">
</div></body></html>
"""

WT_VIEWER_URL = "https://www.webtoons.com/en/action/a-toon/episode-2/viewer?title_no=1571&episode_no=2"


@pytest.fixture
def wt():
    return WebtoonsAdapter(sessions({
        WT_LIST: WT_LIST_HTML,
        WT_VIEWER_URL: WT_VIEWER_HTML,
    }))


@pytest.mark.asyncio
async def test_webtoons_reads_only_the_series_own_author(wt):
    """The list page also carries a "you may also like" strip with authors."""
    series = await wt.fetch_series(WT_LIST)
    assert series.title == "A Toon"
    assert series.author == "An Artist"


@pytest.mark.asyncio
async def test_webtoons_orders_by_data_episode_no_not_by_listing_order(wt):
    """The site lists newest-first and its labels are free text."""
    series = await wt.fetch_series(WT_LIST)
    chapters = await wt.fetch_chapters(series)
    assert [c.number for c in chapters] == ["2", "3"]
    assert [c.index for c in chapters] == [1, 2]


@pytest.mark.asyncio
async def test_webtoons_drops_locked_episodes(wt):
    series = await wt.fetch_series(WT_LIST)
    assert "4" not in [c.number for c in await wt.fetch_chapters(series)]


@pytest.mark.asyncio
async def test_webtoons_takes_data_url_and_never_the_placeholder(wt):
    """The trap, and the worst one here.

    Every viewer image carries a shared transparent spacer in `src`. Reading it
    produces a chapter of identical 1x1 images that validates as real and packs
    into a real CBZ — nothing downstream can tell it is wrong.
    """
    pages = await wt.fetch_pages(Chapter(url=WT_VIEWER_URL, title="Ep 2", index=1))
    assert [p.url for p in pages] == [
        "https://webtoon-phinf.pstatic.net/a/p1.jpg?type=q90",
        "https://webtoon-phinf.pstatic.net/a/p2.jpg?type=q90",
    ]
    assert all("bg_transparency" not in p.url for p in pages)
    assert [p.index for p in pages] == [1, 2]


@pytest.mark.asyncio
async def test_webtoons_sends_the_viewer_as_referer(wt):
    """Measured: the image host answers 403 without it."""
    pages = await wt.fetch_pages(Chapter(url=WT_VIEWER_URL, title="Ep 2", index=1))
    assert all(p.referer == WT_VIEWER_URL for p in pages)


@pytest.mark.asyncio
async def test_webtoons_reports_a_locked_viewer_as_locked():
    adapter = WebtoonsAdapter(sessions({
        WT_VIEWER_URL: "<html><body>Unlock with Fast Pass</body></html>"
    }))
    with pytest.raises(AdapterError, match="not free to read"):
        await adapter.fetch_pages(Chapter(url=WT_VIEWER_URL, title="x", index=1))


def test_webtoons_normalises_a_viewer_url_to_its_episode_list():
    assert _list_url(WT_VIEWER_URL) == WT_LIST
