"""Backend contracts requested by Codex for the approved UI repairs (docs/audits/2026-10-20-ui-backend-handoff.md).

UI-003: a batch's detail names what each job is (Work, unit, track), whether a finished unit can really be
opened now, its sizes, and why skipped selections never entered the queue — bounded, and without leaking URLs.
UI-004: every source says when it last checked out successfully, a value a later failure never erases.
"""
import json
import sqlite3
import time
from contextlib import closing
from pathlib import Path

from .test_library_api import TS, api, prepare, unit_ids, wait_for_state  # noqa: F401


def db(tmp_path):
    conn = sqlite3.connect(tmp_path / "data" / "oneshelf.db")
    conn.row_factory = sqlite3.Row
    return closing(conn)


def test_ui003_a_batch_names_its_units_and_says_whether_each_can_be_opened(api):
    client, tmp_path = api
    bound = prepare(client, tmp_path)
    first, second = unit_ids(client, tmp_path, ["irr-1", "irr-2"])
    client.post("/api/downloads", json={"unit_ids": [first]})
    wait_for_state(client, client.get("/api/downloads").json()["batches"][0]["batch_id"], "completed")

    batch = client.post("/api/downloads", json={"unit_ids": [first, second]}).json()   # first: already here
    detail = wait_for_state(client, batch["batch_id"], "completed")
    assert detail["jobs_total"] == 1 and len(detail["jobs"]) == 1
    job = detail["jobs"][0]
    assert (job["work_id"], job["track_id"]) == (bound["work_id"], bound["track_id"])
    assert job["work_title"] == "The Irregular Chronicle" and job["unit_title"] == "Chapter 2"
    assert job["available"] is True and job["bytes_total"] > 0 and job["bytes_done"] == job["bytes_total"]
    assert detail["skipped_units"] == [{"reading_unit_id": first, "unit_title": "Chapter 1",
                                        "reason": "already_downloaded"}]

    with db(tmp_path) as conn:
        root = conn.execute("SELECT path FROM storage_roots").fetchone()[0]
        rel = conn.execute("SELECT relative_path FROM assets WHERE reading_unit_id = ?", (second,)).fetchone()[0]
    (Path(root) / rel).unlink()                                     # the file went away after it completed
    assert client.get(f"/api/downloads/{batch['batch_id']}").json()["jobs"][0]["available"] is False


def test_ui003_batch_detail_is_paged_and_bounded(api):
    client, tmp_path = api
    prepare(client, tmp_path)
    units = unit_ids(client, tmp_path, ["irr-1", "irr-2", "irr-3"])
    batch = client.post("/api/downloads", json={"unit_ids": units}).json()
    page = client.get(f"/api/downloads/{batch['batch_id']}", params={"limit": 2, "offset": 1}).json()
    assert page["jobs_total"] == 3 and len(page["jobs"]) == 2 and (page["offset"], page["limit"]) == (1, 2)
    assert client.get(f"/api/downloads/{batch['batch_id']}", params={"limit": 5000}).status_code == 422
    assert client.get("/api/downloads/unknown").status_code == 404


def test_ui003_a_failed_job_never_shows_a_url_s_secrets(api):
    client, tmp_path = api
    prepare(client, tmp_path)
    unit = unit_ids(client, tmp_path, ["irr-1"])[0]
    batch = client.post("/api/downloads", json={"unit_ids": [unit], "label": "x"}).json()
    with db(tmp_path) as conn:
        conn.execute("UPDATE download_jobs SET state = 'FAILED', error_category = 'transport', last_error = ?"
                     " WHERE batch_id = ?", ("Cannot connect to https://cdn.example/p.png?token=SECRET123&page=2",
                                             batch["batch_id"]))
        conn.commit()
    job = client.get(f"/api/downloads/{batch['batch_id']}").json()["jobs"][0]
    assert "SECRET123" not in json.dumps(job) and job["error_category"] == "transport"
    assert job["available"] is False


def test_ui004_sources_report_their_last_successful_check(api):
    client, tmp_path = api
    sources = {s["id"]: s for s in client.get("/api/sources").json()["sources"]}
    assert sources[TS]["last_successful_check_at"] is None                          # never checked yet

    client.get("/api/search", params={"q": "chronicle"})                              # a successful search
    succeeded = {s["id"]: s for s in client.get("/api/sources").json()["sources"]}[TS]["last_successful_check_at"]
    assert succeeded is not None and succeeded.endswith("+00:00")

    from oneshelf.db.connection import open_database
    from oneshelf.sources.health import record_signal
    with open_database(tmp_path / "data" / "oneshelf.db") as conn:                    # then a failed check
        record_signal(conn, TS, "search", "failure", "transport", "1.0.0")
    after = {s["id"]: s for s in client.get("/api/sources").json()["sources"]}[TS]["last_successful_check_at"]
    assert after == succeeded                                                         # a failure never erases it


def test_ui004_a_source_older_than_its_check_record_is_unknown_until_it_succeeds(api):
    """`null` says "never succeeded", which is known only for a source installed once the record was kept.

    Health signals are pruned after seven days, so a source installed before the upgrade may have succeeded
    long ago. Its field is omitted, which the frontend shows as Unknown, until a success is on record.
    """
    client, tmp_path = api
    with db(tmp_path) as conn:
        conn.execute("UPDATE plugins SET installed_at = '2026-01-01T00:00:00+00:00' WHERE id = ?", (TS,))
        conn.commit()

    def source():
        return {s["id"]: s for s in client.get("/api/sources").json()["sources"]}[TS]

    assert "last_successful_check_at" not in source()
    from oneshelf.db.connection import open_database
    from oneshelf.sources.health import record_signal
    with open_database(tmp_path / "data" / "oneshelf.db") as conn:
        record_signal(conn, TS, "search", "failure", "transport", "1.0.0")
    assert "last_successful_check_at" not in source()                                # a failure tells no more
    client.get("/api/search", params={"q": "chronicle"})
    assert source()["last_successful_check_at"].endswith("+00:00")


def test_ui004_source_health_events_follow_changes_and_are_throttled():
    """`source.health` tells clients to re-read the list: at once on a change, at most once a minute otherwise."""
    from types import SimpleNamespace

    from oneshelf.sources.service import SourceService

    published, now = [], [0.0]
    service = SourceService.__new__(SourceService)
    service.events = SimpleNamespace(publish=lambda event, data: published.append((event, data["source_id"])))
    service.clock = lambda: now[0]
    service._health_published = {}
    for at, outcome in ((0, "success"), (5, "success"), (10, "failure"), (12, "failure"), (61, "failure"),
                        (71, "failure"), (72, "success")):
        now[0] = float(at)
        service._publish_health("s", outcome)
    assert [event for event, _ in published] == ["source.health"] * 4   # 0 first, 10 changed, 71 a minute on, 72 changed
