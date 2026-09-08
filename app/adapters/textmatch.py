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
# are what an Arabic-language index is expected to do.
#
# The *table* below deliberately omits ؤ→و and ئ→ي, because Lucene omits them.
# That is not the same as those forms staying distinct, and this comment
# claimed for a long time that they did. They do not: the NFKD pass in `fold`
# decomposes U+0624 to waw + U+0654 and U+0626 to yeh + U+0654, and the
# combining-mark strip that removes harakat removes the hamza with them. So
# they fold together one step earlier than the table, and always have.
# `tests/test_textmatch.py` pins the real behaviour.

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
    # Persian/Urdu forms. These are not Arabic letters, but Arabic titles are
    # routinely *typed* with them — a Persian or Urdu keyboard produces keheh
    # and farsi yeh where an Arabic one produces kaf and yeh, and the two pairs
    # are visually all but identical. A scraped catalogue carries whichever the
    # cataloguer's keyboard emitted, so a reader typing the Arabic form must
    # still reach the record, and vice versa.
    "ک": "ك",  # U+06A9 keheh          -> U+0643 kaf
    "ی": "ي",  # U+06CC farsi yeh      -> U+064A yeh
    "ۀ": "ه",  # U+06C0 heh with yeh   -> U+0647 heh
    "ە": "ه",  # U+06D5 ae             -> U+0647 heh
}

#: Invisible formatting characters, **deleted** rather than separated.
#:
#: These carry no meaning for matching and are not visible to the person who
#: typed them: copying a title out of a browser, a PDF or a right-to-left
#: document routinely drags a bidi mark or a zero-width joiner along with it.
#: Left alone they reach the ``\W+`` rule below and become a **space**, which
#: silently splits one word into two tokens — and ``token_subset`` then looks
#: for both halves. Deleting them is the only treatment that leaves the word
#: the user actually typed.
_INVISIBLE = str.maketrans({c: None for c in (
    "\u200b"  # ZWSP  zero width space
    "\u200c"  # ZWNJ  zero width non-joiner
    "\u200d"  # ZWJ   zero width joiner
    "\ufeff"  # ZWNBSP / BOM
    "\u200e"  # LRM   left-to-right mark
    "\u200f"  # RLM   right-to-left mark
    "\u061c"  # ALM   arabic letter mark
    "\u202a\u202b\u202c\u202d\u202e"  # embedding / override / pop
    "\u2066\u2067\u2068\u2069"          # isolate / pop isolate
)})

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
    # Invisible marks go first: NFKD leaves them intact, and by the time the
    # punctuation rule runs they are indistinguishable from a real separator.
    decomposed = unicodedata.normalize("NFKD", text.translate(_INVISIBLE))
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


# ---------------------------------------------------------- definite article
#
# ``ال`` is Arabic's definite article and it is written joined to its noun, so
# "الغريب" and "غريب" are one word apart for a reader and two unrelated tokens
# for a matcher. Handled here rather than in ``fold`` on purpose: this is a
# *matching* rule, so it reaches only the bounded fallback below and can never
# rewrite a displayed string or decide that two records are the same work.

_ARTICLE = "ال"

#: What has to survive the article for the stripped form to be usable. Two
#: characters is not a word: "الله" would become "له", a different word
#: entirely, and "الف" would become "ف". Three keeps the rule to nouns.
_MIN_STEM = 3


def _article_forms(token: str) -> tuple[str, ...]:
    """``token``, plus its article-stripped stem where one plausibly exists."""
    if token.startswith(_ARTICLE) and len(token) - len(_ARTICLE) >= _MIN_STEM:
        return (token, token[len(_ARTICLE):])
    return (token,)


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
    # Compared with and without the definite article on both sides, so a
    # reader who types it reaches a title that omits it and the other way
    # round. Every other bound -- the length floor, the length gap, the ratio
    # -- still applies to whichever pair is being compared.
    offered = [form for other in available for form in _article_forms(other)]
    return all(any(_similar(form, other) for form in _article_forms(word)
                   for other in offered)
               for word in wanted)


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

