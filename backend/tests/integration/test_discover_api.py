"""Discover: browse a source's own lists one page at a time, and two honest surprises."""
import asyncio
import threading

import aiohttp
import pytest
from starlette.testclient import TestClient

from oneshelf.api.app import AppConfig, create_app
from testsource.build import build_package
from testsource.server import TestSourceServer

TS = "oneshelf.test-source"


@pytest.fixture
def api(tmp_path):
    ready, stop, holder = threading.Event(), threading.Event(), {}

    def serve():
        async def main():
            async with TestSourceServer(scenario=None) as server:
                holder["server"] = server
                ready.set()
                while not stop.is_set():
                    await asyncio.sleep(0.05)
        asyncio.run(main())

    thread = threading.Thread(target=serve, daemon=True)
    thread.start()
    assert ready.wait(10)
    config = AppConfig.from_env({
        "ONESHELF_DATA_DIR": str(tmp_path / "data"), "ONESHELF_ALLOWED_HOSTS": "testserver",
        "ONESHELF_SESSION_KEY_FILE": str(tmp_path / "keys" / "session.key"),
        "ONESHELF_DEV_TEST_SOURCE": "1", "ONESHELF_DEV_TEST_SOURCE_ADDRESS": f"127.0.0.1:{holder['server'].port}",
    })
    with TestClient(create_app(config), client=("127.0.0.1", 50000)) as client:
        data = build_package(tmp_path / "ts.osp", discover=True).read_bytes()
        review = client.post("/api/sources/uploads", content=data,
                             headers={"Content-Type": "application/octet-stream"}).json()
        installed = client.post("/api/sources/install", json={"upload_id": review["upload_id"],
                                                               "approved_permissions": review["permissions"]})
        assert installed.status_code == 200, installed.text
        yield client, holder["server"]
    stop.set()
    thread.join(10)


def control(server, **changes):
    async def send():
        async with aiohttp.ClientSession() as s:
            async with s.post(f"http://127.0.0.1:{server.port}/__control", json=changes) as r:
                assert r.status == 200
    asyncio.run(send())


def titles(page):
    return [item["title"] for item in page["items"]]


def test_sources_that_offer_browsing_are_listed_with_their_feeds(api):
    client, _ = api
    sources = client.get("/api/discover/sources").json()["sources"]
    assert [(s["source_id"], s["feeds"]) for s in sources] == [(TS, ["latest", "trending"])]
    assert sources[0]["name"] == "OneShelf Test Source"


def test_a_feed_is_read_one_page_at_a_time_until_it_ends(api):
    client, _ = api
    first = client.get("/api/discover/list", params={"source": TS, "kind": "latest", "page": 1}).json()
    second = client.get("/api/discover/list", params={"source": TS, "kind": "latest", "page": 2}).json()
    assert len(first["items"]) == 4 and first["has_more"] is True and first["page"] == 1
    assert set(titles(first)).isdisjoint(titles(second))
    last = first
    for page in range(2, 10):
        last = client.get("/api/discover/list", params={"source": TS, "kind": "latest", "page": page}).json()
        if not last["has_more"]:
            break
    assert last["has_more"] is False


def test_a_page_already_read_comes_from_the_cache(api):
    client, server = api
    params = {"source": TS, "kind": "trending", "page": 1}
    assert client.get("/api/discover/list", params=params).json()["cached"] is False
    control(server, browse_broken=True)
    again = client.get("/api/discover/list", params=params)
    assert again.status_code == 200 and again.json()["cached"] is True


def test_works_already_on_the_shelf_say_so(api):
    client, _ = api
    bound = client.post("/api/listings/bind", json={"source_id": TS, "listing_key": "irregular",
                                                    "title": "The Irregular Chronicle", "language": "en",
                                                    "content_type": "manga"}).json()
    client.post(f"/api/shelf/{bound['work_id']}")
    page = client.get("/api/discover/list", params={"source": TS, "kind": "trending", "page": 1}).json()
    chronicle = next(i for i in page["items"] if i["title"] == "The Irregular Chronicle")
    assert chronicle["on_shelf"] is True and chronicle["work_id"] == bound["work_id"]
    assert all(not i["on_shelf"] for i in page["items"] if i is not chronicle)


def test_a_feed_that_fails_says_so_plainly(api):
    client, server = api
    control(server, browse_broken=True)
    failed = client.get("/api/discover/list", params={"source": TS, "kind": "latest", "page": 1})
    assert failed.status_code == 502
    assert failed.json()["error"]["code"] == "SOURCE_FAILED" and failed.json()["error"]["category"]


@pytest.mark.parametrize("params, status", [
    ({"source": TS, "kind": "genres", "page": 1}, 422),
    ({"source": TS, "kind": "latest", "page": 0}, 422),
    ({"source": "oneshelf.nowhere", "kind": "latest", "page": 1}, 404),
])
def test_a_feed_request_that_cannot_be_answered_is_refused(api, params, status):
    client, _ = api
    assert client.get("/api/discover/list", params=params).status_code == status


def test_a_surprise_from_the_sources_is_never_already_on_the_shelf_and_says_where_it_came_from(api):
    client, _ = api
    for key, title in (("irregular", "The Irregular Chronicle"), ("paged", "Paged Archive")):
        bound = client.post("/api/listings/bind", json={"source_id": TS, "listing_key": key, "title": title,
                                                        "language": "en"}).json()
        client.post(f"/api/shelf/{bound['work_id']}")
    for _ in range(5):
        pick = client.get("/api/discover/random", params={"from": "sources"}).json()
        assert pick["item"] is not None and pick["item"]["on_shelf"] is False
        assert pick["reason"]["source_id"] == TS and pick["reason"]["kind"] in ("latest", "trending")
        assert pick["reason"]["source_name"] == "OneShelf Test Source"


def test_a_surprise_from_the_shelf_is_a_work_not_started_yet(api):
    client, _ = api
    assert client.get("/api/discover/random", params={"from": "library"}).json() == {"item": None, "reason": None}
    bound = client.post("/api/listings/bind", json={"source_id": TS, "listing_key": "novel", "title": "A Quiet Novel",
                                                    "language": "en", "content_type": "novel"}).json()
    client.post(f"/api/shelf/{bound['work_id']}")
    pick = client.get("/api/discover/random", params={"from": "library"}).json()
    assert pick["item"]["work_id"] == bound["work_id"] and pick["reason"] == {"kind": "not_started"}
    assert client.get("/api/discover/random", params={"from": "library", "content_type": "manga"}).json()["item"] is None
