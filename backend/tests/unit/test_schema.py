"""Initial domain schema (Master §4, §22–24, Meta Prompt C1 domain boundaries)."""
import sqlite3

import pytest

from oneshelf.db.connection import open_database, transaction
from oneshelf.db.migrate import migrate
from oneshelf.db.schema import MIGRATIONS
from oneshelf.domain.ids import new_id

NOW = "2026-09-17T00:00:00+00:00"


@pytest.fixture
def conn(tmp_path):
    db = tmp_path / "oneshelf.db"
    migrate(db, MIGRATIONS, snapshot_dir=tmp_path / "snap")
    c = open_database(db)
    yield c
    c.close()


def add_work(conn, title="Solo Leveling", content_type="manhwa"):
    wid = new_id()
    conn.execute(
        "INSERT INTO works (id, display_title, content_type, created_at, updated_at) VALUES (?,?,?,?,?)",
        (wid, title, content_type, NOW, NOW),
    )
    return wid


def add_track(conn, work_id, source_id="local", language="ar", kind="local"):
    tid = new_id()
    conn.execute(
        "INSERT INTO source_tracks (id, work_id, source_id, language, kind, created_at) VALUES (?,?,?,?,?,?)",
        (tid, work_id, source_id, language, kind, NOW),
    )
    return tid


def add_unit(conn, track_id, key, order, number=None, unit_type="chapter"):
    uid = new_id()
    conn.execute(
        "INSERT INTO reading_units (id, track_id, source_unit_key, unit_type, source_number, source_order, first_seen_at)"
        " VALUES (?,?,?,?,?,?,?)",
        (uid, track_id, key, unit_type, number, order, NOW),
    )
    return uid


def add_root(conn, root_id="r1"):
    conn.execute(
        "INSERT INTO storage_roots (id, name, path, is_default, created_at, updated_at) VALUES (?,?,?,?,?,?)",
        (root_id, "Library", "/library", 1, NOW, NOW),
    )
    return root_id


def test_ids_are_short_unique_and_filename_safe():
    ids = {new_id() for _ in range(2000)}
    assert len(ids) == 2000
    assert all(len(i) == 12 and i.isalnum() and i.islower() for i in ids)


def test_foreign_keys_are_enforced(conn):
    with pytest.raises(sqlite3.IntegrityError):
        add_track(conn, "no-such-work")


def test_same_title_distinct_works_are_allowed(conn):
    a, b = add_work(conn, "Berserk", "manga"), add_work(conn, "Berserk", "novel")
    assert a != b


def test_one_track_per_work_source_language(conn):
    w = add_work(conn)
    add_track(conn, w, "mangadex", "en", "source")
    add_track(conn, w, "mangadex", "ar", "source")  # different language: distinct track
    add_track(conn, w, "3asq", "ar", "source")  # different source: distinct track
    with pytest.raises(sqlite3.IntegrityError):
        add_track(conn, w, "mangadex", "en", "source")


def test_unknown_language_is_representable(conn):
    w = add_work(conn)
    add_track(conn, w, "local", "und")


def test_unit_numbers_are_not_identity(conn):
    t = add_track(conn, add_work(conn))
    add_unit(conn, t, "src-1", 1, number="10")
    add_unit(conn, t, "src-2", 2, number="10")  # repeated number is legal
    add_unit(conn, t, "src-3", 3, number="3.5", unit_type="special")
    add_unit(conn, t, "src-4", 4, number=None, unit_type="prologue")
    with pytest.raises(sqlite3.IntegrityError):
        add_unit(conn, t, "src-1", 5)  # stable source key is identity within a track


def test_unit_type_rejects_unknown_values(conn):
    t = add_track(conn, add_work(conn))
    with pytest.raises(sqlite3.IntegrityError):
        add_unit(conn, t, "k", 1, unit_type="episode-ish")