# ------------------------------------------------------------ query variants
#
# Everything above rescues a hit the site already returned. It cannot rescue a
# hit the site never returned -- and a site whose own index is unnormalised
# answers "رواية" and "روايه" as two different words. These are the spellings
# worth *sending*, for the one class of site that matches literally.
#
# Deliberately not a cartesian product over every ambiguous letter: that grows
# exponentially and each extra query costs the shared rate limiter and the
# search timeout. One substitution class per variant, applied throughout.

#: Teh marbuta <-> heh and alef maqsura <-> yeh, in *both* directions: which
#: one is the variant depends entirely on how the site spelled its own record.
#:
#: The reverse direction is anchored to the end of a word, because that is the
#: only place teh marbuta and alef maqsura can occur. Substituting every heh
#: in "شهرزاد" would produce a string that is not Arabic at all, and spending
#: one of a handful of query slots on it would cost a real variant its turn.
_SUBSTITUTIONS = (
    ("hamza -> bare alef", re.compile(r"[آأإٱ]"), "ا"),
    ("teh marbuta -> heh", re.compile(r"ة"), "ه"),
    ("alef maqsura -> yeh", re.compile(r"ى"), "ي"),
    ("final heh -> teh marbuta", re.compile(r"ه(?=\s|$)"), "ة"),
    ("final yeh -> alef maqsura", re.compile(r"ي(?=\s|$)"), "ى"),
)


def clean_query(text: str) -> str:
    """What should be *sent* to a site: the query, minus what nobody typed.

    Invisible marks only. Unlike :func:`fold` this preserves case, punctuation
    and every letter, because the string is going to a third-party index that
    may well be case- and letter-exact -- and because it is shown back to the
    user as the query they searched for.
    """
    return " ".join(text.translate(_INVISIBLE).split())


#: Persian/Urdu letters mapped to the Arabic ones an Arabic index will hold.
#: The same pairs `_ARABIC_FOLD` handles, applied to a string being *sent*.
_PERSIAN_TO_ARABIC = str.maketrans({"ک": "ك", "ی": "ي", "ۀ": "ه", "ە": "ه"})


def undecorate(text: str) -> str:
    """``text`` with the marks no index stores: harakat, tatweel, Persian forms.

    Distinct from :func:`fold`, which also collapses ة/ى and casefolds. This
    changes only what is decorative or plainly foreign to an Arabic index, so
    the result is still the word the reader meant and is safe to *send*.

    Measured 2026-09-08 across five Arabic sites: `رِوايَة` (harakat),
    `روايـــة` (tatweel) and `کتاب` (Persian keheh) each returned **0 hits on
    every site**, while their undecorated spellings are ordinary catalogue
    entries. Nobody types tatweel into a search box on purpose -- it arrives by
    copy-paste from a justified heading.
    """
    decomposed = unicodedata.normalize("NFC", text)
    kept = "".join(c for c in decomposed
                   if not unicodedata.combining(c) and c != TATWEEL)
    return kept.translate(_PERSIAN_TO_ARABIC)


def query_variants(query: str, limit: int = 3) -> list[str]:
    """Alternative spellings to try when a literal-matching site found nothing.

    ``query`` itself is always first. The rest are ordered by how often the
    substitution is the one that matters, and capped: this list is multiplied
    by the number of sites in a fan-out that already shares one rate limiter.
    """
    cleaned = clean_query(query)
    out = [cleaned]

    # Decoration first: it is the one change that is almost never wrong, and
    # the letter substitutions below are worth more applied on top of it than
    # to a string still carrying harakat no index has.
    plain = undecorate(cleaned)
    if plain != cleaned:
        out.append(plain)

    for _name, pattern, replacement in _SUBSTITUTIONS:
        variant = pattern.sub(replacement, plain)
        if variant not in out:
            out.append(variant)
        if len(out) > limit:
            break
    return out[:limit + 1]
