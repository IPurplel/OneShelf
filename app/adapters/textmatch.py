"""Text normalisation and similarity, shared by every adapter.

Kept separate from ``base`` so the rules can be read, tested and calibrated on
their own; ``base`` imports from here, so every existing
``from .base import query_matches, relevance`` keeps working.

**Why this module exists.** Measured against the live site on 2026-09-07: a
search for ``روايه`` returned **30 candidates from 8ghrb.com, of which our own
gate discarded 29** — every one of them a real book whose title begins
``رواية``. The only survivor was the single title that happened to spell the
word the same way the query did. The site had the results; we threw them away.
Typing ``ه`` for ``ة`` is not a mistake a reader should be punished for.

Three ideas keep the rest honest:

* **Normalising is for matching, never for display.** Every caller keeps the
  original string and shows that. Folding is lossy on purpose.
* **A normalised match is evidence of relevance, not proof of identity.**
  ``على`` and ``علي`` are different words that fold together, so nothing here
  may be used to decide that two records are the same work.
* **Different failures need different treatments.** A spelling variant is a
  normalisation problem, a typo is an edit-distance problem, and a query that
  is one word of a longer title is a tokenisation problem. Answering all three
  with one loose similarity score is what turns a search into noise.
"""

from __future__ import annotations

import re
import unicodedata
from difflib import SequenceMatcher

# --------------------------------------------------------------- Arabic rules
#
# These are Lucene's ArabicNormalizer rules, which are the established set and
# are what an Arabic-language index is expected to do. Deliberately *not*
# extended to ؤ→و or ئ→ي: those conflate more aggressively than Lucene does,
# and every variant in the measured evidence is already covered without them.

#: ``ـ`` U+0640. Decorative letter-stretching; carries no meaning at all.
TATWEEL = "ـ"

#: Alef forms, alef maqsura, and teh marbuta.
_ARABIC_FOLD = {
    "آ": "ا",  # آ alef with madda
    "أ": "ا",  # أ alef with hamza above
    "إ": "ا",  # إ alef with hamza below
    "ٱ": "ا",  # ٱ alef wasla
    "ى": "ي",  # ى alef maqsura   -> ي yeh
    "ة": "ه",  # ة teh marbuta    -> ه heh
}

#: Arabic-Indic and extended Arabic-Indic digits, so ٢٠٢٦ matches 2026.
_DIGIT_FOLD = {
    **{chr(0x0660 + i): str(i) for i in range(10)},
    **{chr(0x06F0 + i): str(i) for i in range(10)},
}

_FOLD_TABLE = str.maketrans({**_ARABIC_FOLD, **_DIGIT_FOLD, TATWEEL: None})

#: Apostrophes are **deleted**, not turned into a separator. Splitting on them
#: is what made ``A Dragonslayer's Peerless Regression`` normalise to
#: "dragonslayer s ...", leaving a stray one-letter token that no reader typing
#: "dragonslayers" could ever match.
_APOSTROPHES = str.maketrans({c: None for c in "'’ʼʻ‘`"})

#: Everything else that is not a word character becomes one space. Punctuation
#: is what separates "Berserk", "Berserk:" and "Berserk – GuideBook" for a
#: machine and nothing at all for a reader.
_NON_WORD = re.compile(r"\W+", re.UNICODE)


def fold(text: str) -> str:
    """The canonical form used for *all* comparison.

    Compatibility-decompose, drop combining marks (Arabic harakat and Latin
    accents alike), apply the Arabic letter rules, strip tatweel, fold digits,
    delete apostrophes, casefold, and flatten remaining punctuation to single
    spaces.

    Never use the result for display or for deciding identity.
    """
    if not text:
        return ""
    decomposed = unicodedata.normalize("NFKD", text)
    # Mn is "mark, nonspacing" — harakat, shadda, sukun, and Latin accents.
    stripped = "".join(c for c in decomposed if not unicodedata.combining(c))
    translated = stripped.translate(_APOSTROPHES).translate(_FOLD_TABLE)
    return _NON_WORD.sub(" ", translated.casefold()).strip()


def tokens(text: str) -> list[str]:
    """``fold`` split into words."""
    folded = fold(text)
    return folded.split() if folded else []


# ------------------------------------------------------------- romanisation
#
# A second, looser key for the one class normalisation cannot reach: the same
# name transliterated two ways. Applied only after the strict key has missed,
# because it conflates genuinely different words.

_ROMAN_RULES = (
    (re.compile(r"ou"), "o"),    # kyoujin -> kyojin
    (re.compile(r"uu"), "u"),    # yuuki   -> yuki
    (re.compile(r"oh(?=[^aeiou]|$)"), "o"),
    (re.compile(r"(.)\1"), r"\1"),   # levelling -> leveling, ss -> s
)


def romanise(text: str) -> str:
    """A transliteration-insensitive key. Lossy; matching only."""
    value = fold(text)
    for pattern, replacement in _ROMAN_RULES:
        value = pattern.sub(replacement, value)
    return value


# -------------------------------------------------------------- similarity
#
# Bounded on purpose. `HANDOFF.md` records three sites that answer a query they
# cannot match by returning their whole catalogue; the exact-substring test is
# what turns that back into "nothing found", and a generous similarity score
# would hand it straight back.

#: Below this many characters a token is not fuzzy-matched at all. One edit on
#: a three-letter word reaches most other three-letter words, which is how a
#: typo allowance becomes a catalogue dump.
MIN_FUZZY_LEN = 4

#: Similarity a token pair must reach. Calibrated against the corpus in
#: ``tests/test_textmatch.py`` — measured: berserck/berserk 0.933,
#: levelling/leveling 0.941, and the unrelated pairs that must stay out sit
#: well below this.
FUZZY_RATIO = 0.86

#: A query shorter than this is too ambiguous to fuzzy-match as a whole.
MIN_FUZZY_QUERY = 4


def _similar(a: str, b: str) -> bool:
    """Whether two single tokens are within the allowed distance."""
    if a == b:
        return True
    if len(a) < MIN_FUZZY_LEN or len(b) < MIN_FUZZY_LEN:
        return False
    # A large length gap is a different word, not a typo, and comparing them
    # wastes the ratio's discrimination.
    if abs(len(a) - len(b)) > max(2, min(len(a), len(b)) // 3):
        return False
    return SequenceMatcher(None, a, b).ratio() >= FUZZY_RATIO


def token_subset(query: str, haystack: str) -> bool:
    """Whether every query token appears in ``haystack``, allowing one typo each.

    Token-level rather than whole-string: a short query against a long title
    dilutes to a low whole-string ratio even when it is a perfect prefix, so
    comparing the two strings entire would reject exactly the queries people
    type most.
    """
    wanted = tokens(query)
    if not wanted:
        return False
    available = tokens(haystack)
    if not available:
        return False
    return all(any(_similar(word, other) for other in available) for word in wanted)


def close_enough(query: str, haystack: str) -> bool:
    """Whether ``haystack`` plausibly answers ``query`` despite not matching.

    The last resort, and deliberately the narrowest: the query must be long
    enough to be unambiguous, and every one of its tokens must find a home in
    the candidate. Returns False rather than raising on anything unusable.
    """
    folded_query = fold(query)
    if len(folded_query) < MIN_FUZZY_QUERY:
        return False
    if token_subset(query, haystack):
        return True
    # Transliteration differences survive neither fold() nor a per-token edit
    # bound when they change length, so try the looser key before giving up.
    return romanise(query) == romanise(haystack)
