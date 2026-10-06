"""Migration 0016: an asset may be format 'text' (text reading units, architecture review C).

Widening the format constraint rebuilds assets and the two tables that reference it, imports and
download_jobs. This checks that every row survives with its relationships, against a database that
already holds an asset, an import and a download job from the previous schema.
"""
import sqlite3
from contextlib import closing

import pytest

from oneshelf.db.migrate import migrate
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
