"""Adapter selection.

Picks the adapter for a URL, preferring DOM fingerprinting over hostname
matching. Fetching the page once here means a site that merely *looks* like
Madara by URL but is not gets correctly routed to the generic adapter.
"""

from __future__ import annotations

import logging

from .base import Adapter
from .ao3 import AO3Adapter
from .blogger import BloggerAdapter
from .books import BooksAdapter
from .gutenberg import GutenbergAdapter
from .comix import ComixAdapter
from .generic import GenericAdapter
from .madara import MadaraAdapter
from .mangadex import MangaDexAdapter
from .mangathemesia import MangaThemesiaAdapter
from .royalroad import RoyalRoadAdapter
from .scribblehub import ScribbleHubAdapter
from .sunovels import SunovelsAdapter
from .vcomics import VComicsAdapter
from .webtoons import WebtoonsAdapter

log = logging.getLogger(__name__)

#: Ordered by how specific each fingerprint is, not by preference. TS carries
#: class names Madara never uses, so it is checked first; the generic
#: heuristic is always last.
#: The kinds of thing this app downloads. Search is asked for exactly one of
#: them, and every adapter declares which it serves.
CONTENT_TYPES = frozenset({"manga", "comics", "book"})

ADAPTERS: list[type[Adapter]] = [
    MangaDexAdapter,
    AO3Adapter,
    RoyalRoadAdapter,
    ScribbleHubAdapter,
    SunovelsAdapter,
    WebtoonsAdapter,
    GutenbergAdapter,
    VComicsAdapter,
    MangaThemesiaAdapter,
    MadaraAdapter,
    ComixAdapter,
    BloggerAdapter,
    # Below every comic adapter: a manga page that happens to link a PDF must
    # be read as manga, and only what nothing else claims can be a book.
    BooksAdapter,
    GenericAdapter,
]


def by_id(adapter_id: str) -> type[Adapter] | None:
    for adapter in ADAPTERS:
        if adapter.id == adapter_id:
            return adapter
    return None


def select(url: str, html: str | None = None) -> type[Adapter]:
    """Return the best adapter class for ``url``."""
    ranked = sorted(ADAPTERS, key=lambda a: a.priority, reverse=True)
    for adapter in ranked:
        try:
            if adapter.matches(url, html):
                return adapter
        except Exception:  # pragma: no cover - a broken matcher must not block
            log.debug("Adapter %s raised during matches()", adapter.id, exc_info=True)
    return GenericAdapter


async def resolve(url: str, session_manager) -> Adapter:
    """Instantiate the right adapter, fingerprinting the live page first.

    Falls back to URL-only matching if the page cannot be fetched, so the caller
    still gets a usable adapter and a meaningful error later.
    """
    # A few adapters own their hostname outright, and for those the fetch is
    # pure cost: MangaDex is an API client that needs no browser at all, yet
    # fingerprinting made every job render its JavaScript site first — and fail
    # with it if the browser could not start.
    certain = select(url)
    if certain.owns_its_host:
        log.info("Using adapter %s for %s (by host)", certain.id, url)
        return certain(session_manager)

    html: str | None = None
    try:
        html = await session_manager.fetch_html(url)
    except Exception:
        log.debug("Could not pre-fetch %s for fingerprinting", url, exc_info=True)

    adapter_cls = select(url, html)
    log.info("Using adapter %s for %s", adapter_cls.id, url)

    adapter = adapter_cls(session_manager)
    if html is not None:
        # Hand over the page we already fetched so the adapter need not repeat it.
        adapter._last_html = (url, html)
    return adapter


def describe() -> list[dict]:
    return [
        {"id": a.id, "name": a.name, "priority": a.priority,
         "content_type": a.content_type}
        for a in sorted(ADAPTERS, key=lambda a: a.priority, reverse=True)
    ]
