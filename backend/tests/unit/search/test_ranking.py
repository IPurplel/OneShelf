"""Master §6.2–6.4: local index, normalization without stemming, ranking tiers and bounded boosts."""
import pytest

from oneshelf.search.normalize import search_keys, tokens
from oneshelf.search.ranking import TIERS, Boosts, Candidate, rank


def candidate(title, aliases=(), **kw):
    return Candidate(entity_id=title, title=title, aliases=list(aliases), **kw)


def tiers_for(query, titles, aliases=()):
    results = rank(query, [candidate(t, aliases) for t in titles])
    return {r.candidate.title: r.tier for r in results}


def test_search_keys_preserve_the_original_text():
    keys = search_keys("  أَلْكِتَابُ   الكَبير ")
    assert keys.original == "  أَلْكِتَابُ   الكَبير "
    assert keys.normalized == "الكتاب الكبير"
    assert keys.loose == "الكتاب الكبير"
    assert keys.tokens == ("الكتاب", "الكبير")


def test_loose_key_applies_ta_marbuta_equivalence():
    assert search_keys("مدرسة").loose == search_keys("مدرسه").loose
    assert search_keys("مدرسة").normalized != search_keys("مدرسه").normalized


def test_tokens_split_on_punctuation_and_keep_numbers():
    assert tokens("Solo Leveling: Ragnarok - vol. 2") == ("solo", "leveling", "ragnarok", "vol", "2")


@pytest.mark.parametrize("query,title,tier", [
    ("Solo Leveling", "Solo Leveling", "exact_title"),
    ("solo   leveling", "Solo Leveling", "exact_normalized"),
    ("مدرسه الظلام", "مدرسة الظلام", "exact_loose"),
    ("Solo", "Solo Leveling", "prefix"),
    ("leveling solo", "Solo Leveling", "all_token"),
    ("Level", "Solo Leveling", "substring"),
    ("Solo Levelling", "Solo Leveling", "fuzzy"),
    ("Completely Different", "Solo Leveling", None),
])
def test_relevance_tiers(query, title, tier):
    results = rank(query, [candidate(title)])
    assert (results[0].tier if results else None) == tier


def test_alias_matches_rank_as_alias_tier():
    results = rank("القمر", [candidate("Moon Chronicle", aliases=["حكاية القمر", "القمر"])])
    assert results[0].tier == "exact_alias"


def test_tier_order_is_stable():
    titles = ["Solo Leveling", "Solo Levelling Returns", "Solo Leveling: Ragnarok", "solo leveling"]
    results = rank("Solo Leveling", [candidate(t) for t in titles])
    assert [r.candidate.title for r in results][:2] == ["Solo Leveling", "solo leveling"]
    assert [TIERS.index(r.tier) for r in results] == sorted(TIERS.index(r.tier) for r in results)


def test_no_stemming_articles_are_not_stripped():
    tiers = tiers_for("كتاب", ["الكتاب", "كتاب"])
    assert tiers["كتاب"] == "exact_title" and tiers["الكتاب"] == "substring"
    assert tiers_for("book", ["books", "book"])["books"] in ("prefix", "substring", "fuzzy")


def test_boosts_cannot_overpower_textual_relevance():
    strong = candidate("Solo Leveling")
    weak = candidate("Solo Levelling Chronicles", boosts=Boosts(user_mapping=True, on_shelf=True,
                                                                language_alias=True, agreeing_sources=4))
    results = rank("Solo Leveling", [weak, strong])
    assert results[0].candidate is strong


def test_boosts_order_within_a_tier():
    plain = candidate("Moonlight Sonata")
    boosted = candidate("Moonlight Serenade", boosts=Boosts(on_shelf=True))
    results = rank("Moonlight", [plain, boosted])
    assert {r.tier for r in results} == {"prefix"}
    assert results[0].candidate is boosted


def test_unknown_metadata_never_lowers_a_match():
    known = candidate("Berserk", creator="Kentaro Miura", content_type="manga")
    unknown = candidate("Berserk", creator=None, content_type=None)
    results = rank("Berserk", [unknown, known])
    assert {r.tier for r in results} == {"exact_title"} and len(results) == 2
