"""The generated adapter must actually work: search → work → catalog → reader (Master §12.3)."""
import asyncio

import pytest

from oneshelf.generator.discovery import discover
from oneshelf.generator.draft import build_draft, write_package
from oneshelf.net.http import HttpClient
from oneshelf.net.governor import Priority, TrafficGovernor
from oneshelf.net.policy import EgressPolicy
from oneshelf.plugins.package import load_package
from oneshelf.plugins.runtime import RecipeRuntime
from oneshelf.sources.fetcher import DevHostsResolver, SourceFetcher
from testsource.server import HOST, TestSourceServer


def run(coro):
    return asyncio.run(asyncio.wait_for(coro, 60))


async def generated(tmp_path, server):
    site = await discover(f"http://{HOST}/gen/search?q=a", dev_hosts=server.hosts(), allow_http=True)
    draft = build_draft(site, name="Generated Test Source")
    return load_package(write_package(draft, tmp_path / "generated.osp")), site


def runtime_for(package, server) -> tuple[RecipeRuntime, HttpClient]:
    policy = EgressPolicy(domains=tuple(package.manifest.network.domains),
                          cdn_domains=tuple(package.manifest.network.cdn_domains),
                          allow_http=True, dev_loopback_exception=True)
    client = HttpClient(policy, resolver_backend=DevHostsResolver(server.hosts()))
    return client, policy


@pytest.fixture
def outcome(tmp_path):
    """Runs the generated recipes against the live Test Source, exactly as the source runtime would."""
    async def go():
        async with TestSourceServer() as server:
            package, site = await generated(tmp_path, server)
            client, _policy = runtime_for(package, server)
            async with client:
                fetcher = SourceFetcher(package, client, TrafficGovernor(), None, Priority.INTERACTIVE)
                runtime = RecipeRuntime(package, fetcher)
                results = {}
                results["site"] = site
                results["package"] = package
                results["search"] = await runtime.run("search", {"query": "irregular"})
                listing_key = results["search"].items[0].listing_key
                results["listing_key"] = listing_key
                results["work"] = await runtime.run("work", {"listing_key": listing_key})
                results["catalog"] = await runtime.run("catalog", {"listing_key": listing_key})
                unit_key = results["catalog"].items[0].unit_key
                results["reader"] = await runtime.run("reader", {"unit_key": unit_key})
                return results
    return run(go())


def test_generated_search_returns_real_listings(outcome):
    items = outcome["search"].items
    assert items and items[0].title == "The Irregular Chronicle"
    assert items[0].listing_key == "irregular"
    assert items[0].cover_url.endswith("/covers/irregular.png")


def test_generated_work_and_catalog_follow_the_source_order(outcome):
    assert outcome["work"].title == "The Irregular Chronicle"
    units = outcome["catalog"].items
    assert [u.raw_title for u in units][:3] == ["Prologue", "Chapter 1", "Chapter 2"]
    assert all(u.unit_key for u in units)
    assert units[0].unit_key == "irr-prologue"
    assert [u.order_index for u in units] == sorted(u.order_index for u in units)


def test_generated_reader_returns_the_page_images(outcome):
    pages = outcome["reader"].items
    assert len(pages) == 3
    assert all(p.url.startswith("http://cdn.testsource.example/img/") for p in pages)


def test_the_generated_package_only_requests_the_domains_it_uses(outcome):
    network = outcome["package"].manifest.network
    assert [str(d) for d in network.domains] == [HOST]
    assert "tracker.example" not in [str(d) for d in network.cdn_domains]
    assert outcome["package"].permissions  # domain permissions are explicit and reviewable
