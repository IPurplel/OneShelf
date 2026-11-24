"""Global Source Traffic Governor (Master §15, §16.2, INV-26).

Leases are per request. Grant order: priority, then least-served source (fairness), then FIFO.
- HTTP capacity is global; background priorities (read-ahead, Follow, Health) never take the reserved
  foreground slots, and the Reader has slots of its own that interactive and manual work never take.
- Browser capacity is independent; background browser leases are preempted (their task cancelled)
  when Reader, interactive or direct user work needs the browser.
- Per-source concurrency, minimum request spacing and Retry-After windows apply to every priority.
- The declared rate is a token bucket. By default its size is one: a full spacing before every request, which
  some sites require. A package may declare a small `burst` (plugin API 1.4): that many starts may follow one
  another (never faster than the host ceiling below) before the spacing applies, and tokens come back one per
  spacing, so the long-run rate is the declared one. Background work leaves the last token for the person.
- A source may declare a separate budget for its resources (images and files on its CDN, plugin API 1.4).
  Without one, resources share the source's own budget exactly as before.

Protecting the person's address from a source's anti-abuse systems (a ban is worse than a slow page):
- Every host a source is reached on has its own state. A 429 or 503 halves that host's rate (the spacing
  between starts doubles), and successes win it back a little at a time (AIMD).
- Repeated failures open a circuit for that host: nothing is sent to it until a cooling-off period ends,
  and the period doubles each time the circuit opens again.
- While a host is under pressure, read-ahead work for it (covers, page prefetch) is shed at once instead of
  queued, so what the person is actually looking at goes first and the host gets fewer requests.
- Spacing carries a small random jitter, and no host is ever asked more often than a fixed Core ceiling,
  whatever a package declares.
- Everything is counted per source and host, so a change that sends more traffic is visible (snapshot()).
"""
from __future__ import annotations

import asyncio
import itertools
import random
import time
from collections import deque
from dataclasses import dataclass, field
from enum import IntEnum
from typing import Callable, Literal
from weakref import WeakKeyDictionary

from oneshelf.settings.defaults import DEFAULTS

Kind = Literal["http", "browser"]
Lane = Literal["page", "resource"]
Outcome = Literal["ok", "not_found", "client_error", "throttled", "refused", "server_error", "transport_error"]


class Priority(IntEnum):
    READER = 1
    INTERACTIVE = 2
    MANUAL = 3
    READ_AHEAD = 4
    FOLLOW = 5
    HEALTH = 6


BACKGROUND = Priority.READ_AHEAD  # priorities >= this are background work
DEFAULT_SOURCE_CONCURRENCY = 2
MAX_BURST = 4                    # the most a package may declare (plugins.schema.RateLimit.burst)

# Ban protection (see module docstring). Deliberately conservative; none of these can be raised by a package.
HOST_MIN_INTERVAL = 0.1          # Core ceiling: at most 10 request starts per second to any one host
JITTER_FRACTION = 0.15           # up to +15 % on a spacing, never less than the declared spacing
PENALTY_MAX = 32.0               # a throttled host is slowed to at most 1/32 of its declared rate
PENALTY_BASE_INTERVAL = 0.25     # spacing used under penalty when the source declared none
PENALTY_RECOVERY = 0.85          # each success removes 15 % of the remaining penalty
SHED_FACTOR = 4.0                # from this penalty on, read-ahead work for the host is shed
BREAKER_THRESHOLD = 5            # consecutive failures that open a host's circuit
BREAKER_COOLDOWN = 30.0          # first cooling-off period, doubled on each reopening
BREAKER_COOLDOWN_MAX = 600.0
STATS_WINDOW = 60.0


class TrafficShed(RuntimeError):
    """Read-ahead work refused because its host is under pressure; try again after `retry_after` seconds."""

    def __init__(self, source: str, host: str, retry_after: float) -> None:
        super().__init__(f"{source} ({host}) is under pressure; read-ahead deferred")
        self.source, self.host, self.retry_after = source, host, retry_after


@dataclass
class _LaneState:
    concurrency: int = DEFAULT_SOURCE_CONCURRENCY
    min_interval: float = 0.0
    in_use: int = 0
    last_start: float = float("-inf")
    jitter: float = 0.0
    # The lane's token bucket. With burst 1 (the default) it is exactly "last start + one spacing".
    burst: int = 1
    tokens: float = 1.0
    refilled_at: float = field(default_factory=time.monotonic)

    def refill(self, now: float, interval: float, capacity: float) -> None:
        if interval > 0 and now > self.refilled_at:
            self.tokens = min(capacity, self.tokens + (now - self.refilled_at) / interval)
        self.tokens = min(self.tokens, capacity)
        self.refilled_at = now

    def set_limits(self, min_interval: float, burst: int, now: float) -> None:
        """Called before every request with what the package declares: it changes the limits, never the
        tokens the lane has already earned or spent."""
        if min_interval != self.min_interval or burst != self.burst:
            self.refill(now, self.min_interval, float(self.burst))
            fresh = self.last_start == float("-inf")
            self.min_interval, self.burst = min_interval, burst
            self.tokens = float(burst) if fresh else min(self.tokens, float(burst))
            self.refilled_at = now


