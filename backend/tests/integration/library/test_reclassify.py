"""I-92 / I-94: repairing classification recorded before the shared classifier, without losing anything.

The library below is what an installation built before I-92 looks like: a Work from a source that leaves
type and language to its plugin, stored `unknown`/`und`, opened again by URL so the same listing has an `en`
twin, with progress, a bookmark, a correction, a download and a Follow spread across the two.
"""
from pathlib import Path

import pytest

from oneshelf.db.connection import open_database
from oneshelf.storage.roots import register_root

from ..test_library_api import TS, api  # noqa: F401  (the live Test Source with its plugin installed)

NOW = "2026-10-01T00:00:00+00:00"


def build_pre_i92_library(db_path, library_dir):
    with open_database(db_path) as conn:
        root = register_root(conn, "Old", library_dir)
        ex = conn.execute
        ex("INSERT INTO works (id, display_title, content_type, content_type_source, created_at, updated_at)"
           " VALUES ('w1', 'Unlabelled Scans', 'unknown', 'unknown', ?, ?)", (NOW, NOW))
        ex("INSERT INTO works (id, display_title, content_type, content_type_source, created_at, updated_at)"
           " VALUES ('w2', 'My Comic', 'comic', 'user', ?, ?)", (NOW, NOW))
        ex("INSERT INTO works (id, display_title, content_type, content_type_source, created_at, updated_at)"
           " VALUES ('w3', 'Local Only', 'unknown', 'unknown', ?, ?)", (NOW, NOW))
        ex("INSERT INTO source_listings (id, source_id, source_listing_key, raw_title, work_id, mapping_decided_by,"
           " created_at, last_seen_at) VALUES ('L1', ?, 'unlabelled', 'Unlabelled Scans', 'w1', 'user', ?, ?)",
           (TS, NOW, NOW))
        ex("INSERT INTO source_listings (id, source_id, source_listing_key, raw_title, work_id, mapping_decided_by,"
           " created_at, last_seen_at) VALUES ('L2', ?, 'paged', 'My Comic', 'w2', 'user', ?, ?)", (TS, NOW, NOW))
        for track, work, listing, language, kind, source in (("T-und", "w1", "L1", "und", "source", TS),
                                                              ("T-en", "w1", "L1", "en", "source", TS),
                                                              ("T-two", "w2", "L2", "und", "source", TS),
                                                              ("T-local", "w3", None, "und", "local", "local")):
            ex("INSERT INTO source_tracks (id, work_id, source_id, language, kind, listing_id, availability,"
               " created_at) VALUES (?,?,?,?,?,?, 'available', ?)", (track, work, source, language, kind, listing, NOW))
        for unit, track, key in (("u-und-1", "T-und", "un-1"), ("u-und-2", "T-und", "un-2"),
                                 ("u-en-1", "T-en", "un-1"), ("u-en-3", "T-en", "un-3"), ("u-two", "T-two", "pg-1"),
                                 ("u-local", "T-local", "local-1")):
            ex("INSERT INTO reading_units (id, track_id, source_unit_key, raw_title, display_title, unit_type,"
               " source_order, first_seen_at) VALUES (?,?,?,?,?, 'chapter', 1, ?)", (unit, track, key, key, key, NOW))
        # progress: further on the old (und) copy, behind on the twin -> must keep the further one
        ex("INSERT INTO reading_state (reading_unit_id, read_state, fraction, revision, updated_at)"
           " VALUES ('u-und-1', 'partial', 0.6, 3, ?)", (NOW,))
        ex("INSERT INTO reading_state (reading_unit_id, read_state, fraction, revision, updated_at)"
           " VALUES ('u-en-1', 'partial', 0.1, 1, ?)", (NOW,))
        ex("INSERT INTO reading_bookmarks (id, reading_unit_id, locator_json, locator_key, label, created_at)"
           " VALUES ('b1', 'u-und-1', '{\"page\":4}', '{\"page\":4}', 'fight', ?)", (NOW,))
        ex("INSERT INTO user_overrides (id, target_kind, target_id, field, value_json, created_at, updated_at)"
           " VALUES ('o1', 'reading_unit', 'u-und-2', 'number', '\"0.5\"', ?, ?)", (NOW, NOW))
        ex("UPDATE reading_units SET user_number = '0.5' WHERE id = 'u-und-2'")
        for asset, unit in (("a-und", "u-und-1"), ("a-en", "u-en-1")):
            ex("INSERT INTO assets (id, reading_unit_id, format, variant, storage_root_id, relative_path, size_bytes,"
               " sha256, integrity, created_at, updated_at) VALUES (?,?, 'cbz', '', ?, ?, 1, ?, 'ok', ?, ?)",
               (asset, unit, root.id, f"x/{asset}.cbz", "0" * 64, NOW, NOW))
        ex("INSERT INTO follows (id, work_id, language, preferred_source_id, track_id, created_at)"
           " VALUES ('f1', 'w1', 'und', ?, 'T-und', ?)", (TS, NOW))


