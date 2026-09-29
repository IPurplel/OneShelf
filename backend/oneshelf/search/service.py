"""Local-first search with progressive live enrichment (Master §6.1, §7; INV-27).

Local results are shown immediately and are never cleared while live sources are still working. Each
source reports its own state (pending, cached, done, failed with a category) and can be retried on its
own. Nothing about the query is written to the library database.
"""
from __future__ import annotations

import asyncio
import sqlite3
import time
from collections.abc import AsyncIterator, Callable
from dataclasses import asdict, dataclass, field
from typing import Any, Protocol

from oneshelf.net.governor import Priority
from oneshelf.plugins.results import ListResult
from oneshelf.plugins.runtime import AuthRequired, CapabilityError, RateLimited
from oneshelf.search.cache import DiscoveryCache
from oneshelf.search.grouping import LiveListing, ResultWork, group_results
from oneshelf.search.index import search_local
from oneshelf.search.normalize import search_keys

SEARCH_KIND = "search"


class Sources(Protocol):
    def searchable_sources(self) -> list[tuple[str, str]]: ...

    async def run(self, plugin_id: str, capability: str, inputs: dict, *, priority: Priority) -> Any: ...


@dataclass
class SearchUpdate:
    stage: str  # local | partial | complete
    results: list[ResultWork]
    source_status: dict[str, dict]
    sources_total: int

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

    def _local_results(self, query: str) -> list[ResultWork]:
        return [ResultWork(work_id=local.work_id, title=local.title, content_type=local.candidate.content_type, soft=False)
                for local in search_local(self.conn, query, limit=self.limit)]

    def _combine(self, query: str, state: _QueryState) -> list[ResultWork]:
        live_groups = group_results(self.conn, list(state.listings.values()))
        by_work = {g.work_id: g for g in live_groups if g.work_id}
        combined: list[ResultWork] = []
        used: set[int] = set()
        for local in self._local_results(query):
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

    def _update(self, stage: str, query: str, state: _QueryState, total: int) -> SearchUpdate:
        return SearchUpdate(stage, self._combine(query, state), dict(state.status), total)

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
        entries = [_to_live(source_id, entry) for entry in result.entries]
        for entry in entries:
            state.listings[(entry.source_id, entry.listing_key)] = entry
        self.cache.put(source_id, version, SEARCH_KIND, key, {"listings": [asdict(e) for e in entries]})
        state.status[source_id] = {"state": "done", "complete": result.complete}

    # -- public API --------------------------------------------------------------------------------

    async def search(self, query: str, *, refresh: bool = False, limit: int | None = None) -> AsyncIterator[SearchUpdate]:
        if limit:
            self.limit = limit
        key = search_keys(query).normalized
        sources = self.sources.searchable_sources()
        state = _QueryState(versions=dict(sources), status={source_id: {"state": "pending"} for source_id, _ in sources})
        self._remember(key, state)
        total = len(sources)
        yield SearchUpdate("local", self._local_results(query), dict(state.status), total)
        if not sources:
            yield self._update("complete", query, state, total)
            return
        pending = {asyncio.create_task(self._run_source(state, source_id, version, query, key, refresh))
                   for source_id, version in sources}
        tasks = set(pending)
        try:
            while pending:
                done, pending = await asyncio.wait(pending, return_when=asyncio.FIRST_COMPLETED)
                for task in done:
                    task.result()
                state.last_used = self.clock()
                yield self._update("partial" if pending else "complete", query, state, total)
        finally:
            # Closing an SSE response owns cancellation of every source it launched.
            for task in tasks:
                if not task.done():
                    task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)

    async def retry_source(self, query: str, source_id: str) -> AsyncIterator[SearchUpdate]:
        key = search_keys(query).normalized
        self._prune_states()
        state = self._states.get(key, _QueryState())
        self._remember(key, state)
        version = state.versions.get(source_id) or dict(self.sources.searchable_sources()).get(source_id, "unknown")
        state.status[source_id] = {"state": "pending"}
        yield self._update("partial", query, state, len(state.status))
        await self._run_source(state, source_id, version, query, key, refresh=True)
        yield self._update("complete", query, state, len(state.status))
