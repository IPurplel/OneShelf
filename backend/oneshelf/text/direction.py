"""Content direction from a BCP 47 language tag (Meta Prompt: UI direction and content direction are
independent). Only a text unit's own language decides how its text runs; the interface language never does."""
from __future__ import annotations

# Languages written right to left in their default script.
RTL_LANGUAGES = {"ar", "arc", "ckb", "dv", "fa", "he", "iw", "ks", "ku", "ps", "sd", "syr", "ug", "ur", "yi"}
RTL_SCRIPTS = {"arab", "hebr", "syrc", "thaa", "nkoo", "adlm", "rohg"}
LTR_SCRIPTS = {"latn", "cyrl", "grek"}


def content_direction(language: str | None) -> str:
    if not language:
        return "ltr"
    parts = language.replace("_", "-").lower().split("-")
    script = next((p for p in parts[1:] if len(p) == 4 and p.isalpha()), None)
    if script in RTL_SCRIPTS:
        return "rtl"
    if script in LTR_SCRIPTS:
        return "ltr"
    return "rtl" if parts[0] in RTL_LANGUAGES else "ltr"
