"""One classifier for every entry path (Master §9.2; I-92, I-94).

Precedence: user override > explicit source classification > plugin default > Unknown. User overrides live
on Works and Reading Units (`oneshelf.library.overrides`) and are never touched here; this module decides what
a *source listing* is, the same way for search results, direct URLs and opened listings, so the language and
type a Work gets never depend on how the person happened to reach it.
"""
from __future__ import annotations

from dataclasses import dataclass, replace

from oneshelf.plugins.runtime import CONTENT_TYPES, _LANGUAGE

UNKNOWN_LANGUAGE = "und"


@dataclass(frozen=True)
class Classification:
    language: str | None
    language_source: str            # source | plugin_default | unknown
    content_type: str | None
    content_type_source: str        # source | plugin_default | unknown


def classify(*, language: str | None, content_type: str | None, defaults) -> Classification:
    """`defaults` is a manifest's `defaults` (or None when the plugin cannot be loaded)."""
    if isinstance(language, str) and language != UNKNOWN_LANGUAGE and _LANGUAGE.match(language):
        lang, lang_source = language, "source"
    elif defaults is not None and defaults.language:
        lang, lang_source = defaults.language, "plugin_default"
    else:
        lang, lang_source = None, "unknown"
    if isinstance(content_type, str) and content_type in CONTENT_TYPES:
        kind, kind_source = content_type, "source"
    elif defaults is not None and defaults.content_type:
        kind, kind_source = defaults.content_type, "plugin_default"
    else:
        kind, kind_source = None, "unknown"
    return Classification(lang, lang_source, kind, kind_source)


def defaults_for(plugins, source_id: str):
    """The active package's declared defaults, or None when the plugin is missing or unloadable."""
    if plugins is None or source_id == "local":
        return None
    try:
        return plugins.load_active(source_id).manifest.defaults
    except Exception:  # noqa: BLE001 — an unavailable plugin simply contributes no defaults
        return None


def classify_listing(listing, defaults):
    """A LiveListing with its language and type filled from the plugin defaults where the source was silent.

    A listing that names its languages (`available_languages`) keeps them: those are explicit source values.
    """
    result = classify(language=listing.language, content_type=listing.content_type, defaults=defaults)
    language = listing.language if listing.available_languages else result.language
    return replace(listing, language=language, content_type=result.content_type)
