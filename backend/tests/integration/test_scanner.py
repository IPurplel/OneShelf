"""Master §24.6–24.7, §38: reconciliation never deletes records and never mass-marks offline roots."""
import os
import shutil
from pathlib import Path

import pytest

from oneshelf.importer.service import CreateLocalWork, import_file
from oneshelf.storage.roots import register_root
from oneshelf.storage.scanner import reconcile
from tests.fixtures.builders import make_cbz, make_pdf


@pytest.fixture
def root(db, tmp_path):
    (tmp_path / "lib").mkdir()
    return register_root(db, "Library", tmp_path / "lib")


@pytest.fixture
def imported(db, root, tmp_path):
    (tmp_path / "inbox").mkdir()
    outs = [
        import_file(db, make_cbz(tmp_path / "inbox" / f"{i}.cbz"), decision=CreateLocalWork(title=f"W{i}", content_type="manga"))
        for i in range(3)
    ]
    return outs


def integrity(db, asset_id):
    return db.execute("SELECT integrity FROM assets WHERE id = ?", (asset_id,)).fetchone()[0]


def test_healthy_library_reconciles_without_changes(db, root, imported):
    report = reconcile(db)
    assert report.changed == 0 and report.missing == 0


def test_manual_deletion_marks_missing_but_keeps_records(db, root, imported):
    victim = imported[0]
    os.remove(Path(root.path) / victim.relative_path)
    report = reconcile(db)
    assert report.missing == 1
    assert integrity(db, victim.asset_id) == "missing_local_file"
    for table, col, value in [("works", "id", victim.work_id), ("reading_units", "id", victim.unit_id),
                              ("shelf_entries", "work_id", victim.work_id), ("assets", "id", victim.asset_id)]:
        assert db.execute(f"SELECT count(*) FROM {table} WHERE {col} = ?", (value,)).fetchone()[0] == 1
    assert reconcile(db).changed == 0  # repeatable


def test_offline_root_is_unavailable_not_mass_missing(db, root, imported, tmp_path):
    shutil.move(tmp_path / "lib", tmp_path / "lib-unmounted")
    (tmp_path / "lib").mkdir()  # empty mount point
    report = reconcile(db)
    assert report.unavailable_roots == [root.id]
    assert report.missing == 0
    assert {integrity(db, o.asset_id) for o in imported} == {"ok"}
    assert db.execute("SELECT last_availability FROM storage_roots").fetchone()[0] == "unavailable"


def test_root_reconnect_restores_previously_missing_assets(db, root, imported, tmp_path):
    victim = imported[1]
    path = Path(root.path) / victim.relative_path
    saved = path.read_bytes()
    path.unlink()
    reconcile(db)
    assert integrity(db, victim.asset_id) == "missing_local_file"
    path.write_bytes(saved)
    reconcile(db)
    assert integrity(db, victim.asset_id) == "ok"
    assert db.execute("SELECT last_availability FROM storage_roots").fetchone()[0] == "available"


def test_manual_relocation_is_recovered_by_id_and_checksum(db, root, imported):
    victim = imported[2]
    old = Path(root.path) / victim.relative_path
    new_dir = Path(root.path) / "Sorted by me"
    new_dir.mkdir()
    shutil.move(old, new_dir / old.name)
    report = reconcile(db)
    assert report.relocated == 1
    row = db.execute("SELECT relative_path, integrity FROM assets WHERE id = ?", (victim.asset_id,)).fetchone()
    assert row["relative_path"] == f"Sorted by me/{old.name}" and row["integrity"] == "ok"


def test_relocated_file_with_different_content_is_not_adopted(db, root, imported, tmp_path):
    victim = imported[0]
    old = Path(root.path) / victim.relative_path
    impostor_dir = Path(root.path) / "Elsewhere"
    impostor_dir.mkdir()
    make_pdf(impostor_dir / old.name)
    old.unlink()
    reconcile(db)
    assert integrity(db, victim.asset_id) == "missing_local_file"


def test_size_change_marks_corrupt(db, root, imported):
    victim = imported[0]
    with open(Path(root.path) / victim.relative_path, "ab") as f:
        f.write(b"garbage")
    reconcile(db)
    assert integrity(db, victim.asset_id) == "corrupt"


def test_symlink_replacing_asset_is_not_followed(db, root, imported, tmp_path):
    victim = imported[0]
    path = Path(root.path) / victim.relative_path
    outside = tmp_path / "outside.cbz"
    shutil.move(path, outside)
    os.symlink(outside, path)
    reconcile(db)
    assert integrity(db, victim.asset_id) == "missing_local_file"


def test_staging_contents_are_never_relocation_candidates(db, root, imported):
    victim = imported[0]
    old = Path(root.path) / victim.relative_path
    stash = Path(root.path) / ".oneshelf" / "staging" / "manual"
    stash.mkdir()
    shutil.move(old, stash / old.name)
    report = reconcile(db)
    assert report.relocated == 0
    assert integrity(db, victim.asset_id) == "missing_local_file"
