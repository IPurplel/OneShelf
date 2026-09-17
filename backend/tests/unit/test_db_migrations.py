"""Master §18 / Meta Prompt C1: WAL, migrations, consistent snapshots, recoverable failures."""
import sqlite3
from contextlib import closing

import pytest

from oneshelf.db.connection import open_database, transaction
from oneshelf.db.migrate import Migration, MigrationError, NewerSchemaError, current_version, migrate

M1 = Migration(1, "create_a", "CREATE TABLE a (id INTEGER PRIMARY KEY, v TEXT NOT NULL);")
M2 = Migration(2, "create_b", "CREATE TABLE b (id INTEGER PRIMARY KEY);\nINSERT INTO a (v) VALUES ('seed');")
BROKEN = Migration(3, "broken", "CREATE TABLE c (id INTEGER PRIMARY KEY);\nINSERT INTO missing_table VALUES (1);")


def tables(path):
    with closing(sqlite3.connect(path)) as c:
        return {r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'")}


def test_connection_uses_wal_and_foreign_keys(tmp_path):
    conn = open_database(tmp_path / "x.db")
    assert conn.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
    assert conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1
    assert conn.execute("PRAGMA synchronous").fetchone()[0] == 2  # FULL
    conn.close()


def test_transaction_rolls_back_on_error(tmp_path):
    conn = open_database(tmp_path / "x.db")
    conn.execute("CREATE TABLE t (v INTEGER)")
    with pytest.raises(RuntimeError):
        with transaction(conn):
            conn.execute("INSERT INTO t VALUES (1)")
            raise RuntimeError("boom")
    assert conn.execute("SELECT count(*) FROM t").fetchone()[0] == 0
    conn.close()


def test_fresh_database_migrates_to_latest(tmp_path):
    db = tmp_path / "app.db"
    applied = migrate(db, [M1, M2], snapshot_dir=tmp_path / "snap")
    assert applied == [1, 2]
    assert current_version(db) == 2
    assert {"a", "b"} <= tables(db)


def test_migrate_is_idempotent(tmp_path):
    db = tmp_path / "app.db"
    migrate(db, [M1, M2], snapshot_dir=tmp_path / "snap")
    assert migrate(db, [M1, M2], snapshot_dir=tmp_path / "snap") == []


def test_newer_schema_is_refused_without_changes(tmp_path):
    db = tmp_path / "app.db"
    migrate(db, [M1, M2], snapshot_dir=tmp_path / "snap")
    before = db.read_bytes()
    with pytest.raises(NewerSchemaError):
        migrate(db, [M1], snapshot_dir=tmp_path / "snap")
    assert current_version(db) == 2
    assert db.read_bytes() == before


def test_failed_migration_rolls_back_completely(tmp_path):
    db = tmp_path / "app.db"
    migrate(db, [M1, M2], snapshot_dir=tmp_path / "snap")
    with pytest.raises(MigrationError):
        migrate(db, [M1, M2, BROKEN], snapshot_dir=tmp_path / "snap")
    assert current_version(db) == 2
    assert "c" not in tables(db)  # DDL from the failed migration did not persist


def test_existing_database_is_snapshotted_before_migrating(tmp_path):
    db = tmp_path / "app.db"
    snap = tmp_path / "snap"
    migrate(db, [M1], snapshot_dir=snap)
    with open_database(db) as conn, transaction(conn):
        conn.execute("INSERT INTO a (v) VALUES ('user data')")
    migrate(db, [M1, M2], snapshot_dir=snap)
    snapshots = sorted(snap.glob("pre-migration-v1-*.db"))
    assert len(snapshots) == 1
    with closing(sqlite3.connect(snapshots[0])) as c:
        assert c.execute("SELECT integrity_check FROM pragma_integrity_check").fetchone()[0] == "ok"
        assert [r[0] for r in c.execute("SELECT v FROM a")] == ["user data"]
        assert "b" not in {r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'")}


def test_fresh_database_needs_no_snapshot(tmp_path):
    snap = tmp_path / "snap"
    migrate(tmp_path / "app.db", [M1], snapshot_dir=snap)
    assert not snap.exists() or not any(snap.iterdir())


def test_migrations_must_be_contiguous(tmp_path):
    with pytest.raises(MigrationError):
        migrate(tmp_path / "app.db", [M1, Migration(3, "gap", "SELECT 1;")], snapshot_dir=tmp_path / "s")