def counts(conn):
    return {t: conn.execute(f"SELECT count(*) FROM {t}").fetchone()[0]
            for t in ("works", "reading_bookmarks", "user_overrides", "assets", "follows")}


@pytest.fixture
def old_library(api):
    client, tmp_path = api
    (tmp_path / "old-lib").mkdir()
    build_pre_i92_library(tmp_path / "data" / "oneshelf.db", tmp_path / "old-lib")
    return client, tmp_path


def test_preview_lists_the_repairs_and_writes_nothing(old_library):
    client, tmp_path = old_library
    db = tmp_path / "data" / "oneshelf.db"
    with open_database(db) as conn:
        before = conn.execute("SELECT group_concat(id || language) FROM source_tracks").fetchone()[0]
    preview = client.get("/api/maintenance/reclassification").json()
    kinds = sorted((c["kind"], c["work_id"]) for c in preview["changes"])
    assert kinds == [("track_language", "w2"), ("track_merge", "w1"), ("work_type", "w1")]
    assert preview["applied"] is False and preview["snapshot"] is None
    with open_database(db) as conn:
        assert conn.execute("SELECT group_concat(id || language) FROM source_tracks").fetchone()[0] == before


def test_apply_merges_the_twin_and_keeps_every_piece_of_the_library(old_library):
    client, tmp_path = old_library
    db = tmp_path / "data" / "oneshelf.db"
    with open_database(db) as conn:
        before = counts(conn)
    applied = client.post("/api/maintenance/reclassification").json()
    assert applied["applied"] is True and Path(applied["snapshot"]).is_file()
    with open_database(db) as conn:
        assert counts(conn) == before                                   # nothing lost
        tracks = {r["id"]: r["language"] for r in conn.execute("SELECT id, language FROM source_tracks")}
        assert tracks == {"T-en": "en", "T-two": "en", "T-local": "und"}
        units = {r["source_unit_key"]: r["id"] for r in conn.execute(
            "SELECT id, source_unit_key FROM reading_units WHERE track_id = 'T-en'")}
        assert set(units) == {"un-1", "un-2", "un-3"}                   # the twin's units joined, none duplicated
        state = conn.execute("SELECT read_state, fraction FROM reading_state WHERE reading_unit_id = ?",
                             (units["un-1"],)).fetchone()
        assert tuple(state) == ("partial", 0.6)                         # progress never regresses
        assert conn.execute("SELECT reading_unit_id FROM reading_bookmarks").fetchone()[0] == units["un-1"]
        assert conn.execute("SELECT user_number FROM reading_units WHERE id = ?", (units["un-2"],)).fetchone()[0] == "0.5"
        assets = conn.execute("SELECT variant FROM assets WHERE reading_unit_id = ? ORDER BY variant",
                              (units["un-1"],)).fetchall()
        assert [a[0] for a in assets] == ["", "merged-a-und"]           # both downloaded copies still recorded
        follow = conn.execute("SELECT track_id, language FROM follows").fetchone()
        assert tuple(follow) == ("T-en", "en")
        works = {r["id"]: (r["content_type"], r["content_type_source"]) for r in conn.execute("SELECT * FROM works")}
        assert works == {"w1": ("manga", "plugin_default"), "w2": ("comic", "user"), "w3": ("unknown", "unknown")}


def test_apply_is_idempotent(old_library):
    client, _ = old_library
    client.post("/api/maintenance/reclassification")
    again = client.post("/api/maintenance/reclassification").json()
    assert again["count"] == 0 and again["snapshot"] is None
    assert client.get("/api/maintenance/reclassification").json()["count"] == 0


def test_a_failure_part_way_leaves_the_library_as_it_was(old_library, monkeypatch):
    from oneshelf.library import reclassify
    client, tmp_path = old_library
    db = tmp_path / "data" / "oneshelf.db"
    with open_database(db) as conn:
        before = conn.execute("SELECT group_concat(id || ':' || track_id) FROM reading_units").fetchone()[0]

    def boom(*_args):
        raise RuntimeError("disk error in the middle of the merge")

    monkeypatch.setattr(reclassify, "_merge", boom)
    with pytest.raises(RuntimeError):
        client.post("/api/maintenance/reclassification")
    with open_database(db) as conn:
        assert conn.execute("SELECT group_concat(id || ':' || track_id) FROM reading_units").fetchone()[0] == before
        assert conn.execute("SELECT language FROM source_tracks WHERE id = 'T-two'").fetchone()[0] == "und"