@dataclass
class _SourceState:
    page: _LaneState = field(default_factory=_LaneState)
    resource: _LaneState | None = None       # None: resources share the page lane
    served: int = 0
    retry_until: float = 0.0

    def lane(self, lane: Lane) -> _LaneState:
        return self.resource if lane == "resource" and self.resource is not None else self.page

    @property
    def in_use(self) -> int:                  # kept for callers and tests that read it
        return self.page.in_use + (self.resource.in_use if self.resource is not None else 0)


@dataclass
class _HostStats:
    requests: int = 0
    outcomes: dict = field(default_factory=dict)
    wait_seconds: float = 0.0
    max_wait_seconds: float = 0.0
    shed: int = 0
    recent: deque = field(default_factory=deque)


@dataclass
class _HostState:
    penalty: float = 1.0
    failures: int = 0
    open_until: float = 0.0
    cooldown: float = BREAKER_COOLDOWN
    last_start: float = float("-inf")
    stats: _HostStats = field(default_factory=_HostStats)


@dataclass(eq=False)
class Lease:
    source: str
    priority: Priority
    kind: Kind
    task: asyncio.Task | None
    preempted: bool = False
    released: bool = False
    host: str = "*"
    lane: Lane = "page"


@dataclass(eq=False)
class _Waiter:
    seq: int
    source: str
    priority: Priority
    kind: Kind
    future: asyncio.Future
    task: asyncio.Task | None = field(default=None)
    host: str = "*"
    lane: Lane = "page"


class _LeaseContext:
    def __init__(self, governor: TrafficGovernor, source: str, priority: Priority, kind: Kind,
                 host: str, lane: Lane) -> None:
        self.governor, self.source, self.priority, self.kind = governor, source, Priority(priority), kind
        self.host, self.lane = host, lane
        self.lease: Lease | None = None

    async def __aenter__(self) -> Lease:
        started = time.monotonic()
        self.lease = await self.governor._wait(self.source, self.priority, self.kind, self.host, self.lane)
        self.governor._record_wait(self.source, self.host, time.monotonic() - started)
        return self.lease

    async def __aexit__(self, *exc) -> None:
        if self.lease is not None:
            self.governor._release(self.lease)


