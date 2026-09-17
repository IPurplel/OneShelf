"""Master §33.5–33.7: restore preflight, compatibility, Replace safety snapshot, deterministic Merge."""
import hashlib
import json
import zipfile
from pathlib import Path

import pytest

from oneshelf.backup.service import BackupService
from oneshelf.restore.service import RestoreBlocked, RestoreError, RestoreService
from tests.fixtures.library import read_manifest


def backup_service(library, clock):
    return BackupService(library.conn, library.path / "data" / "oneshelf.db",
                         backup_dir=library.path / "backups", clock=lambda: clock["now"])


def restore_service(library, clock):
    return RestoreService(library.conn, library.path / "data" / "oneshelf.db",
                          backups=backup_service(library, clock))


def make_backup(library, clock, kind="library", works=None):
    return backup_service(library, clock).create(kind, works=works)


def test_preflight_reports_contents_plugins_and_compatibility(library, clock):
    library.add_work("Solo Leveling")
    library.add_plugin("mangadex", "1.2.0", ("network:domain:mangadex.org",))
    record = make_backup(library, clock)
    library.conn.execute("DELETE FROM plugin_versions")
    library.conn.execute("DELETE FROM plugins")

    preflight = restore_service(library, clock).preflight(record.path)
    assert preflight.ok and preflight.compatible and preflight.kind == "library"
    assert preflight.counts["works"] == 1
    assert preflight.plugins[0].id == "mangadex" and preflight.plugins[0].installed is False
    assert preflight.space_needed > 0 and preflight.issues == []


def test_a_newer_backup_is_refused_by_an_older_application(library, clock, tmp_path):
    library.add_work("Solo Leveling")
    record = make_backup(library, clock)
    future = tmp_path / "future.osbackup"
    with zipfile.ZipFile(record.path) as source, zipfile.ZipFile(future, "w") as target:
        for name in source.namelist():
            data = source.read(name)
            if name == "manifest.json":
                manifest = json.loads(data)
                manifest["schema_version"] = 9999
                manifest["inventory"] = manifest["inventory"]
                data = json.dumps(manifest).encode()
            target.writestr(name, data)
    service = restore_service(library, clock)
    preflight = service.preflight(future)
    assert not preflight.compatible and "newer" in preflight.issues[0]
    with pytest.raises(RestoreError, match="newer"):
        service.restore(future, mode="merge")
    assert library.conn.execute("SELECT count(*) FROM works").fetchone()[0] == 1   # nothing changed


def test_an_older_backup_migrates_forward_in_staging_without_changing_the_file(library, clock, tmp_path):
    from oneshelf.db.connection import open_database
    from oneshelf.db.migrate import migrate
    from oneshelf.db.schema import MIGRATIONS

    old_db = tmp_path / "old.db"
    migrate(old_db, MIGRATIONS[:-2], snapshot_dir=tmp_path / "s")
    with open_database(old_db) as conn:
        conn.execute("INSERT INTO works (id, display_title, created_at, updated_at)"
                     " VALUES ('old-work', 'Older Backup Work', '2026-01-01', '2026-01-01')")
    data = old_db.read_bytes()
    archive = tmp_path / "old.osbackup"
    manifest = {"schema": "oneshelf.backup/1", "kind": "library", "created_at": "2026-01-01T00:00:00+00:00",
                "schema_version": len(MIGRATIONS) - 2, "app_schema_version": len(MIGRATIONS) - 2,
                "counts": {"works": 1}, "plugins": [], "content": [], "works": [],
                "inventory": [{"path": "library.db", "sha256": hashlib.sha256(data).hexdigest(), "size": len(data)}]}
    with zipfile.ZipFile(archive, "w") as z:
        z.writestr("library.db", data)
        z.writestr("manifest.json", json.dumps(manifest))

    before = hashlib.sha256(archive.read_bytes()).hexdigest()
    report = restore_service(library, clock).restore(archive, mode="merge")
    assert report.added["works"] == 1
    assert hashlib.sha256(archive.read_bytes()).hexdigest() == before   # the backup file is never modified
    assert library.conn.execute("SELECT display_title FROM works WHERE id = 'old-work'").fetchone()[0] == \
        "Older Backup Work"


def test_replace_creates_a_safety_snapshot_first(library, clock):
    kept = library.add_work("Solo Leveling")
    record = make_backup(library, clock)
    library.add_work("Added After Backup")
    service = restore_service(library, clock)
    report = service.restore(record.path, mode="replace")
    assert report.safety_snapshot is not None and Path(report.safety_snapshot).exists()
    titles = {r[0] for r in library.conn.execute("SELECT display_title FROM works")}
    assert titles == {"Solo Leveling"}
    snapshot_manifest = read_manifest(Path(report.safety_snapshot))
    assert snapshot_manifest["counts"]["works"] == 2   # the pre-restore state is recoverable


