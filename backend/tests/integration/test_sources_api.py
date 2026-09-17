"""Sources management API (Master §10, §13, §21 surfaces) on top of C3 services."""
import pytest
from starlette.testclient import TestClient

from oneshelf.api.app import AppConfig, create_app
from testsource.build import build_package

TS = "oneshelf.test-source"


@pytest.fixture
def api(tmp_path):
    config = AppConfig.from_env({"ONESHELF_DATA_DIR": str(tmp_path / "data"), "ONESHELF_ALLOWED_HOSTS": "testserver",
                                 "ONESHELF_SESSION_KEY_FILE": str(tmp_path / "keys" / "session.key")})
    with TestClient(create_app(config), client=("127.0.0.1", 50000)) as client:
        yield client, tmp_path


def upload(client, tmp_path):
    data = build_package(tmp_path / "ts.osp").read_bytes()
    r = client.post("/api/sources/uploads", content=data, headers={"Content-Type": "application/octet-stream"})
    assert r.status_code == 200, r.text
    return r.json()


def test_upload_review_then_install(api):
    client, tmp_path = api
    review = upload(client, tmp_path)
    assert review["id"] == TS and review["version"] == "1.0.0" and review["tests"]["passed"] is True
    assert "network:domain:testsource.example" in review["permissions"] and review["auth_available"] is True
    assert client.get("/api/sources").json()["sources"] == []  # inspecting installs nothing

    r = client.post("/api/sources/install", json={"upload_id": review["upload_id"], "approved_permissions": []})
    assert r.status_code == 200 and r.json()["state"] == "pending_review"
    r = client.post(f"/api/sources/{TS}/approve", json={"version": "1.0.0", "approved_permissions": review["permissions"]})
    assert r.json()["state"] == "active"

    sources = client.get("/api/sources").json()["sources"]
    assert sources[0]["id"] == TS and sources[0]["trust_label"] == "local" and sources[0]["session_state"] == "not_connected"
    assert set(sources[0]["capabilities"]) >= {"search", "catalog", "check_session"}


def test_invalid_upload_is_rejected(api):
    client, _ = api
    r = client.post("/api/sources/uploads", content=b"#!/bin/sh\n", headers={"Content-Type": "application/octet-stream"})
    assert r.status_code == 422 and r.json()["error"]["code"] == "INVALID_PACKAGE"


def test_management_actions_and_session_endpoints(api):
    client, tmp_path = api
    review = upload(client, tmp_path)
    client.post("/api/sources/install", json={"upload_id": review["upload_id"], "approved_permissions": review["permissions"]})
    assert client.post(f"/api/sources/{TS}/disable").json()["state"] == "disabled"
    assert client.post(f"/api/sources/{TS}/enable").json()["state"] == "active"
    assert client.post(f"/api/sources/{TS}/rollback").status_code == 409  # nothing to roll back to
    session = client.get(f"/api/sources/{TS}/session").json()
    assert session == {"source_id": TS, "state": "not_connected"}
    assert client.delete(f"/api/sources/{TS}/session").json()["state"] == "not_connected"
    assert client.get(f"/api/sources/{TS}/health").json() == {"source_id": TS, "signals": []}
    assert client.delete(f"/api/sources/{TS}").json()["state"] == "uninstalled"
    assert client.get("/api/sources").json()["sources"][0]["state"] == "uninstalled"


def test_unknown_upload_and_source_errors(api):
    client, _ = api
    assert client.post("/api/sources/install", json={"upload_id": "nope", "approved_permissions": []}).status_code == 404
    assert client.post("/api/sources/missing.plugin/disable").status_code == 404


def test_session_material_never_appears_in_responses(api):
    client, tmp_path = api
    review = upload(client, tmp_path)
    client.post("/api/sources/install", json={"upload_id": review["upload_id"], "approved_permissions": review["permissions"]})
    body = client.get("/api/sources").text + client.get(f"/api/sources/{TS}/session").text
    assert "cookie" not in body.lower() and "secrets.db" not in body


@pytest.mark.browser
def test_login_api_flow_with_test_source(tmp_path):
    import asyncio
    import threading

    from testsource.server import TestSourceServer

    ready, stop = threading.Event(), threading.Event()
    holder = {}

    def serve():
        async def main():
            async with TestSourceServer() as server:
                holder["port"] = server.port
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
        "ONESHELF_DEV_TEST_SOURCE": "1", "ONESHELF_DEV_TEST_SOURCE_ADDRESS": f"127.0.0.1:{holder['port']}",
    })
    try:
        with TestClient(create_app(config), client=("127.0.0.1", 50000)) as client:
            review = upload(client, tmp_path)
            client.post("/api/sources/install", json={"upload_id": review["upload_id"],
                                                      "approved_permissions": review["permissions"]})
            started = client.post(f"/api/sources/{TS}/login").json()
            assert started["status"] == "open"
            login_id = started["login_id"]
            frame = client.get(f"/api/logins/{login_id}/frame")
            assert frame.status_code == 200 and frame.headers["content-type"] == "image/jpeg" and frame.content[:2] == b"\xff\xd8"
            # Username field sits first on the Test Source form; Tab moves focus to the password field.
            assert client.post(f"/api/logins/{login_id}/input", json={"type": "key", "key": "Tab"}).status_code == 200
            client.post(f"/api/logins/{login_id}/input", json={"type": "type", "text": "reader"})
            client.post(f"/api/logins/{login_id}/input", json={"type": "key", "key": "Tab"})
            client.post(f"/api/logins/{login_id}/input", json={"type": "type", "text": "correct horse"})
            client.post(f"/api/logins/{login_id}/input", json={"type": "key", "key": "Enter"})
            done = client.post(f"/api/logins/{login_id}/complete").json()
            assert done["outcome"] == "connected"
            assert client.get(f"/api/sources/{TS}/session").json()["state"] == "connected"
            assert client.post(f"/api/sources/{TS}/session/validate").json()["state"] == "connected"
            assert client.delete(f"/api/sources/{TS}/session").json()["state"] == "not_connected"
    finally:
        stop.set()
        thread.join(10)
