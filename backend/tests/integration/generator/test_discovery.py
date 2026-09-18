"""Master §12.2–12.3: static-first discovery that maps a real site into recipe material."""
import asyncio

import pytest

from oneshelf.generator.discovery import discover
from testsource.server import CDN_HOST, HOST, TestSourceServer


def run(coro):
    return asyncio.run(asyncio.wait_for(coro, 60))


def map_site(path: str):
    """Discovery and the Test Source must share one event loop."""
    async def go():
        async with TestSourceServer() as server:
            return await discover(f"http://{HOST}{path}", dev_hosts=server.hosts(), allow_http=True)
    return run(go())


def fails(path: str):
    async def go():
        async with TestSourceServer() as server:
            return await discover(path, dev_hosts=server.hosts(), allow_http=True)
    return run(go())


def test_search_results_are_mapped_from_the_url_the_developer_pasted():
    site = map_site("/search?q=a")
    assert site.base_url == f"http://{HOST}"
    assert site.search.url_template == f"http://{HOST}/search?q={{query}}"
    assert site.search.item_selector == "li.result"
    fields = site.search.fields
    assert fields["title"].css and "title" in fields["title"].css
    assert fields["url"].css and "href" in fields["url"].css
    assert fields["cover_url"].css and "src" in fields["cover_url"].css
    assert site.capabilities["search"] in ("confirmed", "probable")


def test_a_work_page_is_reached_from_a_result_and_mapped():
    site = map_site("/search?q=a")
    assert site.work.url_template and "{work_id}" in site.work.url_template
    assert site.work.fields["title"].css
    assert site.samples["work"], "at least one sample work page must be fetched"
    assert site.capabilities["work"] in ("confirmed", "probable")


def test_units_and_reader_pages_are_discovered_with_their_order():
    site = map_site("/gen/work/irregular")
    assert site.catalog.item_selector == "li.chapter"
    assert site.catalog.fields["title"].css and site.catalog.fields["unit_key"].css
    assert site.reader.image_selector == "img.page::attr(src)"
    assert site.capabilities["catalog"] in ("confirmed", "probable")
    assert site.capabilities["reader"] in ("confirmed", "probable")


def test_source_and_cdn_domains_are_separated_from_third_parties():
    site = map_site("/gen/work/irregular")
    assert site.domains == [HOST]
    assert site.cdn_domains == [CDN_HOST]
    assert "tracker.example" not in site.domains + site.cdn_domains       # ads/analytics never become permissions
    assert "tracker.example" in site.rejected_domains


def test_discovery_never_leaves_the_site_or_reaches_private_addresses():
    with pytest.raises(Exception):
        fails("http://127.0.0.1:1/")


def test_a_javascript_only_page_is_reported_rather_than_guessed():
    site = map_site("/js-search?q=a")
    assert site.capabilities["search"] in ("unknown", "unsupported")
    assert any("javascript" in note.lower() for note in site.notes)
