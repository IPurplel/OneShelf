"""SourceFetcher feeds each host's answers back to the governor, and turns shedding into a deferral."""
import asyncio
from types import SimpleNamespace

import pytest
from multidict import CIMultiDict

from oneshelf.net.governor import Priority, TrafficGovernor
from oneshelf.net.http import FetchFailed, HttpResponse
from oneshelf.plugins.runtime import RateLimited, TrafficDeferred
from oneshelf.sources.fetcher import SourceFetcher, outcome_for_status


class FakeClient:
    def __init__(self, statuses):
        self.statuses = list(statuses)
        self.calls = 0

    async def fetch(self, url, **kwargs):
        self.calls += 1
        status = self.statuses.pop(0)
        if status == "fail":
            raise FetchFailed("reset")
        return HttpResponse(url=url, status=status, headers=CIMultiDict(), body=b"x")


def fetcher(client, gov, priority=Priority.READER):
    package = SimpleNamespace(id="src", manifest=SimpleNamespace(auth=None))
    return SourceFetcher(package, client, gov, None, priority)


def hosts(gov):
    return {h["host"]: h for h in gov.snapshot()["hosts"]}


def test_status_outcomes():
    assert [outcome_for_status(s) for s in (200, 304, 404, 401, 403, 429, 503, 500)] == [
        "ok", "ok", "not_found", "client_error", "refused", "throttled", "throttled", "server_error"]


def test_answers_are_observed_per_host():
    async def scenario():
        gov = TrafficGovernor(rng=lambda: 0.0)
        f = fetcher(FakeClient([200, 503]), gov)
        await f.request("https://cdn.example/a.jpg", capability="reader", auth_mode="none", lane="resource")
        await f.request("https://cdn.example/b.jpg", capability="reader", auth_mode="none", lane="resource")
        return hosts(gov)["cdn.example"]
    cdn = asyncio.run(scenario())
    assert cdn["outcomes"] == {"ok": 1, "throttled": 1} and cdn["penalty"] == 2.0


def test_transport_failures_count_against_the_host():
    async def scenario():
        gov = TrafficGovernor()
        f = fetcher(FakeClient(["fail"]), gov)
        with pytest.raises(FetchFailed):
            await f.request("https://www.example/p", capability="catalog", auth_mode="none")
        return hosts(gov)["www.example"]["outcomes"]
    assert asyncio.run(scenario()) == {"transport_error": 1}


def test_shed_read_ahead_becomes_a_deferral_and_sends_nothing():
    async def scenario():
        gov = TrafficGovernor()
        for _ in range(3):
            gov.observe("src", "cdn.example", "throttled")
        client = FakeClient([200])
        f = fetcher(client, gov, Priority.READ_AHEAD)
        with pytest.raises(TrafficDeferred) as deferred:
            await f.request("https://cdn.example/c.jpg", capability="work", auth_mode="none", lane="resource")
        return deferred.value, client.calls
    deferred, calls = asyncio.run(scenario())
    assert isinstance(deferred, RateLimited) and deferred.retry_after > 0 and calls == 0