def test_merge_adds_missing_records_but_keeps_current_user_decisions(library, clock):
    library.add_work("Solo Leveling")
    record = make_backup(library, clock)
    library.conn.execute("DELETE FROM shelf_entries")
    library.conn.execute("UPDATE works SET display_title = 'Solo Leveling (renamed by me)'")
    library.conn.execute("INSERT INTO settings (scope, scope_id, key, value_json, updated_at)"
                         " VALUES ('global', '', 'extraction.method', '\"browser\"', '2026-09-17')")
    library.add_work("Only Local")

    report = restore_service(library, clock).restore(record.path, mode="merge")
    titles = {r[0] for r in library.conn.execute("SELECT display_title FROM works")}
    assert titles == {"Solo Leveling (renamed by me)", "Only Local"}      # current manual edit wins
    assert library.conn.execute("SELECT value_json FROM settings WHERE key = 'extraction.method'").fetchone()[0] == '"browser"'
    # the backup's shelf entry is restored; the locally added work keeps its own
    assert library.conn.execute("SELECT count(*) FROM shelf_entries").fetchone()[0] == 2
    assert report.kept["works"] >= 1


@pytest.mark.parametrize("backup_progress,current_progress,expected", [(0.9, 0.2, 0.9), (0.2, 0.9, 0.9)])
def test_merge_never_regresses_progress(library, clock, backup_progress, current_progress, expected):
    work = library.add_work("Solo Leveling", progress=backup_progress)
    record = make_backup(library, clock)
    library.conn.execute("UPDATE reading_state SET fraction = ?, revision = 5 WHERE reading_unit_id = ?",
                         (current_progress, work["unit_id"]))
    restore_service(library, clock).restore(record.path, mode="merge")
    fraction = library.conn.execute("SELECT fraction FROM reading_state WHERE reading_unit_id = ?",
                                    (work["unit_id"],)).fetchone()[0]
    assert fraction == pytest.approx(expected)


def test_merge_repairs_missing_or_corrupt_files_but_leaves_healthy_ones(library, clock):
    healthy = library.add_work("Healthy", content=b"healthy chapter")
    missing = library.add_work("Missing", content=b"missing chapter")
    corrupt = library.add_work("Corrupt", content=b"corrupt chapter")
    record = make_backup(library, clock, kind="full",
                         works=[healthy["work_id"], missing["work_id"], corrupt["work_id"]])

    (library.root_path / missing["relative"]).unlink()
    (library.root_path / corrupt["relative"]).write_bytes(b"damaged")
    library.conn.execute("UPDATE assets SET integrity = 'missing_local_file' WHERE id = ?", (missing["asset_id"],))
    library.conn.execute("UPDATE assets SET integrity = 'corrupt' WHERE id = ?", (corrupt["asset_id"],))
    (library.root_path / healthy["relative"]).write_bytes(b"healthy chapter edited by user")

    report = restore_service(library, clock).restore(record.path, mode="merge")
    assert report.repaired_files == 2
    assert (library.root_path / missing["relative"]).read_bytes() == b"missing chapter"
    assert (library.root_path / corrupt["relative"]).read_bytes() == b"corrupt chapter"
    assert (library.root_path / healthy["relative"]).read_bytes() == b"healthy chapter edited by user"
    integrity = {r[0] for r in library.conn.execute("SELECT integrity FROM assets")}
    assert integrity == {"ok"}


def test_missing_plugins_do_not_block_restore_and_are_reported(library, clock):
    library.add_work("Solo Leveling")
    library.add_plugin("mangadex", "1.2.0")
    record = make_backup(library, clock)
    library.conn.execute("DELETE FROM plugin_versions")
    library.conn.execute("DELETE FROM plugins")
    library.conn.execute("DELETE FROM reading_state")
    library.conn.execute("DELETE FROM assets")
    library.conn.execute("DELETE FROM reading_units")
    library.conn.execute("DELETE FROM source_tracks")
    library.conn.execute("DELETE FROM shelf_entries")
    library.conn.execute("DELETE FROM works")

    report = restore_service(library, clock).restore(record.path, mode="merge")
    assert report.plugins_missing == ["mangadex"]
    assert library.conn.execute("SELECT count(*) FROM works").fetchone()[0] == 1
    assert library.conn.execute("SELECT count(*) FROM source_tracks WHERE source_id = 'mangadex'").fetchone()[0] == 1


def test_new_plugin_permissions_require_explicit_approval(library, clock):
    library.add_work("Solo Leveling")
    library.add_plugin("mangadex", "1.2.0", ("network:domain:mangadex.org", "network:cdn:uploads.mangadex.org"))
    record = make_backup(library, clock)
    library.conn.execute("UPDATE plugin_versions SET approved_permissions_json = ?",
                         (json.dumps(["network:domain:mangadex.org"]),))

    service = restore_service(library, clock)
    preflight = service.preflight(record.path)
    assert preflight.plugins[0].new_permissions == ["network:cdn:uploads.mangadex.org"]
    with pytest.raises(RestoreBlocked, match="permission"):
        service.restore(record.path, mode="merge")
    report = service.restore(record.path, mode="merge", approve_new_permissions=True)
    assert report.plugins_missing == []
