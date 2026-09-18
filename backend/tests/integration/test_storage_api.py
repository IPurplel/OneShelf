"""C7 gate through the API: storage, import, backup, restore and export."""
import json
import zipfile
from pathlib import Path

import pytest
from starlette.testclient import TestClient

from oneshelf.api.app import AppConfig, create_app
from tests.fixtures.builders import make_cbz


@pytest.fixture
def api(tmp_path):
    config = AppConfig.from_env({"ONESHELF_DATA_DIR": str(tmp_path / "data"), "ONESHELF_ALLOWED_HOSTS": "testserver",
                                 "ONESHELF_SESSION_KEY_FILE": str(tmp_path / "keys" / "session.key")})
    with TestClient(create_app(config), client=("127.0.0.1", 50000)) as client:
        (tmp_path / "library").mkdir()
        root = client.post("/api/storage/roots", json={"name": "Library", "path": str(tmp_path / "library")}).json()
        yield client, tmp_path, root


def import_cbz(client, tmp_path, title="Imported Work", name="chapter.cbz"):
    path = make_cbz(tmp_path / name)
    review = client.post(f"/api/import/uploads?filename={name}", content=path.read_bytes(),
                         headers={"Content-Type": "application/octet-stream"}).json()
    return review, client.post("/api/import", json={"upload_id": review["upload_id"], "title": title,
                                                    "content_type": "manga", "language": "en"}).json()


def test_storage_overview_and_scan(api):
    client, tmp_path, root = api
    overview = client.get("/api/storage").json()
    assert overview["roots"][0]["id"] == root["id"] and overview["roots"][0]["available"] is True
    assert overview["roots"][0]["free"] > 0 and overview["roots"][0]["reserve"] > 0
    assert client.post("/api/storage/scan").json()["missing"] == 0


def test_import_upload_review_and_commit(api):
    client, tmp_path, _ = api
    review, outcome = import_cbz(client, tmp_path)
    assert review["format"] == "cbz" and review["page_count"] == 3 and review["suggested_title"] == "chapter"
    assert review["suggestions"] == []           # nothing in the library to associate with yet
    assert outcome["asset_id"] and outcome["path"].endswith(".cbz")
    assert (tmp_path / "library" / outcome["path"]).exists()

    again, _ = import_cbz(client, tmp_path, name="Imported Work.cbz")
    assert again["suggested_title"] == "Imported Work"
    assert again["suggestions"][0]["work_id"] == outcome["work_id"]
    assert again["suggestions"][0]["confident"] is True


def test_unsupported_import_is_rejected(api):
    client, tmp_path, _ = api
    response = client.post("/api/import/uploads", content=b"<html>not a book</html>",
                           headers={"Content-Type": "application/octet-stream"})
    assert response.status_code == 422 and response.json()["error"]["code"] == "UNSUPPORTED_FILE"


def test_backup_restore_round_trip(api):
    client, tmp_path, _ = api
    _, outcome = import_cbz(client, tmp_path)
    created = client.post("/api/backups", json={"kind": "full", "works": [outcome["work_id"]]}).json()
    assert Path(created["path"]).exists() and created["kind"] == "full"
    listing = client.get("/api/backups").json()
    assert listing["due"] is False and listing["location_warning"]["same_device_as_library"] is True
    # The list is read by a person: how big the archive is, and whether the file is still there (§33.4).
    entry = listing["backups"][0]
    assert entry["size_bytes"] == Path(created["path"]).stat().st_size
    assert entry["present"] is True

    client.delete(f"/api/shelf/{outcome['work_id']}")
    assert client.get("/api/shelf").json()["entries"] == []

    preflight = client.post("/api/restore/preflight", json={"path": created["path"]}).json()
    assert preflight["compatible"] is True and preflight["counts"]["works"] == 1
    report = client.post("/api/restore", json={"path": created["path"], "mode": "merge"}).json()
    assert report["added"].get("shelf_entries") == 1
    assert client.get("/api/shelf").json()["entries"][0]["work_id"] == outcome["work_id"]


def test_export_preview_and_run(api):
    client, tmp_path, _ = api
    _, outcome = import_cbz(client, tmp_path)
    destination = tmp_path / "usb"
    destination.mkdir()
    body = {"work_id": outcome["work_id"], "language": "en", "source_id": "local",
            "unit_ids": [outcome["reading_unit_id"]], "destination": str(destination)}
    preview = client.post("/api/export/preview", json=body).json()
    assert preview["files"] == 1 and preview["missing_units"] == [] and preview["disclosure"] is None
    report = client.post("/api/export", json=body).json()
    assert report["state"] == "completed" and report["copied"] == 1
    exported = list(destination.rglob("*.cbz"))
    assert len(exported) == 1 and zipfile.is_zipfile(exported[0])
    metadata = json.loads((exported[0].parent / "oneshelf-export.json").read_text())
    assert metadata["source"] == "local" and metadata["units"][0]["files"][0]["sha256"]
    assert client.delete("/api/export/history").json()["removed"] == 0     # recent job is kept


def test_export_accepts_several_selected_works(api):
    client, tmp_path, _ = api
    first = import_cbz(client, tmp_path, title="First Work", name="first.cbz")[1]
    second = import_cbz(client, tmp_path, title="Second Work", name="second.cbz")[1]
    destination = tmp_path / "usb-many"
    destination.mkdir()
    body = {"destination": str(destination),
            "works": [{"work_id": w["work_id"], "language": "en", "source_id": "local",
                       "unit_ids": [w["reading_unit_id"]]} for w in (first, second)]}
    assert client.post("/api/export/preview", json=body).json()["files"] == 2
    report = client.post("/api/export", json=body).json()
    assert report["state"] == "completed" and report["copied"] == 2
    assert sorted(p.name for p in destination.iterdir()) == ["First Work (en)", "Second Work (en)"]
