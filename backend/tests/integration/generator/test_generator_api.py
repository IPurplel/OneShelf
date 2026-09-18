"""Master §12.2–12.3 over HTTP: preview, tests, Generate, submission bundle, repair — each explicit."""
import zipfile

import pytest
from starlette.testclient import TestClient

from oneshelf.api.app import AppConfig, create_app
from testsource.server import HOST, BackgroundTestSource


@pytest.fixture
def live(tmp_path):
    """The app with the Test Source running, exactly as a developer's dev instance would be."""
    with BackgroundTestSource() as server:
        config = AppConfig.from_env({
            "ONESHELF_DATA_DIR": str(tmp_path / "data"),
            "ONESHELF_ALLOWED_HOSTS": "testserver",
            "ONESHELF_SESSION_KEY_FILE": str(tmp_path / "keys" / "session.key"),
            "ONESHELF_DEV_TEST_SOURCE": "1",
            "ONESHELF_DEV_TEST_SOURCE_ADDRESS": server.address(),
        })
        with TestClient(create_app(config), client=("127.0.0.1", 50000)) as client:
            yield client


def start_draft(live, path=f"http://{HOST}/gen/search?q=a"):
    return live.post("/api/generator/drafts", json={"url": path, "name": "Generated Test Source"})


def test_discovery_preview_shows_recipes_confidence_and_every_fetch(live):
    created = start_draft(live)
    assert created.status_code == 200
    draft_id = created.json()["id"]

    preview = live.get(f"/api/generator/drafts/{draft_id}").json()
    assert preview["manifest"]["network"]["domains"] == [HOST]
    assert set(preview["recipes"]) == {"search", "work", "catalog", "reader"}
    assert preview["confidence"]["search"] in ("confirmed", "probable")
    assert preview["fetches"] and all("url" in f and "status" in f for f in preview["fetches"])
    assert live.get("/api/generator/drafts").json()["drafts"][0]["id"] == draft_id


def test_tests_run_before_anything_is_generated(live):
    draft_id = start_draft(live).json()["id"]
    report = live.post(f"/api/generator/drafts/{draft_id}/test").json()
    assert report["passed"] is True and report["cases"] >= 1


def test_generate_writes_a_package_and_does_not_install_it(live, tmp_path):
    draft_id = start_draft(live).json()["id"]
    generated = live.post(f"/api/generator/drafts/{draft_id}/generate").json()
    assert generated["path"].endswith(".osp") and zipfile.is_zipfile(generated["path"])
    assert generated["installed"] is False
    assert live.get("/api/sources").json()["sources"] == []          # §12.3: Generate != Install


def test_a_submission_bundle_is_prepared_locally_and_never_published(live):
    draft_id = start_draft(live).json()["id"]
    live.post(f"/api/generator/drafts/{draft_id}/generate")
    bundle = live.post(f"/api/generator/drafts/{draft_id}/submission").json()
    assert bundle["published"] is False and bundle["path"].endswith(".zip")
    with zipfile.ZipFile(bundle["path"]) as archive:
        names = set(archive.namelist())
    assert "submission.json" in names and any(n.endswith(".osp") for n in names)


def test_an_unsupported_site_is_reported_not_faked(live):
    created = start_draft(live, f"http://{HOST}/js-search?q=a")
    body = created.json()
    assert created.status_code == 200
    preview = live.get(f"/api/generator/drafts/{body['id']}").json()
    assert "search" in preview["unsupported"]
    assert any("javascript" in note.lower() for note in preview["notes"])


def test_repair_diffs_and_validates_before_the_developer_installs(live):
    draft_id = start_draft(live).json()["id"]
    generated = live.post(f"/api/generator/drafts/{draft_id}/generate").json()
    permissions = live.get(f"/api/generator/drafts/{draft_id}").json()["permissions"]
    installed = live.post(f"/api/generator/drafts/{draft_id}/install",
                          json={"approved_permissions": permissions})
    assert installed.status_code == 200, installed.text
    plugin_id = installed.json()["plugin_id"]

    live.post("/api/generator/test-source/markup", json={"version": 2})
    response = live.post(f"/api/generator/repair/{plugin_id}/diagnose")
    assert response.status_code == 200, response.text
    assert response.json()["broken"] == ["catalog"]

    repaired = live.post(f"/api/generator/repair/{plugin_id}").json()
    assert repaired["validated"] is True and repaired["version"] == "0.1.1"
    assert any(change["capability"] == "catalog" for change in repaired["changes"])
    assert repaired["installed"] is False                              # activation stays an explicit action

    activated = live.post(f"/api/generator/repair/{plugin_id}/activate",
                          json={"path": repaired["path"], "approved_permissions": permissions})
    assert activated.status_code == 200 and activated.json()["version"] == "0.1.1"
