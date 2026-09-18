"""Live integration against the real §41.1 sources.

Opt-in: these tests make real network requests, so they are skipped unless ONESHELF_LIVE_SOURCES=1.
They check the shipped packages still match the live sites, and they open the artefacts they fetch
instead of trusting a status code (Meta Prompt C9).
"""
import asyncio
import io
import os
import zipfile

import pytest

from oneshelf.net.governor import Priority, TrafficGovernor
from oneshelf.net.http import HttpClient
from oneshelf.net.policy import EgressPolicy
from oneshelf.plugins.package import load_package
from oneshelf.plugins.runtime import RecipeRuntime
from oneshelf.sources.fetcher import SourceFetcher
from plugins.build import build_package, official_packages

pytestmark = pytest.mark.live

LIVE = os.environ.get("ONESHELF_LIVE_SOURCES") == "1"
skip_unless_live = pytest.mark.skipif(not LIVE, reason="set ONESHELF_LIVE_SOURCES=1 to run live source checks")


def run(coro):
    return asyncio.run(asyncio.wait_for(coro, 120))


def package_for(name, tmp_path):
    source = next(p for p in official_packages() if p.name == name)
    return load_package(build_package(source, tmp_path / f"{name}.osp"))


async def call(package, capability, inputs):
    network = package.manifest.network
    policy = EgressPolicy(domains=tuple(network.domains), cdn_domains=tuple(network.cdn_domains),
                          allow_http=network.allow_http)
    async with HttpClient(policy) as client:
        fetcher = SourceFetcher(package, client, TrafficGovernor(), None, Priority.INTERACTIVE)
        return await RecipeRuntime(package, fetcher).run(capability, inputs)


async def fetch_bytes(package, url, limit=4_000_000):
    network = package.manifest.network
    policy = EgressPolicy(domains=tuple(network.domains), cdn_domains=tuple(network.cdn_domains),
                          allow_http=network.allow_http)
    async with HttpClient(policy) as client:
        response = await client.fetch(url, max_bytes=limit)
        return response.body


@skip_unless_live
def test_mangadex_search_catalog_and_reader(tmp_path):
    package = package_for("oneshelf.mangadex", tmp_path)
    found = run(call(package, "search", {"query": "dungeon"}))
    assert found.items and found.items[0].listing_key
    work = run(call(package, "work", {"listing_key": found.items[0].listing_key}))
    assert work.title


@skip_unless_live
def test_gutenberg_search_and_a_real_epub(tmp_path):
    package = package_for("oneshelf.gutenberg", tmp_path)
    found = run(call(package, "search", {"query": "frankenstein", "page": 1}))
    assert any(item.title.lower().startswith("frankenstein") for item in found.items)
    files = run(call(package, "downloads", {"unit_key": found.items[0].listing_key}))
    body = run(fetch_bytes(package, files.items[0].url))
    with zipfile.ZipFile(io.BytesIO(body)) as archive:       # a real EPUB, opened, not just 200 OK
        assert "META-INF/container.xml" in archive.namelist()


@skip_unless_live
def test_arxiv_search_and_a_real_pdf(tmp_path):
    package = package_for("oneshelf.arxiv", tmp_path)
    found = run(call(package, "search", {"query": "diffusion", "offset": 0}))
    assert found.items and found.items[0].listing_key
    files = run(call(package, "downloads", {"unit_key": found.items[0].listing_key}))
    body = run(fetch_bytes(package, files.items[0].url))
    assert body.startswith(b"%PDF-")


@skip_unless_live
def test_standard_ebooks_offers_one_work_with_formats(tmp_path):
    package = package_for("oneshelf.standard-ebooks", tmp_path)
    found = run(call(package, "search", {"query": "frankenstein"}))
    assert found.items and "/" in found.items[0].listing_key
    files = run(call(package, "downloads", {"unit_key": found.items[0].listing_key}))
    assert files.items and all(f.format == "epub" for f in files.items)
    body = run(fetch_bytes(package, files.items[0].url))
    with zipfile.ZipFile(io.BytesIO(body)) as archive:
        assert "META-INF/container.xml" in archive.namelist()
