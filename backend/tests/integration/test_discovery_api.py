"""C4 gate through the API against the live OneShelf Test Source (Master §5, §6, §8, §31)."""
import asyncio
import json
import threading

import pytest
from starlette.testclient import TestClient

from oneshelf.api.app import AppConfig, create_app
from testsource.build import build_package
from testsource.server import TestSourceServer

TS = "oneshelf.test-source"


@pytest.fixture
def live(tmp_path):
    ready, stop, holder = threading.Event(), threading.Event(), {}

    def serve():
        async def main():
            async with TestSourceServer() as server:
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
        data = build_package(tmp_path / "ts.osp").read_bytes()
        review = client.post("/api/sources/uploads", content=data,
                             headers={"Content-Type": "application/octet-stream"}).json()
        installed = client.post("/api/sources/install", json={"upload_id": review["upload_id"],
                                                              "approved_permissions": review["permissions"]}).json()
        assert installed["state"] == "active"
        yield client, holder["server"]
    stop.set()
    thread.join(10)


def control(server, **changes):
    async def send():
        import aiohttp
        async with aiohttp.ClientSession() as s:
            async with s.post(f"http://127.0.0.1:{server.port}/__control", json=changes) as r:
                assert r.status == 200
    asyncio.run(send())


def sse_events(response):
    events, event, data = [], None, []
    for line in response.text.splitlines():
        if line.startswith("event: "):
            event = line[7:]
        elif line.startswith("data: "):
            data.append(line[6:])
        elif not line and event:
            events.append((event, json.loads(data[-1])))
            event, data = None, []
    return events


def bind(client, listing_key, title, language="en", content_type="manga"):
    return client.post("/api/listings/bind", json={"source_id": TS, "listing_key": listing_key, "title": title,
                                                   "language": language, "content_type": content_type}).json()


def test_search_streams_local_then_live_results(live):
    client, _ = live
    bind(client, "irregular", "The Irregular Chronicle")
    events = sse_events(client.get("/api/search?q=chronicle"))
    assert [e[0] for e in events][0] == "local" and [e[0] for e in events][-1] == "complete"
    local, complete = events[0][1], events[-1][1]
    assert [r["title"] for r in local["results"]] == ["The Irregular Chronicle"]  # library result first
    assert complete["sources_total"] == 1 and complete["sources_done"] == 1
    assert complete["source_status"][TS]["state"] == "done"
    result = next(r for r in complete["results"] if r["title"] == "The Irregular Chronicle")
    assert result["soft"] is False and result["provenance"][0]["source_id"] == TS
    assert result["availability"] == {"en": 1}


def test_search_uses_cache_on_the_second_call_and_refresh_bypasses_it(live):
    client, server = live
    client.get("/api/search?q=chronicle")
    before = len([r for r in server.scenario.request_log if r.startswith("testsource.example/search")])
    cached = sse_events(client.get("/api/search?q=chronicle"))[-1][1]
    assert cached["source_status"][TS]["state"] == "cached"
    assert len([r for r in server.scenario.request_log if r.startswith("testsource.example/search")]) == before
    refreshed = sse_events(client.get("/api/search?q=chronicle&refresh=true"))[-1][1]
    assert refreshed["source_status"][TS]["state"] == "done"


def test_direct_url_entry_previews_without_persisting(live):
    client, _ = live
    response = client.post("/api/resolve-url", json={"url": "http://testsource.example/work/irregular"})
    assert response.status_code == 200
    body = response.json()
    assert body["identifier"] == "irregular" and body["details"]["title"] == "The Irregular Chronicle"
    assert body["result"]["provenance"][0]["listing_key"] == "irregular"
    assert client.post("/api/resolve-url", json={"url": "http://unknown.example/x"}).status_code == 422


def test_catalog_refresh_collapse_and_explicit_trust(live):
    client, server = live
    track = bind(client, "big", "A Very Long Saga", content_type="manhwa")["track_id"]
    first = client.post(f"/api/tracks/{track}/catalog/refresh").json()
    assert first["state"] == "trusted" and first["unit_count"] == 300

    control(server, big_collapsed=True)
    collapsed = client.post(f"/api/tracks/{track}/catalog/refresh").json()
    assert collapsed["state"] == "suspicious" and collapsed["lost"] == 293
    state = client.get(f"/api/tracks/{track}/catalog").json()
    assert state["trusted"]["unit_count"] == 300 and state["suspicious"]["unit_count"] == 7

    trusted = client.post(f"/api/tracks/{track}/catalog/trust", json={"snapshot_id": collapsed["snapshot_id"]}).json()
    assert trusted["state"] == "trusted" and trusted["unit_count"] == 7
    assert client.get(f"/api/tracks/{track}/catalog").json()["trusted"]["unit_count"] == 7


def test_incomplete_catalog_never_replaces_trusted_state(live):
    client, server = live
    track = bind(client, "paged", "Paged Archive", content_type="comic")["track_id"]
    assert client.post(f"/api/tracks/{track}/catalog/refresh").json()["unit_count"] == 120
    control(server, paged_mode="fail_page_3")
    outcome = client.post(f"/api/tracks/{track}/catalog/refresh").json()
    assert outcome["state"] == "incomplete" and outcome["reason"] == "server_error"
    assert client.get(f"/api/tracks/{track}/catalog").json()["trusted"]["unit_count"] == 120
    with pytest.raises(Exception):
        client.post(f"/api/tracks/{track}/catalog/trust", json={"snapshot_id": outcome["snapshot_id"]}).raise_for_status()


def test_mapping_actions_persist_and_are_honoured(live):
    client, _ = live
    first = bind(client, "irregular", "The Irregular Chronicle")
    second = bind(client, "arabic", "حكاية القمر", language="ar")
    merged = client.post("/api/mappings/merge", json={"work_id": first["work_id"], "other_work_id": second["work_id"]})
    assert merged.status_code == 200
    unlinked = client.post("/api/mappings/unlink", json={"listing_id": second["listing_id"]}).json()
    assert unlinked["work_id"] is None
    split = client.post("/api/mappings/split", json={"listing_id": second["listing_id"], "title": "Moon Tale"}).json()
    assert split["work_id"] != first["work_id"]
    never = client.post("/api/mappings/never-match", json={"listing_id": first["listing_id"], "work_id": split["work_id"]})
    assert never.status_code == 200


def test_home_hides_sections_without_source_data(live):
    client, _ = live
    body = client.get("/api/home").json()
    assert body["trending"] == [] and body["latest"] == []  # Test Source provides neither capability
    assert body["hero"] is None and body["recently_added"] == []


def test_binding_the_same_listing_twice_reuses_its_work(live):
    client, _ = live
    first = bind(client, "big", "A Very Long Saga", content_type="manhwa")
    second = bind(client, "big", "A Very Long Saga", content_type="manhwa")
    assert (second["work_id"], second["track_id"], second["listing_id"]) == \
           (first["work_id"], first["track_id"], first["listing_id"])
    results = sse_events(client.get("/api/search?q=saga"))[-1][1]["results"]
    assert [r["title"] for r in results] == ["A Very Long Saga"]  # one logical Work, not duplicated
