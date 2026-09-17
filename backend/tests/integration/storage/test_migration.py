"""Master §24.5–24.8: disk guard, offline roots, resumable migration, mount remap (INV-18)."""
import shutil
from pathlib import Path

import pytest

from oneshelf.domain.clock import utcnow_iso
from oneshelf.domain.ids import new_id
from oneshelf.storage.migration import MigrationError, StorageMigration
from oneshelf.storage.roots import GiB, register_root
from oneshelf.storage.scanner import reconcile

NOW = utcnow_iso()


@pytest.fixture
def roots(db, tmp_path):
    (tmp_path / "old").mkdir()
    (tmp_path / "new").mkdir()
    return register_root(db, "Library", tmp_path / "old"), tmp_path


def add_asset(db, root, relative, data=b"chapter bytes"):
    import hashlib
    work, track, unit, asset = new_id(), new_id(), new_id(), new_id()
    db.execute("INSERT INTO works (id, display_title, created_at, updated_at) VALUES (?,?,?,?)", (work, "W", NOW, NOW))
    db.execute("INSERT INTO source_tracks (id, work_id, source_id, language, kind, created_at) VALUES (?,?,?,?,?,?)",
               (track, work, "local", "en", "local", NOW))
    db.execute("INSERT INTO reading_units (id, track_id, source_unit_key, unit_type, source_order, first_seen_at)"
               " VALUES (?,?,?,?,?,?)", (unit, track, relative, "chapter", 1, NOW))
    path = Path(root.path) / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    db.execute("INSERT INTO assets (id, reading_unit_id, format, storage_root_id, relative_path, size_bytes, sha256,"
               " integrity, created_at, updated_at) VALUES (?,?,'cbz',?,?,?,?, 'ok', ?, ?)",
               (asset, unit, root.id, relative, len(data), hashlib.sha256(data).hexdigest(), NOW, NOW))
    return asset


def test_migration_copies_verifies_and_switches_without_deleting_the_old_copy(db, roots):
    root, tmp_path = roots
    add_asset(db, root, "Books/one.cbz")
    add_asset(db, root, "Books/two.cbz", b"second chapter")
    migration = StorageMigration(db)
    plan = migration.plan(root.id, tmp_path / "new")
    assert plan.files == 2 and plan.bytes > 0

    report = migration.run(plan)
    assert report.copied == 2 and report.verified == 2 and report.state == "completed"
    assert (tmp_path / "new" / "Books" / "one.cbz").read_bytes() == b"chapter bytes"
    assert (tmp_path / "old" / "Books" / "one.cbz").exists()          # never deleted automatically (§24.8)
    assert db.execute("SELECT path FROM storage_roots WHERE id = ?", (root.id,)).fetchone()[0] == str(tmp_path / "new")
    assert reconcile(db).missing == 0


def test_migration_resumes_after_an_interruption_without_recopying(db, roots):
    root, tmp_path = roots
    add_asset(db, root, "Books/one.cbz")
    add_asset(db, root, "Books/two.cbz", b"second chapter")
    copied = {"n": 0}

    def fault(point):
        if point == "file_copied":
            copied["n"] += 1
            if copied["n"] == 1:
                raise KeyboardInterrupt("interrupted")

    migration = StorageMigration(db, fault=fault)
    plan = migration.plan(root.id, tmp_path / "new")
    with pytest.raises(KeyboardInterrupt):
        migration.run(plan)
    assert migration.state(plan.id).state == "copying"

    resumed = StorageMigration(db).resume(plan.id)
    assert resumed.copied == 1 and resumed.state == "completed"      # only the missing file was copied
    assert (tmp_path / "new" / "Books" / "two.cbz").exists()


def test_migration_refuses_a_destination_without_enough_space(db, roots, monkeypatch):
    root, tmp_path = roots
    add_asset(db, root, "Books/one.cbz")
    from collections import namedtuple
    usage = namedtuple("usage", "total used free")
    monkeypatch.setattr(shutil, "disk_usage", lambda _p: usage(100 * GiB, 99 * GiB, 1024))
    with pytest.raises(MigrationError, match="space"):
        StorageMigration(db).plan(root.id, tmp_path / "new")


def test_migration_refuses_an_unavailable_or_overlapping_destination(db, roots):
    root, tmp_path = roots
    with pytest.raises(MigrationError):
        StorageMigration(db).plan(root.id, tmp_path / "missing")
    with pytest.raises(MigrationError, match="overlap"):
        StorageMigration(db).plan(root.id, Path(root.path) / "inside")


def test_old_copy_is_removed_only_on_an_explicit_request(db, roots):
    root, tmp_path = roots
    add_asset(db, root, "Books/one.cbz")
    migration = StorageMigration(db)
    plan = migration.plan(root.id, tmp_path / "new")
    migration.run(plan)
    assert (tmp_path / "old" / "Books" / "one.cbz").exists()
    removed = migration.discard_old_copy(plan.id)
    assert removed == 1 and not (tmp_path / "old" / "Books" / "one.cbz").exists()
    assert (tmp_path / "new" / "Books" / "one.cbz").exists()


def test_a_mount_path_change_only_remaps_and_validates(db, roots):
    root, tmp_path = roots
    add_asset(db, root, "Books/one.cbz")
    shutil.move(tmp_path / "old", tmp_path / "moved")
    migration = StorageMigration(db)
    remapped = migration.remap(root.id, tmp_path / "moved")
    assert remapped.path == str(tmp_path / "moved")
    assert migration.history(root.id) == []          # no copying happened
    assert reconcile(db).missing == 0


def test_offline_root_is_reported_and_never_mass_marked_missing(db, roots):
    root, tmp_path = roots
    add_asset(db, root, "Books/one.cbz")
    shutil.move(tmp_path / "old", tmp_path / "unmounted")
    (tmp_path / "old").mkdir()
    report = reconcile(db)
    assert report.unavailable_roots == [root.id] and report.missing == 0
    with pytest.raises(MigrationError, match="unavailable"):
        StorageMigration(db).plan(root.id, tmp_path / "new")
