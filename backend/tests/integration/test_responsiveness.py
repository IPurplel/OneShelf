"""I-96 (BE-006): long library jobs must not freeze the application (Master §15, §26.24, §34.9, §56).

The audit measured a 1.06 s stall of every request during an 82 MB backup. Here a backup, a verification, a
checksum scan, an export and a restore preflight each run over ~96 MB of content while another client polls
`/api/health`; the slowest poll must stay well under the time the job takes.
"""
import os
import statistics
import threading
import time
from concurrent.futures import ThreadPoolExecutor

import pytest
from starlette.testclient import TestClient

from oneshelf.api.app import AppConfig, create_app
from oneshelf.db.connection import open_database
from oneshelf.domain.ids import new_id
from oneshelf.storage.hashing import sha256_file

FILES, SIZE = 3, 32 * 1024 * 1024
NOW = "2026-10-19T00:00:00+00:00"


@pytest.fixture
def library(tmp_path):
    config = AppConfig.from_env({"ONESHELF_DATA_DIR": str(tmp_path / "data"), "ONESHELF_ALLOWED_HOSTS": "testserver",
                                 "ONESHELF_SESSION_KEY_FILE": str(tmp_path / "keys" / "session.key")})
    with TestClient(create_app(config), client=("127.0.0.1", 50000)) as client:
        (tmp_path / "lib").mkdir()
        root = client.post("/api/storage/roots", json={"name": "Library", "path": str(tmp_path / "lib")}).json()
        works = []
        with open_database(tmp_path / "data" / "oneshelf.db") as conn:
            for i in range(FILES):
                work, track, unit, asset = new_id(), new_id(), new_id(), new_id()
                rel = f"Books/Big {i}/en/local/big-{i}.pdf"
                path = tmp_path / "lib" / rel
                path.parent.mkdir(parents=True)
                path.write_bytes(b"%PDF-1.4\n" + os.urandom(SIZE))
                sha, size = sha256_file(path)
                conn.execute("INSERT INTO works (id, display_title, content_type, created_at, updated_at)"
                             " VALUES (?,?, 'book', ?, ?)", (work, f"Big {i}", NOW, NOW))
                conn.execute("INSERT INTO source_tracks (id, work_id, source_id, language, kind, created_at)"
                             " VALUES (?,?, 'local', 'en', 'local', ?)", (track, work, NOW))
                conn.execute("INSERT INTO reading_units (id, track_id, source_unit_key, unit_type, source_order,"
                             " first_seen_at) VALUES (?,?,?, 'one_shot', 1, ?)", (unit, track, f"big-{i}", NOW))
                conn.execute("INSERT INTO assets (id, reading_unit_id, format, storage_root_id, relative_path,"
                             " size_bytes, sha256, integrity, created_at, updated_at)"
                             " VALUES (?,?, 'pdf', ?, ?, ?, ?, 'ok', ?, ?)",
                             (asset, unit, root["id"], rel, size, sha, NOW, NOW))
                works.append({"work_id": work, "unit_id": unit})
        yield client, tmp_path, works


def while_polling(client, job):
    """Run `job()` while another thread polls /api/health; returns (job result, job seconds, poll latencies)."""
    latencies, done = [], threading.Event()

    def poll():
        while not done.is_set():
            started = time.monotonic()
            assert client.get("/api/health").status_code == 200
            latencies.append(time.monotonic() - started)
            time.sleep(0.02)

    with ThreadPoolExecutor(max_workers=1) as pool:
        poller = pool.submit(poll)
        time.sleep(0.2)
        started = time.monotonic()
        result = job()
        elapsed = time.monotonic() - started
        time.sleep(0.2)
        done.set()
        poller.result()
    return result, elapsed, latencies


def assert_responsive(name, elapsed, latencies):
    worst = max(latencies)
    print(f"{name}: job {elapsed:.2f}s, {len(latencies)} polls, median {statistics.median(latencies) * 1000:.0f} ms,"
          f" worst {worst * 1000:.0f} ms")
    assert len(latencies) >= 5, f"{name}: the poller barely ran ({len(latencies)} polls in {elapsed:.2f}s)"
    assert worst < 0.25, f"{name}: a request waited {worst:.2f}s while the job ran {elapsed:.2f}s"


def test_i96_the_application_stays_responsive_during_heavy_library_jobs(library):
    client, tmp_path, works = library

    created, elapsed, latencies = while_polling(client, lambda: client.post(
        "/api/backups", json={"kind": "full", "works": [w["work_id"] for w in works]}))
    assert created.status_code == 200, created.text
    assert_responsive("full backup", elapsed, latencies)
    path = created.json()["path"]

    verified, elapsed, latencies = while_polling(client, lambda: client.post("/api/backups/verify",
                                                                             json={"path": path}))
    assert verified.json()["ok"] is True
    assert_responsive("verify", elapsed, latencies)

    preflight, elapsed, latencies = while_polling(client, lambda: client.post("/api/restore/preflight",
                                                                              json={"path": path}))
    assert preflight.status_code == 200
    assert_responsive("restore preflight", elapsed, latencies)

    scanned, elapsed, latencies = while_polling(client, lambda: client.post("/api/storage/scan?verify_checksums=true"))
    assert scanned.status_code == 200
    assert_responsive("checksum scan", elapsed, latencies)

    (tmp_path / "export").mkdir()
    exported, elapsed, latencies = while_polling(client, lambda: client.post("/api/export", json={
        "work_id": works[0]["work_id"], "language": "en", "source_id": "local", "unit_ids": [works[0]["unit_id"]],
        "destination": str(tmp_path / "export")}))
    assert exported.status_code == 200, exported.text
    assert_responsive("export", elapsed, latencies)


def test_i96_long_jobs_can_run_as_background_tasks(library):
    """WP-8: `?background=true` answers 202 at once; the task then reports the same outcome."""
    client, tmp_path, works = library
    started = client.post("/api/backups?background=true",
                          json={"kind": "full", "works": [w["work_id"] for w in works]})
    assert started.status_code == 202 and started.json()["kind"] == "backup"
    task_id = started.json()["task_id"]
    deadline = time.monotonic() + 60
    while time.monotonic() < deadline:
        task = client.get(f"/api/tasks/{task_id}").json()
        if task["state"] != "running":
            break
        time.sleep(0.1)
    assert task["state"] == "completed" and task["status"] == 200
    assert client.post("/api/backups/verify", json={"path": task["result"]["path"]}).json()["ok"] is True

    refused = client.post("/api/restore?background=true", json={"path": str(tmp_path / "nope.osbackup")})
    assert refused.status_code == 202
    while client.get(f"/api/tasks/{refused.json()['task_id']}").json()["state"] == "running":
        time.sleep(0.05)
    failed = client.get(f"/api/tasks/{refused.json()['task_id']}").json()
    assert failed["state"] == "failed" and failed["status"] == 422
    assert failed["result"]["error"]["code"] == "RESTORE_REFUSED"
    assert client.get("/api/tasks/unknown").status_code == 404
