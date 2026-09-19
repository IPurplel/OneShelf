"""Downloads and Reader API against the live Test Source (Master §16, §19, §26, §27; INV-07, INV-23)."""
import asyncio
import threading
import time

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
        client.post("/api/sources/install", json={"upload_id": review["upload_id"],
                                                  "approved_permissions": review["permissions"]})
        client.post("/api/storage/roots", json={"name": "Library", "path": str(tmp_path / "library")}) \
            if False else None
        yield client, tmp_path
    stop.set()
    thread.join(10)


def prepare(client, tmp_path, listing_key="irregular", title="The Irregular Chronicle", content_type="manga"):
    """Register a storage root directly, bind the listing and refresh its catalog."""
    from oneshelf.db.connection import open_database
    from oneshelf.storage.roots import list_roots, register_root

    library = tmp_path / "library"
    library.mkdir(exist_ok=True)
    with open_database(tmp_path / "data" / "oneshelf.db") as conn:
        if not list_roots(conn):
            register_root(conn, "Library", library)
    bound = client.post("/api/listings/bind", json={"source_id": TS, "listing_key": listing_key, "title": title,
                                                    "language": "en", "content_type": content_type}).json()
    client.post(f"/api/tracks/{bound['track_id']}/catalog/refresh")
    return bound


def unit_ids(client, tmp_path, keys):
    from oneshelf.db.connection import open_database

    with open_database(tmp_path / "data" / "oneshelf.db") as conn:
        return [conn.execute("SELECT id FROM reading_units WHERE source_unit_key = ?", (k,)).fetchone()[0] for k in keys]


def wait_for_state(client, batch_id, state, timeout=30):
    deadline = time.time() + timeout
    while time.time() < deadline:
        body = client.get(f"/api/downloads/{batch_id}").json()
        if body["state"] == state:
            return body
        time.sleep(0.2)
    raise AssertionError(f"batch stayed in {body['state']!r}")


def test_enqueue_and_complete_a_download_then_read_it_locally(api):
    client, tmp_path = api
    prepare(client, tmp_path)
    units = unit_ids(client, tmp_path, ["irr-1"])
    batch = client.post("/api/downloads", json={"unit_ids": units}).json()
    assert batch["state"] in ("active", "completed")
    done = wait_for_state(client, batch["batch_id"], "completed")
    assert done["completed"] == 1 and done["failed"] == 0

    pages = client.get(f"/api/reader/units/{units[0]}/pages").json()
    assert len(pages["pages"]) == 3
    page = client.get(f"/api/reader/units/{units[0]}/pages/1")
    assert page.status_code == 200 and page.headers["x-oneshelf-origin"] == "local"
    assert "sandbox" in page.headers["content-security-policy"] and page.headers["x-content-type-options"] == "nosniff"
    assert page.content[:8] == b"\x89PNG\r\n\x1a\n"


def test_reading_online_is_not_a_download(api):
    client, tmp_path = api
    prepare(client, tmp_path)
    units = unit_ids(client, tmp_path, ["irr-2"])
    page = client.get(f"/api/reader/units/{units[0]}/pages/1")
    assert page.status_code == 200 and page.headers["x-oneshelf-origin"] == "online"
    again = client.get(f"/api/reader/units/{units[0]}/pages/1")
    assert again.headers["x-oneshelf-origin"] == "cache"
    assert client.get("/api/downloads").json()["batches"] == []   # INV-07


def test_progress_endpoints_and_stale_writes(api):
    client, tmp_path = api
    prepare(client, tmp_path)
    unit = unit_ids(client, tmp_path, ["irr-1"])[0]
    first = client.post(f"/api/reader/units/{unit}/progress", json={"locator": {"page": 2}, "fraction": 0.2}).json()
    assert first["read_state"] == "partial" and first["revision"] == 1
    stale = client.post(f"/api/reader/units/{unit}/progress",
                        json={"locator": {"page": 1}, "fraction": 0.1, "revision": 0})
    assert stale.status_code == 409 and stale.json()["error"]["code"] == "STALE_PROGRESS"
    assert client.post(f"/api/reader/units/{unit}/mark-unread").json()["read_state"] == "unread"


