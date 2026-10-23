"""Master §33.5–33.7: restore preflight, compatibility, Replace safety snapshot, deterministic Merge."""
import hashlib
import json
import zipfile
from pathlib import Path

import pytest

from oneshelf.backup.service import BackupService
from oneshelf.restore.service import RestoreBlocked, RestoreError, RestoreReport, RestoreService
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


def test_merge_maps_forked_listing_track_and_unit_ids_before_adding_chapters(tmp_path):
    from oneshelf.db.connection import open_database
    from oneshelf.db.migrate import migrate
    from oneshelf.db.schema import MIGRATIONS

    current_path, backup_path = tmp_path / "current.db", tmp_path / "backup.db"
    for path in (current_path, backup_path):
        migrate(path, MIGRATIONS, snapshot_dir=tmp_path / "snapshots")
    for path, suffix, unit_key in ((current_path, "current", "chapter-1"),
                                   (backup_path, "backup", "chapter-2")):
        with open_database(path) as conn:
            conn.execute("INSERT INTO works (id, display_title, created_at, updated_at)"
                         " VALUES ('work', 'Book', '2026-01-01', '2026-01-01')")
            conn.execute("INSERT INTO source_listings (id, source_id, source_listing_key, work_id, created_at)"
                         " VALUES (?, 'source', 'edition', 'work', '2026-01-01')", (f"{suffix}-listing",))
            conn.execute("INSERT INTO source_tracks (id, work_id, source_id, language, kind, listing_id, created_at)"
                         " VALUES (?, 'work', 'source', 'en', 'source', ?, '2026-01-01')",
                         (f"{suffix}-track", f"{suffix}-listing"))
            conn.execute("INSERT INTO reading_units (id, track_id, source_unit_key, source_order, first_seen_at)"
                         " VALUES (?, ?, ?, 1, '2026-01-01')", (f"{suffix}-unit", f"{suffix}-track", unit_key))
    with open_database(current_path) as conn:
        RestoreService(conn, current_path, backups=None)._merge(backup_path, RestoreReport(mode="merge"))
        units = conn.execute("SELECT track_id, source_unit_key FROM reading_units ORDER BY source_unit_key").fetchall()
        assert [(row["track_id"], row["source_unit_key"]) for row in units] == [
            ("current-track", "chapter-1"), ("current-track", "chapter-2")]
        assert conn.execute("PRAGMA foreign_key_check").fetchall() == []


def test_merge_does_not_follow_a_track_mapped_to_a_different_current_work(tmp_path):
    from oneshelf.db.connection import open_database
    from oneshelf.db.migrate import migrate
    from oneshelf.db.schema import MIGRATIONS

    current_path, backup_path = tmp_path / "current.db", tmp_path / "backup.db"
    for path in (current_path, backup_path):
        migrate(path, MIGRATIONS, snapshot_dir=tmp_path / "snapshots")
    for path, work_id, suffix in ((current_path, "current-work", "current"),
                                  (backup_path, "backup-work", "backup")):
        with open_database(path) as conn:
            conn.execute("INSERT INTO works (id, display_title, created_at, updated_at)"
                         " VALUES (?, 'Book', '2026-01-01', '2026-01-01')", (work_id,))
            conn.execute("INSERT INTO source_listings (id, source_id, source_listing_key, work_id, created_at)"
                         " VALUES (?, 'source', 'edition', ?, '2026-01-01')", (f"{suffix}-listing", work_id))
            conn.execute("INSERT INTO source_tracks (id, work_id, source_id, language, kind, listing_id, created_at)"
                         " VALUES (?, ?, 'source', 'en', 'source', ?, '2026-01-01')",
                         (f"{suffix}-track", work_id, f"{suffix}-listing"))
            if suffix == "backup":
                conn.execute("INSERT INTO follows (id, work_id, language, preferred_source_id, track_id, created_at)"
                             " VALUES ('backup-follow', ?, 'en', 'source', 'backup-track', '2026-01-01')",
                             (work_id,))
    with open_database(current_path) as conn:
        RestoreService(conn, current_path, backups=None)._merge(backup_path, RestoreReport(mode="merge"))
        assert conn.execute("SELECT count(*) FROM follows").fetchone()[0] == 0


def test_merge_preserves_backup_never_match_for_existing_listing_without_conflict(tmp_path):
    from oneshelf.db.connection import open_database
    from oneshelf.db.migrate import migrate
    from oneshelf.db.schema import MIGRATIONS

    current_path, backup_path = tmp_path / "current.db", tmp_path / "backup.db"
    for path in (current_path, backup_path):
        migrate(path, MIGRATIONS, snapshot_dir=tmp_path / "snapshots")
    for path, suffix in ((current_path, "current"), (backup_path, "backup")):
        with open_database(path) as conn:
            for work in ("book", "forbidden"):
                conn.execute("INSERT INTO works (id, display_title, created_at, updated_at)"
                             " VALUES (?,?, '2026-01-01', '2026-01-01')", (work, work))
            conn.execute("INSERT INTO source_listings (id, source_id, source_listing_key, work_id, created_at)"
                         " VALUES (?, 'source', 'edition', 'book', '2026-01-01')", (f"{suffix}-listing",))
            if suffix == "backup":
                conn.execute("INSERT INTO work_mappings (id, kind, listing_id, work_id, decided_by, created_at)"
                             " VALUES ('decision', 'never_match', 'backup-listing', 'forbidden', 'user', '2026-01-01')")
    with open_database(current_path) as conn:
        RestoreService(conn, current_path, backups=None)._merge(backup_path, RestoreReport(mode="merge"))
        row = conn.execute("SELECT listing_id, work_id FROM work_mappings WHERE id = 'decision'").fetchone()
        assert row is not None and tuple(row) == ("current-listing", "forbidden")


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


