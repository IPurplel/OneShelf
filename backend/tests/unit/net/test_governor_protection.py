"""Ban protection and resource budgets in the Source Traffic Governor (net/governor.py)."""
import asyncio
import time

import pytest

from oneshelf.net import governor as g
from oneshelf.net.governor import Priority, TrafficGovernor, TrafficShed


def run(coro):
    return asyncio.run(asyncio.wait_for(coro, timeout=10))


async def starts(gov, source, n, *, host="h", lane="page", priority=Priority.READER):
    out = []
    for _ in range(n):
        async with gov.acquire(source, priority, host=host, lane=lane):
            out.append(time.monotonic())
    return out


def test_throttled_host_slows_down_and_recovers_on_success():
    async def scenario():
        gov = TrafficGovernor(rng=lambda: 0.0)
        gov.configure_source("s", concurrency=1, requests_per_minute=1200)   # 0.05 s spacing
        gov.observe("s", "h", "throttled")
        gov.observe("s", "h", "throttled")                                   # penalty 4 -> 0.25 * 4 = 1.0 s
        penalised = await starts(gov, "s", 2)
        for _ in range(60):
            gov.observe("s", "h", "ok")
        recovered = await starts(gov, "s", 2)
        return penalised[1] - penalised[0], recovered[1] - recovered[0]
    slow, fast = run(scenario())
    assert slow >= 0.95
    assert fast < 0.2


def test_other_hosts_of_the_source_are_not_penalised():
    async def scenario():
        gov = TrafficGovernor(rng=lambda: 0.0)
        gov.configure_source("s", concurrency=2, requests_per_minute=None)
        for _ in range(3):
            gov.observe("s", "cdn.example", "throttled")
        t = time.monotonic()
        async with gov.acquire("s", Priority.READER, host="www.example"):
            pass
        async with gov.acquire("s", Priority.READER, host="www.example"):
            pass
        return time.monotonic() - t
    assert run(scenario()) < 0.3


def test_repeated_failures_open_the_circuit_for_that_host():
    async def scenario():
        gov = TrafficGovernor(rng=lambda: 0.0)
        for _ in range(g.BREAKER_THRESHOLD):
            gov.observe("s", "h", "transport_error")
        snap = {h["host"]: h for h in gov.snapshot()["hosts"]}
        blocked = None
        try:
            await asyncio.wait_for(starts(gov, "s", 1), timeout=0.3)
        except asyncio.TimeoutError:
            blocked = True
        return snap["h"]["circuit_open_for"], blocked
    open_for, blocked = run(scenario())
    assert open_for > 20 and blocked


def test_read_ahead_is_shed_when_the_host_is_under_pressure_but_the_reader_is_not():
    async def scenario():
        gov = TrafficGovernor(rng=lambda: 0.0)
        gov.configure_source("s", concurrency=2, requests_per_minute=6000)
        for _ in range(3):
            gov.observe("s", "h", "throttled")                     # penalty 8 >= SHED_FACTOR
        with pytest.raises(TrafficShed) as shed:
            async with gov.acquire("s", Priority.READ_AHEAD, host="h"):
                pass
        async with gov.acquire("s", Priority.READER, host="h"):
            reader_ok = True
        stats = {h["host"]: h for h in gov.snapshot()["hosts"]}["h"]
        return shed.value.retry_after, reader_ok, stats["shed"]
    retry_after, reader_ok, shed = run(scenario())
    assert retry_after > 0 and reader_ok and shed == 1


