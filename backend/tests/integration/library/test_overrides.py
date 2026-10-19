"""I-102 (BE-012): user corrections are written, win over every other tier, and survive refreshes.

Master §9.2 (user override first), §4.4 (user correction overrides derived numbering), INV-4.
"""
import pytest
from starlette.testclient import TestClient

from oneshelf.api.app import AppConfig, create_app
from oneshelf.catalog.trust import CatalogTrust
from oneshelf.db.connection import open_database
from oneshelf.plugins.results import Evidence, ListResult, UnitDescriptor
from tests.fixtures.builders import make_cbz


@pytest.fixture
def api(tmp_path):
    config = AppConfig.from_env({"ONESHELF_DATA_DIR": str(tmp_path / "data"), "ONESHELF_ALLOWED_HOSTS": "testserver",
                                 "ONESHELF_SESSION_KEY_FILE": str(tmp_path / "keys" / "session.key")})
    with TestClient(create_app(config), client=("127.0.0.1", 50000)) as client:
        (tmp_path / "library").mkdir()
        client.post("/api/storage/roots", json={"name": "Library", "path": str(tmp_path / "library")})
        yield client, tmp_path


def imported(client, tmp_path, content_type="unknown"):
    path = make_cbz(tmp_path / "one.cbz")
    review = client.post("/api/import/uploads?filename=one.cbz", content=path.read_bytes(),
                         headers={"Content-Type": "application/octet-stream"}).json()
    return client.post("/api/import", json={"upload_id": review["upload_id"], "title": "Berserk",
                                            "content_type": content_type, "language": "ar"}).json()


def test_i102_a_work_type_and_title_can_be_corrected_and_the_correction_is_marked_as_the_users(api):
    client, tmp_path = api
    work_id = imported(client, tmp_path)["work_id"]
    changed = client.patch(f"/api/works/{work_id}", json={"content_type": "manga", "title": "Berserk (Deluxe)"})
    assert changed.status_code == 200, changed.text
    work = client.get(f"/api/works/{work_id}").json()["work"]
    assert work["content_type"] == "manga" and work["content_type_source"] == "user"
    assert work["title"] == "Berserk (Deluxe)"


def test_i102_an_unknown_type_is_refused_and_a_cleared_override_stops_winning(api):
    client, tmp_path = api
    work_id = imported(client, tmp_path)["work_id"]
    assert client.patch(f"/api/works/{work_id}", json={"content_type": "cartoon"}).status_code == 422
    client.patch(f"/api/works/{work_id}", json={"content_type": "manhwa"})
    cleared = client.patch(f"/api/works/{work_id}", json={"content_type": None})
    assert cleared.status_code == 200
    work = client.get(f"/api/works/{work_id}").json()["work"]
    assert work["content_type_source"] != "user"
    assert client.patch("/api/works/nope", json={"content_type": "manga"}).status_code == 404


def test_i102_a_reading_unit_number_title_and_type_can_be_corrected(api):
    client, tmp_path = api
    made = imported(client, tmp_path, content_type="manga")
    unit_id = made["reading_unit_id"]
    changed = client.patch(f"/api/reading-units/{unit_id}",
                           json={"number": "0.5", "title": "Prologue — The Black Swordsman", "unit_type": "prologue"})
    assert changed.status_code == 200, changed.text
    unit = client.get(f"/api/works/{made['work_id']}").json()["units"][0]
    assert unit["number"] == "0.5" and unit["unit_type"] == "prologue"
    assert unit["title"] == "Prologue — The Black Swordsman"
    assert client.patch(f"/api/reading-units/{unit_id}", json={"unit_type": "bonus"}).status_code == 422


def _catalog(*titles):
    return ListResult("catalog", [UnitDescriptor(unit_key=f"k{i}", order_index=i, raw_title=title, number=str(i + 1),
                                                 volume=None, unit_type="unknown", url=None, release_date=None)
                                  for i, title in enumerate(titles)], True, Evidence())


def test_i102_unit_corrections_survive_a_catalog_refresh(api):
    client, tmp_path = api
    made = imported(client, tmp_path, content_type="manga")
    with open_database(tmp_path / "data" / "oneshelf.db") as conn:
        track = conn.execute("SELECT track_id FROM reading_units WHERE id = ?",
                             (made["reading_unit_id"],)).fetchone()[0]
        trust = CatalogTrust(conn)
        trust.refresh(track, _catalog("Ch. 1", "Ch. 2"), plugin_version="1")
        unit_id = conn.execute("SELECT id FROM reading_units WHERE track_id = ? AND source_unit_key = 'k0'",
                               (track,)).fetchone()[0]
    assert client.patch(f"/api/reading-units/{unit_id}",
                        json={"number": "0", "title": "Prologue", "unit_type": "prologue"}).status_code == 200
    with open_database(tmp_path / "data" / "oneshelf.db") as conn:
        CatalogTrust(conn).refresh(track, _catalog("Chapter 1 (renamed at the source)", "Ch. 2"), plugin_version="2")
        row = conn.execute("SELECT raw_title, display_title, unit_type, user_number, source_number FROM reading_units"
                           " WHERE id = ?", (unit_id,)).fetchone()
    assert row["raw_title"] == "Chapter 1 (renamed at the source)"          # source metadata still updates
    assert (row["display_title"], row["unit_type"], row["user_number"]) == ("Prologue", "prologue", "0")
    assert row["source_number"] == "1"
