"""Prose extraction and EPUB packaging.

The markup here mirrors the real structure captured from each reader on
2026-09-07 — the class names, id names, attribute names and nesting are the
ones the live pages use. The *prose* inside them is written for the test:
these are copyrighted works, and the parser depends on the shape, not on the
words.
"""

from __future__ import annotations

import zipfile

import pytest
from selectolax.parser import HTMLParser

from app.adapters.prose import blocks_from, looks_like_prose, normalise, strip_noise
from app.models import TextBlock, TextChapter
from app.packager import (
    PackagingError,
    is_rtl_language,
    verify_epub,
    write_epub,
)


def parse(html: str):
    return HTMLParser(html)


# ------------------------------------------------------------------- blocks


def test_blocks_come_back_in_document_order_not_selector_order():
    """The trap: querying headings and paragraphs separately reorders them.

    Collecting `h2`s and then `p`s and concatenating moves every heading to the
    top, which reads as a table of contents followed by an unbroken wall of
    text — and looks entirely plausible in the output.
    """
    tree = parse(
        "<div><p>one</p><h2>First</h2><p>two</p><h2>Second</h2><p>three</p></div>"
    )
    blocks = blocks_from(tree.css_first("div"))
    assert [(b.kind, b.text) for b in blocks] == [
        ("p", "one"),
        ("h2", "First"),
        ("p", "two"),
        ("h2", "Second"),
        ("p", "three"),
    ]


def test_line_breaks_inside_a_paragraph_become_separate_blocks():
    """`<br>` carries verse and system messages; dropping it joins two lines."""
    tree = parse("<div><p>Line one<br>Line two<br/>Line three</p></div>")
    blocks = blocks_from(tree.css_first("div"))
    assert [b.text for b in blocks] == ["Line one", "Line two", "Line three"]
    assert {b.kind for b in blocks} == {"p"}


def test_a_paragraph_is_read_once_even_when_nested():
    tree = parse("<div><blockquote><p>quoted</p></blockquote></div>")
    blocks = blocks_from(tree.css_first("div"))
    assert [b.text for b in blocks] == ["quoted"]


def test_comment_threads_and_furniture_are_not_chapter_text():
    """Every one of these is made of paragraphs and none of them is the story."""
    tree = parse(
        """<div id="reader">
             <p>Real chapter text.</p>
             <div class="comment-list"><p>somebody's comment</p></div>
             <div id="related-stories"><p>you may also like</p></div>
             <script>var ads = 1;</script>
             <div class="share-buttons"><p>share this</p></div>
           </div>"""
    )
    container = tree.css_first("#reader")
    strip_noise(container)
    assert [b.text for b in blocks_from(container)] == ["Real chapter text."]


def test_arabic_text_and_its_joiners_survive_extraction():
    """`\\s` would eat the joiners and gaps Arabic text depends on."""
    joined = "\u0627\u0644\u0641\u0635\u0644\u200c\u0627\u0644\u0623\u0648\u0644"
    tree = parse(f"<div><p>   {joined}  \u00a0 x   </p></div>")
    blocks = blocks_from(tree.css_first("div"))
    text = blocks[0].text
    assert "\u200c" in text, "zero-width joiner was stripped"
    assert "\u00a0" in text, "non-breaking space was stripped"
    assert "  " not in text, "ordinary whitespace runs should collapse"


def test_ordinary_whitespace_runs_collapse():
    assert normalise("a   b\n\n c\t d") == "a b c d"


def test_a_reader_that_uses_bare_text_and_breaks_still_yields_blocks():
    """Some readers put the chapter in text nodes with `<br>` between them."""
    tree = parse("<div>first line<br>second line</div>")
    assert [b.text for b in blocks_from(tree.css_first("div"))] == [
        "first line",
        "second line",
    ]


def test_an_ornament_heading_is_demoted_to_a_paragraph():
    tree = parse("<div><h3>* * *</h3><p>after the break</p></div>")
    kinds = [b.kind for b in blocks_from(tree.css_first("div"))]
    assert kinds == ["p", "p"]


# --------------------------------------------------------------------- epub


def chapter(**kw) -> TextChapter:
    kw.setdefault("title", "Chapter 1")
    kw.setdefault("blocks", [TextBlock("h2", "Chapter 1"), TextBlock("p", "Text.")])
    return TextChapter(**kw)


def test_an_epub_is_a_valid_container_with_a_stored_mimetype(tmp_path):
    path = write_epub(tmp_path / "c.epub", chapter(), series_title="A Novel")
    with zipfile.ZipFile(path) as archive:
        assert archive.namelist()[0] == "mimetype"
        assert archive.getinfo("mimetype").compress_type == zipfile.ZIP_STORED
        assert archive.read("mimetype") == b"application/epub+zip"
        assert "META-INF/container.xml" in archive.namelist()
    assert verify_epub(path)


def test_arabic_chapters_are_written_right_to_left(tmp_path):
    path = write_epub(
        tmp_path / "ar.epub",
        chapter(blocks=[TextBlock("p", "نص عربي")],
                language="ar"),
        series_title="رواية",
    )
    with zipfile.ZipFile(path) as archive:
        doc = archive.read("OEBPS/chapter.xhtml").decode("utf-8")
        opf = archive.read("OEBPS/content.opf").decode("utf-8")
    assert 'dir="rtl"' in doc
    assert 'page-progression-direction="rtl"' in opf
    assert "نص عربي" in doc


def test_english_chapters_stay_left_to_right(tmp_path):
    path = write_epub(tmp_path / "en.epub", chapter(language="en"), series_title="N")
    with zipfile.ZipFile(path) as archive:
        assert 'dir="ltr"' in archive.read("OEBPS/chapter.xhtml").decode("utf-8")


