"""Migration 0017: an asset may be format 'text' after main's mark-operation migration.

Widening the format constraint rebuilds assets and the two tables that reference it, imports and
download_jobs. This checks that every row survives with its relationships, against a database that
already holds an asset, an import and a download job from the previous schema.
"""
import sqlite3
from contextlib import closing

import pytest

from oneshelf.db.migrate import Migration, MigrationError, current_version, migrate
from oneshelf.db.schema import MIGRATIONS

NOW = "2026-01-01T00:00:00+00:00"
VERSION = next(m.version for m in MIGRATIONS if m.name == "text_format")


def at_version(path, version):
    migrate(path, MIGRATIONS[:version], snapshot_dir=path.parent / "snap")


def insert_asset(conn, asset_id, fmt, relative_path, unit="u1"):
    conn.execute("INSERT INTO assets (id, reading_unit_id, format, storage_root_id, relative_path, size_bytes, sha256,"
                 " page_count, integrity, created_at, updated_at) VALUES (?, ?, ?, 'r1', ?, 10, ?, 3, 'ok', ?, ?)",
                 (asset_id, unit, fmt, relative_path, "a" * 64, NOW, NOW))


@pytest.fixture
def before(tmp_path):
    path = tmp_path / "oneshelf.db"
    at_version(path, VERSION - 1)
    with closing(sqlite3.connect(path)) as conn:
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("INSERT INTO works (id, display_title, created_at, updated_at) VALUES ('w1', 'W', ?, ?)", (NOW, NOW))
        conn.execute("INSERT INTO source_tracks (id, work_id, source_id, language, kind, created_at)"
                     " VALUES ('t1', 'w1', 'oneshelf.x', 'en', 'source', ?)", (NOW,))
        conn.execute("INSERT INTO reading_units (id, track_id, source_unit_key, source_order, first_seen_at)"
                     " VALUES ('u1', 't1', 'k1', 1, ?)", (NOW,))
        conn.execute("INSERT INTO storage_roots (id, name, path, created_at, updated_at)"
                     " VALUES ('r1', 'Library', '/library', ?, ?)", (NOW, NOW))
        insert_asset(conn, "a1", "cbz", "Comics/W/u1.cbz")
        conn.execute("INSERT INTO imports (id, original_filename, mode, format, state, work_id, asset_id, created_at,"
                     " updated_at) VALUES ('i1', 'u1.cbz', 'copy', 'cbz', 'completed', 'w1', 'a1', ?, ?)", (NOW, NOW))
        conn.execute("INSERT INTO download_batches (id, created_at, updated_at, paused) VALUES ('b1', ?, ?, 1)",
                     (NOW, NOW))
        conn.execute("INSERT INTO download_jobs (id, batch_id, reading_unit_id, state, attempts, created_at,"
                     " updated_at, method, asset_id, storage_root_id, bytes_done, manifest_json) VALUES"
                     " ('j1', 'b1', 'u1', 'COMPLETED', 2, ?, ?, 'html_api', 'a1', 'r1', 99, '{\"pages\": 3}')",
                     (NOW, NOW))
        conn.execute("INSERT INTO reading_bookmarks (id, reading_unit_id, locator_json, locator_key, label,"
                     " created_at, operation_id) VALUES ('bm1', 'u1', '{\"chapter\": 1}', 'chapter:1',"
                     " 'Chapter 1', ?, '00000000-0000-4000-8000-000000000001')", (NOW,))
        conn.execute("INSERT INTO reading_highlights (id, reading_unit_id, locator_json, text, colour,"
                     " created_at, operation_id) VALUES ('hl1', 'u1', '{\"chapter\": 1}', 'A passage',"
                     " 'yellow', ?, '00000000-0000-4000-8000-000000000002')", (NOW,))
        conn.commit()
    migrate(path, MIGRATIONS, snapshot_dir=tmp_path / "snap")
    return path


def test_rows_survive_the_rebuild(before):
    with closing(sqlite3.connect(before)) as conn:
        assert conn.execute("SELECT id, format, relative_path, page_count FROM assets").fetchall() == [
            ("a1", "cbz", "Comics/W/u1.cbz", 3)]
        assert conn.execute("SELECT id, asset_id, format FROM imports").fetchall() == [("i1", "a1", "cbz")]
        assert conn.execute("SELECT id, asset_id, method, attempts, bytes_done, manifest_json, storage_root_id"
                            " FROM download_jobs").fetchall() == [
            ("j1", "a1", "html_api", 2, 99, '{"pages": 3}', "r1")]