def test_asset_paths_are_root_relative_and_unique_per_root(conn):
    t = add_track(conn, add_work(conn))
    u = add_unit(conn, t, "k", 1)
    add_root(conn, "r1")
    add_root(conn, "r2")

    def add_asset(root, path, fmt="cbz", variant=""):
        conn.execute(
            "INSERT INTO assets (id, reading_unit_id, format, variant, storage_root_id, relative_path, size_bytes, sha256,"
            " integrity, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (new_id(), u, fmt, variant, root, path, 1, "0" * 64, "ok", NOW, NOW),
        )

    add_asset("r1", "Sequential Art/x.cbz")
    add_asset("r2", "Sequential Art/x.cbz", fmt="pdf")
    with pytest.raises(sqlite3.IntegrityError):
        add_asset("r1", "Sequential Art/x.cbz", fmt="epub")
    with pytest.raises(sqlite3.IntegrityError):
        add_asset("r1", "/abs/path.cbz", fmt="epub")  # absolute paths rejected


def test_tracks_with_assets_cannot_be_deleted_by_cascade(conn):
    w = add_work(conn)
    t = add_track(conn, w)
    u = add_unit(conn, t, "k", 1)
    add_root(conn)
    conn.execute(
        "INSERT INTO assets (id, reading_unit_id, format, storage_root_id, relative_path, size_bytes, sha256, integrity,"
        " created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
        (new_id(), u, "pdf", "r1", "Books/a.pdf", 1, "0" * 64, "ok", NOW, NOW),
    )
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("DELETE FROM works WHERE id = ?", (w,))


def test_shelf_and_follow_are_independent(conn):
    w = add_work(conn)
    t = add_track(conn, w, "mangadex", "en", "source")
    with transaction(conn):
        conn.execute("INSERT INTO shelf_entries (work_id, added_at) VALUES (?, ?)", (w, NOW))
        conn.execute(
            "INSERT INTO follows (id, work_id, language, preferred_source_id, track_id, created_at) VALUES (?,?,?,?,?,?)",
            (new_id(), w, "en", "mangadex", t, NOW),
        )
    conn.execute("DELETE FROM shelf_entries WHERE work_id = ?", (w,))
    assert conn.execute("SELECT count(*) FROM follows WHERE work_id = ?", (w,)).fetchone()[0] == 1


def test_download_job_states_are_constrained(conn):
    t = add_track(conn, add_work(conn))
    u = add_unit(conn, t, "k", 1)
    b = new_id()
    conn.execute("INSERT INTO download_batches (id, created_at, updated_at) VALUES (?,?,?)", (b, NOW, NOW))
    states = ["QUEUED", "PREPARING", "DOWNLOADING", "VERIFYING", "PACKAGING", "COMMITTING", "COMPLETED", "PAUSED",
              "WAITING_FOR_SESSION", "WAITING_FOR_RATE_LIMIT", "RETRY_WAIT", "FAILED", "CANCELED", "RECOVERING"]
    for s in states:
        conn.execute(
            "INSERT INTO download_jobs (id, batch_id, reading_unit_id, state, created_at, updated_at) VALUES (?,?,?,?,?,?)",
            (new_id(), b, u, s, NOW, NOW),
        )
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO download_jobs (id, batch_id, reading_unit_id, state, created_at, updated_at) VALUES (?,?,?,?,?,?)",
            (new_id(), b, u, "DONE-ish", NOW, NOW),
        )


def test_notification_dedupe_key_is_unique(conn):
    ins = ("INSERT INTO notifications (id, dedupe_key, class, created_at, updated_at) VALUES (?,?,?,?,?)")
    conn.execute(ins, (new_id(), "storage-low:r1", "important", NOW, NOW))
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(ins, (new_id(), "storage-low:r1", "important", NOW, NOW))


def test_session_references_hold_no_secret_material(conn):
    cols = {r["name"] for r in conn.execute("PRAGMA table_info(source_session_refs)")}
    assert cols and not cols & {"cookies", "token", "password", "secret", "session_data", "headers"}


def test_expected_domain_tables_exist(conn):
    names = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert {
        "storage_roots", "works", "work_aliases", "source_listings", "source_tracks", "reading_units", "assets",
        "work_mappings", "user_overrides", "catalog_snapshots", "shelf_entries", "follows", "reading_state",
        "download_batches", "download_jobs", "commit_journal", "imports", "notifications", "backup_records",
        "export_jobs", "source_session_refs",
    } <= names