def test_merge_repairs_content_when_current_asset_has_a_different_id(library, clock):
    work = library.add_work("Forked asset", content=b"saved chapter")
    record = make_backup(library, clock, kind="full", works=[work["work_id"]])
    library.conn.execute("UPDATE assets SET id = 'current-asset', integrity = 'missing_local_file' WHERE id = ?",
                         (work["asset_id"],))
    (library.root_path / work["relative"]).unlink()

    report = restore_service(library, clock).restore(record.path, mode="merge")

    assert report.repaired_files == 1
    assert (library.root_path / work["relative"]).read_bytes() == b"saved chapter"
    assert library.conn.execute("SELECT integrity FROM assets WHERE id = 'current-asset'").fetchone()[0] == "ok"


def test_i89_full_restore_streams_large_content_repair_without_loading_it_into_memory(library, clock):
    import gc
    import tracemalloc

    content = b"large selected content" * (1024 * 1024)
    work = library.add_work("Large repair", content=content)
    backup = make_backup(library, clock, "full", works=[work["work_id"]])
    (library.root_path / work["relative"]).unlink()

    gc.collect()
    tracemalloc.start()
    try:
        report = restore_service(library, clock).restore(backup.path, mode="merge")
        _current, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()

    assert report.repaired_files == 1 and not report.issues
    assert peak < 8 * 1024 * 1024, f"full restore retained {peak} bytes of working memory"
    assert hashlib.sha256((library.root_path / work["relative"]).read_bytes()).hexdigest() == \
        hashlib.sha256(content).hexdigest()


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


def test_restore_blocks_failed_space_preflight_before_mutation(library, clock, monkeypatch):
    from collections import namedtuple
    import shutil
    library.add_work('Book')
    backup = make_backup(library, clock)
    library.conn.execute('DELETE FROM shelf_entries')
    usage = namedtuple('usage', 'total used free')
    monkeypatch.setattr(shutil, 'disk_usage', lambda _: usage(100, 100, 0))
    with pytest.raises(RestoreError, match='space'):
        restore_service(library, clock).restore(backup.path)
    assert library.conn.execute('SELECT count(*) FROM shelf_entries').fetchone()[0] == 0


def test_restore_does_not_recreate_unavailable_root(library, clock):
    library.add_work('Book')
    backup = make_backup(library, clock, 'full', works=[library.works['Book']['work_id']])
    library.root_path.rename(library.root_path.with_name('offline'))
    report = restore_service(library, clock).restore(backup.path)
    assert not library.root_path.exists()
    assert report.repaired_files == 0 and report.issues


def test_restore_failed_write_keeps_missing_asset_unhealthy(library, clock, monkeypatch):
    work = library.add_work('Book')
    backup = make_backup(library, clock, 'full', works=[library.works['Book']['work_id']])
    library.conn.execute('DELETE FROM assets')
    (library.root_path / work['relative']).unlink()
    original = Path.open
    def fail_content(path, *args, **kwargs):
        if path.name == "content" and path.is_relative_to(library.root_path):
            raise OSError('simulated write failure')
        return original(path, *args, **kwargs)
    monkeypatch.setattr(Path, 'open', fail_content)
    report = restore_service(library, clock).restore(backup.path)
    assert library.conn.execute('SELECT integrity FROM assets').fetchone()[0] != 'ok'
    assert report.repaired_files == 0 and report.issues


def test_i102_merge_restores_corrections_and_current_corrections_still_win(library, clock):
    """INV-04: a correction carried in a backup is applied; a correction made since then is kept."""
    from oneshelf.library.overrides import set_unit, set_work
    made = library.add_work("Berserk")
    set_work(library.conn, made["work_id"], content_type="manhwa")
    set_unit(library.conn, made["unit_id"], number="0", unit_type="prologue")
    record = make_backup(library, clock)
    # Since the backup: the type correction was changed and the unit corrections were cleared and lost.
    set_work(library.conn, made["work_id"], content_type="comic")
    library.conn.execute("DELETE FROM user_overrides WHERE target_kind = 'reading_unit'")
    library.conn.execute("UPDATE reading_units SET user_number = NULL, unit_type = 'chapter'")

    restore_service(library, clock).restore(record.path, mode="merge")
    work = library.conn.execute("SELECT content_type, content_type_source FROM works").fetchone()
    unit = library.conn.execute("SELECT user_number, unit_type FROM reading_units").fetchone()
    assert tuple(work) == ("comic", "user")                     # the current correction wins
    assert tuple(unit) == ("0", "prologue")                     # the backup's correction is restored and applied
