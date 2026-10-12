"""Core reads adapter labels without making legacy manifests invalid."""

from oneshelf.plugins.labels import CATEGORIES, metadata_from_manifest, parse_adapter_label, validate_metadata


def test_parser_matches_adapter_repository_vocabulary_and_order():
    assert tuple(CATEGORIES) == (
        "Manga", "Webtoons", "Comics", "Books", "Children's books", "Academic books",
        "Textbooks", "Poetry", "Religious texts", "Journal", "Papers", "Reports",
        "Manuscripts", "Newspapers", "Digital library",
    )
    assert parse_adapter_label("3asq (Al-Aasheq) · Manga · AR") == ("Manga", ("AR",))
    assert parse_adapter_label("مجلة آداب الكوفة (University of Kufa, Iraq) · Journal · AR") == ("Journal", ("AR",))
    assert parse_adapter_label("ATU · Journal · FA/AR") == ("Journal", ("FA", "AR"))
    assert parse_adapter_label("MangaDex · Manga · Multi") == ("Manga", ("Multi",))


def test_invalid_labels_are_absent_and_legacy_language_uses_defaults():
    for name in ("Old source", "A·Manga·AR", "A · manga · AR", "A · Manga · ar",
                 "A · Manga · EN/FR/DE/AR/JA", " · Manga · AR", " A · Manga · AR",
                 "A · Manga · AR · More", "A" * 81 + " · Manga · AR"):
        assert parse_adapter_label(name) is None
    assert metadata_from_manifest({"name": "Old source", "defaults": {"language": "arz-EG"}}) == (None, ("AR",))
    assert metadata_from_manifest({"name": "Old source", "defaults": {"language": "en-US"}}) == (None, ("EN",))
    assert metadata_from_manifest({"name": "Old source"}) == (None, ())
    assert metadata_from_manifest({"name": "Source · Manga · AR",
                                   "defaults": {"language": "en", "content_type": "manga"}}) == (None, ("EN",))
    assert metadata_from_manifest({"name": "Source · Manga · EN",
                                   "defaults": {"language": "en", "content_type": "book"}}) == (None, ("EN",))


def test_untrusted_index_metadata_requires_known_category_and_valid_codes():
    assert validate_metadata("Journal", ["FA", "AR"]) == ("Journal", ("FA", "AR"))
    assert validate_metadata("Manga", ["Multi"]) == ("Manga", ("Multi",))
    assert validate_metadata(None, ["EN"]) == (None, ("EN",))
    for category, languages in (("Unknown", ["AR"]), ("Journal", ["AR", "Multi"]),
                                ("Journal", ["ar"]), ("Journal", ["AAAA"]),
                                ("Journal", []), ("Journal", "AR")):
        assert validate_metadata(category, languages) is None
