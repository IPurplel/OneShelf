"""Bookmarks and highlights (Master §26.22): a reader's own marks, kept where the library keeps state."""
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
        client.post("/api/storage/roots", json={"name": "Library", "path": str(tmp_path / "library")})
        yield client, tmp_path


def import_unit(client, tmp_path, name="one.cbz"):
    path = make_cbz(tmp_path / name)
    review = client.post(f"/api/import/uploads?filename={name}", content=path.read_bytes(),
                         headers={"Content-Type": "application/octet-stream"}).json()
    return client.post("/api/import", json={"upload_id": review["upload_id"], "title": "The Manual",
                                            "language": "en"}).json()


def test_a_bookmark_is_kept_with_the_library_not_in_a_browser(api):
    client, tmp_path = api
    unit = import_unit(client, tmp_path)["reading_unit_id"]

    made = client.post(f"/api/reader/units/{unit}/bookmarks", json={"locator": {"chapter": 2}, "label": "Chapter 3"})
    assert made.status_code == 200, made.text
    marks = client.get(f"/api/reader/units/{unit}/marks").json()
    assert [b["label"] for b in marks["bookmarks"]] == ["Chapter 3"]
    assert marks["bookmarks"][0]["locator"] == {"chapter": 2}
    assert marks["highlights"] == []

    client.delete(f"/api/reader/bookmarks/{made.json()['id']}")
    assert client.get(f"/api/reader/units/{unit}/marks").json()["bookmarks"] == []


def test_a_highlight_keeps_the_text_it_was_made_from(api):
    client, tmp_path = api
    unit = import_unit(client, tmp_path)["reading_unit_id"]

    made = client.post(f"/api/reader/units/{unit}/highlights",
                       json={"locator": {"chapter": 1, "start": 40, "end": 61}, "text": "a sentence worth keeping"})
    assert made.status_code == 200, made.text
    highlight = client.get(f"/api/reader/units/{unit}/marks").json()["highlights"][0]
    assert highlight["text"] == "a sentence worth keeping"
    assert highlight["locator"]["start"] == 40

    client.delete(f"/api/reader/highlights/{highlight['id']}")
    assert client.get(f"/api/reader/units/{unit}/marks").json()["highlights"] == []


def test_the_same_place_is_not_bookmarked_twice(api):
    client, tmp_path = api
    unit = import_unit(client, tmp_path)["reading_unit_id"]

    first = client.post(f"/api/reader/units/{unit}/bookmarks", json={"locator": {"chapter": 2}, "label": "Chapter 3"})
    again = client.post(f"/api/reader/units/{unit}/bookmarks", json={"locator": {"chapter": 2}, "label": "Chapter 3"})
    assert again.json()["id"] == first.json()["id"]
    assert len(client.get(f"/api/reader/units/{unit}/marks").json()["bookmarks"]) == 1


def test_marks_for_a_unit_that_does_not_exist_are_refused(api):
    client, _ = api
    response = client.post("/api/reader/units/nope/bookmarks", json={"locator": {"chapter": 1}, "label": "x"})
    assert response.status_code == 404 and response.json()["error"]["code"] == "UNIT_NOT_FOUND"


def test_marks_travel_in_a_library_backup(api):
    client, tmp_path = api
    unit = import_unit(client, tmp_path)["reading_unit_id"]
    client.post(f"/api/reader/units/{unit}/bookmarks", json={"locator": {"chapter": 2}, "label": "Chapter 3"})
    client.post(f"/api/reader/units/{unit}/highlights", json={"locator": {"chapter": 1}, "text": "kept"})

    created = client.post("/api/backups", json={"kind": "library"}).json()
    preflight = client.post("/api/restore/preflight", json={"path": created["path"]}).json()
    assert preflight["counts"]["reading_bookmarks"] == 1 and preflight["counts"]["reading_highlights"] == 1

    marks = client.get(f"/api/reader/units/{unit}/marks").json()
    client.delete(f"/api/reader/bookmarks/{marks['bookmarks'][0]['id']}")
    client.delete(f"/api/reader/highlights/{marks['highlights'][0]['id']}")
    assert client.post("/api/restore", json={"path": created["path"], "mode": "merge"}).status_code == 200

    back = client.get(f"/api/reader/units/{unit}/marks").json()
    assert [b["label"] for b in back["bookmarks"]] == ["Chapter 3"]
    assert [h["text"] for h in back["highlights"]] == ["kept"]
