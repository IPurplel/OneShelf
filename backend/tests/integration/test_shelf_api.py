"""C6 gate through the API: Shelf, Follow, notifications and health (Master §20-§23, §30, §44)."""
import asyncio
import threading
import time

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
                server.scenario.big_collapsed = True   # start small so growth produces new releases
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
        yield client, holder["server"], tmp_path
    stop.set()
    thread.join(10)


def control(server, **changes):
    async def send():
        async with aiohttp.ClientSession() as s:
            async with s.post(f"http://127.0.0.1:{server.port}/__control", json=changes) as r:
                assert r.status == 200
    asyncio.run(send())


def bind(client, listing_key, title, content_type="manhwa"):
    return client.post("/api/listings/bind", json={"source_id": TS, "listing_key": listing_key, "title": title,
                                                   "language": "en", "content_type": content_type}).json()


def test_shelf_actions_and_views(api):
    client, _, _ = api
    bound = bind(client, "irregular", "The Irregular Chronicle", content_type="manga")
    work = bound["work_id"]
    entry = client.post(f"/api/shelf/{work}", json={"favorite": True, "pinned": True}).json()
    assert entry["is_favorite"] and entry["is_pinned"]
    assert [e["work_id"] for e in client.get("/api/shelf?view=favorites").json()["entries"]] == [work]
    assert [e["work_id"] for e in client.get("/api/shelf?q=irregular").json()["entries"]] == [work]
    assert client.get("/api/shelf?q=مدرسة").json()["entries"] == []
    completed = client.post(f"/api/shelf/{work}", json={"completed": True}).json()
    assert completed["completed_at"] is not None
    assert [e["work_id"] for e in client.get("/api/shelf?view=completed").json()["entries"]] == [work]


def test_follow_reports_new_releases_and_notifies_without_downloading(api):
    client, server, _ = api
    bound = bind(client, "big", "A Very Long Saga")
    work, track = bound["work_id"], bound["track_id"]
    client.post(f"/api/tracks/{track}/catalog/refresh")
    followed = client.post(f"/api/follows/{work}", json={"language": "en", "source_id": TS, "track_id": track}).json()
    assert followed["baseline_units"] == 7 and followed["baseline_kind"] == "first_follow"
    assert client.post(f"/api/follows/{work}/check").json()["new_units"] == []

    control(server, big_collapsed=False)   # the source publishes the full catalog
    checked = client.post(f"/api/follows/{work}/check").json()
    assert len(checked["new_units"]) == 293 and checked["state"] == "new_releases"
    assert client.get("/api/downloads").json()["batches"] == []      # INV-09

    notifications = client.get("/api/notifications").json()
    release = next(n for n in notifications["notifications"] if n["dedupe_key"] == f"new-release:{work}")
    assert release["summary"].startswith("293 new releases")
    assert notifications["needs_attention"] == 0                      # releases are inbox items, not problems
    assert client.get("/api/follows").json()["follows"][0]["state"] == "new_releases"


def test_marking_notifications_seen_never_changes_reading_state(api):
    client, server, tmp_path = api
    bound = bind(client, "big", "A Very Long Saga")
    client.post(f"/api/tracks/{bound['track_id']}/catalog/refresh")
    client.post(f"/api/follows/{bound['work_id']}", json={"language": "en", "source_id": TS,
                                                          "track_id": bound["track_id"]})
    control(server, big_collapsed=False)
    client.post(f"/api/follows/{bound['work_id']}/check")

    from oneshelf.db.connection import open_database
    with open_database(tmp_path / "data" / "oneshelf.db") as conn:
        unit = conn.execute("SELECT id FROM reading_units LIMIT 1").fetchone()[0]
    client.post(f"/api/reader/units/{unit}/progress", json={"fraction": 0.4, "locator": {"page": 2}})

    assert client.post("/api/notifications/mark-all-seen").json()["updated"] >= 1
    with open_database(tmp_path / "data" / "oneshelf.db") as conn:
        state = conn.execute("SELECT read_state, fraction FROM reading_state WHERE reading_unit_id = ?",
                             (unit,)).fetchone()
    assert state["read_state"] == "partial" and state["fraction"] == pytest.approx(0.4)   # INV-22
    assert client.post("/api/notifications/clear-seen").json()["removed"] >= 1


