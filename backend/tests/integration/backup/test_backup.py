"""Master §33.1–33.5, §33.8–33.9, §18; INV-19: backup contents, exclusions, verification, rotation."""
import sqlite3
import zipfile
from contextlib import closing
from datetime import timedelta
from pathlib import Path

import pytest

from oneshelf.backup.service import BackupError, BackupService
from tests.fixtures.library import archive_names, read_manifest

EXCLUDED_TABLES = ("source_session_refs", "commit_journal", "download_jobs", "download_batches", "search_index")


def service(library, clock, **kwargs):
    return BackupService(library.conn, library.path / "data" / "oneshelf.db",
                         backup_dir=library.path / "backups", clock=lambda: clock["now"], **kwargs)


def test_library_backup_holds_state_but_no_reading_files(library, clock):
    library.add_work("Solo Leveling")
    library.add_plugin()
    record = service(library, clock).create("library")
    names = archive_names(Path(record.path))
    assert "manifest.json" in names and "library.db" in names
    assert not any(n.startswith("content/") for n in names)
    manifest = read_manifest(Path(record.path))
    assert manifest["kind"] == "library" and manifest["schema"] == "oneshelf.backup/1"
    assert manifest["plugins"] == [{"id": "mangadex", "version": "1.2.0",
                                    "permissions": ["network:domain:mangadex.org"]}]
    assert manifest["counts"]["works"] == 1 and manifest["counts"]["assets"] == 1


def test_backup_excludes_every_secret_and_rebuildable_store(library, clock, tmp_path):
    secret = library.add_secret_session()
    library.add_work("Solo Leveling")
    (tmp_path / "data" / "secrets.db").write_bytes(b"encrypted blob " + secret.encode())
    (tmp_path / "keys").mkdir()
    (tmp_path / "keys" / "session.key").write_bytes(b"MASTER-KEY-BYTES")
    staging = library.root_path / ".oneshelf" / "staging" / "area"
    staging.mkdir(parents=True)
    (staging / "partial.cbz").write_bytes(b"partial download")

    record = service(library, clock).create("full", works=[library.works["Solo Leveling"]["work_id"]])
    raw = Path(record.path).read_bytes()
    assert secret.encode() not in raw and b"MASTER-KEY-BYTES" not in raw and b"partial download" not in raw
    assert not any("staging" in name or "secrets" in name for name in archive_names(Path(record.path)))

    with zipfile.ZipFile(record.path) as z:
        z.extract("library.db", tmp_path / "check")
    with closing(sqlite3.connect(tmp_path / "check" / "library.db")) as conn:
        for table in EXCLUDED_TABLES:
            assert conn.execute(f"SELECT count(*) FROM {table}").fetchone()[0] == 0   # INV-19


def test_full_backup_includes_only_the_selected_works(library, clock):
    keep = library.add_work("Solo Leveling", content=b"kept chapter")
    library.add_work("Berserk", content=b"other chapter")
    record = service(library, clock).create("full", works=[keep["work_id"]])
    manifest = read_manifest(Path(record.path))
    assert len(manifest["content"]) == 1 and manifest["content"][0]["reading_unit_id"] == keep["unit_id"]
    with zipfile.ZipFile(record.path) as z:
        stored = [n for n in z.namelist() if n.startswith("content/")]
        assert len(stored) == 1 and z.read(stored[0]) == b"kept chapter"


def test_snapshot_is_consistent_even_if_the_library_changes_during_the_backup(library, clock):
    library.add_work("Solo Leveling")

    def fault(point):
        if point == "after_snapshot":
            library.add_work("Added During Backup")

    record = service(library, clock, fault=fault).create("library")
    assert read_manifest(Path(record.path))["counts"]["works"] == 1   # the snapshot, not the live database


def test_verification_detects_a_tampered_archive(library, clock, tmp_path):
    library.add_work("Solo Leveling")
    backup = service(library, clock)
    record = backup.create("library")
    assert backup.verify(record.path).ok

    tampered = tmp_path / "tampered.osbackup"
    with zipfile.ZipFile(record.path) as source, zipfile.ZipFile(tampered, "w") as target:
        for item in source.namelist():
            data = source.read(item)
            target.writestr(item, b"corrupted" if item == "library.db" else data)
    result = backup.verify(tampered)
    assert not result.ok and "checksum" in result.reason


def test_retention_keeps_four_verified_backups_and_never_rotates_before_verifying(library, clock):
    library.add_work("Solo Leveling")
    backup = service(library, clock)
    created = []
    for _ in range(5):
        clock["now"] += timedelta(days=8)
        created.append(backup.create("library"))
    remaining = [Path(r.path).name for r in backup.list_backups()]
    assert len(remaining) == 4 and Path(created[0].path).name not in remaining
    assert not Path(created[0].path).exists() and all(Path(r.path).exists() for r in created[1:])

    def failing_verify(_path):
        from oneshelf.backup.service import VerifyResult
        return VerifyResult(False, "injected verification failure")

    backup.verify = failing_verify
    with pytest.raises(BackupError):
        backup.create("library")
    assert len([p for p in (library.path / "backups").glob("*.osbackup")]) == 4   # prior verified backups kept


def test_schedule_is_seven_days_with_catch_up_after_downtime(library, clock):
    library.add_work("Solo Leveling")
    backup = service(library, clock)
    assert backup.due() is True          # no backup yet
    backup.create("library")
    assert backup.due() is False
    clock["now"] += timedelta(days=6)
    assert backup.due() is False
    clock["now"] += timedelta(days=2)
    assert backup.due() is True          # 7 days passed, or was missed during downtime
    assert backup.due(kind="full") is False   # Full Backup is manual by default


def test_same_physical_disk_warning(library, clock, tmp_path):
    library.add_work("Solo Leveling")
    same = service(library, clock)
    assert same.location_warning(library.path / "backups")["same_device_as_library"] is True
    assert "same physical disk" in same.location_warning(library.path / "backups")["message"]
