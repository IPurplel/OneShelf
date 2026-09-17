"""Search keys (Master §6.3). Display text is never modified; only keys are normalized. No stemming."""
from __future__ import annotations

import re
from dataclasses import dataclass

from oneshelf.text.arabic import normalize_loose, normalize_strong

_TOKEN = re.compile(r"\w+", re.UNICODE)


@dataclass(frozen=True)
class Keys:
    original: str
    normalized: str
    loose: str
    tokens: tuple[str, ...]


def tokens(text: str) -> tuple[str, ...]:
    return tuple(_TOKEN.findall(normalize_strong(text)))


def search_keys(text: str) -> Keys:
    normalized = normalize_strong(text)
    return Keys(original=text, normalized=normalized, loose=normalize_loose(text), tokens=tuple(_TOKEN.findall(normalized)))
