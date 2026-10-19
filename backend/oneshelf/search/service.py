"""Local-first search with progressive live enrichment (Master §6.1, §7; INV-27).

Local results are shown immediately and are never cleared while live sources are still working. Each
source reports its own state (pending, cached, done, failed with a category) and can be retried on its
own. Nothing about the query is written to the library database.
"""
from __future__ import annotations

import asyncio
import json
import sqlite3
import time
from collections.abc import AsyncIterator, Callable
from dataclasses import asdict, dataclass, field, replace
from typing import Any, Protocol

from oneshelf.plugins.classification import classify_listing, defaults_for
from oneshelf.net.governor import Priority
from oneshelf.plugins.results import ListResult
from oneshelf.plugins.labels import language_code
from oneshelf.plugins.runtime import AuthRequired, CapabilityError, RateLimited
from oneshelf.search.cache import DiscoveryCache
from oneshelf.search.grouping import LiveListing, ResultWork, group_results
from oneshelf.search.index import FTS_CANDIDATE_LIMIT, LIKE_CANDIDATE_LIMIT, search_local
from oneshelf.search.normalize import search_keys
from oneshelf.search.presentation import work_cover

SEARCH_KIND = "search"
# Local search policy deliberately follows the user's clear mappings. Categories absent here
# (Manuscripts, Newspapers, Digital library) leave local works unfiltered. Reports maps to
# paper for local search even though a Reports adapter may default to book content.
CATEGORY_CONTENT_TYPES = {
    "Manga": frozenset({"manga"}),
    "Comics": frozenset({"comic", "manhwa", "manhua"}),
    "Webtoons": frozenset({"comic", "manhwa", "manhua"}),
    "Books": frozenset({"book", "novel"}),
    "Children's books": frozenset({"book", "novel"}),
    "Academic books": frozenset({"book", "novel"}),
    "Textbooks": frozenset({"book", "novel"}),
    "Poetry": frozenset({"book", "novel"}),
    "Religious texts": frozenset({"book", "novel"}),
    "Journal": frozenset({"paper"}),
    "Papers": frozenset({"paper"}),
    "Reports": frozenset({"paper"}),
}


class Sources(Protocol):
    def searchable_sources(self) -> list[tuple[str, str]]: ...

    async def run(self, plugin_id: str, capability: str, inputs: dict, *, priority: Priority) -> Any: ...


@dataclass
class SearchUpdate:
    stage: str  # local | partial | complete
    results: list[ResultWork]
    source_status: dict[str, dict]
    sources_total: int
    sources_available: int = 0

    @property
    def sources_done(self) -> int:
        return sum(1 for s in self.source_status.values() if s["state"] in ("done", "cached"))

    @property
    def sources_failed(self) -> int:
        return sum(1 for s in self.source_status.values() if s["state"] == "failed")


@dataclass
class _QueryState:
    last_used: float = 0
    listings: dict[tuple[str, str], LiveListing] = field(default_factory=dict)
    status: dict[str, dict] = field(default_factory=dict)
    versions: dict[str, str] = field(default_factory=dict)
    sources_available: int = 0


def _to_live(source_id: str, entry) -> LiveListing:
    return LiveListing(source_id=source_id, listing_key=entry.listing_key, title=entry.title, url=entry.url,
                       content_type=entry.content_type, language=entry.language, cover_url=entry.cover_url,
                       creator=entry.creator, original_title=entry.original_title,
                       available_languages=getattr(entry, "available_languages", None))


