"""Master §17 / §25 startup ordering: recover jobs → recover commits → reconcile → clean proven orphans."""
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from oneshelf.domain.clock import utcnow_iso
from oneshelf.importer.service import CreateLocalWork, ImportRejected, import_file
from oneshelf.services.startup import run_startup_recovery
from oneshelf.storage.commit import Crash
from oneshelf.storage.roots import register_root
from oneshelf.storage.staging import new_staging_area
from tests.fixtures.builders import make_cbz

NOW = datetime.now(UTC)


@pytest.fixture
def root(db, tmp_path):
    (tmp_path / "lib").mkdir()
    return register_root(db, "Library", tmp_path / "lib")


def areas(root):
    return sorted(p.name for p in (Path(root.path) / ".oneshelf" / "staging").iterdir())


def crash_import(db, tmp_path, point):
    (tmp_path / "inbox").mkdir(exist_ok=True)
    src = make_cbz(tmp_path / "inbox" / f"{point}.cbz")

    def fault(name):
        if name == point:
            raise Crash(name)

    with pytest.raises(Crash):
        import_file(db, src, decision=CreateLocalWork(title="C", content_type="comic"), fault=fault)


def test_interrupted_commit_is_recovered_before_cleanup(db, root, tmp_path):
    crash_import(db, tmp_path, "after_move")
    report = run_startup_recovery(db, now=NOW + timedelta(days=30))
    assert report.order == ["recover_jobs", "recover_commits", "reconcile", "clean_staging"]
    assert report.commits.done == 1
    assert db.execute("SELECT state FROM imports").fetchone()[0] == "completed"
    assert db.execute("SELECT count(*) FROM assets WHERE integrity = 'ok'").fetchone()[0] == 1
    assert areas(root) == []  # completed owner and older than 24h → proven orphan


def test_open_commit_on_unavailable_root_keeps_its_staging(db, root, tmp_path):
    crash_import(db, tmp_path, "after_journal")
    marker = Path(root.path) / ".oneshelf" / "root.json"
    saved = marker.read_text()
    marker.unlink()
    report = run_startup_recovery(db, now=NOW + timedelta(days=30))
    assert report.commits.skipped_unavailable == 1
    marker.write_text(saved)
    assert len(areas(root)) == 1  # nothing cleaned while the commit is still open
    report = run_startup_recovery(db, now=NOW + timedelta(days=30))
    assert report.commits.done == 1
    assert db.execute("SELECT state FROM imports").fetchone()[0] == "completed"


def test_interrupted_validation_fails_import_and_cleans_after_ttl(db, root):
    now = utcnow_iso()
    db.execute("INSERT INTO imports (id, original_filename, mode, state, created_at, updated_at)"
               " VALUES ('imp1', 'x.cbz', 'copy', 'validating', ?, ?)", (now, now))
    area, _ = new_staging_area(root, purpose="import", owner_id="imp1")
    (area / "artifact.cbz").write_bytes(b"partial")
    run_startup_recovery(db, now=NOW + timedelta(hours=1))
    assert db.execute("SELECT state, error FROM imports").fetchone()[:] == ("failed", "interrupted")
    assert len(areas(root)) == 1  # younger than 24h
    run_startup_recovery(db, now=NOW + timedelta(hours=25))
    assert areas(root) == []


def test_resumable_partials_are_kept_for_seven_days(db, root):
    area, _ = new_staging_area(root, purpose="download", owner_id="job-missing", resumable=True)
    run_startup_recovery(db, now=NOW + timedelta(days=6))
    assert len(areas(root)) == 1
    run_startup_recovery(db, now=NOW + timedelta(days=8))
    assert areas(root) == []


def test_unknown_staging_areas_are_treated_conservatively(db, root):
    stray = Path(root.path) / ".oneshelf" / "staging" / "stray"
    stray.mkdir()
    (stray / "blob").write_bytes(b"?")
    run_startup_recovery(db, now=NOW + timedelta(days=2))
    assert areas(root) == ["stray"]
    run_startup_recovery(db, now=NOW + timedelta(days=8))
    assert areas(root) == []


def test_rejected_import_left_no_area_and_startup_is_noop(db, root, tmp_path):
    (tmp_path / "inbox").mkdir()
    bad = tmp_path / "inbox" / "bad.cbz"
    bad.write_bytes(b"<html>")
    with pytest.raises(ImportRejected):
        import_file(db, bad, decision=CreateLocalWork(title="B"))
    report = run_startup_recovery(db, now=NOW)
    assert report.commits.changed == 0 and report.staging_removed == 0