def test_queued_read_ahead_is_shed_when_pressure_arrives():
    async def scenario():
        gov = TrafficGovernor(http_capacity=2, reserved_for_foreground=0, rng=lambda: 0.0)
        gov.configure_source("s", concurrency=1, requests_per_minute=None)
        release = asyncio.Event()

        async def holder():
            async with gov.acquire("s", Priority.READER, host="h"):
                await release.wait()

        h = asyncio.create_task(holder())
        await asyncio.sleep(0.01)
        queued = asyncio.create_task(starts(gov, "s", 1, priority=Priority.READ_AHEAD))
        await asyncio.sleep(0.01)
        for _ in range(3):
            gov.observe("s", "h", "throttled")
        result = await asyncio.gather(queued, return_exceptions=True)
        release.set()
        await h
        return result[0]
    assert isinstance(run(scenario()), TrafficShed)


def test_resource_budget_is_separate_from_the_page_budget():
    async def scenario():
        gov = TrafficGovernor(rng=lambda: 0.0)
        gov.configure_source("s", concurrency=1, requests_per_minute=20,          # pages: 3 s apart
                             resource_concurrency=4, resource_requests_per_minute=600)
        async with gov.acquire("s", Priority.READER, host="www", lane="page"):
            pass
        images = await starts(gov, "s", 5, host="cdn", lane="resource")
        return images[-1] - images[0]
    assert run(scenario()) < 0.7          # 4 spacings of 0.1 s (+ jitter at most 15 %)


def test_without_a_resource_budget_resources_share_the_page_budget():
    async def scenario():
        gov = TrafficGovernor(rng=lambda: 0.0)
        gov.configure_source("s", concurrency=1, requests_per_minute=600)          # 0.1 s
        times = []
        async with gov.acquire("s", Priority.READER, host="www", lane="page"):
            times.append(time.monotonic())
        async with gov.acquire("s", Priority.READER, host="cdn", lane="resource"):
            times.append(time.monotonic())
        return times[1] - times[0]
    assert run(scenario()) >= 0.09


def test_core_ceiling_spaces_starts_to_one_host_whatever_is_declared():
    async def scenario():
        gov = TrafficGovernor(rng=lambda: 0.0)
        gov.configure_source("s", concurrency=4, requests_per_minute=None)
        t = await starts(gov, "s", 4, host="h")
        return t[-1] - t[0]
    assert run(scenario()) >= 3 * g.HOST_MIN_INTERVAL - 0.01


def test_jitter_only_ever_lengthens_the_spacing():
    async def scenario():
        gov = TrafficGovernor(rng=lambda: 1.0)
        gov.configure_source("s", concurrency=1, requests_per_minute=600)          # 0.1 s
        t = await starts(gov, "s", 2, host="h")
        return t[1] - t[0]
    spacing = run(scenario())
    assert 0.1 <= spacing < 0.1 * (1 + g.JITTER_FRACTION) + 0.05


def test_reader_has_slots_that_interactive_work_cannot_take():
    async def scenario():
        gov = TrafficGovernor(http_capacity=4, reserved_for_foreground=1, reserved_for_reader=1)
        release = asyncio.Event()
        taken = []

        async def interactive(i):
            async with gov.acquire(f"i{i}", Priority.INTERACTIVE):
                taken.append(i)
                await release.wait()

        tasks = [asyncio.create_task(interactive(i)) for i in range(6)]
        await asyncio.sleep(0.05)
        count = len(taken)
        t = time.monotonic()
        async with gov.acquire("reader", Priority.READER):
            waited = time.monotonic() - t
        release.set()
        await asyncio.gather(*tasks)
        return count, waited
    count, waited = run(scenario())
    assert count == 3 and waited < 0.05


def test_snapshot_counts_requests_and_outcomes_per_host():
    async def scenario():
        gov = TrafficGovernor()
        await starts(gov, "s", 2, host="cdn")
        gov.observe("s", "cdn", "ok")
        gov.observe("s", "cdn", "throttled")
        return {h["host"]: h for h in gov.snapshot()["hosts"]}["cdn"]
    cdn = run(scenario())
    assert cdn["requests"] == 2 and cdn["outcomes"] == {"ok": 1, "throttled": 1}
    assert cdn["requests_last_minute"] == 2 and cdn["penalty"] == 2.0
