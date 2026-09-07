"""Adapter contract.

An adapter knows how to turn a series URL into a title, a chapter list, and a
list of page image URLs. Everything downstream — queue, packager, UI — is
site-agnostic and talks only through this interface.
"""

from __future__ import annotations

import json
import re
from abc import ABC, abstractmethod
from urllib.parse import unquote, urljoin, urlparse

from selectolax.parser import HTMLParser

from ..models import Chapter, Page, SearchResult, Series, TextChapter
from .textmatch import close_enough, fold


class AdapterError(RuntimeError):
    """Raised when a page could not be parsed into the expected shape."""


class Adapter(ABC):
    id: str = "base"
    name: str = "Base"
    priority: int = 0
    """Higher wins when several adapters claim the same URL."""
    owns_its_host: bool = False
    """Whether matching the hostname is proof enough to skip fingerprinting.

    Adapters are normally chosen by DOM fingerprint, which is what lets one
    Madara adapter serve sites it has never heard of. A site with its own
    documented API is the exception: nothing else can be at ``mangadex.org``,
    and fetching the page to confirm it costs a browser render for nothing.
    """
    right_to_left: bool | None = None
    """Reading direction for this platform, or ``None`` to use the setting.

    Manga reads right-to-left, Western comics left-to-right, and a single
    global setting cannot be correct for both at once. An adapter that knows
    which kind of material it serves says so here.
    """

    def __init__(self, session_manager) -> None:
        self.sessions = session_manager

    @classmethod
    @abstractmethod
    def matches(cls, url: str, html: str | None = None) -> bool:
        """Whether this adapter can handle ``url``.

        ``html`` is supplied when the caller has already fetched the page, which
        allows fingerprinting by DOM structure rather than by hostname — the
        whole point of supporting a *platform* instead of a hardcoded site.
        """

    @abstractmethod
    async def fetch_series(self, url: str) -> Series:
        ...

    @abstractmethod
    async def fetch_chapters(self, series: Series) -> list[Chapter]:
        ...

    @abstractmethod
    async def fetch_pages(self, chapter: Chapter) -> list[Page]:
        ...

    async def fetch_text(self, chapter: Chapter) -> TextChapter:
        """Return one prose chapter, in reading order.

        Only called for an adapter whose packaging is ``"text"``. It is
        separate from :meth:`fetch_pages` rather than a special value returned
        from it because the two produce genuinely different things: pages are
        URLs the downloader fetches, while prose is already the artifact and
        arrives with the same request that found it. Folding them together
        would mean every image adapter carrying a branch it never takes.
        """
        raise AdapterError(
            f"{self.name} does not serve prose chapters"
        )

    content_type: str | None = None
    """What this adapter serves: ``"manga"``, ``"comics"`` or ``"book"``.

    Search is asked for one kind at a time, so this decides which sites a query
    even reaches. Deliberately ``None`` here rather than a default: an adapter
    that forgets to declare it should be caught by the test that checks every
    registered adapter, not quietly filed under whichever kind was convenient.
    """
    packaging: str = "cbz"
    """What the queue should do with what this adapter yields.

    ``"cbz"`` collects a chapter's pages into an archive. ``"file"`` says the
    adapter yields whole files that are already the finished artifact — a book —
    and the download is written through unchanged. ``"pdf"`` is the third case:
    pages, like a CBZ, but bound into a document — for a site that serves a
    book only through its own page-by-page reader. ``"text"`` is the fourth:
    the site serves marked-up prose rather than pictures of it, so the chapter
    comes from :meth:`fetch_text` and is bound into an EPUB, which is the only
    one of the four formats that keeps reflow and reading direction.
    """

    def packaging_for(self, chapter: Chapter) -> str:
        """:attr:`packaging`, unless one adapter serves more than one shape.

        ``books`` does: most of its sites link a finished PDF or EPUB, while
        Noor exposes a book only as reader pages. Both are the same adapter
        because they share every other behaviour, so the choice cannot be a
        class attribute.
        """
        return self.packaging

    def transform_page(self, content: bytes) -> bytes:
        """Convert a downloaded page into an image, if it did not arrive as one.

        The hook exists for Noor, whose reader serves each page as an SVG
        wrapping a base64 PNG. Everything downstream — validation, the format
        sniff, the archive — wants the image itself, and the alternative was to
        teach all three about a container only one site uses.
        """
        return content
    pages_expire: bool = False
    """Whether page URLs go stale, so a failed download is worth re-listing.

    Most sites serve pages from stable paths, where asking twice returns the
    same dead URL. MangaDex is the exception: its page URLs name one
    MangaDex@Home node and carry a short-lived token, so a node dropping out
    fails pages that a fresh listing downloads without trouble.
    """

    async def refresh_pages(self, chapter: Chapter) -> list[Page]:
        """Re-list a chapter's pages after some of them failed to download.

        Only consulted when :attr:`pages_expire` is set. The default simply
        asks again, which is right for any adapter whose page URLs are minted
        per request rather than cached.
        """
        return await self.fetch_pages(chapter)

    #: Base path this platform serves its own search from, relative to the site
    #: root. ``None`` means the adapter cannot search and is skipped.
    search_path: str | None = None

    async def search(self, site: str, query: str, limit: int = 12) -> list[SearchResult]:
        """Find series matching ``query`` on ``site``.

        Sites are searched through their own search page rather than a
        third-party index: it is always current, needs no API key, and returns
        exactly what that site actually hosts.

        Adapters that cannot search return nothing rather than raising, so one
        unsupported site never breaks a multi-site query.
        """
        return []

    # ------------------------------------------------------------- utilities

    async def get_html(
        self,
        url: str,
        *,
        referer: str | None = None,
        wait_for: str | None = None,
        wait_ms: int = 0,
    ) -> str:
        """Fetch a page, optionally waiting for JS-injected content.

        ``wait_for``/``wait_ms`` are forwarded only when set, so a session
        manager without them (the test fakes) keeps working unchanged.
        """
        if wait_for or wait_ms:
            return await self.sessions.fetch_html(
                url, referer=referer, wait_for=wait_for, wait_ms=wait_ms
            )
        return await self.sessions.fetch_html(url, referer=referer)

    async def get_json(self, url: str, *, referer: str | None = None):
        """Fetch and decode JSON through the browser's own network stack.

        Uses ``fetch_bytes`` rather than ``fetch_html``: an API answers with
        JSON, and rendering it in a tab would hand back that JSON wrapped in
        the browser's document markup. It also matters that the request carries
        the browser's cookies and TLS fingerprint — comix.to's API returns 403
        to anything else.
        """
        body = await self.sessions.get_via_page(url, referer=referer)
        try:
            return json.loads(body)
        except ValueError as exc:
            raise AdapterError(f"{url} did not return JSON: {exc}") from exc

    @staticmethod
    def parse(html: str) -> HTMLParser:
        return HTMLParser(html)

    @staticmethod
    def absolute(base: str, href: str | None) -> str | None:
        if not href:
            return None
        href = href.strip()
        if not href:
            return None
        if href.startswith("//"):
            return f"{urlparse(base).scheme}:{href}"
        return urljoin(base, href)

    @staticmethod
    def text(node, default: str = "") -> str:
        if node is None:
            return default
        return " ".join(node.text(strip=True).split()) or default


