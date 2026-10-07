"""Text reading units: source markup is reduced to an allowlist before it is returned or stored (Master §27)."""
import pytest

from oneshelf.text.sanitise import (
    MAX_TEXT_UNIT_BYTES, TextUnitTooLarge, plain_text, sanitise, split_sections,
)

HOSTILE = [
    ("<p onclick='steal()'>a</p><script>alert(1)</script>", "<p>a</p>"),
    ("<a href='javascript:alert(1)'>x</a>", '<a rel="noopener noreferrer">x</a>'),
    ("<svg onload='x()'><script>alert(1)</script><text>t</text></svg><p>after</p>", "<p>after</p>"),
    ("<style>body{background:url(https://evil/)}</style><p style='background:url(https://evil/)'>s</p>", "<p>s</p>"),
    ("<base href='https://evil/'><meta http-equiv='refresh' content='0;url=https://evil/'><p>t</p>", "<p>t</p>"),
    ("<iframe src='https://evil/'></iframe><object data='x'></object><embed src='x'><p>t</p>", "<p>t</p>"),
    ("<form action='https://evil/'><input name='q'><button>go</button></form><p>t</p>", "<p>t</p>"),
    ("<img src='https://tracker/' srcset='a 1x, b 2x' onerror='x()'><p>t</p>", "<p>t</p>"),
    ("<!-- <script>alert(1)</script> --><p>t</p>", "<p>t</p>"),
    ("<math><mi>x</mi></math><p>t</p>", "<p>t</p>"),
]


@pytest.mark.parametrize(("markup", "expected"), HOSTILE)
def test_hostile_markup_is_reduced_to_the_allowlist(markup, expected):
    assert sanitise(markup) == expected


@pytest.mark.parametrize(("markup", "_"), HOSTILE)
def test_sanitising_is_idempotent(markup, _):
    once = sanitise(markup)
    assert sanitise(once) == once


def test_reading_structure_survives():
    markup = ("<h2>序</h2><p><ruby>漢<rp>(</rp><rt>かん</rt><rp>)</rp></ruby></p>"
              "<p dir='rtl' lang='ar'>مرحبا</p><table><tr><td colspan='2'>c</td></tr></table>"
              "<ol start='3'><li>i</li></ol><blockquote><em>q</em></blockquote>")
    cleaned = sanitise(markup)
    for kept in ("<h2>序</h2>", "<ruby>漢<rp>(</rp><rt>かん</rt><rp>)</rp></ruby>", 'dir="rtl"', 'lang="ar"',
                 'colspan="2"', 'start="3"', "<blockquote><em>q</em></blockquote>"):
        assert kept in cleaned


def test_links_are_absolute_http_https_or_mailto_only():
    markup = "<a href='/wiki/Next'>n</a><a href='mailto:a@b.example'>m</a><a href='data:text/html,x'>d</a>"
    assert sanitise(markup) == ('<a rel="noopener noreferrer">n</a>'
                                '<a href="mailto:a@b.example" rel="noopener noreferrer">m</a>'
                                '<a rel="noopener noreferrer">d</a>')
    resolved = sanitise("<a href='/wiki/Next'>n</a>", base_url="https://en.wikisource.org/w/api.php")
    assert resolved == '<a href="https://en.wikisource.org/wiki/Next" rel="noopener noreferrer">n</a>'


def test_an_image_becomes_its_alt_text_in_version_1():
    assert plain_text(sanitise("<p>A <img src='cat.png' alt='cat'> sat</p>")) == "A cat sat"


def test_an_oversized_unit_is_refused():
    with pytest.raises(TextUnitTooLarge):
        sanitise("<p>" + "x" * MAX_TEXT_UNIT_BYTES + "</p>")


def test_sections_split_at_block_boundaries_and_carry_headings():
    chapters = "".join(f"<h2>Part {i}</h2><p>{'word ' * 400}</p>" for i in range(5))
    sections = split_sections(sanitise(chapters), target_chars=4500)
    assert len(sections) == 3
    assert [s.title for s in sections] == ["Part 0", "Part 2", "Part 4"]
    assert all(sanitise(s.html) == s.html for s in sections)
    assert sum(s.characters for s in sections) == len(plain_text(sanitise(chapters))) - 2  # joins drop a space each


def test_a_short_unit_is_one_section_and_empty_is_none():
    assert len(split_sections("<p>short</p>")) == 1
    assert split_sections("") == []


def test_the_items_of_one_reader_result_are_one_unit():
    """A chapter that arrives verse by verse (Sefaria) is one chapter, not a section per verse."""
    from oneshelf.text.sanitise import unit_sections
    verses = [(f"<p><sup>{n}</sup> Verse {n} <script>x()</script>of the chapter.</p>", "Genesis 1" if n == 1 else None)
              for n in range(1, 32)]
    sections = unit_sections(verses)
    assert len(sections) == 1 and sections[0].title == "Genesis 1"
    assert sections[0].html.count("<p>") == 31 and "<script" not in sections[0].html
    assert plain_text(sections[0].html).startswith("1 Verse 1 of the chapter.")


def test_a_long_unit_of_many_items_is_still_sectioned():
    from oneshelf.text.sanitise import unit_sections
    items = [(f"<p>{'word ' * 400}</p>", None) for _ in range(20)]
    assert len(unit_sections(items)) > 1


def test_items_without_text_are_skipped_and_nothing_is_no_unit():
    from oneshelf.text.sanitise import unit_sections
    assert unit_sections([(None, "t"), ("<script>x</script>", None)]) == []
    assert len(unit_sections([(None, None), ("<p>only</p>", None)])) == 1


def test_a_unit_has_a_size_cap_of_its_own():
    from oneshelf.text.sanitise import MAX_UNIT_BYTES, unit_sections
    item = "<p>" + "x" * (MAX_TEXT_UNIT_BYTES - 100) + "</p>"
    with pytest.raises(TextUnitTooLarge):
        unit_sections([(item, None)] * (MAX_UNIT_BYTES // MAX_TEXT_UNIT_BYTES + 1))
