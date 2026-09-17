"""Master §9.4: bounded safe transform library (no code, bounded regex, resource limits)."""
import time

import pytest

from oneshelf.plugins.transforms import MAX_STEPS, MAX_VALUE_BYTES, TransformError, apply_pipeline, validate_pipeline
from oneshelf.text.arabic import normalize_loose, normalize_strong

BASE = "https://source.example/manga/solo/"


def run(value, *steps):
    validate_pipeline(list(steps))
    return apply_pipeline(value, list(steps), base_url=BASE)


def test_trim_replace_split_join():
    assert run("  Hello  ", "trim") == "Hello"
    assert run("a-b-c", {"replace": {"old": "-", "new": " "}}) == "a b c"
    assert run("a, b, c", {"split": {"sep": ","}}, "trim") == ["a", "b", "c"]
    assert run("a,b,c", {"split": {"sep": ",", "index": 1}}) == "b"
    assert run(["x", "y"], {"join": {"sep": "/"}}) == "x/y"


def test_none_stays_unknown():
    assert run(None, "trim", "extract_number") is None


@pytest.mark.parametrize("raw,expected", [
    ("Chapter 12", "12"), ("Ch. 3.5 - Special", "3.5"), ("الفصل ٣٫٥", "3.5"), ("الفصل ١٢", "12"),
    ("Extra Story", None), ("vol 2 ch 7", "2"),
])
def test_extract_number_preserves_decimals_and_arabic_digits(raw, expected):
    assert run(raw, "extract_number") == expected


@pytest.mark.parametrize("raw,expected", [
    ("2026-09-17", "2026-09-17"), ("2026-09-17T10:20:30Z", "2026-09-17"), ("Sep 17, 2026", "2026-09-17"),
    ("17/09/2026", None), ("3 days ago", None), ("", None),
])
def test_parse_date_default_formats(raw, expected):
    assert run(raw, "parse_date") == expected


def test_parse_date_with_explicit_format():
    assert run("17/09/2026", {"parse_date": {"formats": ["%d/%m/%Y"]}}) == "2026-09-17"


@pytest.mark.parametrize("raw,expected", [
    ("chapter-1", "https://source.example/manga/solo/chapter-1"),
    ("/manga/solo#top", "https://source.example/manga/solo"),
    ("//cdn.source.example/p.jpg", "https://cdn.source.example/p.jpg"),
    ("javascript:alert(1)", None), ("data:text/html,x", None), ("file:///etc/passwd", None),
    ("https://user:pw@source.example/x", None),
])
def test_normalize_url(raw, expected):
    assert run(raw, "normalize_url") == expected


def test_decoders():
    assert run("Tom &amp; Jerry &#1587;", "html_decode") == "Tom & Jerry س"
    assert run("%D8%B3%20x", "url_decode") == "س x"
    assert run("2LPZhNin2YU=", "base64_decode") == "سلام"
    with pytest.raises(TransformError):
        run("!!!not-base64", "base64_decode")


def test_regex_extract_and_replace():
    assert run("id=4821&x", {"regex_extract": {"pattern": r"id=(\d+)", "group": 1}}) == "4821"
    assert run("no id", {"regex_extract": {"pattern": r"id=(\d+)", "group": 1}}) is None
    assert run("a1b22c", {"regex_replace": {"pattern": r"\d+", "replacement": "#"}}) == "a#b#c"


def test_regex_is_linear_time_on_catastrophic_patterns():
    started = time.monotonic()
    assert run("a" * 50_000 + "!", {"regex_extract": {"pattern": r"^(a+)+$", "group": 1}}) is None
    assert time.monotonic() - started < 1.0


@pytest.mark.parametrize("pattern", [r"(a)\1", r"(?=x)y", r"(?<!x)y", "x" * 600])
def test_unsupported_or_oversized_regex_is_rejected_at_validation(pattern):
    with pytest.raises(TransformError):
        validate_pipeline([{"regex_extract": {"pattern": pattern, "group": 0}}])


@pytest.mark.parametrize("spec", [
    ["eval"], [{"exec": "import os"}], [{"trim": {"unexpected": 1}}], [{"replace": {"old": "a"}}],
    [{"trim": None, "replace": {"old": "a", "new": "b"}}], ["trim"] * (MAX_STEPS + 1), "trim", [42],
])
def test_invalid_pipelines_are_rejected(spec):
    with pytest.raises(TransformError):
        validate_pipeline(spec)


def test_oversized_values_are_rejected():
    with pytest.raises(TransformError):
        run("x" * (MAX_VALUE_BYTES + 1), "trim")
    with pytest.raises(TransformError):
        run("ab" * (MAX_VALUE_BYTES // 4), {"replace": {"old": "a", "new": "a" * 10}})


def test_arabic_normalization_levels_without_stemming():
    assert normalize_strong("أَلْكِتَابُ") == "الكتاب"  # diacritics removed, alef unified, article kept
    assert normalize_strong("إسـلام آمنة") == "اسلام امنة"  # tatweel removed
    assert normalize_strong("مستشفى") == "مستشفي"
    assert normalize_loose("مدرسة") == normalize_loose("مدرسه") == "مدرسه"
    assert normalize_strong("مدرسة") != normalize_strong("مدرسه")  # ة↔ه only at the loose level
    assert run("أَلْكِتَابُ", "normalize_arabic") == "الكتاب"