class TrafficGovernor:
    def __init__(
        self,
        *,
        http_capacity: int = DEFAULTS.traffic.http_capacity,
        browser_capacity: int = DEFAULTS.downloads.browser_concurrency,
        reserved_for_foreground: int = 1,
        reserved_for_reader: int = 0,
        rng: Callable[[], float] | None = None,
    ) -> None:
        if http_capacity < 1 or browser_capacity < 1:
            raise ValueError("capacities must be at least 1")
        self.http_capacity = http_capacity
        self.browser_capacity = browser_capacity
        self.reserve = min(reserved_for_foreground, http_capacity - 1)
        self.reader_reserve = min(reserved_for_reader, max(0, http_capacity - 1 - self.reserve))
        self._sources: dict[str, _SourceState] = {}
        self._hosts: dict[tuple[str, str], _HostState] = {}
        self._waiters: list[_Waiter] = []
        self._leases: set[Lease] = set()
        self._http_in_use = 0
        self._browser_in_use = 0
        self._seq = itertools.count()
        self._timer: asyncio.TimerHandle | None = None
        self._promoted: WeakKeyDictionary[asyncio.Task, Priority] = WeakKeyDictionary()
        self._rng = rng or random.random

    # -- configuration --------------------------------------------------------------------------

    def _source(self, source: str) -> _SourceState:
        return self._sources.setdefault(source, _SourceState())

    def _host(self, source: str, host: str) -> _HostState:
        return self._hosts.setdefault((source, host), _HostState())

    def configure_source(self, source: str, *, concurrency: int, requests_per_minute: int | None,
                         burst: int | None = None,
                         resource_concurrency: int | None = None,
                         resource_requests_per_minute: int | None = None) -> None:
        """Called before every request with the package's declared limits."""
        state = self._source(source)
        now = time.monotonic()
        state.page.concurrency = max(1, concurrency)
        state.page.set_limits(60.0 / requests_per_minute if requests_per_minute else 0.0,
                              min(MAX_BURST, max(1, burst)) if burst is not None else 1, now)
        if resource_concurrency is None and resource_requests_per_minute is None:
            state.resource = None
        else:
            if state.resource is None:
                state.resource = _LaneState()
            state.resource.concurrency = max(1, resource_concurrency or 1)
            state.resource.set_limits(60.0 / resource_requests_per_minute if resource_requests_per_minute else 0.0,
                                      1, now)
        self._dispatch()

    def set_retry_after(self, source: str, seconds: float) -> None:
        """A Retry-After from the source: every lane of the source waits (the host's own penalty comes from
        `observe`, which the fetcher calls with the same response)."""
        state = self._source(source)
        state.retry_until = max(state.retry_until, time.monotonic() + max(0.0, seconds))
        self._dispatch()

    # -- observation (Phase 0) and backoff (Phase 3) ----------------------------------------------

    def observe(self, source: str, host: str | None, outcome: Outcome) -> None:
        """What a request to `host` came back as. Drives the host's penalty and circuit, and the counters."""
        hs = self._host(source, host or "*")
        now = time.monotonic()
        stats = hs.stats
        stats.requests += 1
        stats.outcomes[outcome] = stats.outcomes.get(outcome, 0) + 1
        stats.recent.append(now)
        while stats.recent and now - stats.recent[0] > STATS_WINDOW:
            stats.recent.popleft()
        if outcome in ("ok", "not_found", "client_error"):     # the host answered normally
            hs.failures = 0
            hs.penalty = max(1.0, 1.0 + (hs.penalty - 1.0) * PENALTY_RECOVERY)
            if hs.penalty < 1.01:
                hs.penalty = 1.0
                hs.cooldown = BREAKER_COOLDOWN
        else:
            hs.failures += 1
            if outcome == "throttled":
                hs.penalty = min(PENALTY_MAX, hs.penalty * 2.0)
            elif outcome == "refused":
                hs.penalty = min(PENALTY_MAX, hs.penalty * 1.5)
            if hs.failures >= BREAKER_THRESHOLD:
                hs.open_until = now + hs.cooldown
                hs.cooldown = min(BREAKER_COOLDOWN_MAX, hs.cooldown * 2.0)
                hs.failures = 0
        self._dispatch()

    def _record_wait(self, source: str, host: str, seconds: float) -> None:
        stats = self._host(source, host).stats
        stats.wait_seconds += seconds
        stats.max_wait_seconds = max(stats.max_wait_seconds, seconds)

    def _under_pressure(self, source: str, host: str, now: float) -> float | None:
        """Seconds until the host may be asked again, when read-ahead for it should be shed; else None."""
        hs = self._hosts.get((source, host))
        if hs is None:
            return None
        if hs.open_until > now:
            return hs.open_until - now
        if hs.penalty >= SHED_FACTOR:
            lane = self._source(source).page
            return max(PENALTY_BASE_INTERVAL, lane.min_interval) * hs.penalty
        return None

    def snapshot(self) -> dict:
        now = time.monotonic()
        hosts = []
        for (source, host), hs in sorted(self._hosts.items()):
            s = hs.stats
            hosts.append({
                "source": source, "host": host, "requests": s.requests,
                "requests_last_minute": sum(1 for t in s.recent if now - t <= STATS_WINDOW),
                "outcomes": dict(s.outcomes), "shed": s.shed,
                "wait_seconds_total": round(s.wait_seconds, 3), "wait_seconds_max": round(s.max_wait_seconds, 3),
                "penalty": round(hs.penalty, 2), "circuit_open_for": round(max(0.0, hs.open_until - now), 1),
            })
        return {"http_in_use": self._http_in_use, "browser_in_use": self._browser_in_use,
                "waiting": len(self._waiters), "http_capacity": self.http_capacity, "hosts": hosts}

    # -- leasing --------------------------------------------------------------------------------

    def acquire(self, source: str, priority: Priority, *, kind: Kind = "http", host: str | None = None,
                lane: Lane = "page") -> _LeaseContext:
        if kind not in ("http", "browser"):
            raise ValueError(f"invalid lease kind {kind!r}")
        if lane not in ("page", "resource"):
            raise ValueError(f"invalid lane {lane!r}")
        return _LeaseContext(self, source, priority, kind, (host or "*").lower(), lane)

    def promote(self, task: asyncio.Task, priority: Priority) -> None:
        """Raise a queued request's priority, including one that has not reached its lease yet."""
        priority = Priority(priority)
        self._promoted[task] = min(priority, self._promoted.get(task, priority))
        for waiter in self._waiters:
            if waiter.task is task and priority < waiter.priority:
                waiter.priority = priority
        self._dispatch()

    def _shed(self, source: str, host: str, retry_after: float) -> TrafficShed:
        self._host(source, host).stats.shed += 1
        return TrafficShed(source, host, retry_after)

    async def _wait(self, source: str, priority: Priority, kind: Kind, host: str = "*",
                    lane: Lane = "page") -> Lease:
        loop = asyncio.get_running_loop()
        task = asyncio.current_task()
        effective = min(Priority(priority), self._promoted.get(task, Priority(priority))) if task else Priority(priority)
        if effective == Priority.READ_AHEAD:
            pressure = self._under_pressure(source, host, time.monotonic())
            if pressure is not None:
                raise self._shed(source, host, pressure)
        waiter = _Waiter(next(self._seq), source, effective, kind, loop.create_future(), task, host, lane)
        self._waiters.append(waiter)
        self._dispatch()
        try:
            return await waiter.future
        except asyncio.CancelledError:
            if waiter in self._waiters:
                self._waiters.remove(waiter)
            elif waiter.future.done() and not waiter.future.cancelled() and waiter.future.exception() is None:
                self._release(waiter.future.result())
            self._dispatch()
            raise

    def _release(self, lease: Lease) -> None:
        if lease.released:
            return
        lease.released = True
        self._leases.discard(lease)
        self._source(lease.source).lane(lease.lane).in_use -= 1
        if lease.kind == "http":
            self._http_in_use -= 1
        else:
            self._browser_in_use -= 1
        self._dispatch()

    def _capacity_ok(self, waiter: _Waiter) -> bool:
        if waiter.kind == "browser":
            return self._browser_in_use < self.browser_capacity
        if waiter.priority >= BACKGROUND:
            limit = self.http_capacity - self.reserve - self.reader_reserve
        elif waiter.priority == Priority.READER:
            limit = self.http_capacity
        else:
            limit = self.http_capacity - self.reader_reserve
        return self._http_in_use < max(1, limit)

    def _spacing(self, lane: _LaneState, hs: _HostState | None) -> float:
        interval = lane.min_interval
        if hs is not None and hs.penalty > 1.0:
            interval = max(interval, PENALTY_BASE_INTERVAL) * hs.penalty
        return interval

    @staticmethod
    def _capacity(lane: _LaneState, hs: _HostState | None) -> float:
        """The bucket's size right now: a host under pressure gets one start per (lengthened) spacing, whatever
        a package's burst, so saved-up tokens never carry a burst past a 429."""
        return 1.0 if hs is not None and hs.penalty > 1.0 else float(lane.burst)

    def _lane_ready_at(self, lane: _LaneState, hs: _HostState | None, now: float, background: bool) -> float:
        interval = self._spacing(lane, hs)
        if interval <= 0:
            return now
        capacity = self._capacity(lane, hs)
        lane.refill(now, interval, capacity)
        # Background work (read-ahead, Follow, health) leaves the last token of a burst for the person.
        needed = 2.0 if background and capacity >= 2 else 1.0
        if lane.tokens >= needed - 1e-9:
            return now
        return now + (needed - lane.tokens) * interval + lane.jitter

    def _source_ready_at(self, waiter: _Waiter, now: float) -> float | None:
        """None if blocked by source concurrency; otherwise the time the source and host allow a start."""
        state = self._source(waiter.source)
        lane = state.lane(waiter.lane)
        if lane.in_use >= lane.concurrency:
            return None
        hs = self._hosts.get((waiter.source, waiter.host))
        ready = max(self._lane_ready_at(lane, hs, now, waiter.priority >= BACKGROUND), state.retry_until)
        if hs is not None and waiter.kind == "http":
            ready = max(ready, hs.open_until, hs.last_start + HOST_MIN_INTERVAL)
        return ready

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
                if waiter.priority == Priority.READ_AHEAD:
                    pressure = self._under_pressure(waiter.source, waiter.host, now)
                    if pressure is not None:
                        self._waiters.remove(waiter)
                        waiter.future.set_exception(self._shed(waiter.source, waiter.host, pressure))
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
        lane = state.lane(waiter.lane)
        lane.in_use += 1
        state.served += 1
        hs = self._hosts.get((waiter.source, waiter.host))
        interval = self._spacing(lane, hs)
        lane.refill(now, interval, self._capacity(lane, hs))
        lane.tokens = max(0.0, lane.tokens - 1.0)
        lane.last_start = now
        lane.jitter = interval * JITTER_FRACTION * self._rng()
        if waiter.kind == "http":
            self._host(waiter.source, waiter.host).last_start = now
            self._http_in_use += 1
        else:
            self._browser_in_use += 1
        lease = Lease(waiter.source, waiter.priority, waiter.kind, waiter.task, host=waiter.host, lane=waiter.lane)
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
