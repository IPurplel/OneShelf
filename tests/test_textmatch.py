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
    clean_query,
    close_enough,
    fold,
    query_variants,
    romanise,
    token_subset,
    tokens,
    undecorate,
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


# --------------------------------------------------- invisible marks (WP-3 B)
#
# None of these is visible to the person who typed the query. All of them
# arrive by copy-paste, from a browser, a PDF or a right-to-left document.

INVISIBLE = [
    ("‎", "LRM, left-to-right mark"),
    ("‏", "RLM, right-to-left mark"),
    ("؜", "ALM, arabic letter mark"),
    ("​", "zero width space"),
    ("‌", "ZWNJ, zero width non-joiner"),
    ("‍", "ZWJ, zero width joiner"),
    ("﻿", "BOM / zero width no-break space"),
    ("‪", "left-to-right embedding"),
    ("‫", "right-to-left embedding"),
    ("‬", "pop directional formatting"),
    ("‭", "left-to-right override"),
    ("‮", "right-to-left override"),
    ("⁦", "left-to-right isolate"),
    ("⁩", "pop directional isolate"),
]


@pytest.mark.parametrize("mark, why", INVISIBLE)
def test_an_invisible_mark_around_a_query_changes_nothing(mark, why):
    assert fold(f"{mark}الغريب{mark}") == fold(
        "الغريب"), why
    assert clean_query(
        f"{mark}الغريب{mark}"
    ) == "الغريب", why


@pytest.mark.parametrize("mark, why", INVISIBLE)
def test_an_invisible_mark_inside_a_word_does_not_split_it(mark, why):
    """The failure this rule exists for.

    Before it, an invisible mark reached the punctuation rule in ``fold`` and
    became a *space*, so one word became two tokens and every gate downstream
    went looking for both halves separately.
    """
    assert tokens(f"روا{mark}ية") == ["روايه"], why
    assert query_matches(f"روا{mark}ية",
                         "رواية الغريب"), why


def test_a_pasted_query_still_matches_the_title_it_was_pasted_from():
    pasted = "‫‏رواية الغريب‎‬"
    plain = "رواية الغريب"
    assert query_matches(pasted, plain)
    assert relevance(pasted, plain) == relevance(plain, plain)


# ------------------------------------------- persian and urdu forms (WP-3 C)


@pytest.mark.parametrize("variant, canonical, why", [
    ("کتاب", "كتاب",
     "U+06A9 keheh is typed where U+0643 kaf is meant"),
    ("یوم", "يوم", "U+06CC farsi yeh for U+064A yeh"),
    ("کیمیا", "كيميا",
     "both substitutions in one word"),
    ("نامۀ", "نامه",
     "U+06C0 heh with yeh above"),
    ("کتابە", "كتابه", "U+06D5 ae"),
])
def test_persian_and_urdu_letter_forms_fold_to_their_arabic_equivalents(
        variant, canonical, why):
    assert fold(variant) == fold(canonical), why
    assert query_matches(variant, canonical), why


@pytest.mark.parametrize("carrier, bare, why", [
    ("ؤ", "و", "U+0624 decomposes to waw + U+0654 combining hamza"),
    ("ئ", "ي", "U+0626 decomposes to yeh + U+0654 combining hamza"),
])
def test_the_hamza_carriers_are_folded_by_decomposition_not_by_the_table(
        carrier, bare, why):
    """What this module actually does, as opposed to what it said it did.

    ``_ARABIC_FOLD`` deliberately omits the hamza carriers, and the docstring
    used to present that as the behaviour. It is not: NFKD decomposes both to a
    bare letter plus U+0654 combining hamza, and the combining-mark strip --
    the same pass that removes harakat -- then deletes the hamza. Pinned to a
    test rather than to a comment that was wrong for as long as it existed.
    """
    assert fold(carrier) == fold(bare), why


# ---------------------------------------------- the definite article (WP-3 C)


def test_the_definite_article_does_not_stop_a_match_in_either_direction():
    assert query_matches("الغريب",
                         "غريب في المدينة")
    assert query_matches("غريب", "الغريب")


def test_an_article_stripped_match_ranks_in_the_lowest_band():
    """Evidence of relevance, never proof of identity: it reaches only
    ``close_enough``, so it can never outrank a real containment match."""
    assert relevance("الغريب",
                     "غريب في المدينة") == SCORE_FUZZY


@pytest.mark.parametrize("query, title, why", [
    ("الله", "له",
     "stripping the article here would produce a different word"),
    ("الف", "ف", "two letters left is not a word"),
])
def test_the_article_rule_will_not_conflate_short_words(query, title, why):
    assert not query_matches(query, title), why


# --------------------------------------------------- query variants (WP-3 A)


def test_a_query_is_offered_in_the_spellings_a_reader_might_have_typed():
    assert query_variants("رواية")[:2] == [
        "رواية", "روايه"]
    assert query_variants("ليلى")[:2] == [
        "ليلى", "ليلي"]
    assert query_variants("الأمير")[:2] == [
        "الأمير", "الامير"]


def test_variants_never_include_the_query_twice_and_stay_bounded():
    for query in ("رواية", "berserk", "شهرزاد"):
        variants = query_variants(query)
        assert variants[0] == clean_query(query)
        assert len(variants) == len(set(variants))
        assert len(variants) <= 4


def test_a_word_with_no_ambiguous_letter_produces_no_variants():
    """Spending a query slot on a string with nothing to vary costs the shared
    rate limiter for no possible gain."""
    assert query_variants("شهرزاد") == ["شهرزاد"]
    assert query_variants("berserk") == ["berserk"]


def test_the_reverse_substitutions_only_apply_at_the_end_of_a_word():
    """Teh marbuta and alef maqsura cannot occur anywhere else, so substituting
    every heh in a word would produce a string that is not Arabic at all."""
    assert "شةرزاد" not in query_variants("شهرزاد")
    assert "مدينه" in query_variants("مدينة")


def test_a_variant_keeps_the_letters_the_user_typed():
    """Variants are for *sending*. Unlike fold() they are not canonicalised: a
    site index may well be case- and punctuation-exact."""
    assert query_variants("Berserk: The Guide") == ["Berserk: The Guide"]


@pytest.mark.parametrize("typed, plain, why", [
    ("رِوايَة", "رواية",
     "harakat are decoration; no index stores them"),
    ("روايـــة", "رواية",
     "tatweel arrives by copy-paste from justified text"),
    ("کتاب", "كتاب",
     "Persian keheh where an Arabic index holds kaf"),
])
def test_a_decorated_query_is_also_sent_undecorated(typed, plain, why):
    """Measured 2026-09-08 across five Arabic sites: each of these returned
    **0 hits on every site** as typed, while the plain spelling is an ordinary
    catalogue entry."""
    assert undecorate(typed) == plain, why
    assert plain in query_variants(typed), why


def test_undecorating_is_not_folding():
    """`undecorate` is for a string being *sent*, so it must not collapse the
    letters a site may genuinely distinguish -- only what is decorative."""
    assert undecorate("رواية") == "رواية"
    assert undecorate("ليلى") == "ليلى"
    assert undecorate("الأمير") == "الأمير"
    assert undecorate("Berserk") == "Berserk"
    assert fold("رواية") != undecorate("رواية")
