"""A source edition has its own durable track without losing older library data."""

from oneshelf.db.connection import open_database
from oneshelf.db.migrate import migrate
from oneshelf.db.schema import MIGRATIONS
from oneshelf.domain.clock import utcnow_iso


def test_upgrade_preserves_units_and_archives_stale_source_links(tmp_path):
    path = tmp_path / "library.db"
    migrate(path, MIGRATIONS[:19], snapshot_dir=tmp_path / "snapshots")
    now = utcnow_iso()
    with open_database(path) as conn:
        for work in ("old", "new"):
            conn.execute("INSERT INTO works (id, display_title, created_at, updated_at) VALUES (?,?,?,?)",
                         (work, work, now, now))
        conn.execute("INSERT INTO source_listings (id, source_id, source_listing_key, raw_title, work_id, created_at)"
                     " VALUES ('listing', 'source', 'edition', 'Old edition', 'new', ?)", (now,))
        conn.execute("INSERT INTO source_tracks (id, work_id, source_id, language, kind, listing_id, created_at)"
                     " VALUES ('old-track', 'old', 'source', 'en', 'source', 'listing', ?)", (now,))
        conn.execute("INSERT INTO source_tracks (id, work_id, source_id, language, kind, created_at)"
                     " VALUES ('orphan-track', 'new', 'source', 'en', 'source', ?)", (now,))
        conn.execute("INSERT INTO reading_units (id, track_id, source_unit_key, source_order, first_seen_at)"
                     " VALUES ('saved', 'old-track', 'chapter', 1, ?)", (now,))
    assert migrate(path, MIGRATIONS[:20], snapshot_dir=tmp_path / "snapshots") == [20]   # the v20 upgrade itself
    with open_database(path) as conn:
        track = conn.execute("SELECT listing_id, listing_title, listing_key, availability"
                             " FROM source_tracks WHERE id = 'old-track'").fetchone()
        assert (track["listing_id"], track["availability"]) == (None, "unavailable")
        assert (track["listing_title"], track["listing_key"]) == ("Old edition", "edition")
        assert conn.execute("SELECT availability FROM source_tracks WHERE id = 'orphan-track'").fetchone()[0] == \
            "unavailable"
        assert conn.execute("SELECT track_id FROM reading_units WHERE id = 'saved'").fetchone()[0] == "old-track"
        assert conn.execute("PRAGMA foreign_key_check").fetchall() == []


def test_fresh_schema_allows_two_listings_but_one_track_per_listing_language(tmp_path):
    path = tmp_path / "library.db"
    migrate(path, MIGRATIONS, snapshot_dir=tmp_path / "snapshots")
    now = utcnow_iso()
    with open_database(path) as conn:
        conn.execute("INSERT INTO works (id, display_title, created_at, updated_at) VALUES ('work','Work',?,?)",
                     (now, now))
        for key in ("first", "second"):
            conn.execute("INSERT INTO source_listings (id, source_id, source_listing_key, work_id, created_at)"
                         " VALUES (?, 'source', ?, 'work', ?)", (key, key, now))
            conn.execute("INSERT INTO source_tracks (id, work_id, source_id, language, kind, listing_id, created_at)"
                         " VALUES (?, 'work', 'source', 'en', 'source', ?, ?)", (key, key, now))
        assert conn.execute("SELECT count(*) FROM source_tracks").fetchone()[0] == 2