# ------------------------------------------------------------------ relevance
# A site's own search decides what to *return*; it does not decide what is worth
# showing first. Measured on "berserk" across the eight configured manga sites:
# 26 hits, of which the real Berserk appeared at positions 1, 7 and 20 because
# results were interleaved by site with no ranking at all, while `Magic Emperor`
# and `The Hero Becomes Duke's Eldest Son` — no shared word with the query —
# occupied slots above two of them.

#: Relevance bands, best first. Numbers rather than an enum because the caller
#: sorts on them and interleaves sites within each band.
SCORE_EXACT = 100
"""The title *is* the query. "Berserk" for `berserk`."""
SCORE_PREFIX = 80
"""The title opens with the query. "Berserk Gaiden", "Berserk of Gluttony"."""
SCORE_WORD = 60
"""The query appears as a whole word further in. "Boushoku no Berserk"."""
SCORE_WORD_PREFIX = 40
"""Only as the start of a longer word. "Berserker", "Berserkness"."""
SCORE_SUBSTRING = 20
"""Buried inside a word. Weak, but the site did think it matched."""
SCORE_FUZZY = 10
"""Matched only after a typo or transliteration allowance.

Below every band that rests on the text actually agreeing, so an approximate
hit can be offered without ever displacing a real one.
"""
SCORE_UNJUDGEABLE = 5
"""Nothing matched, and nothing could have — see :func:`relevance`."""
SCORE_IRRELEVANT = 0
"""Judged and rejected. The caller drops these."""

