"""I-92: classification precedence for source listings (Master §9.2)."""
from types import SimpleNamespace

from oneshelf.plugins.classification import classify, classify_listing
from oneshelf.search.grouping import LiveListing

ARABIC_MANGA = SimpleNamespace(language="ar", content_type="manga")
NO_DEFAULTS = SimpleNamespace(language=None, content_type=None)


def test_an_explicit_source_value_beats_the_plugin_default():
    c = classify(language="en", content_type="manhwa", defaults=ARABIC_MANGA)
    assert (c.language, c.language_source, c.content_type, c.content_type_source) == ("en", "source", "manhwa", "source")


def test_the_plugin_default_fills_what_the_source_left_out():
    c = classify(language=None, content_type=None, defaults=ARABIC_MANGA)
    assert (c.language, c.language_source, c.content_type, c.content_type_source) == \
        ("ar", "plugin_default", "manga", "plugin_default")


def test_invalid_or_unknown_source_values_count_as_silence_not_as_evidence():
    c = classify(language="und", content_type="not-a-type", defaults=ARABIC_MANGA)
    assert (c.language, c.content_type) == ("ar", "manga")
    c = classify(language="Klingon!!", content_type="", defaults=NO_DEFAULTS)
    assert (c.language, c.language_source, c.content_type, c.content_type_source) == (None, "unknown", None, "unknown")


def test_without_a_plugin_nothing_is_invented():
    c = classify(language=None, content_type=None, defaults=None)
    assert (c.language, c.content_type) == (None, None)


def test_a_listing_that_names_its_languages_keeps_them():
    listing = LiveListing(source_id="s", listing_key="k", title="t", available_languages=["en", "fr"])
    assert classify_listing(listing, ARABIC_MANGA).language is None
    assert classify_listing(listing, ARABIC_MANGA).content_type == "manga"
