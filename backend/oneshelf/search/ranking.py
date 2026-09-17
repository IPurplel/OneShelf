"""Textual relevance tiers and bounded boosts (Master §6.4).

Tier order follows the Master, with the intentional loose Arabic equivalence (§6.3) placed directly
after the normalized-title tier. Boosts only reorder candidates inside one tier; they can never lift a
weak textual match above a stronger one. Unknown metadata never lowers a match (§6.7).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from difflib import SequenceMatcher

from oneshelf.search.normalize import Keys, search_keys

TIERS = ("exact_title", "exact_normalized", "exact_loose", "exact_alias", "prefix", "all_token", "substring", "fuzzy")
FUZZY_RATIO = 0.82


@dataclass(frozen=True)
class Boosts:
    user_mapping: bool = False
    verified_mapping: bool = False
    on_shelf: bool = False
    language_alias: bool = False
    agreeing_sources: int = 0

    @property
    def value(self) -> float:
        return (3.0 * self.user_mapping + 2.0 * self.verified_mapping + 1.0 * self.on_shelf
                + 1.0 * self.language_alias + 0.5 * min(self.agreeing_sources, 4))


@dataclass
class Candidate:
    entity_id: str
    title: str
    aliases: list[str] = field(default_factory=list)
    original_title: str | None = None
    creator: str | None = None
    content_type: str | None = None
    work_id: str | None = None
    boosts: Boosts = field(default_factory=Boosts)


@dataclass(frozen=True)
class Ranked:
    candidate: Candidate
    tier: str
    boost: float


def _tier_for(query: Keys, text: str, *, alias: bool) -> str | None:
    keys = search_keys(text)
    if not keys.normalized:
        return None
    if not alias:
        if text.strip() == query.original.strip():
            return "exact_title"
        if keys.normalized == query.normalized:
            return "exact_normalized"
        if keys.loose == query.loose:
            return "exact_loose"
    elif keys.normalized == query.normalized or keys.loose == query.loose:
        return "exact_alias"
    if keys.normalized.startswith(query.normalized):
        return "prefix"
    if query.tokens and set(query.tokens) <= set(keys.tokens):
        return "all_token"
    if query.normalized in keys.normalized:
        return "substring"
    if SequenceMatcher(None, query.normalized, keys.normalized).ratio() >= FUZZY_RATIO:
        return "fuzzy"
    return None


def best_tier(query: str | Keys, candidate: Candidate) -> str | None:
    keys = query if isinstance(query, Keys) else search_keys(query)
    tiers = [t for t in (_tier_for(keys, candidate.title, alias=False),) if t]
    for text in filter(None, [candidate.original_title]):
        tier = _tier_for(keys, text, alias=False)
        if tier:
            tiers.append(tier)
    for alias in candidate.aliases:
        tier = _tier_for(keys, alias, alias=True)
        if tier:
            tiers.append(tier)
    return min(tiers, key=TIERS.index) if tiers else None


def rank(query: str, candidates: list[Candidate]) -> list[Ranked]:
    keys = search_keys(query)
    if not keys.normalized:
        return []
    ranked = []
    for candidate in candidates:
        tier = best_tier(keys, candidate)
        if tier is not None:
            ranked.append(Ranked(candidate, tier, candidate.boosts.value))
    ranked.sort(key=lambda r: (TIERS.index(r.tier), -r.boost, r.candidate.title))
    return ranked