#: An alternative title is a real match but a weaker signal than the name the
#: site actually displays, so it sorts just below an identical primary hit.
ALT_PENALTY = 5

#: A book *by* the person you named. One flat band, deliberately: it outranks a
#: title merely *starting with* the name (80) — "Kentaro Miura Memorial Manga"
#: is not what you asked for and Berserk is — while still losing to a title that
#: *is* the query (100), the other thing those words could have meant.
#:
#: Flat because the match quality of the name itself carries no information
#: worth ranking on. MangaDex stores Berserk's author as "Miura Kentarou"; the
#: query is "Kentaro Miura". Reordered and transliterated differently, that
#: scores one band lower than an identical string — and grading on it put the
#: right answer below the wrong one. Measured: with a graded score Berserk did
#: not appear at all.
SCORE_AUTHOR = 90

#: The floor for believing an author matched. Word-*prefix* and up, which is
#: what absorbs "Kentaro"/"Kentarou" and any word order, while still excluding
#: SCORE_SUBSTRING — a fragment buried inside a name ("ser" in "Kaiser") is a
#: coincidence. A title keeps its substring band: a title is prose, and the
#: site did think it matched.
MIN_AUTHOR_SCORE = SCORE_WORD_PREFIX

_SCRIPT_RANGES = (
    ("latin", re.compile(r"[a-z]", re.I)),
    ("arabic", re.compile(r"[؀-ۿݐ-ݿﭐ-﷿ﹰ-﻿]")),
    ("cjk", re.compile(r"[぀-ヿ㐀-䶿一-鿿가-힯]")),
    ("cyrillic", re.compile(r"[Ѐ-ӿ]")),
)


def _scripts(text: str) -> frozenset[str]:
    return frozenset(name for name, pattern in _SCRIPT_RANGES if pattern.search(text))


def _normalise(text: str) -> str:
    """The comparison key. See :func:`app.adapters.textmatch.fold`.

    Delegated rather than implemented here because every adapter and the API
    layer must fold identically — and because the previous version, which only
    casefolded and split on punctuation, is what discarded 29 of 30 real
    results for the query ``روايه`` (measured against 8ghrb.com on 2026-09-07:
    every rejected title was a book spelled ``رواية``).
    """
    return fold(text)


def _score(query_norm: str, query_words: list[str], haystack: str) -> int:
    normalised = _normalise(haystack)
    if not normalised:
        return SCORE_IRRELEVANT
    if normalised == query_norm:
        return SCORE_EXACT
    if normalised.startswith(f"{query_norm} "):
        return SCORE_PREFIX
    words = normalised.split()
    if all(word in words for word in query_words):
        return SCORE_WORD
    if all(any(w.startswith(word) for w in words) for word in query_words):
        return SCORE_WORD_PREFIX
    if all(word in normalised for word in query_words):
        return SCORE_SUBSTRING
    # Last, and only once every test resting on the text agreeing has failed:
    # a bounded typo/transliteration allowance. See textmatch.close_enough for
    # why it is deliberately the narrowest rule here.
    if close_enough(query_norm, normalised):
        return SCORE_FUZZY
    return SCORE_IRRELEVANT


def relevance(
    query: str,
    title: str,
    alt_title: str | None = None,
    author: str | None = None,
) -> int:
    """How well a hit answers ``query``. ``SCORE_IRRELEVANT`` means drop it.

    Three things can carry the match, and the caller must pass all it has.
    Scoring only the title is what made an author search impossible: ask for
    "Kentaro Miura" and the one book you want is called *Berserk*, which shares
    no word with the query and would be judged, and dropped, as noise.

    The one case that must not be judged at all: a query and a title in
    different scripts. These sites index names in several writing systems and
    display only one, so an English query legitimately lands on a series shown
    under an Arabic title with nothing in common on the page. Text cannot
    settle that either way — the site matched on a name we are not being shown —
    so such a hit is kept and simply ranked last, while a Latin query against a
    Latin title that shares not one word is judged, and dropped.
    """
    query_norm = _normalise(query)
    query_words = query_norm.split()
    if not query_words:
        return SCORE_UNJUDGEABLE

    best = _score(query_norm, query_words, title)
    if alt_title:
        alt = _score(query_norm, query_words, alt_title)
        if alt:
            best = max(best, alt - ALT_PENALTY)
    if author and _score(query_norm, query_words, author) >= MIN_AUTHOR_SCORE:
        best = max(best, SCORE_AUTHOR)
    if best:
        return best

    if _scripts(query) & _scripts(f"{title} {alt_title or ''} {author or ''}"):
        return SCORE_IRRELEVANT
    return SCORE_UNJUDGEABLE


