"""In-process event bus fanned out to Server-Sent Events clients (Master §36, ledger K5).

Publishing never blocks: a subscriber that falls behind receives a final `resync` event and is
dropped, so its client refetches state instead of stalling downloads or the Reader.
"""
from __future__ import annotations

import asyncio
import itertools
import json
import threading
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class Event:
    id: int
    type: str
    data: dict[str, Any]


class Subscription:
    def __init__(self, loop: asyncio.AbstractEventLoop, queue_size: int) -> None:
        self.loop = loop
        self.queue: asyncio.Queue[Event] = asyncio.Queue(maxsize=queue_size)
        self.closed = False

    async def get(self) -> Event:
        return await self.queue.get()


class EventBus:
    def __init__(self, queue_size: int = 256) -> None:
        if queue_size < 2:
            raise ValueError("queue_size must leave room for a resync event")
        self.queue_size = queue_size
        self._ids = itertools.count(1)
        self._lock = threading.Lock()
        self._subscribers: set[Subscription] = set()

    @property
    def subscriber_count(self) -> int:
        with self._lock:
            return len(self._subscribers)

    def subscribe(self) -> Subscription:
        sub = Subscription(asyncio.get_running_loop(), self.queue_size)
        with self._lock:
            self._subscribers.add(sub)
        return sub

    def unsubscribe(self, sub: Subscription) -> None:
        sub.closed = True
        with self._lock:
            self._subscribers.discard(sub)

    def publish(self, event_type: str, data: dict[str, Any]) -> Event:
        with self._lock:
            event = Event(next(self._ids), event_type, data)
            subscribers = list(self._subscribers)
        for sub in subscribers:
            try:
                in_loop = asyncio.get_running_loop() is sub.loop
            except RuntimeError:
                in_loop = False
            if in_loop:
                self._deliver(sub, event)
            elif not sub.loop.is_closed():
                sub.loop.call_soon_threadsafe(self._deliver, sub, event)
        return event

    def _deliver(self, sub: Subscription, event: Event) -> None:
        if sub.closed:
            return
        if sub.queue.qsize() >= self.queue_size - 1:
            sub.queue.put_nowait(Event(event.id, "resync", {}))
            self.unsubscribe(sub)
            return
        sub.queue.put_nowait(event)


def encode_sse(event_id: int, event_type: str, data: dict[str, Any]) -> str:
    payload = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
    return f"id: {event_id}\nevent: {event_type}\ndata: {payload}\n\n"


async def sse_stream(
    bus: EventBus,
    is_disconnected: Callable[[], Awaitable[bool]],
    *,
    heartbeat_seconds: float = 15.0,
) -> AsyncIterator[str]:
    sub = bus.subscribe()
    try:
        yield encode_sse(0, "hello", {})
        while not await is_disconnected():
            try:
                event = await asyncio.wait_for(sub.get(), timeout=heartbeat_seconds)
            except TimeoutError:
                yield ": keepalive\n\n"
                continue
            yield encode_sse(event.id, event.type, event.data)
            if event.type == "resync":
                break
    finally:
        bus.unsubscribe(sub)
