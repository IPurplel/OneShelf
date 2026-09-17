"""Global Source Traffic Governor (Master §15, §16.2, INV-26).

Leases are per request. Grant order: priority, then least-served source (fairness), then FIFO.
- HTTP capacity is global; background priorities (read-ahead, Follow, Health) never take the last slot.
- Browser capacity is independent; background browser leases are preempted (their task cancelled)
  when Reader, interactive or direct user work needs the browser.
- Per-source concurrency, minimum request spacing and Retry-After windows apply to every priority.
"""
from __future__ import annotations

import asyncio
import itertools
import time
from dataclasses import dataclass, field
from enum import IntEnum
from typing import Literal

from oneshelf.settings.defaults import DEFAULTS

Kind = Literal["http", "browser"]


class Priority(IntEnum):
    READER = 1
    INTERACTIVE = 2
    MANUAL = 3
    READ_AHEAD = 4
    FOLLOW = 5
    HEALTH = 6


BACKGROUND = Priority.READ_AHEAD  # priorities >= this are background work
DEFAULT_SOURCE_CONCURRENCY = 2


@dataclass
class _SourceState:
    concurrency: int = DEFAULT_SOURCE_CONCURRENCY
    min_interval: float = 0.0
    in_use: int = 0
    served: int = 0
    next_start: float = 0.0
    retry_until: float = 0.0


@dataclass(eq=False)
class Lease:
    source: str
    priority: Priority
    kind: Kind
    task: asyncio.Task | None
    preempted: bool = False
    released: bool = False


@dataclass(eq=False)
class _Waiter:
    seq: int
    source: str
    priority: Priority
    kind: Kind
    future: asyncio.Future
    task: asyncio.Task | None = field(default=None)


class _LeaseContext:
    def __init__(self, governor: TrafficGovernor, source: str, priority: Priority, kind: Kind) -> None:
        self.governor, self.source, self.priority, self.kind = governor, source, Priority(priority), kind
        self.lease: Lease | None = None

    async def __aenter__(self) -> Lease:
        self.lease = await self.governor._wait(self.source, self.priority, self.kind)
        return self.lease

    async def __aexit__(self, *exc) -> None:
        if self.lease is not None:
            self.governor._release(self.lease)


class TrafficGovernor:
    def __init__(
        self,
        *,
        http_capacity: int = DEFAULTS.downloads.http_concurrency,
        browser_capacity: int = DEFAULTS.downloads.browser_concurrency,
        reserved_for_foreground: int = 1,
    ) -> None:
        if http_capacity < 1 or browser_capacity < 1:
            raise ValueError("capacities must be at least 1")
        self.http_capacity = http_capacity
        self.browser_capacity = browser_capacity
        self.reserve = min(reserved_for_foreground, http_capacity - 1)
        self._sources: dict[str, _SourceState] = {}
        self._waiters: list[_Waiter] = []
        self._leases: set[Lease] = set()
        self._http_in_use = 0
        self._browser_in_use = 0
        self._seq = itertools.count()
        self._timer: asyncio.TimerHandle | None = None

    # -- configuration --------------------------------------------------------------------------

    def _source(self, source: str) -> _SourceState:
        return self._sources.setdefault(source, _SourceState())

    def configure_source(self, source: str, *, concurrency: int, requests_per_minute: int | None) -> None:
        state = self._source(source)
        state.concurrency = max(1, concurrency)
        state.min_interval = 60.0 / requests_per_minute if requests_per_minute else 0.0
        self._dispatch()

    def set_retry_after(self, source: str, seconds: float) -> None:
        state = self._source(source)
        state.retry_until = max(state.retry_until, time.monotonic() + max(0.0, seconds))
        self._dispatch()

    def snapshot(self) -> dict:
        return {"http_in_use": self._http_in_use, "browser_in_use": self._browser_in_use, "waiting": len(self._waiters)}

    # -- leasing --------------------------------------------------------------------------------

    def acquire(self, source: str, priority: Priority, *, kind: Kind = "http") -> _LeaseContext:
        if kind not in ("http", "browser"):
            raise ValueError(f"invalid lease kind {kind!r}")
        return _LeaseContext(self, source, priority, kind)

    async def _wait(self, source: str, priority: Priority, kind: Kind) -> Lease:
        loop = asyncio.get_running_loop()
        waiter = _Waiter(next(self._seq), source, priority, kind, loop.create_future(), asyncio.current_task())
        self._waiters.append(waiter)
        self._dispatch()
        try:
            return await waiter.future
        except asyncio.CancelledError:
            if waiter in self._waiters:
                self._waiters.remove(waiter)
            elif waiter.future.done() and not waiter.future.cancelled():
                self._release(waiter.future.result())
            self._dispatch()
            raise

    def _release(self, lease: Lease) -> None:
        if lease.released:
            return
        lease.released = True
        self._leases.discard(lease)
        self._source(lease.source).in_use -= 1
        if lease.kind == "http":
            self._http_in_use -= 1
        else:
            self._browser_in_use -= 1
        self._dispatch()

    def _capacity_ok(self, waiter: _Waiter) -> bool:
        if waiter.kind == "browser":
            return self._browser_in_use < self.browser_capacity
        limit = self.http_capacity - (self.reserve if waiter.priority >= BACKGROUND else 0)
        return self._http_in_use < limit

    def _source_ready_at(self, waiter: _Waiter, now: float) -> float | None:
        """None if blocked by source concurrency; otherwise the time the source allows a start."""
        state = self._source(waiter.source)
        if state.in_use >= state.concurrency:
            return None
        return max(state.next_start, state.retry_until)

    def _dispatch(self) -> None:
        now = time.monotonic()
        earliest: float | None = None
        granted = True
        while granted:
            granted = False
            ordered = sorted(self._waiters, key=lambda w: (w.priority, self._source(w.source).served, w.seq))
            for waiter in ordered:
                if waiter.future.done():
                    self._waiters.remove(waiter)
                    continue
                ready_at = self._source_ready_at(waiter, now)
                if ready_at is None or not self._capacity_ok(waiter):
                    continue
                if ready_at > now:
                    earliest = ready_at if earliest is None else min(earliest, ready_at)
                    continue
                self._grant(waiter, now)
                granted = True
                break
        self._preempt_background_browser(now)
        self._schedule(earliest, now)

    def _grant(self, waiter: _Waiter, now: float) -> None:
        self._waiters.remove(waiter)
        state = self._source(waiter.source)
        state.in_use += 1
        state.served += 1
        state.next_start = now + state.min_interval
        if waiter.kind == "http":
            self._http_in_use += 1
        else:
            self._browser_in_use += 1
        lease = Lease(waiter.source, waiter.priority, waiter.kind, waiter.task)
        self._leases.add(lease)
        waiter.future.set_result(lease)

    def _preempt_background_browser(self, now: float) -> None:
        urgent = [w for w in self._waiters if w.kind == "browser" and w.priority < BACKGROUND
                  and self._source_ready_at(w, now) is not None]
        if not urgent or self._browser_in_use < self.browser_capacity:
            return
        victims = sorted((l for l in self._leases if l.kind == "browser" and l.priority >= BACKGROUND
                          and not l.preempted), key=lambda l: -l.priority)
        for lease in victims[: len(urgent)]:
            lease.preempted = True
            if lease.task is not None and not lease.task.done():
                lease.task.cancel()

    def _schedule(self, earliest: float | None, now: float) -> None:
        if self._timer is not None:
            self._timer.cancel()
            self._timer = None
        if earliest is None or not self._waiters:
            return
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return
        self._timer = loop.call_later(max(0.0, earliest - now), self._dispatch)
