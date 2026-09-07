"""A short-lived cache for what each source answered.

Deliberately caches **per source**, not per whole search, and stores the
*candidates* a site returned rather than the finished result list. Matching and
ranking then run fresh on every request. Two things fall out of that:

* a cached response stays usable when the ranking rules change, and
* related queries against the same site reuse one fetch.

**What is never cached.** A timeout, a transport error or a parse failure is
not an answer — it is the absence of one. Storing "this site had nothing" for
two minutes because it was briefly slow would turn one bad moment into a
sustained lie, and the site would never be retried inside that window. Only a
site that actually answered is remembered, and an empty answer from a site that
genuinely responded is a real result worth keeping.

Nothing here is persisted: a restart starts cold, which is the right default
for a cache whose whole purpose is to be a little bit ahead of the sites.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections import OrderedDict
from typing import Any, Awaitable, Callable, Hashable

log = logging.getLogger(__name__)

#: How long an answer stays fresh. Long enough to cover a burst of debounced
#: keystrokes and a user changing their mind and coming back; short enough that
#: a newly published chapter shows up on the next search rather than the next
#: restart.
DEFAULT_TTL = 120.0

#: Entries kept before the oldest is evicted. Each holds a handful of search
#: hits, so this is kilobytes, not megabytes.
DEFAULT_MAX_ENTRIES = 256

#: Outcomes worth remembering. Everything else describes a failure to answer.
CACHEABLE = frozenset({"ok", "empty"})


class SourceCache:
    """TTL + LRU cache with single-flight de-duplication.

    Bounded on both axes on purpose: a cache with no size limit is a memory
    leak with good intentions, and one with no expiry is a stale-data bug.
    """

    def __init__(
        self,
        ttl: float = DEFAULT_TTL,
        max_entries: int = DEFAULT_MAX_ENTRIES,
    ) -> None:
        self.ttl = ttl
        self.max_entries = max_entries
        self._entries: OrderedDict[Hashable, tuple[float, Any]] = OrderedDict()
        self._inflight: dict[Hashable, asyncio.Future] = {}
        self.hits = 0
        self.misses = 0
        self.coalesced = 0

    # ------------------------------------------------------------- internals

    def _live(self, key: Hashable) -> tuple[bool, Any]:
        entry = self._entries.get(key)
        if entry is None:
            return False, None
        stored_at, value = entry
        if (time.monotonic() - stored_at) > self.ttl:
            # Expired. Drop it now rather than leaving it to the size bound.
            self._entries.pop(key, None)
            return False, None
        self._entries.move_to_end(key)
        return True, value

    def _store(self, key: Hashable, value: Any) -> None:
        self._entries[key] = (time.monotonic(), value)
        self._entries.move_to_end(key)
        while len(self._entries) > self.max_entries:
            self._entries.popitem(last=False)   # evict least recently used

    # ---------------------------------------------------------------- public

    def peek(self, key: Hashable) -> tuple[bool, Any]:
        """Whether ``key`` is cached and live, without recording a hit."""
        return self._live(key)

    def invalidate(self, key: Hashable | None = None) -> None:
        if key is None:
            self._entries.clear()
        else:
            self._entries.pop(key, None)

    async def get_or_fetch(
        self,
        key: Hashable,
        produce: Callable[[], Awaitable[tuple[Any, str]]],
        *,
        refresh: bool = False,
    ) -> tuple[Any, str, bool]:
        """Return ``(value, status, from_cache)`` for ``key``.

        ``produce`` must return ``(value, status)``; only a status in
        :data:`CACHEABLE` is stored. ``refresh`` bypasses the lookup but still
        repopulates, which is what a "search again" control needs.

        Identical concurrent calls are coalesced onto one execution — a
        debounced input can fire several searches that overlap, and without
        this each one fans out to every site independently.
        """
        if not refresh:
            fresh, value = self._live(key)
            if fresh:
                self.hits += 1
                return value, "ok" if value else "empty", True

        running = self._inflight.get(key)
        if running is not None and not refresh:
            self.coalesced += 1
            value, status = await asyncio.shield(running)
            return value, status, False

        self.misses += 1
        loop = asyncio.get_running_loop()
        future: asyncio.Future = loop.create_future()
        self._inflight[key] = future
        try:
            value, status = await produce()
        except BaseException as exc:
            if not future.done():
                future.set_exception(exc)
                # Mark it retrieved. A coalesced waiter may never arrive, and
                # an unretrieved exception on a discarded future is logged by
                # asyncio at ERROR level, which buries real failures in noise.
                future.exception()
            raise
        else:
            if not future.done():
                future.set_result((value, status))
            if status in CACHEABLE:
                self._store(key, value)
            else:
                # A failure is the absence of an answer, not an answer. Leaving
                # it uncached is what keeps the site retryable immediately.
                log.debug("Not caching %s outcome for %r", status, key)
            return value, status, False
        finally:
            self._inflight.pop(key, None)

    def stats(self) -> dict[str, int | float]:
        return {
            "entries": len(self._entries),
            "hits": self.hits,
            "misses": self.misses,
            "coalesced": self.coalesced,
            "ttl": self.ttl,
            "max_entries": self.max_entries,
        }