class SearchService:
    def __init__(self, conn: sqlite3.Connection, sources: Sources, cache: DiscoveryCache, *, limit: int = 50,
                 max_states: int = 128, state_ttl_seconds: float = 1800,
                 clock: Callable[[], float] = time.monotonic) -> None:
        self.conn = conn
        self.sources = sources
        self.cache = cache
        self.limit = limit
        self.max_states = max(1, max_states)
        self.state_ttl_seconds = state_ttl_seconds
        self.clock = clock
        self._states: dict[str, _QueryState] = {}

    def _prune_states(self) -> None:
        cutoff = self.clock() - self.state_ttl_seconds
        for key, state in list(self._states.items()):
            if state.last_used <= cutoff:
                del self._states[key]
        while len(self._states) > self.max_states:
            oldest = min(self._states, key=lambda key: self._states[key].last_used)
            del self._states[oldest]

    def _remember(self, key: str, state: _QueryState) -> None:
        state.last_used = self.clock()
        self._states[key] = state
        self._prune_states()

    # -- result assembly ---------------------------------------------------------------------------

    @staticmethod
    def _state_key(query: str, categories: frozenset[str], languages: frozenset[str]) -> str:
        normalized = search_keys(query).normalized
        if not categories and not languages:
            return normalized
        return json.dumps([normalized, sorted(categories), sorted(languages)], ensure_ascii=False)

    def _source_metadata(self, source_id: str) -> tuple[str | None, tuple[str, ...]]:
        plugins = getattr(self.sources, "plugins", None)
        if plugins is None:
            return None, ()
        try:
            record = plugins.get(source_id)
            if hasattr(record, "category") and hasattr(record, "languages"):
                return record.category, tuple(record.languages or ())
            from oneshelf.plugins.labels import metadata_from_manifest
            return metadata_from_manifest(plugins.load_active(source_id).manifest)
        except Exception:
            return None, ()

    def _scoped_sources(self, categories: frozenset[str], languages: frozenset[str],
                        sources: list[tuple[str, str]]) -> list[tuple[str, str]]:
        if not categories and not languages:
            return sources
        selected = []
        for source_id, version in sources:
            category, source_languages = self._source_metadata(source_id)
            if categories and category not in categories:
                continue
            source_codes = {language_code(language) for language in source_languages}
            if languages and "MULTI" not in source_codes and not languages.intersection(source_codes):
                continue
            selected.append((source_id, version))
        return selected

    def _local_results(self, query: str, categories: frozenset[str] = frozenset(),
                       languages: frozenset[str] = frozenset()) -> list[ResultWork]:
        content_types = set().union(*(CATEGORY_CONTENT_TYPES[c] for c in categories if c in CATEGORY_CONTENT_TYPES))
        filter_type = bool(categories) and all(c in CATEGORY_CONTENT_TYPES for c in categories)
        results = []
        candidate_limit = FTS_CANDIDATE_LIMIT + LIKE_CANDIDATE_LIMIT if categories or languages else self.limit
        for local in search_local(self.conn, query, limit=candidate_limit):
            if filter_type and local.candidate.content_type not in content_types:
                continue
            if languages and not any(
                language_code(track[0]) in languages
                for track in self.conn.execute("SELECT language FROM source_tracks WHERE work_id = ?", (local.work_id,))
            ):
                continue
            results.append(ResultWork(work_id=local.work_id, title=local.title,
                                      content_type=local.candidate.content_type,
                                      soft=False, cover_url=work_cover(self.conn, local.work_id)))
            if len(results) >= self.limit:
                break
        return results

    def _combine(self, query: str, state: _QueryState, categories: frozenset[str],
                 languages: frozenset[str]) -> list[ResultWork]:
        listings = []
        for listing in state.listings.values():
            if not languages:
                listings.append(listing)
                continue
            if listing.available_languages is not None:
                available = [language for language in listing.available_languages
                             if language_code(language) in languages]
                if available:
                    listings.append(replace(listing, available_languages=available))
            elif language_code(listing.language or "") in languages:
                listings.append(listing)
        live_groups = group_results(self.conn, listings)
        by_work = {g.work_id: g for g in live_groups if g.work_id}
        combined: list[ResultWork] = []
        used: set[int] = set()
        for local in self._local_results(query, categories, languages):
            group = by_work.get(local.work_id)
            if group is not None:
                combined.append(group)
                used.add(id(group))
            else:
                combined.append(local)
        for group in live_groups:
            if id(group) not in used:
                combined.append(group)
        return combined[: self.limit]

    def _update(self, stage: str, query: str, state: _QueryState, total: int,
                categories: frozenset[str], languages: frozenset[str]) -> SearchUpdate:
        return SearchUpdate(stage, self._combine(query, state, categories, languages), dict(state.status),
                            total, state.sources_available)

    # -- source execution --------------------------------------------------------------------------

    def _cached(self, source_id: str, version: str, key: str) -> list[LiveListing] | None:
        payload = self.cache.get(source_id, version, SEARCH_KIND, key)
        return None if payload is None else [LiveListing(**item) for item in payload["listings"]]

    async def _run_source(self, state: _QueryState, source_id: str, version: str, query: str, key: str,
                          refresh: bool) -> None:
        if not refresh:
            cached = self._cached(source_id, version, key)
            if cached is not None:
                for entry in cached:
                    state.listings[(entry.source_id, entry.listing_key)] = entry
                state.status[source_id] = {"state": "cached"}
                return
        try:
            result: ListResult = await self.sources.run(source_id, "search", {"query": query},
                                                        priority=Priority.INTERACTIVE)
        except RateLimited as exc:
            state.status[source_id] = {"state": "failed", "category": "rate_limit", "retry_after": exc.retry_after}
            return
        except AuthRequired:
            state.status[source_id] = {"state": "failed", "category": "auth_failure"}
            return
        except CapabilityError as exc:
            state.status[source_id] = {"state": "failed", "category": exc.category}
            return
        except Exception as exc:  # transport or unexpected plugin failure must not clear other results
            state.status[source_id] = {"state": "failed", "category": "transport", "detail": type(exc).__name__}
            return
        defaults = defaults_for(getattr(self.sources, "plugins", None), source_id)
        entries = [classify_listing(_to_live(source_id, entry), defaults) for entry in result.entries]
        for entry in entries:
            state.listings[(entry.source_id, entry.listing_key)] = entry
        self.cache.put(source_id, version, SEARCH_KIND, key, {"listings": [asdict(e) for e in entries]})
        state.status[source_id] = {"state": "done", "complete": result.complete}

    # -- public API --------------------------------------------------------------------------------

    async def search(self, query: str, *, refresh: bool = False, limit: int | None = None,
                     categories: set[str] | None = None, languages: set[str] | None = None) -> AsyncIterator[SearchUpdate]:
        if limit:
            self.limit = limit
        category_scope = frozenset(categories or ())
        language_scope = frozenset(language_code(language) for language in (languages or ()))
        key = self._state_key(query, category_scope, language_scope)
        cache_key = search_keys(query).normalized
        all_sources = self.sources.searchable_sources()
        sources = self._scoped_sources(category_scope, language_scope, all_sources)
        state = _QueryState(versions=dict(sources), status={source_id: {"state": "pending"} for source_id, _ in sources},
                            sources_available=len(all_sources))
        self._remember(key, state)
        total = len(sources)
        yield SearchUpdate("local", self._local_results(query, category_scope, language_scope),
                           dict(state.status), total, state.sources_available)
        if not sources:
            yield self._update("complete", query, state, total, category_scope, language_scope)
            return
        pending = {asyncio.create_task(self._run_source(state, source_id, version, query, cache_key, refresh))
                   for source_id, version in sources}
        tasks = set(pending)
        try:
            while pending:
                done, pending = await asyncio.wait(pending, return_when=asyncio.FIRST_COMPLETED)
                for task in done:
                    task.result()
                state.last_used = self.clock()
                yield self._update("partial" if pending else "complete", query, state, total,
                                   category_scope, language_scope)
        finally:
            # Closing an SSE response owns cancellation of every source it launched.
            for task in tasks:
                if not task.done():
                    task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)

    async def retry_source(self, query: str, source_id: str, *, categories: set[str] | None = None,
                           languages: set[str] | None = None) -> AsyncIterator[SearchUpdate]:
        category_scope = frozenset(categories or ())
        language_scope = frozenset(language_code(language) for language in (languages or ()))
        key = self._state_key(query, category_scope, language_scope)
        cache_key = search_keys(query).normalized
        self._prune_states()
        state = self._states.get(key, _QueryState())
        self._remember(key, state)
        all_sources = self.sources.searchable_sources()
        state.sources_available = len(all_sources)
        sources = dict(self._scoped_sources(category_scope, language_scope, all_sources))
        if source_id not in sources:
            yield self._update("complete", query, state, len(state.status), category_scope, language_scope)
            return
        version = state.versions.get(source_id) or sources[source_id]
        state.status[source_id] = {"state": "pending"}
        yield self._update("partial", query, state, len(state.status), category_scope, language_scope)
        await self._run_source(state, source_id, version, query, cache_key, refresh=True)
        yield self._update("complete", query, state, len(state.status), category_scope, language_scope)
