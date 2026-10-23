"""Whether a finished download can be opened now (UI-003; Codex's BE-003 handoff, docs/audits/2026-10-20-ui-backend-handoff.md).

`available` is true only when the Reader would open a local copy of the unit right now: a sound record, its
Storage Location connected and its own, the file in it. A deleted, missing or disconnected copy is never offered
as openable, a copy that went missing can be downloaded again, and deleting a downloaded Work's files works
(I-110: it failed on the job's reference to the file, after the file itself was already gone).
"""
import os
import sqlite3
from contextlib import closing
from pathlib import Path

from .test_library_api import TS, api, prepare, unit_ids, wait_for_state  # noqa: F401


def db(tmp_path):
    conn = sqlite3.connect(tmp_path / "data" / "oneshelf.db")
    conn.row_factory = sqlite3.Row
    return closing(conn)


def download(client, unit_ids):
    batch = client.post("/api/downloads", json={"unit_ids": unit_ids}).json()
    return wait_for_state(client, batch["batch_id"], "completed")


def jobs(client, batch_id):
    return client.get(f"/api/downloads/{batch_id}").json()["jobs"]


def stored_file(tmp_path, unit_id) -> Path:
    with db(tmp_path) as conn:
        row = conn.execute("SELECT r.path, a.relative_path FROM assets a JOIN storage_roots r ON r.id = a.storage_root_id"
                           " WHERE a.reading_unit_id = ?", (unit_id,)).fetchone()
    return Path(row[0]) / row[1]


def test_ui003_deleting_a_downloaded_works_files_works_and_the_unit_is_no_longer_openable(api):
    client, tmp_path = api
    bound = prepare(client, tmp_path)
    unit, = unit_ids(client, tmp_path, ["irr-1"])
    first = download(client, [unit])
    path = stored_file(tmp_path, unit)
    assert jobs(client, first["batch_id"])[0]["available"] is True
    assert jobs(client, first["batch_id"])[0]["available_format"] == "cbz"

    response = client.delete(f"/api/works/{bound['work_id']}/files")
    assert response.status_code == 200 and response.json()["deleted_files"] == 1
    assert not path.exists()
    with db(tmp_path) as conn:
        assert conn.execute("SELECT count(*) FROM assets").fetchone()[0] == 0              # no record left saying "ok"
        assert conn.execute("SELECT state, asset_id FROM download_jobs").fetchone()[:] == ("COMPLETED", None)
    job = jobs(client, first["batch_id"])[0]
    assert job["state"] == "COMPLETED" and job["available"] is False
    assert client.get(f"/api/reader/units/{unit}/context").json()["formats"] == []

    again = download(client, [unit])                                         # it can be downloaded again
    assert again["completed"] == 1 and again["skipped"] == 0
    assert jobs(client, again["batch_id"])[0]["available"] is True
    assert jobs(client, first["batch_id"])[0]["available"] is True          # the unit opens again from either batch


def test_ui003_a_file_gone_from_a_connected_location_is_unavailable_and_can_be_downloaded_again(api):
    client, tmp_path = api
    prepare(client, tmp_path)
    unit, = unit_ids(client, tmp_path, ["irr-1"])
    first = download(client, [unit])
    with db(tmp_path) as conn:
        asset_id = conn.execute("SELECT id FROM assets").fetchone()[0]
    stored_file(tmp_path, unit).unlink()                                     # gone behind OneShelf's back
    assert jobs(client, first["batch_id"])[0]["available"] is False

    again = download(client, [unit])                                         # not skipped as "already downloaded"
    assert again["completed"] == 1 and again["skipped"] == 0 and again["skipped_units"] == []
    with db(tmp_path) as conn:
        assert [r[:] for r in conn.execute("SELECT id, integrity FROM assets")] == [(asset_id, "ok")]   # one record
    assert stored_file(tmp_path, unit).is_file()
    assert [jobs(client, b["batch_id"])[0]["available"] for b in (first, again)] == [True, True]


def test_ui003_a_copy_on_a_disconnected_location_is_unavailable_but_never_downloaded_twice(api):
    client, tmp_path = api
    prepare(client, tmp_path)
    unit, = unit_ids(client, tmp_path, ["irr-1"])
    first = download(client, [unit])
    library = tmp_path / "library"
    library.rename(tmp_path / "unplugged")                                   # the drive is not connected
    assert jobs(client, first["batch_id"])[0]["available"] is False

    batch = client.post("/api/downloads", json={"unit_ids": [unit]}).json()
    detail = client.get(f"/api/downloads/{batch['batch_id']}").json()
    assert detail["jobs_total"] == 0 and detail["skipped_units"][0]["reason"] == "already_downloaded"
    with db(tmp_path) as conn:
        assert conn.execute("SELECT integrity FROM assets").fetchone()[0] == "ok"   # still the library's copy

    (tmp_path / "unplugged").rename(library)                                 # plugged back in
    assert jobs(client, first["batch_id"])[0]["available"] is True


def test_ui003_a_read_only_location_still_opens(api):
    client, tmp_path = api
    prepare(client, tmp_path)
    unit, = unit_ids(client, tmp_path, ["irr-1"])
    first = download(client, [unit])
    staging = next(p for p in (tmp_path / "library").rglob("*") if p.is_dir() and "staging" in p.name)
    staging.chmod(0o500)
    try:
        if os.access(staging, os.W_OK):                                      # running as root: nothing to show
            return
        assert jobs(client, first["batch_id"])[0]["available"] is True
    finally:
        staging.chmod(0o700)


def test_ui003_unsound_records_are_never_openable(api):
    client, tmp_path = api
    prepare(client, tmp_path)
    unit, = unit_ids(client, tmp_path, ["irr-1"])
    first = download(client, [unit])
    for integrity in ("corrupt", "missing_local_file", "unknown"):
        with db(tmp_path) as conn:
            conn.execute("UPDATE assets SET integrity = ?", (integrity,))
            conn.commit()
        assert jobs(client, first["batch_id"])[0]["available"] is False, integrity

    with db(tmp_path) as conn:
        conn.execute("UPDATE assets SET integrity = 'ok'")
        conn.commit()
    path = stored_file(tmp_path, unit)
    outside = tmp_path / "elsewhere.cbz"
    path.rename(outside)
    path.symlink_to(outside)                                                 # a link out of the location
    assert jobs(client, first["batch_id"])[0]["available"] is False


def test_ui003_legacy_completed_jobs_without_a_file_reference(api):
    """Jobs finished before files were linked to them, or whose file was deleted, say what the unit has now."""
    client, tmp_path = api
    prepare(client, tmp_path)
    kept, lost = unit_ids(client, tmp_path, ["irr-1", "irr-2"])
    first = download(client, [kept, lost])
    with db(tmp_path) as conn:
        conn.execute("UPDATE download_jobs SET asset_id = NULL")
        conn.execute("DELETE FROM assets WHERE reading_unit_id = ?", (lost,))
        conn.commit()
    available = {j["reading_unit_id"]: j["available"] for j in jobs(client, first["batch_id"])}
    assert available == {kept: True, lost: False}