def test_markup_in_the_text_is_escaped_not_rendered(tmp_path):
    path = write_epub(
        tmp_path / "e.epub",
        chapter(blocks=[TextBlock("p", '<script>x</script> & "quoted"')]),
        series_title="N",
    )
    with zipfile.ZipFile(path) as archive:
        doc = archive.read("OEBPS/chapter.xhtml").decode("utf-8")
    assert "<script>x</script>" not in doc
    assert "&lt;script&gt;" in doc and "&amp;" in doc


def test_every_document_in_the_epub_is_well_formed_xml(tmp_path):
    from xml.etree import ElementTree as ET

    path = write_epub(
        tmp_path / "x.epub",
        chapter(blocks=[TextBlock("h2", "A & B"), TextBlock("p", "x < y")]),
        series_title="N & Co",
        author="Someone <tagged>",
    )
    with zipfile.ZipFile(path) as archive:
        for name in ("OEBPS/content.opf", "OEBPS/nav.xhtml", "OEBPS/chapter.xhtml"):
            ET.fromstring(archive.read(name))


def test_an_empty_chapter_is_refused_rather_than_stored(tmp_path):
    """A login wall or a removed chapter parses cleanly and yields nothing.

    Writing it would leave a valid, empty book in the library that no later run
    would ever retry, because it verifies.
    """
    with pytest.raises(PackagingError):
        write_epub(tmp_path / "n.epub", chapter(blocks=[]), series_title="N")
    with pytest.raises(PackagingError):
        write_epub(
            tmp_path / "n.epub",
            chapter(blocks=[TextBlock("p", "   ")]),
            series_title="N",
        )
    assert not (tmp_path / "n.epub").exists()
    assert not (tmp_path / "n.epub.tmp").exists()


def test_verify_rejects_a_truncated_or_foreign_file(tmp_path):
    broken = tmp_path / "b.epub"
    broken.write_bytes(b"PK\x03\x04" + b"0" * 900)
    assert not verify_epub(broken)
    assert not verify_epub(tmp_path / "missing.epub")


def test_block_kinds_are_a_closed_set():
    """They become XHTML element names, so an unknown one is markup injection."""
    with pytest.raises(ValueError):
        TextBlock("div", "x")


def test_rtl_detection_covers_the_scripts_these_sources_use():
    assert is_rtl_language("ar") and is_rtl_language("ar-EG") and is_rtl_language("he")
    assert not is_rtl_language("en") and not is_rtl_language(None)


# --------------------------------------------- telling prose from pictures


def _container(html: str):
    from selectolax.parser import HTMLParser
    return HTMLParser(html).css_first("div")


def test_a_reader_with_images_is_never_prose():
    """An image anywhere in the reader settles it.

    Calling a comic chapter prose would silently drop every page, so a long
    translator's note must not tip the decision. Deliberately not a ratio.
    """
    node = _container("<div><img src='a.jpg'><p>%s</p></div>" % ("word " * 900))
    assert not looks_like_prose(node, 1)


def test_a_reader_of_paragraphs_is_prose():
    node = _container("<div><p>%s</p></div>" % ("الفصل " * 500))
    assert looks_like_prose(node, 0)


def test_an_empty_or_failed_page_is_not_a_novel():
    """The character floor is what stops a broken fetch becoming an EPUB."""
    assert not looks_like_prose(_container("<div><p>Loading…</p></div>"), 0)
    assert not looks_like_prose(_container("<div></div>"), 0)
    assert not looks_like_prose(None, 0)


# ------------------------------- a short chapter is still a chapter (audit fix)


SHORT_PROSE = "<div>" + "".join(
    f"<p>{'قصيرة ' * 20}</p>" for _ in range(4)) + "</div>"


def test_a_short_chapter_of_real_paragraphs_is_prose():
    """A ~500-character chapter is short, not a comic.

    The character floor was 1,500, so a genuinely short chapter was judged "not
    prose", packaged as `cbz`, and then died in `fetch_pages` with "no reader
    images" — the exact failure the prose routing exists to remove.
    """
    assert looks_like_prose(_container(SHORT_PROSE), 0)


def test_an_image_reader_that_yielded_no_images_is_still_not_prose():
    """The case the character floor was really guarding, and the reason the
    replacement is a *block* count.

    Measured across the captured fixtures: every comic reader parses to **0
    blocks** — including `madara_chapter_page.html`, which has no images
    either. Every prose reader parses to 56 or more. Blocks separate them;
    characters do not.
    """
    reader = _container("<div><a href='/next'>Next</a> <span>Chapter 12</span></div>")
    assert not looks_like_prose(reader, 0)


@pytest.mark.parametrize("fixture, selector, prose", [
    ("riwayatarab/chapter1.html", "div.chapter-content", True),
    ("rewayat/chapter1.html", "div.v-card--flat", True),
    ("wuxiabox/chapter.html", "div.chapter-content", True),
    ("madara_reader.html", "div.reading-content", False),
    ("madara_chapter_page.html", "div.reading-content", False),
    # vcomics is deliberately absent: its Astro reader has no
    # `div.reading-content`, so the row would only ever skip. The two Madara
    # rows carry the comic case, including the no-image one that matters.
])
def test_real_readers_are_classified_from_their_blocks(fixture, selector, prose):
    """The table this rule was calibrated on, pinned so it cannot drift."""
    from pathlib import Path
    from selectolax.parser import HTMLParser

    path = Path(__file__).parent / "fixtures" / fixture
    tree = HTMLParser(path.read_text(encoding="utf-8", errors="replace"))
    node = tree.css_first(selector)
    assert node is not None, f"{fixture} no longer has {selector}"
    images = len(node.css("img"))
    assert looks_like_prose(node, images) is prose
