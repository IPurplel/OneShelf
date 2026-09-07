"""Normalisation, similarity, and the corpus that calibrates the thresholds.

Every case here is drawn from a measured failure or a documented noise case,
not invented. The two halves matter equally: the *recall* corpus is what the
engine must find, and the *precision* corpus is what it must keep refusing.
Moving a threshold to satisfy one half without running the other is how this
regresses.

Provenance of the headline case, measured against 8ghrb.com on 2026-09-07:
searching ``روايه`` returned 30 candidates and the gate discarded 29 — every
one a real book titled ``رواية …``. The only survivor spelled the word exactly
as the query did.
"""

from __future__ import annotations

import pytest

from app.adapters.base import (
    SCORE_FUZZY,
    SCORE_IRRELEVANT,
    query_matches,
    relevance,
)
from app.adapters.textmatch import (
    close_enough,
    fold,
    romanise,
    token_subset,
    tokens,
)


# ----------------------------------------------------------------- folding


@pytest.mark.parametrize("variant, canonical, why", [
    ("الغريـب", "الغريب", "tatweel is decorative and carries no meaning"),
    ("أحمد", "احمد", "alef with hamza above"),
    ("إبراهيم", "ابراهيم", "alef with hamza below"),
    ("آلام", "الام", "alef with madda"),
    ("مَانْجَا", "مانجا", "harakat"),
    ("رواية", "روايه", "teh marbuta folds to heh"),
    ("مصطفى", "مصطفي", "alef maqsura folds to yeh"),
    ("٢٠٢٦", "2026", "arabic-indic digits"),
])
def test_arabic_variants_fold_together(variant, canonical, why):
    assert fold(variant) == fold(canonical), why


@pytest.mark.parametrize("text, expected", [
    ("Café", "cafe"),
    ("naïve", "naive"),
    ("Berserk:", "berserk"),
    ("Berserk – GuideBook", "berserk guidebook"),
])
def test_latin_folding(text, expected):
    assert fold(text) == expected


def test_an_apostrophe_is_deleted_not_split_on():
    """The bug this fixes, in one line.

    Splitting on the apostrophe left a stray one-letter token, so
    "dragonslayers" could never match "Dragonslayer's" — a query a reader
    types constantly.
    """
    assert fold("A Dragonslayer's Peerless Regression") == \
        "a dragonslayers peerless regression"
    assert "dragonslayers" in tokens("A Dragonslayer's Peerless Regression")


def test_folding_is_idempotent():
    for text in ["رواية الغريب", "Café Society", "A Dragonslayer's Regression"]:
        assert fold(fold(text)) == fold(text)


def test_folding_never_raises_on_empty_or_punctuation():
    assert fold("") == ""
    assert fold("   ") == ""
    assert fold("!!!") == ""


# ------------------------------------------------------------ romanisation


@pytest.mark.parametrize("a, b", [
    ("Shingeki no Kyoujin", "Shingeki no Kyojin"),
    ("Yuuki", "Yuki"),
    ("Solo Levelling", "Solo Leveling"),
])
def test_transliteration_variants_share_a_romanised_key(a, b):
    assert romanise(a) == romanise(b)


# --------------------------------------------------------------- similarity
#
# The recall corpus. Each of these was measured returning 0 before this module
# existed.

RECALL = [
    ("الغريب", "الغريـب", "tatweel"),
    ("احمد", "أحمد", "hamza alef"),
    ("مانجا", "مَانْجَا", "harakat"),
    ("روايه", "رواية العقد", "teh marbuta, the measured case"),
    ("روايه", "رواية عزسفير", "a title the gate really discarded"),
    ("مصطفى", "مصطفي", "alef maqsura"),
    ("dragonslayers regression", "A Dragonslayer's Peerless Regression", "apostrophe"),
    ("berserck", "Berserk", "one transposed letter"),
    ("solo levelling", "Solo Leveling", "doubled consonant"),
    ("shingeki no kyojin", "Shingeki no Kyoujin", "long vowel"),
    ("cafe", "Café Society", "latin accent, query is a prefix"),
]

# The precision corpus. Three of these are the catalogue-dump cases HANDOFF.md
# records; if a threshold change lets one through, the change is wrong.
PRECISION = [
    ("berserk", "Magic Emperor", "documented catalogue-dump noise"),
    ("berserk", "The Hero Becomes Duke's Eldest Son", "documented catalogue-dump noise"),
    ("berserk", "Solo Leveling", "unrelated series"),
    ("روايه", "مسرحية آلام سياوش", "مسرحية is a play, not a novel"),
    ("naruto", "Boruto", "similar spelling, different work"),
    ("one piece", "One Punch Man", "shares one token only"),
]


@pytest.mark.parametrize("query, title, why", RECALL)
def test_the_engine_finds_what_it_used_to_discard(query, title, why):
    assert relevance(query, title) > SCORE_IRRELEVANT, why


@pytest.mark.parametrize("query, title, why", PRECISION)
def test_the_engine_still_refuses_noise(query, title, why):
    assert relevance(query, title) == SCORE_IRRELEVANT, why


@pytest.mark.parametrize("query, title, why", PRECISION)
def test_the_gate_still_refuses_noise(query, title, why):
    """The gate is the half that actually protects a multi-site search."""
    assert not query_matches(query, title), why


@pytest.mark.parametrize("query, title, why", RECALL)
def test_the_gate_admits_real_variants(query, title, why):
    assert query_matches(query, title), why


def test_a_cross_script_hit_is_ranked_last_rather_than_judged():
    """The one thing relevance must not do is judge across scripts.

    These sites index names in several writing systems and display one, so an
    Arabic query can legitimately land on a romanised title with nothing in
    common on the page — the site matched on a name we are not being shown.
    Such a hit is unjudgeable, so it is kept and ranked last. The *gate*, which
    protects a multi-site search from catalogue dumps, still refuses it.
    """
    from app.adapters.base import SCORE_UNJUDGEABLE

    assert relevance("الغريب", "Power Piece (Arabic)") == SCORE_UNJUDGEABLE
    assert not query_matches("الغريب", "Power Piece (Arabic)")


def test_a_short_query_is_never_fuzzy_matched():
    """One edit on a three-letter word reaches most other three-letter words."""
    assert not close_enough("ali", "all")
    assert not close_enough("abc", "abd")


def test_a_fuzzy_hit_ranks_below_every_real_match():
    """An approximate answer may be offered; it must never displace a real one."""
    assert relevance("berserck", "Berserk") == SCORE_FUZZY
    assert SCORE_FUZZY < relevance("berserk", "Berserk of Gluttony")
    assert SCORE_FUZZY < relevance("berserk", "Berserk")


def test_token_subset_allows_one_typo_per_word_not_a_free_for_all():
    assert token_subset("solo levelling", "Solo Leveling Manhwa")
    assert not token_subset("solo levelling", "Completely Different Title")


# ------------------------------------------------------- identity vs relevance


def test_folding_together_is_not_proof_of_being_the_same_work():
    """The trap this guards, called out during review.

    `على` and `علي` are different words that fold to the same key. Folding is
    evidence for *relevance*; deciding two records are the same work needs
    more than a shared normalised title, which is why grouping in
    ``app.main`` requires the author and content type to agree as well.
    """
    assert fold("على") == fold("علي")
    from app.main import _identity_key

    left = {"title": "على", "author": "A", "content_type": "book"}
    right = {"title": "علي", "author": "B", "content_type": "book"}
    assert _identity_key(left) != _identity_key(right), \
        "a shared normalised title alone must not merge two works"
