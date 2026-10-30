"""Master §33.1–33.5, §33.8–33.9, §18; INV-19: backup contents, exclusions, verification, rotation."""
import sqlite3
import zipfile
import json
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


@pytest.mark.parametrize("change", ["missing", "changed"])
def test_i68_full_backup_refuses_selected_content_that_does_not_match_asset(library, clock, change):
    work = library.add_work("Selected", content=b"original")
    source = library.root_path / work["relative"]
    if change == "missing":
        source.unlink()
    else:
        source.write_bytes(b"different")

    with pytest.raises(BackupError):
        service(library, clock).create("full", works=[work["work_id"]])
    assert library.conn.execute("SELECT count(*) FROM backup_records WHERE state = 'verified'").fetchone()[0] == 0


def test_i68_verify_detects_selected_content_removed_from_archive_and_manifest(library, clock, tmp_path):
    import json

    work = library.add_work("Selected", content=b"original")
    backup = service(library, clock)
    record = backup.create("full", works=[work["work_id"]])
    assert backup.verify(record.path).ok
    omitted = tmp_path / "omitted.osbackup"
    with zipfile.ZipFile(record.path) as source, zipfile.ZipFile(omitted, "w") as target:
        manifest = json.loads(source.read("manifest.json"))
        manifest["content"] = []
        manifest.pop("expected_content", None)
        manifest["inventory"] = [entry for entry in manifest["inventory"] if entry["path"] == "library.db"]
        target.writestr("library.db", source.read("library.db"))
        target.writestr("manifest.json", json.dumps(manifest))
    assert not backup.verify(omitted).ok


def test_i68_full_backup_refuses_unreadable_selected_content(library, clock, monkeypatch):
    import builtins

    work = library.add_work("Unreadable", content=b"original")
    source = library.root_path / work["relative"]
    original_open = builtins.open

    def unreadable(path, *args, **kwargs):
        if isinstance(path, (str, Path)) and Path(path) == source:
            raise PermissionError("inaccessible")
        return original_open(path, *args, **kwargs)

    monkeypatch.setattr(builtins, "open", unreadable)
    with pytest.raises(BackupError, match="unavailable"):
        service(library, clock).create("full", works=[work["work_id"]])


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


@pytest.mark.parametrize("manifest", [[], {"content": None}, b"\xff\xfe"])
def test_i87_malformed_backup_manifest_is_reported_as_unreadable(library, clock, tmp_path, manifest):
    library.add_work("Selected")
    backup = service(library, clock)
    original = backup.create("library")
    malformed = tmp_path / "malformed.osbackup"
    with zipfile.ZipFile(original.path) as source, zipfile.ZipFile(malformed, "w") as target:
        target.writestr("library.db", source.read("library.db"))
        if isinstance(manifest, dict):
            original_manifest = json.loads(source.read("manifest.json"))
            original_manifest.update(manifest)
            manifest = original_manifest
        target.writestr("manifest.json", manifest if isinstance(manifest, bytes) else json.dumps(manifest))

    result = backup.verify(malformed)
    assert not result.ok and result.reason


def test_i88_backup_verification_requires_a_database_inventory_checksum(library, clock, tmp_path):
    library.add_work("Selected")
    backup = service(library, clock)
    original = backup.create("library")
    missing_inventory = tmp_path / "no-database-checksum.osbackup"
    with zipfile.ZipFile(original.path) as source, zipfile.ZipFile(missing_inventory, "w") as target:
        manifest = json.loads(source.read("manifest.json"))
        manifest["inventory"] = []
        target.writestr("library.db", source.read("library.db"))
        target.writestr("manifest.json", json.dumps(manifest))

    assert not backup.verify(missing_inventory).ok


