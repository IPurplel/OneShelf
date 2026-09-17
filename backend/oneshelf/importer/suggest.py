"""Conservative import association (Master §22, §37).

Only an unambiguous, strong title match with a compatible content type is treated as confident. Anything
else is offered as a choice (Choose Work or Create Local Work) rather than merged automatically.
"""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass

from oneshelf.search.grouping import compatible
from oneshelf.search.index import search_local

STRONG_TIERS = ("exact_title", "exact_normalized", "exact_loose", "exact_alias")


@dataclass(frozen=True)
class Suggestion:
    work_id: str
    title: str
    tier: str
    content_type: str | None
    confident: bool


def suggest_targets(conn: sqlite3.Connection, title: str, *, content_type: str | None = None,
                    limit: int = 5) -> list[Suggestion]:
    candidates = []
    for result in search_local(conn, title, limit=limit):
        if not compatible(content_type, result.candidate.content_type):
            continue
        candidates.append(result)
    suggestions = []
    for result in candidates:
        confident = len(candidates) == 1 and result.tier in STRONG_TIERS
        suggestions.append(Suggestion(result.work_id, result.title, result.tier, result.candidate.content_type,
                                      confident))
    return suggestions
