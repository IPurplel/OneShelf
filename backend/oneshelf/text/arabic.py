"""Arabic text normalization for keys (Master §6.3). Never stems; never used for display text.

strong: diacritics/tatweel removed, alef forms unified, alef maqsura → ya, Persian letter variants,
        Arabic-Indic digits → ASCII, NFKC presentation forms, casefold, collapsed whitespace.
loose:  strong + intentional ة ↔ ه equivalence.
"""
from __future__ import annotations

import re
import unicodedata

_DIACRITICS = re.compile("[ؐ-ًؚ-ٰٟۖ-ۭ]")
_TATWEEL = "ـ"
_TRANSLATE = str.maketrans({
    "أ": "ا", "إ": "ا", "آ": "ا", "ٱ": "ا",  # أ إ آ ٱ → ا
    "ى": "ي", "ی": "ي",  # ى ی → ي
    "ک": "ك",  # ک → ك
    **{chr(0x0660 + i): str(i) for i in range(10)},
    **{chr(0x06F0 + i): str(i) for i in range(10)},
})
_WHITESPACE = re.compile(r"\s+")


def normalize_strong(text: str) -> str:
    text = unicodedata.normalize("NFKC", text)
    text = _DIACRITICS.sub("", text).replace(_TATWEEL, "")
    text = text.translate(_TRANSLATE).casefold()
    return _WHITESPACE.sub(" ", text).strip()


def normalize_loose(text: str) -> str:
    return normalize_strong(text).replace("ة", "ه")  # ة → ه