def test_suspicious_catalog_raises_needs_attention_and_keeps_trusted_units(api):
    client, server, _ = api
    control(server, big_collapsed=False)
    bound = bind(client, "big", "A Very Long Saga")
    client.post(f"/api/tracks/{bound['track_id']}/catalog/refresh")
    client.post(f"/api/follows/{bound['work_id']}", json={"language": "en", "source_id": TS,
                                                          "track_id": bound["track_id"]})
    control(server, big_collapsed=True)
    checked = client.post(f"/api/follows/{bound['work_id']}/check").json()
    assert checked["catalog_state"] == "suspicious" and checked["new_units"] == []
    attention = client.get("/api/notifications?attention=true").json()
    assert [n["dedupe_key"] for n in attention["notifications"]] == [f"catalog-suspicious:{TS}"]
    assert client.get(f"/api/tracks/{bound['track_id']}/catalog").json()["trusted"]["unit_count"] == 300


def test_unfollow_undo_and_independence_from_shelf(api):
    client, _, _ = api
    bound = bind(client, "irregular", "The Irregular Chronicle", content_type="manga")
    work, track = bound["work_id"], bound["track_id"]
    client.post(f"/api/tracks/{track}/catalog/refresh")
    client.post(f"/api/shelf/{work}")
    client.post(f"/api/follows/{work}", json={"language": "en", "source_id": TS, "track_id": track})
    token = client.delete(f"/api/follows/{work}").json()["undo_token"]
    assert client.get("/api/follows").json()["follows"] == []
    assert client.get("/api/shelf").json()["entries"][0]["work_id"] == work     # INV-10
    restored = client.post("/api/follows/undo", json={"undo_token": token}).json()
    assert restored["track_id"] == track and len(client.get("/api/follows").json()["follows"]) == 1


def test_removal_summary_then_remove_keeps_follow_and_progress(api):
    client, _, tmp_path = api
    bound = bind(client, "irregular", "The Irregular Chronicle", content_type="manga")
    work, track = bound["work_id"], bound["track_id"]
    client.post(f"/api/tracks/{track}/catalog/refresh")
    client.post(f"/api/shelf/{work}")
    client.post(f"/api/follows/{work}", json={"language": "en", "source_id": TS, "track_id": track})
    summary = client.get(f"/api/shelf/{work}/removal-summary").json()
    assert summary["is_followed"] is True and summary["files"] == 0
    client.delete(f"/api/shelf/{work}")
    assert client.get("/api/shelf").json()["entries"] == []
    assert len(client.get("/api/follows").json()["follows"]) == 1


def test_health_state_reflects_recorded_signals(api):
    client, server, _ = api
    bound = bind(client, "paged", "Paged Archive", content_type="comic")
    control(server, paged_mode="fail_page_3")
    for _ in range(3):
        client.post(f"/api/tracks/{bound['track_id']}/catalog/refresh")
    health = client.get(f"/api/sources/{TS}/health/state").json()
    assert health["capabilities"]["catalog"]["state"] in ("degraded", "unavailable")
    assert health["capabilities"]["catalog"]["plugin_version"] == "1.0.0"
    control(server, paged_mode="normal")
    for _ in range(2):
        client.post(f"/api/tracks/{bound['track_id']}/catalog/refresh")
    assert client.get(f"/api/sources/{TS}/health/state").json()["capabilities"]["catalog"]["state"] == "healthy"


def test_notification_preferences_are_the_ones_the_service_honours(api):
    """§30.10: Source Recovered is optional and silent by default, and Settings can turn it on."""
    client = api[0] if isinstance(api, tuple) else api

    assert client.get("/api/notifications/settings").json() == {"source_recovered": False}
    assert client.post("/api/notifications/settings", json={"source_recovered": True}).status_code == 200
    assert client.get("/api/notifications/settings").json() == {"source_recovered": True}