def test_i89_full_backup_streams_large_selected_content_without_loading_it_all_into_memory(library, clock):
    import gc
    import tracemalloc

    content = b"large selected content" * (1024 * 1024)
    work = library.add_work("Large selected", content=content)
    backup = service(library, clock)

    gc.collect()
    tracemalloc.start()
    try:
        record = backup.create("full", works=[work["work_id"]])
        assert backup.verify(record.path).ok
        _current, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()

    assert peak < 8 * 1024 * 1024, f"full backup retained {peak} bytes of working memory"


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


# -- I-105 (BE-015): remote Web UI authentication never travels in a backup (Master §33.3) ---------------

REMOTE_AUTH_TABLES = ("remote_sessions", "remote_recovery", "remote_credentials", "webauthn_challenges")


def test_i105_backup_excludes_remote_web_ui_authentication(library, clock, tmp_path):
    now = "2026-10-19T00:00:00+00:00"
    library.conn.execute("INSERT INTO remote_sessions (id, token_hash, label, created_at, last_active_at)"
                         " VALUES ('s1', 'hash-of-a-live-token', 'Phone', ?, ?)", (now, now))
    library.conn.execute("INSERT INTO remote_recovery (id, verifier, salt, created_at) VALUES (1, 'v', 's', ?)",
                         (now,))
    library.conn.execute("INSERT INTO remote_credentials (credential_id, public_key, label, created_at)"
                         " VALUES ('c1', x'00', 'Phone', ?)", (now,))
    record = service(library, clock).create("library")
    with zipfile.ZipFile(record.path) as z:
        z.extract("library.db", tmp_path / "check")
    with closing(sqlite3.connect(tmp_path / "check" / "library.db")) as conn:
        for table in REMOTE_AUTH_TABLES:
            assert conn.execute(f"SELECT count(*) FROM {table}").fetchone()[0] == 0, table
    assert b"hash-of-a-live-token" not in Path(record.path).read_bytes()


def test_i105_every_table_is_either_carried_or_excluded_on_purpose(library):
    """A new table must be classified before it can ride along in backups unreviewed."""
    from oneshelf.backup.service import EXCLUDED_TABLES as excluded, KEPT_TABLES as kept
    tables = {r[0] for r in library.conn.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%'"
        " AND name NOT LIKE 'search_index_%'")}
    assert not set(excluded) & set(kept)
    assert tables - set(excluded) - set(kept) == set(), "classify these tables for backups"


def test_backup_carries_private_notes_ratings_tags_and_collections(library, clock, tmp_path):
    work = library.add_work("Private library")["work_id"]
    library.conn.execute("INSERT INTO tags VALUES ('tag', 'Favorites', '#123456', '2026-10-29')")
    library.conn.execute("INSERT INTO work_tags VALUES (?, 'tag', '2026-10-29')", (work,))
    library.conn.execute("INSERT INTO collections VALUES ('collection', 'Reading next', 0, NULL, '2026-10-29', '2026-10-29')")
    library.conn.execute("INSERT INTO collection_works VALUES ('collection', ?, '2026-10-29')", (work,))
    library.conn.execute("INSERT INTO work_notes VALUES (?, 8, 'Private note', '2026-10-29', '2026-10-29')", (work,))

    record = service(library, clock).create("library")
    with zipfile.ZipFile(record.path) as archive:
        archive.extract("library.db", tmp_path / "private-check")
    with closing(sqlite3.connect(tmp_path / "private-check" / "library.db")) as conn:
        assert conn.execute("SELECT name, color FROM tags").fetchall() == [("Favorites", "#123456")]
        assert conn.execute("SELECT work_id, tag_id FROM work_tags").fetchall() == [(work, "tag")]
        assert conn.execute("SELECT name FROM collections").fetchall() == [("Reading next",)]
        assert conn.execute("SELECT collection_id, work_id FROM collection_works").fetchall() == [("collection", work)]
        assert conn.execute("SELECT work_id, rating, note FROM work_notes").fetchall() == [(work, 8, "Private note")]
    assert not {"tags", "work_tags", "collections", "collection_works", "work_notes"} & read_manifest(Path(record.path))["counts"].keys()
