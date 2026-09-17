"""Master §36 / ledger K5: internal event channel with SSE encoding and non-blocking fan-out."""
import asyncio
import json
import threading

from oneshelf.events.bus import EventBus, encode_sse, sse_stream


def run(coro):
    return asyncio.run(coro)


def test_subscribers_receive_events_in_order():
    async def scenario():
        bus = EventBus()
        a, b = bus.subscribe(), bus.subscribe()
        bus.publish("import.completed", {"n": 1})
        bus.publish("import.completed", {"n": 2})
        got_a = [await a.get(), await a.get()]
        got_b = [await b.get(), await b.get()]
        return got_a, got_b

    got_a, got_b = run(scenario())
    assert [e.data["n"] for e in got_a] == [1, 2] == [e.data["n"] for e in got_b]
    assert got_a[0].id < got_a[1].id


def test_slow_subscriber_is_dropped_with_resync_without_blocking_publisher():
    async def scenario():
        bus = EventBus(queue_size=3)
        slow = bus.subscribe()
        for i in range(10):
            bus.publish("x", {"i": i})  # must not block or raise
        items = []
        while not slow.queue.empty():
            items.append(await slow.get())
        return bus, slow, items

    bus, slow, items = run(scenario())
    assert items[-1].type == "resync"
    assert slow.closed and bus.subscriber_count == 0


def test_publish_from_worker_thread_is_delivered():
    async def scenario():
        bus = EventBus()
        sub = bus.subscribe()
        thread = threading.Thread(target=bus.publish, args=("job.progress", {"p": 50}))
        thread.start()
        thread.join()
        return await asyncio.wait_for(sub.get(), timeout=1)

    event = run(scenario())
    assert event.type == "job.progress" and event.data == {"p": 50}


def test_sse_encoding_is_single_line_json():
    frame = encode_sse(7, "note", {"text": "line1\nline2", "ar": "مرحبا"})
    lines = frame.split("\n")
    assert lines[0] == "id: 7" and lines[1] == "event: note"
    assert json.loads(lines[2].removeprefix("data: ")) == {"text": "line1\nline2", "ar": "مرحبا"}
    assert frame.endswith("\n\n")


def test_sse_stream_sends_hello_then_events_and_stops_on_disconnect():
    async def scenario():
        bus = EventBus()
        disconnected = asyncio.Event()

        async def is_disconnected():
            return disconnected.is_set()

        stream = sse_stream(bus, is_disconnected, heartbeat_seconds=0.05)
        frames = [await anext(stream)]
        bus.publish("download.progress", {"p": 1})
        frames.append(await anext(stream))
        disconnected.set()
        rest = [f async for f in stream]
        return bus, frames, rest

    bus, frames, rest = run(scenario())
    assert "event: hello" in frames[0]
    assert "event: download.progress" in frames[1]
    assert all("event:" not in f or "hello" not in f for f in rest)
    assert bus.subscriber_count == 0
