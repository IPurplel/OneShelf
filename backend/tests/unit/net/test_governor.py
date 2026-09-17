"""Master §15 / INV-26: global Source Traffic Governor."""
import asyncio
import time

import pytest

from oneshelf.net.governor import Priority, TrafficGovernor


def run(coro):
    return asyncio.run(asyncio.wait_for(coro, timeout=10))


async def hold(gov, source, priority, kind, log, name, seconds, started=None):
    async with gov.acquire(source, priority, kind=kind) as lease:
        log.append(name)
        if started:
            started.set()
        await asyncio.sleep(seconds)
        return lease


def test_global_http_capacity_is_respected():
    async def scenario():
        gov = TrafficGovernor(http_capacity=4)
        active = peak = 0

        async def work(i):
            nonlocal active, peak
            async with gov.acquire(f"s{i}", Priority.MANUAL):
                active += 1
                peak = max(peak, active)
                await asyncio.sleep(0.02)
                active -= 1

        await asyncio.gather(*(work(i) for i in range(10)))
        return peak
    assert run(scenario()) == 4


def test_waiters_are_granted_in_priority_order():
    async def scenario():
        gov = TrafficGovernor(http_capacity=1)
        log = []
        blocker = asyncio.Event()

        async def first():
            async with gov.acquire("s0", Priority.MANUAL):
                await blocker.wait()

        t0 = asyncio.create_task(first())
        await asyncio.sleep(0.01)
        tasks = [asyncio.create_task(hold(gov, f"s{p}", p, "http", log, p.name, 0)) for p in
                 (Priority.HEALTH, Priority.FOLLOW, Priority.MANUAL, Priority.READER)]
        await asyncio.sleep(0.01)
        blocker.set()
        await asyncio.gather(t0, *tasks)
        return log
    assert run(scenario()) == ["READER", "MANUAL", "FOLLOW", "HEALTH"]


def test_background_work_cannot_take_the_last_http_slot():
    async def scenario():
        gov = TrafficGovernor(http_capacity=4)
        release = asyncio.Event()
        background = []

        async def bg(i):
            async with gov.acquire(f"bg{i}", Priority.HEALTH):
                background.append(i)
                await release.wait()

        tasks = [asyncio.create_task(bg(i)) for i in range(6)]
        await asyncio.sleep(0.05)
        assert len(background) == 3  # one slot stays reserved
        started = time.monotonic()
        async with gov.acquire("reader-source", Priority.READER):
            waited = time.monotonic() - started
        release.set()
        await asyncio.gather(*tasks)
        return waited
    assert run(scenario()) < 0.05


def test_browser_capacity_is_independent_from_http():
    async def scenario():
        gov = TrafficGovernor(http_capacity=1, browser_capacity=1)
        release = asyncio.Event()

        async def http_holder():
            async with gov.acquire("a", Priority.MANUAL, kind="http"):
                await release.wait()

        t = asyncio.create_task(http_holder())
        await asyncio.sleep(0.01)
        started = time.monotonic()
        async with gov.acquire("b", Priority.MANUAL, kind="browser"):
            waited = time.monotonic() - started
        release.set()
        await t
        return waited
    assert run(scenario()) < 0.05


def test_background_browser_work_is_preempted_for_reader():
    async def scenario():
        gov = TrafficGovernor(browser_capacity=1)
        holding = asyncio.Event()
        outcome = {}

        async def health_probe():
            try:
                async with gov.acquire("src", Priority.HEALTH, kind="browser") as lease:
                    outcome["lease"] = lease
                    holding.set()
                    await asyncio.sleep(30)
            except asyncio.CancelledError:
                outcome["cancelled"] = True
                raise

        probe = asyncio.create_task(health_probe())
        await holding.wait()
        started = time.monotonic()
        async with gov.acquire("src", Priority.READER, kind="browser"):
            outcome["waited"] = time.monotonic() - started
        with pytest.raises(asyncio.CancelledError):
            await probe
        return outcome
    outcome = run(scenario())
    assert outcome["cancelled"] and outcome["lease"].preempted
    assert outcome["waited"] < 0.2


