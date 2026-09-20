"""The interface is served from the same origin as the API (§2.1, §27, §28).

In development Vite proxies to the backend; in a container there is one process and one origin, so the
built SPA has to come from here. What matters is that serving it changes none of the boundaries: the
access classifier still decides who gets in, the API still answers as the API, and nothing under the
web root can be used to read a file that is not part of it.
"""
from pathlib import Path

import pytest
from starlette.testclient import TestClient

from oneshelf.api.app import AppConfig, create_app


@pytest.fixture
def web_root(tmp_path):
    root = tmp_path / "web"
    (root / "assets").mkdir(parents=True)
    (root / "index.html").write_text("<!doctype html><title>OneShelf</title><div id=root></div>", encoding="utf-8")
    (root / "assets" / "app.js").write_text("console.log('oneshelf')", encoding="utf-8")
    (root / "favicon.svg").write_text("<svg/>", encoding="utf-8")
    (tmp_path / "secret.txt").write_text("not part of the interface", encoding="utf-8")
    return root


def client_for(tmp_path, web_root, host="127.0.0.1", **extra):
    config = AppConfig.from_env({
        "ONESHELF_DATA_DIR": str(tmp_path / "data"),
        "ONESHELF_ALLOWED_HOSTS": "testserver",
        "ONESHELF_SESSION_KEY_FILE": str(tmp_path / "keys" / "session.key"),
        "ONESHELF_WEB_ROOT": str(web_root) if web_root else "",
        **extra,
    })
    return TestClient(create_app(config), client=(host, 50000))


def test_the_interface_is_served_at_the_root(tmp_path, web_root):
    with client_for(tmp_path, web_root) as client:
        response = client.get("/")
    assert response.status_code == 200
    assert "<div id=root>" in response.text
    assert response.headers["content-type"].startswith("text/html")


def test_its_assets_are_served_too(tmp_path, web_root):
    with client_for(tmp_path, web_root) as client:
        asset = client.get("/assets/app.js")
    assert asset.status_code == 200 and "oneshelf" in asset.text


def test_a_client_route_falls_back_to_the_interface_rather_than_404(tmp_path, web_root):
    """The SPA owns its own routing: /shelf is a screen, not a file (§32)."""
    with client_for(tmp_path, web_root) as client:
        for path in ("/shelf", "/works/abc", "/settings/storage"):
            response = client.get(path)
            assert response.status_code == 200, path
            assert "<div id=root>" in response.text, path


def test_the_api_still_answers_as_the_api(tmp_path, web_root):
    """A missing API route is a JSON 404, never the interface pretending everything is fine."""
    with client_for(tmp_path, web_root) as client:
        assert client.get("/api/health").json()["status"] == "ok"
        missing = client.get("/api/does-not-exist")
        assert missing.status_code == 404
        assert "<div id=root>" not in missing.text


@pytest.mark.parametrize("path", ["/../secret.txt", "/assets/../../secret.txt", "/%2e%2e/secret.txt"])
def test_nothing_outside_the_web_root_can_be_reached(tmp_path, web_root, path):
    with client_for(tmp_path, web_root) as client:
        response = client.get(path)
    assert "not part of the interface" not in response.text


def test_the_interface_is_behind_the_same_boundary_as_everything_else(tmp_path, web_root):
    """K4: a remote client is refused before it reaches anything, the interface included (§28)."""
    with client_for(tmp_path, web_root, host="203.0.113.50",
                    ONESHELF_TRUSTED_NETWORKS="192.168.1.0/24") as client:
        for path in ("/", "/shelf", "/assets/app.js"):
            response = client.get(path)
            assert response.status_code == 401, path
            assert response.json()["error"]["code"] == "REMOTE_AUTH_REQUIRED"


def test_without_a_built_interface_the_api_still_runs(tmp_path):
    """A source checkout has no `dist/` until it is built; that must not stop the API from serving."""
    with client_for(tmp_path, None) as client:
        assert client.get("/api/health").status_code == 200
        assert client.get("/").status_code == 404
