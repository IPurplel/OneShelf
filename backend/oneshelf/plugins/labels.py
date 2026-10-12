"""Metadata shared by installed plugins, Registry cards, and scoped search.

The vocabulary and label grammar mirror OneShelf-Adapters' tools/lib/adapter_labels.py.
Labels are optional for legacy adapters; an invalid label never prevents installation.
"""
from __future__ import annotations

import re
from collections.abc import Mapping

SEP = " · "
MAX_NAME = 80
CATEGORIES: dict[str, frozenset[str]] = {
    "Manga": frozenset({"manga"}),
    "Webtoons": frozenset({"comic", "manhwa", "manhua"}),
    "Comics": frozenset({"comic"}),
    "Books": frozenset({"book", "novel"}),
    "Children's books": frozenset({"book"}),
    "Academic books": frozenset({"book"}),
    "Textbooks": frozenset({"book"}),
    "Poetry": frozenset({"book"}),
    "Religious texts": frozenset({"book"}),
    "Journal": frozenset({"paper"}),
    "Papers": frozenset({"paper"}),
    "Reports": frozenset({"paper", "book"}),
    "Manuscripts": frozenset({"book", "other"}),
    "Newspapers": frozenset({"other"}),
    "Digital library": frozenset({"book", "other"}),
}
MULTI = "Multi"
LANGS = re.compile(r"^[A-Z]{2,3}(?:/[A-Z]{2,3}){0,3}$")
LABEL_OF = {"arz": "AR"}


def language_code(value: str) -> str:
    """The label's upper-case primary code, including known macrolanguage aliases."""
    primary = value.split("-", 1)[0].lower()
    return LABEL_OF.get(primary, primary.upper())


def parse_adapter_label(name: str) -> tuple[str, tuple[str, ...]] | None:
    """Return (category, ordered languages) for an exact three-part label."""
    if not isinstance(name, str) or len(name) > MAX_NAME:
        return None
    parts = name.split(SEP)
    if len(parts) != 3:
        return None
    source, category, langs = parts
    if not source.strip() or source != source.strip() or category not in CATEGORIES:
        return None
    if langs != MULTI and not LANGS.fullmatch(langs):
        return None
    return category, tuple(langs.split("/"))


def validate_metadata(category: object, languages: object) -> tuple[str | None, tuple[str, ...]] | None:
    """Validate untrusted index metadata before using it for display or search."""
    if category is not None and (not isinstance(category, str) or category not in CATEGORIES):
        return None
    if not isinstance(languages, (list, tuple)) or not languages or not all(isinstance(item, str) for item in languages):
        return None
    if languages == [MULTI] or languages == (MULTI,):
        return category, (MULTI,)
    joined = "/".join(languages)
    if not LANGS.fullmatch(joined):
        return None
    return category, tuple(languages)


def metadata_from_manifest(manifest: object) -> tuple[str | None, tuple[str, ...]]:
    """Parse the label or use a legacy manifest's default language alone."""
    if isinstance(manifest, Mapping):
        name = manifest.get("name")
        defaults = manifest.get("defaults") or {}
        language = defaults.get("language") if isinstance(defaults, Mapping) else None
        content_type = defaults.get("content_type") if isinstance(defaults, Mapping) else None
    else:
        name = getattr(manifest, "name", None)
        defaults = getattr(manifest, "defaults", None)
        language = getattr(defaults, "language", None)
        content_type = getattr(defaults, "content_type", None)
    parsed = parse_adapter_label(name)
    if parsed is not None:
        category, languages = parsed
        expected = language_code(language) if isinstance(language, str) else None
        if (not content_type or content_type in CATEGORIES[category]) and (
            not expected or languages == (MULTI,) or expected in languages
        ):
            return parsed
    if not isinstance(language, str):
        return None, ()
    code = language_code(language)
    return (None, (code,)) if LANGS.fullmatch(code) else (None, ())