def test_auto_download_stays_off_by_default(api):
    client, tmp_path = api
    prepare(client, tmp_path)
    unit = unit_ids(client, tmp_path, ["irr-2"])[0]
    body = client.post(f"/api/reader/units/{unit}/engagement", json={"fraction": 0.9, "interacted": True}).json()
    assert body["queued"] == [] and client.get("/api/downloads").json()["batches"] == []


def test_batch_controls_and_history_clearing(api):
    client, tmp_path = api
    bound = prepare(client, tmp_path)
    units = unit_ids(client, tmp_path, ["irr-1", "irr-2", "irr-3"])
    batch = client.post("/api/downloads", json={"unit_ids": units}).json()
    client.post(f"/api/downloads/{batch['batch_id']}/pause")
    paused = client.get(f"/api/downloads/{batch['batch_id']}").json()
    assert paused["state"] == "paused"
    client.post(f"/api/downloads/{batch['batch_id']}/resume")
    done = wait_for_state(client, batch["batch_id"], "completed")
    assert done["completed"] == 3

    removed = client.delete("/api/downloads/history").json()["removed"]
    assert removed == 3
    page = client.get(f"/api/reader/units/{units[0]}/pages/1")
    assert page.status_code == 200 and page.headers["x-oneshelf-origin"] == "local"  # content survived (INV-23)


def test_download_settings_are_the_ones_the_engine_actually_reads(api):
    """§19, §16.6, §14: Settings shows knobs the engine honours — nothing invented in the UI."""
    client = api[0] if isinstance(api, tuple) else api

    defaults = client.get("/api/downloads/settings")
    assert defaults.status_code == 200, defaults.text
    body = defaults.json()
    assert body["auto_download"] == {"enabled": False, "mode": "current", "read_ahead": 5, "threshold": 0.12}
    assert body["keep_partial_on_cancel"] is False
    assert body["extraction"]["mode"] == "preferred_ask"

    changed = client.post("/api/downloads/settings", json={
        "auto_download": {"enabled": True, "mode": "read_ahead", "read_ahead": 3},
        "keep_partial_on_cancel": True,
        "extraction": {"method": "direct", "mode": "strict"},
    })
    assert changed.status_code == 200, changed.text
    again = client.get("/api/downloads/settings").json()
    assert again["auto_download"] == {"enabled": True, "mode": "read_ahead", "read_ahead": 3, "threshold": 0.12}
    assert again["keep_partial_on_cancel"] is True
    assert again["extraction"]["method"] == "direct" and again["extraction"]["mode"] == "strict"

    assert client.post("/api/downloads/settings",
                       json={"extraction": {"method": "telepathy"}}).status_code == 422
    assert client.post("/api/downloads/settings",
                       json={"auto_download": {"read_ahead": 99}}).status_code == 422


def test_reordering_a_queue_reaches_the_engine(api):
    """§16.1: a reader can reorder a queue. The endpoint was unreachable behind `{action}` (I-15)."""
    client, tmp_path = api
    prepare(client, tmp_path)
    units = unit_ids(client, tmp_path, ["irr-1", "irr-2", "irr-3"])
    batch = client.post("/api/downloads", json={"unit_ids": units}).json()
    client.post(f"/api/downloads/{batch['batch_id']}/pause")

    jobs = client.get(f"/api/downloads/{batch['batch_id']}").json()["jobs"]
    reversed_ids = [job["id"] for job in jobs][::-1]

    response = client.post(f"/api/downloads/{batch['batch_id']}/reorder", json={"job_ids": reversed_ids})
    assert response.status_code == 200, response.text
    assert response.json().get("error") is None

    after = [job["id"] for job in client.get(f"/api/downloads/{batch['batch_id']}").json()["jobs"]]
    assert after == reversed_ids