def test_user_downloads_are_not_preempted_but_reader_waits_boundedly():
    async def scenario():
        gov = TrafficGovernor(browser_capacity=1)
        holding = asyncio.Event()

        async def download_request():
            async with gov.acquire("src", Priority.MANUAL, kind="browser") as lease:
                holding.set()
                await asyncio.sleep(0.1)
                return lease.preempted

        task = asyncio.create_task(download_request())
        await holding.wait()
        started = time.monotonic()
        async with gov.acquire("src", Priority.READER, kind="browser"):
            waited = time.monotonic() - started
        return await task, waited
    preempted, waited = run(scenario())
    assert preempted is False and 0.05 < waited < 0.5


def test_per_source_concurrency():
    async def scenario():
        gov = TrafficGovernor(http_capacity=4)
        gov.configure_source("slow", concurrency=1, requests_per_minute=6000)
        release = asyncio.Event()
        order = []

        async def slow_holder():
            async with gov.acquire("slow", Priority.MANUAL):
                await release.wait()

        t = asyncio.create_task(slow_holder())
        await asyncio.sleep(0.01)
        second = asyncio.create_task(hold(gov, "slow", Priority.READER, "http", order, "slow-2", 0))
        other = asyncio.create_task(hold(gov, "fast", Priority.HEALTH, "http", order, "fast", 0))
        await asyncio.sleep(0.03)
        snapshot = list(order)
        release.set()
        await asyncio.gather(t, second, other)
        return snapshot, order
    snapshot, order = run(scenario())
    assert snapshot == ["fast"] and order == ["fast", "slow-2"]


def test_fairness_across_sources_at_same_priority():
    async def scenario():
        gov = TrafficGovernor(http_capacity=1)
        for s in ("big", "small"):
            gov.configure_source(s, concurrency=4, requests_per_minute=60000)
        log = []
        blocker = asyncio.Event()

        async def first():
            async with gov.acquire("big", Priority.MANUAL):
                await blocker.wait()

        t0 = asyncio.create_task(first())
        await asyncio.sleep(0.01)
        tasks = [asyncio.create_task(hold(gov, "big", Priority.MANUAL, "http", log, "big", 0)) for _ in range(8)]
        await asyncio.sleep(0.01)
        tasks += [asyncio.create_task(hold(gov, "small", Priority.MANUAL, "http", log, "small", 0)) for _ in range(2)]
        await asyncio.sleep(0.01)
        blocker.set()
        await asyncio.gather(t0, *tasks)
        return log
    log = run(scenario())
    assert log.index("small") <= 2 and log[:5].count("small") == 2


def test_source_rate_limit_spaces_request_starts():
    async def scenario():
        gov = TrafficGovernor()
        gov.configure_source("polite", concurrency=4, requests_per_minute=600)  # 0.1 s spacing
        starts = []
        for _ in range(3):
            async with gov.acquire("polite", Priority.READER):
                starts.append(time.monotonic())
        return starts
    starts = run(scenario())
    assert starts[2] - starts[0] >= 0.19


def test_retry_after_blocks_only_that_source():
    async def scenario():
        gov = TrafficGovernor()
        gov.set_retry_after("limited", 0.3)
        t = time.monotonic()
        async with gov.acquire("other", Priority.HEALTH):
            other_wait = time.monotonic() - t
        async with gov.acquire("limited", Priority.READER):
            limited_wait = time.monotonic() - t
        return other_wait, limited_wait
    other_wait, limited_wait = run(scenario())
    assert other_wait < 0.05 and limited_wait >= 0.28


def test_cancelled_waiters_do_not_leak_slots():
    async def scenario():
        gov = TrafficGovernor(http_capacity=1)
        release = asyncio.Event()

        async def holder():
            async with gov.acquire("a", Priority.MANUAL):
                await release.wait()

        h = asyncio.create_task(holder())
        await asyncio.sleep(0.01)
        waiters = [asyncio.create_task(hold(gov, "b", Priority.MANUAL, "http", [], "x", 0)) for _ in range(3)]
        await asyncio.sleep(0.01)
        for w in waiters:
            w.cancel()
        await asyncio.gather(*waiters, return_exceptions=True)
        release.set()
        await h
        async with gov.acquire("c", Priority.HEALTH):
            pass
        return gov.snapshot()
    snap = run(scenario())
    assert snap["http_in_use"] == 0 and snap["waiting"] == 0 and snap["browser_in_use"] == 0