def query_matches(query: str, *haystacks: str) -> bool:
    """Whether a search hit plausibly answers ``query``.

    Every site here has, at some point, answered a query it could not match by
    returning something that merely *looks* like results: a front-page grid, a
    "latest posts" widget, or the entire catalogue newest-first. All three are
    indistinguishable from real results by structure, and each one turned the
    whole search into noise. Requiring every word of the query to appear in the
    hit's own text costs the fuzzy matches a site would have made anyway, and
    buys back the honest answer of "nothing found".
    """
    words = _normalise(query).split()
    if not words:
        return False
    haystack = _normalise(" ".join(haystacks))
    if all(word in haystack for word in words):
        return True
    # The strict test above is what turns a catalogue dump back into "nothing
    # found", so it stays the primary path. This fallback is bounded tightly
    # enough that the documented noise cases still fail it — there are tests
    # for exactly those, because loosening this is how the noise comes back.
    return close_enough(query, haystack)


def first_attr(node, *names: str) -> str | None:
    """Return the first non-empty attribute among ``names``, whitespace-stripped.

    Madara pads lazy-load attributes with newlines and tabs
    (``data-src="\\n\\t\\thttps://...  "``). Forgetting to strip is the single
    most common reason scrapers of these sites break, so it happens here once,
    centrally, rather than at every call site.
    """
    if node is None:
        return None
    for name in names:
        raw = node.attributes.get(name)
        if not raw:
            continue
        value = raw.strip()
        if name == "srcset":
            value = _widest_from_srcset(value)
        if value:
            return value
    return None


def _widest_from_srcset(srcset: str) -> str:
    """Pick the highest-resolution entry from a ``srcset`` list."""
    best_url, best_width = "", -1.0
    for entry in srcset.split(","):
        parts = entry.strip().split()
        if not parts:
            continue
        url = parts[0].strip()
        width = 0.0
        if len(parts) > 1:
            descriptor = parts[1].strip().lower()
            try:
                width = float(descriptor.rstrip("wx"))
            except ValueError:
                width = 0.0
        if width > best_width:
            best_url, best_width = url, width
    return best_url

# --------------------------------------------------- chapter numbering
# Shared by every adapter: sites label chapters in wildly different ways,
# but the ways they get it wrong are the same everywhere.

_CHAPTER_NUM_RE = re.compile(
    r"(?:chapter|ch\.?|فصل|الفصل)\s*[-_]?\s*(\d+(?:\.\d+)?)", re.I
)
#: Labels are overwhelmingly "<number>" or "<number> - <title>". Anchored at
#: the start so a number inside the title text cannot win over the real one.
_LEADING_NUM_RE = re.compile(r"^\W*(\d+(?:\.\d+)?)")
_TRAILING_NUM_RE = re.compile(r"(\d+(?:\.\d+)?)\s*$")
_SLUG_NUM_RE = re.compile(r"chapter[-_]?(\d+(?:[-_.]\d+)?)", re.I)


def extract_number(title: str, url: str) -> str | None:
    """Recover a chapter number from its label, falling back to the URL slug.

    Order matters. An explicit "Chapter N" wins; then a leading number, which
    is the common Madara label shape; only then a trailing one. Reading from
    the end first misparses any title that ends in a number of its own.
    """
    for pattern in (_CHAPTER_NUM_RE, _LEADING_NUM_RE, _TRAILING_NUM_RE):
        match = pattern.search(title)
        if match:
            return match.group(1)

    # Non-Latin slugs arrive percent-encoded, and that encoding is made of hex
    # digits: "372-الغراب" becomes "372-%d8%a7%d9%84...". Scanning the raw slug
    # therefore reads chapter numbers straight out of the escape sequences.
    # Decode first, or "%b1" at the end silently becomes chapter 1.
    slug = unquote(urlparse(url).path.rstrip("/").rsplit("/", 1)[-1])
    for pattern in (_SLUG_NUM_RE, _LEADING_NUM_RE, _TRAILING_NUM_RE):
        match = pattern.search(slug)
        if match:
            return match.group(1).replace("-", ".").replace("_", ".")
    return None
