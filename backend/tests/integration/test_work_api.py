"""Work Details (Master §32.8): one screen's worth of truth about a Work, from real library state."""
import pytest
from starlette.testclient import TestClient

from oneshelf.api.app import AppConfig, create_app
from tests.fixtures.builders import make_cbz, make_pdf


@pytest.fixture
def api(tmp_path):
    config = AppConfig.from_env({"ONESHELF_DATA_DIR": str(tmp_path / "data"), "ONESHELF_ALLOWED_HOSTS": "testserver",
                                 "ONESHELF_SESSION_KEY_FILE": str(tmp_path / "keys" / "session.key")})
    with TestClient(create_app(config), client=("127.0.0.1", 50000)) as client:
        (tmp_path / "library").mkdir()
        client.post("/api/storage/roots", json={"name": "Library", "path": str(tmp_path / "library")})
        yield client, tmp_path


def import_work(client, tmp_path, title="The Irregular Chronicle", name="one.cbz"):
    path = make_cbz(tmp_path / name)
    review = client.post(f"/api/import/uploads?filename={name}", content=path.read_bytes(),
                         headers={"Content-Type": "application/octet-stream"}).json()
    return client.post("/api/import", json={"upload_id": review["upload_id"], "title": title,
                                            "content_type": "manga", "language": "en"}).json()


def test_work_details_describe_the_work_its_tracks_and_its_units(api):
    client, tmp_path = api
    imported = import_work(client, tmp_path)
    details = client.get(f"/api/works/{imported['work_id']}").json()

    assert details["work"]["title"] == "The Irregular Chronicle"
    assert details["work"]["content_type"] == "manga"
    assert details["shelf"]["on_shelf"] is True and details["shelf"]["completed"] is False
    assert details["follow"]["following"] is False

    track = details["tracks"][0]
    assert track["source_id"] == "local" and track["language"] == "en" and track["kind"] == "local"
    assert track["unit_count"] == 1 and details["selected_track_id"] == track["id"]

    unit = details["units"][0]
    assert unit["id"] == imported["reading_unit_id"]
    assert unit["downloaded"] is True and unit["formats"] == ["cbz"]
    assert unit["read_state"] == "unread" and unit["fraction"] == 0.0


def test_units_keep_source_order_and_report_reading_state(api):
    client, tmp_path = api
    first = import_work(client, tmp_path, name="a.cbz")
    second = client.post("/api/import", json={
        "upload_id": client.post("/api/import/uploads?filename=b.cbz",
                                 content=make_cbz(tmp_path / "b.cbz").read_bytes(),
                                 headers={"Content-Type": "application/octet-stream"}).json()["upload_id"],
        "work_id": first["work_id"], "language": "en", "unit_label": "Chapter 2"}).json()

    progress = client.post(f"/api/reader/units/{second['reading_unit_id']}/progress",
                           json={"fraction": 0.5, "revision": 0, "locator": {"page": 2}})
    assert progress.status_code == 200, progress.text
    details = client.get(f"/api/works/{first['work_id']}").json()

    assert [u["id"] for u in details["units"]] == [first["reading_unit_id"], second["reading_unit_id"]]
    assert details["units"][1]["read_state"] == "partial" and details["units"][1]["fraction"] == 0.5
    assert details["continue_unit_id"] == second["reading_unit_id"]


def test_a_second_language_is_a_separate_track_and_must_be_chosen_explicitly(api):
    client, tmp_path = api
    first = import_work(client, tmp_path, name="en.cbz")
    client.post("/api/import", json={
        "upload_id": client.post("/api/import/uploads?filename=ar.cbz",
                                 content=make_cbz(tmp_path / "ar.cbz").read_bytes(),
                                 headers={"Content-Type": "application/octet-stream"}).json()["upload_id"],
        "work_id": first["work_id"], "language": "ar", "unit_label": "الفصل ١"})

    details = client.get(f"/api/works/{first['work_id']}").json()
    assert sorted(t["language"] for t in details["tracks"]) == ["ar", "en"]
    assert len(details["units"]) == 1                       # only the selected track's units (INV-02)

    arabic = next(t for t in details["tracks"] if t["language"] == "ar")
    chosen = client.get(f"/api/works/{first['work_id']}", params={"track_id": arabic["id"]}).json()
    assert chosen["selected_track_id"] == arabic["id"]
    assert chosen["units"][0]["title"] == "الفصل ١"


def test_unknown_work_is_a_plain_404(api):
    client, _ = api
    response = client.get("/api/works/does-not-exist")
    assert response.status_code == 404 and response.json()["error"]["code"] == "WORK_NOT_FOUND"


def test_a_local_book_file_is_served_for_the_isolated_viewer(api):
    """Master §26.22, §27: EPUB and PDF bytes reach a sandboxed viewer, never the app origin."""
    client, tmp_path = api
    pdf = make_pdf(tmp_path / "book.pdf", pages=2)
    review = client.post("/api/import/uploads?filename=book.pdf", content=pdf.read_bytes(),
                         headers={"Content-Type": "application/octet-stream"}).json()
    assert review["format"] == "pdf"
    imported = client.post("/api/import", json={"upload_id": review["upload_id"], "title": "A Book",
                                                "content_type": "book", "language": "en"}).json()

    response = client.get(f"/api/reader/units/{imported['reading_unit_id']}/file")
    assert response.status_code == 200
    assert response.content.startswith(b"%PDF-")
    assert response.headers["content-type"] == "application/pdf"
    assert response.headers["content-security-policy"] == "sandbox; default-src 'none'"
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["content-disposition"].startswith("inline")
    assert response.headers["cache-control"] == "no-store"


def test_asking_for_a_file_that_is_not_downloaded_says_so(api):
    client, tmp_path = api
    imported = import_work(client, tmp_path)
    missing = client.get("/api/reader/units/does-not-exist/file")
    assert missing.status_code == 404 and missing.json()["error"]["code"] == "FILE_NOT_AVAILABLE"
    # A CBZ is read page by page rather than handed over whole.
    cbz = client.get(f"/api/reader/units/{imported['reading_unit_id']}/file")
    assert cbz.status_code == 200 and cbz.headers["content-type"] == "application/vnd.comicbook+zip"