def test_relationships_and_indexes_are_intact(before):
    with closing(sqlite3.connect(before)) as conn:
        conn.execute("PRAGMA foreign_keys = ON")
        assert conn.execute("PRAGMA foreign_key_check").fetchall() == []
        for table in ("imports", "download_jobs"):
            targets = {(row[2], row[3]) for row in conn.execute(f"PRAGMA foreign_key_list({table})")}
            assert ("assets", "asset_id") in targets
        indexes = {row[1] for row in conn.execute("PRAGMA index_list(download_jobs)")}
        assert {"download_jobs_state", "download_jobs_batch", "download_jobs_unit"} <= indexes
        with pytest.raises(sqlite3.IntegrityError):                       # a job's asset must exist
            conn.execute("UPDATE download_jobs SET asset_id = 'nothing' WHERE id = 'j1'")
        with pytest.raises(sqlite3.IntegrityError):                       # still one asset per unit and format
            insert_asset(conn, "a2", "cbz", "Comics/W/other.cbz")


def test_text_is_now_a_format_and_nothing_else_is(before):
    with closing(sqlite3.connect(before)) as conn:
        insert_asset(conn, "a3", "text", "Novels/W/u1.ostext")
        with pytest.raises(sqlite3.IntegrityError):
            insert_asset(conn, "a4", "html", "Novels/W/u1.html")
        with pytest.raises(sqlite3.IntegrityError):                       # imports keep their own list
            conn.execute("INSERT INTO imports (id, original_filename, mode, format, state, created_at, updated_at)"
                         " VALUES ('i2', 'x.ostext', 'copy', 'text', 'completed', ?, ?)", (NOW, NOW))


def test_fresh_database_has_contiguous_migrations_and_both_schema_changes(tmp_path):
    assert [(m.version, m.name) for m in MIGRATIONS[-2:]] == [
        (16, "mark_operation_ids"), (17, "text_format")]
    assert [m.version for m in MIGRATIONS] == list(range(1, VERSION + 1))
    path = tmp_path / "fresh.db"
    assert migrate(path, MIGRATIONS, snapshot_dir=tmp_path / "snap") == list(range(1, VERSION + 1))
    with closing(sqlite3.connect(path)) as conn:
        assert conn.execute("SELECT version, name FROM schema_migrations ORDER BY version DESC LIMIT 2").fetchall() == [
            (17, "text_format"), (16, "mark_operation_ids")]
        assets_sql = conn.execute("SELECT sql FROM sqlite_master WHERE name = 'assets'").fetchone()[0]
        assert "'text'" in assets_sql
        for table in ("reading_bookmarks", "reading_highlights"):
            assert "operation_id" in {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}
        indexes = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'index'")}
        assert {"idx_reading_bookmarks_operation", "idx_reading_highlights_operation"} <= indexes


def test_main_mark_operations_and_snapshot_survive_upgrade(before):
    assert current_version(before) == 17
    with closing(sqlite3.connect(before)) as conn:
        assert conn.execute("SELECT operation_id FROM reading_bookmarks WHERE id = 'bm1'").fetchone() == (
            "00000000-0000-4000-8000-000000000001",)
        assert conn.execute("SELECT operation_id FROM reading_highlights WHERE id = 'hl1'").fetchone() == (
            "00000000-0000-4000-8000-000000000002",)
        indexes = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'index'")}
        assert {"idx_reading_bookmarks_operation", "idx_reading_highlights_operation"} <= indexes
    snapshots = list((before.parent / "snap").glob("pre-migration-v16-*.db"))
    assert len(snapshots) == 1
    with closing(sqlite3.connect(snapshots[0])) as conn:
        assert conn.execute("SELECT max(version) FROM schema_migrations").fetchone() == (16,)
        assert conn.execute("SELECT operation_id FROM reading_bookmarks WHERE id = 'bm1'").fetchone() == (
            "00000000-0000-4000-8000-000000000001",)
        assets_sql = conn.execute("SELECT sql FROM sqlite_master WHERE name = 'assets'").fetchone()[0]
        assert "'text'" not in assets_sql


def test_failed_text_migration_rolls_back_to_main_schema_and_can_retry(tmp_path):
    path = tmp_path / "retry.db"
    at_version(path, VERSION - 1)
    broken = Migration(VERSION, "text_format", "CREATE TABLE should_rollback (id INTEGER);"
                       " INSERT INTO missing_table VALUES (1);")
    with pytest.raises(MigrationError, match="migration v17"):
        migrate(path, (*MIGRATIONS[:-1], broken), snapshot_dir=tmp_path / "snap")
    assert current_version(path) == 16
    with closing(sqlite3.connect(path)) as conn:
        assert conn.execute("SELECT name FROM sqlite_master WHERE name = 'should_rollback'").fetchone() is None
        assert "operation_id" in {row[1] for row in conn.execute("PRAGMA table_info(reading_bookmarks)")}
    assert migrate(path, MIGRATIONS, snapshot_dir=tmp_path / "snap") == [17]
