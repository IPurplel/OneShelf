"""Master §5.5–5.6, §20, §22, §23; INV-09, INV-10: Shelf, Follow and their independence."""
import sqlite3

import pytest

from oneshelf.catalog.trust import CatalogTrust
from oneshelf.domain.clock import utcnow_iso
from oneshelf.domain.ids import new_id
from oneshelf.follow.service import FollowService
from oneshelf.library.shelf import ShelfService
from oneshelf.plugins.results import Evidence, ListResult, UnitDescriptor
from oneshelf.search.index import index_work

NOW = utcnow_iso()


def units(*specs):
    entries = []
    for index, spec in enumerate(specs):
        key, title = (spec, spec) if isinstance(spec, str) else spec
        entries.append(UnitDescriptor(unit_key=key, order_index=index, raw_title=title, number=None, unit_type="chapter"))
    return ListResult("catalog", entries, True, Evidence(pages=1, stop_reason="single_response"))


@pytest.fixture
def library(db):
    def make_work(title="Solo Leveling", source="mangadex", language="en", content_type="manhwa"):
        work_id, track_id = new_id(), new_id()
        db.execute("INSERT INTO works (id, display_title, content_type, created_at, updated_at) VALUES (?,?,?,?,?)",
                   (work_id, title, content_type, NOW, NOW))
        db.execute("INSERT INTO source_tracks (id, work_id, source_id, language, kind, created_at) VALUES (?,?,?,?,?,?)",
                   (track_id, work_id, source, language, "source", NOW))
        index_work(db, work_id)
        return work_id, track_id

    return make_work


@pytest.fixture
def shelf(db):
    return ShelfService(db)


@pytest.fixture
def follow(db):
    return FollowService(db, CatalogTrust(db))


def unit_id(db, key):
    return db.execute("SELECT id FROM reading_units WHERE source_unit_key = ?", (key,)).fetchone()[0]


# -- My Shelf (§22) ---------------------------------------------------------------------------------

def test_adding_to_shelf_is_immediate_and_needs_no_files(library, shelf, db):
    work_id, _ = library()
    entry = shelf.add(work_id)
    assert entry.work_id == work_id and entry.is_favorite is False and entry.is_pinned is False
    assert db.execute("SELECT count(*) FROM assets").fetchone()[0] == 0
    assert [w.work_id for w in shelf.view("all")] == [work_id]
    assert [w.work_id for w in shelf.view("saved")] == [work_id]


def test_favourite_and_pin_are_independent(library, shelf):
    work_id, _ = library()
    shelf.add(work_id)
    shelf.set_favorite(work_id, True)
    assert [w.work_id for w in shelf.view("favorites")] == [work_id]
    assert shelf.get(work_id).is_pinned is False
    shelf.set_pinned(work_id, True)
    shelf.set_favorite(work_id, False)
    assert shelf.get(work_id).is_pinned is True and shelf.get(work_id).is_favorite is False
    assert [w.work_id for w in shelf.view("favorites")] == []


def test_reading_and_completed_views_follow_progress(library, shelf, follow, db):
    work_id, track_id = library()
    shelf.add(work_id)
    CatalogTrust(db).refresh(track_id, units("u1", "u2"), plugin_version="1.0.0")
    db.execute("INSERT INTO reading_state (reading_unit_id, read_state, fraction, revision, updated_at)"
               " VALUES (?, 'partial', 0.3, 1, ?)", (unit_id(db, "u1"), NOW))
    assert [w.work_id for w in shelf.view("reading")] == [work_id]
    shelf.set_completed(work_id, True)
    assert [w.work_id for w in shelf.view("completed")] == [work_id]
    assert [w.work_id for w in shelf.view("reading")] == []


def test_completed_survives_new_releases_and_counts_them(library, shelf, follow, db):
    work_id, track_id = library()
    shelf.add(work_id)
    CatalogTrust(db).refresh(track_id, units("u1", "u2"), plugin_version="1.0.0")
    follow.follow(work_id, language="en", source_id="mangadex", track_id=track_id)
    shelf.set_completed(work_id, True)
    CatalogTrust(db).refresh(track_id, units("u1", "u2", "u3", "u4"), plugin_version="1.0.0")
    follow.check(work_id)
    entry = shelf.get(work_id)
    assert entry.completed_at is not None            # §5.6 Completed stays Completed
    assert entry.releases_since_completion == 2
    assert [w.work_id for w in shelf.view("completed")] == [work_id]


def test_shelf_search_is_local_only(library, shelf, db):
    first, _ = library(title="Solo Leveling")
    second, _ = library(title="Berserk", source="3asq")
    shelf.add(first)
    shelf.add(second)
    assert [w.work_id for w in shelf.search("solo")] == [first]
    assert [w.work_id for w in shelf.search("مدرسة")] == []
    assert shelf.search("   ") == []


def test_remove_from_shelf_offers_file_choices_and_keeps_other_state(library, shelf, follow, db, tmp_path):
    work_id, track_id = library()
    shelf.add(work_id)
    follow.follow(work_id, language="en", source_id="mangadex", track_id=track_id)
    CatalogTrust(db).refresh(track_id, units("u1"), plugin_version="1.0.0")
    unit = unit_id(db, "u1")
    db.execute("INSERT INTO reading_state (reading_unit_id, read_state, fraction, revision, updated_at)"
               " VALUES (?, 'partial', 0.4, 1, ?)", (unit, NOW))
    db.execute("INSERT INTO storage_roots (id, name, path, is_default, created_at, updated_at)"
               " VALUES ('r1','L',?,1,?,?)", (str(tmp_path), NOW, NOW))
    (tmp_path / "Books").mkdir()
    (tmp_path / "Books" / "a.cbz").write_bytes(b"content")
    db.execute("INSERT INTO assets (id, reading_unit_id, format, storage_root_id, relative_path, size_bytes, sha256,"
               " integrity, created_at, updated_at) VALUES (?,?,'cbz','r1','Books/a.cbz',7,?, 'ok', ?, ?)",
               (new_id(), unit, "0" * 64, NOW, NOW))

    summary = shelf.removal_summary(work_id)
    assert summary["files"] == 1 and summary["has_progress"] is True and summary["is_followed"] is True

    shelf.remove(work_id, delete_files=False)
    assert shelf.get(work_id) is None
    assert (tmp_path / "Books" / "a.cbz").exists()
    assert db.execute("SELECT count(*) FROM follows WHERE work_id = ?", (work_id,)).fetchone()[0] == 1   # INV-10
    assert db.execute("SELECT read_state FROM reading_state WHERE reading_unit_id = ?", (unit,)).fetchone()[0] == "partial"


def test_delete_files_keeps_follow_shelf_and_progress(library, shelf, follow, db, tmp_path):
    work_id, track_id = library()
    shelf.add(work_id)
    follow.follow(work_id, language="en", source_id="mangadex", track_id=track_id)
    CatalogTrust(db).refresh(track_id, units("u1"), plugin_version="1.0.0")
    unit = unit_id(db, "u1")
    db.execute("INSERT INTO reading_state (reading_unit_id, read_state, fraction, revision, updated_at)"
               " VALUES (?, 'read', 1.0, 2, ?)", (unit, NOW))
    db.execute("INSERT INTO storage_roots (id, name, path, is_default, created_at, updated_at)"
               " VALUES ('r1','L',?,1,?,?)", (str(tmp_path), NOW, NOW))
    (tmp_path / "Books").mkdir()
    (tmp_path / "Books" / "a.cbz").write_bytes(b"content")
    db.execute("INSERT INTO assets (id, reading_unit_id, format, storage_root_id, relative_path, size_bytes, sha256,"
               " integrity, created_at, updated_at) VALUES (?,?,'cbz','r1','Books/a.cbz',7,?, 'ok', ?, ?)",
               (new_id(), unit, "0" * 64, NOW, NOW))

    removed = shelf.delete_files(work_id)
    assert removed == 1 and not (tmp_path / "Books" / "a.cbz").exists()
    assert shelf.get(work_id) is not None
    assert db.execute("SELECT count(*) FROM follows WHERE work_id = ?", (work_id,)).fetchone()[0] == 1
    assert db.execute("SELECT read_state FROM reading_state WHERE reading_unit_id = ?", (unit,)).fetchone()[0] == "read"
    assert db.execute("SELECT count(*) FROM assets").fetchone()[0] == 0


def _root_with_asset(db, tmp_path, work_id, track_id, unit_key, relative, *, content=b"content"):
    """Give a work one managed file, recorded exactly as the downloader records one."""
    CatalogTrust(db).refresh(track_id, units(unit_key), plugin_version="1.0.0")
    unit = unit_id(db, unit_key)
    root = db.execute("SELECT id FROM storage_roots WHERE path = ?", (str(tmp_path),)).fetchone()
    if root is None:
        root_id = new_id()
        db.execute("INSERT INTO storage_roots (id, name, path, is_default, created_at, updated_at)"
                   " VALUES (?,'L',?,1,?,?)", (root_id, str(tmp_path), NOW, NOW))
    else:
        root_id = root[0]
    target = tmp_path / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(content)
    db.execute("INSERT INTO assets (id, reading_unit_id, format, storage_root_id, relative_path, size_bytes, sha256,"
               " integrity, created_at, updated_at) VALUES (?,?,'cbz',?,?,?,?, 'ok', ?, ?)",
               (new_id(), unit, root_id, relative, len(content), "0" * 64, NOW, NOW))
    return unit, target


def test_delete_files_touches_only_this_works_files(library, shelf, db, tmp_path):
    """§22, §23: deleting one work's files is not a cleanup pass over the library."""
    keep_work, keep_track = library(title="Solo Leveling")
    go_work, go_track = library(title="The Irregular Chronicle")
    shelf.add(keep_work)
    shelf.add(go_work)
    _, kept_file = _root_with_asset(db, tmp_path, keep_work, keep_track, "keep-1", "Books/keep.cbz")
    _, gone_file = _root_with_asset(db, tmp_path, go_work, go_track, "go-1", "Books/go.cbz")

    assert shelf.delete_files(go_work) == 1

    assert not gone_file.exists()
    assert kept_file.exists(), "another work's file was deleted"
    remaining = [row["relative_path"] for row in db.execute("SELECT relative_path FROM assets")]
    assert remaining == ["Books/keep.cbz"]


def test_the_library_cannot_even_record_a_path_outside_its_root(library, db, tmp_path):
    """INV-14, §24.4: path safety is enforced by the schema, so an escaping asset cannot exist."""
    work_id, track_id = library()
    CatalogTrust(db).refresh(track_id, units("u1"), plugin_version="1.0.0")
    unit = unit_id(db, "u1")
    db.execute("INSERT INTO storage_roots (id, name, path, is_default, created_at, updated_at)"
               " VALUES ('r1','L',?,1,?,?)", (str(tmp_path), NOW, NOW))

    for escaping in ("../outside.cbz", "/etc/passwd", "Books/../../outside.cbz", "Books/.."):
        with pytest.raises(sqlite3.IntegrityError):
            db.execute(
                "INSERT INTO assets (id, reading_unit_id, format, storage_root_id, relative_path, size_bytes,"
                " sha256, integrity, created_at, updated_at) VALUES (?,?,'cbz','r1',?,8,?, 'ok', ?, ?)",
                (new_id(), unit, escaping, "0" * 64, NOW, NOW))


def test_a_symlink_standing_in_for_a_managed_file_is_refused_and_never_counted(library, shelf, db, tmp_path):
    """§24.4, §47: the link is not followed, and OneShelf does not claim a deletion it did not make."""
    work_id, track_id = library()
    shelf.add(work_id)
    outside = tmp_path / "outside.cbz"
    outside.write_bytes(b"not ours")
    root = tmp_path / "library"
    root.mkdir()
    (root / "Books").mkdir()
    (root / "Books" / "a.cbz").symlink_to(outside)         # what a replaced file looks like on disk

    CatalogTrust(db).refresh(track_id, units("u1"), plugin_version="1.0.0")
    unit = unit_id(db, "u1")
    db.execute("INSERT INTO storage_roots (id, name, path, is_default, created_at, updated_at)"
               " VALUES ('r1','L',?,1,?,?)", (str(root), NOW, NOW))
    db.execute("INSERT INTO assets (id, reading_unit_id, format, storage_root_id, relative_path, size_bytes, sha256,"
               " integrity, created_at, updated_at) VALUES (?,?,'cbz','r1','Books/a.cbz',8,?, 'ok', ?, ?)",
               (new_id(), unit, "0" * 64, NOW, NOW))

    removed = shelf.delete_files(work_id)

    assert outside.exists(), "the link was followed and a file outside the root was deleted"
    assert removed == 0, "OneShelf counted a file it did not delete"
    assert db.execute("SELECT count(*) FROM assets").fetchone()[0] == 1, \
        "the record of a file that is still there was dropped"


# -- Follow (§20) -----------------------------------------------------------------------------------

def test_first_follow_baselines_without_flooding(library, follow, db):
    work_id, track_id = library()
    CatalogTrust(db).refresh(track_id, units("u1", "u2", "u3"), plugin_version="1.0.0")
    record = follow.follow(work_id, language="en", source_id="mangadex", track_id=track_id)
    assert record.baseline_units == 3
    assert follow.check(work_id).new_units == []
    assert db.execute("SELECT count(*) FROM release_events").fetchone()[0] == 0


def test_only_genuinely_added_units_are_new(library, follow, db):
    work_id, track_id = library()
    trust = CatalogTrust(db)
    trust.refresh(track_id, units("u1", "u2"), plugin_version="1.0.0")
    follow.follow(work_id, language="en", source_id="mangadex", track_id=track_id)
    trust.refresh(track_id, units("u1", "u2", "special", "u3"), plugin_version="1.0.0")
    outcome = follow.check(work_id)
    assert [u["unit_key"] for u in outcome.new_units] == ["special", "u3"]
    assert follow.check(work_id).new_units == []   # already reported


def test_metadata_changes_reordering_and_reappearance_are_not_new(library, follow, db):
    work_id, track_id = library()
    trust = CatalogTrust(db)
    trust.refresh(track_id, units(("u1", "Chapter 1"), ("u2", "Chapter 2")), plugin_version="1.0.0")
    follow.follow(work_id, language="en", source_id="mangadex", track_id=track_id)
    trust.refresh(track_id, units(("u1", "Chapter 1: Renamed"), ("u2", "Chapter 2")), plugin_version="1.0.0")
    assert follow.check(work_id).new_units == []
    trust.refresh(track_id, units(("u2", "Chapter 2"), ("u1", "Chapter 1: Renamed")), plugin_version="1.0.0")
    assert follow.check(work_id).new_units == []
    trust.refresh(track_id, units(("u2", "Chapter 2"),), plugin_version="1.0.0")
    trust.refresh(track_id, units(("u2", "Chapter 2"),), plugin_version="1.0.0")  # recovery: u1 disappeared
    trust.refresh(track_id, units(("u1", "Chapter 1"), ("u2", "Chapter 2")), plugin_version="1.0.0")
    assert follow.check(work_id).new_units == []   # reappearance is not a new release


def test_new_releases_never_enqueue_downloads(library, follow, db):
    work_id, track_id = library()
    trust = CatalogTrust(db)
    trust.refresh(track_id, units("u1"), plugin_version="1.0.0")
    follow.follow(work_id, language="en", source_id="mangadex", track_id=track_id)
    trust.refresh(track_id, units("u1", "u2", "u3"), plugin_version="1.0.0")
    outcome = follow.check(work_id)
    assert len(outcome.new_units) == 2
    assert db.execute("SELECT count(*) FROM download_jobs").fetchone()[0] == 0   # INV-09


def test_incomplete_or_suspicious_catalogs_do_not_produce_releases(library, follow, db):
    work_id, track_id = library()
    trust = CatalogTrust(db)
    trust.refresh(track_id, units(*[f"u{i}" for i in range(1, 11)]), plugin_version="1.0.0")
    follow.follow(work_id, language="en", source_id="mangadex", track_id=track_id)
    incomplete = ListResult("catalog", units("u1", "u2").entries, False,
                            Evidence(pages=1, stop_reason="page_failed"))
    trust.refresh(track_id, incomplete, plugin_version="1.0.0")
    assert follow.check(work_id).new_units == []
    trust.refresh(track_id, units("u1", "u2"), plugin_version="1.0.0")   # suspicious collapse
    assert follow.check(work_id).new_units == []
    assert follow.status(work_id).state == "catalog_suspicious"


def test_changing_preferred_source_baselines_without_flood_and_keeps_progress(library, follow, db):
    work_id, track_id = library()
    trust = CatalogTrust(db)
    trust.refresh(track_id, units("u1", "u2"), plugin_version="1.0.0")
    follow.follow(work_id, language="en", source_id="mangadex", track_id=track_id)
    unit = unit_id(db, "u1")
    db.execute("INSERT INTO reading_state (reading_unit_id, read_state, fraction, revision, updated_at)"
               " VALUES (?, 'read', 1.0, 1, ?)", (unit, NOW))

    other_track = new_id()
    db.execute("INSERT INTO source_tracks (id, work_id, source_id, language, kind, created_at) VALUES (?,?,?,?,?,?)",
               (other_track, work_id, "3asq", "en", "source", NOW))
    trust.refresh(other_track, units("a1", "a2", "a3", "a4"), plugin_version="1.0.0")
    record = follow.change_preferred_source(work_id, source_id="3asq", track_id=other_track)
    assert record.baseline_units == 4 and record.baseline_kind == "source_change"
    assert follow.check(work_id).new_units == []
    assert db.execute("SELECT read_state FROM reading_state WHERE reading_unit_id = ?", (unit,)).fetchone()[0] == "read"


def test_unfollow_is_immediate_with_undo_and_touches_nothing_else(library, shelf, follow, db):
    work_id, track_id = library()
    shelf.add(work_id)
    CatalogTrust(db).refresh(track_id, units("u1"), plugin_version="1.0.0")
    follow.follow(work_id, language="en", source_id="mangadex", track_id=track_id)
    token = follow.unfollow(work_id)
    assert follow.status(work_id) is None
    assert shelf.get(work_id) is not None
    assert db.execute("SELECT count(*) FROM reading_units").fetchone()[0] == 1
    restored = follow.undo_unfollow(token)
    assert restored.track_id == track_id and follow.status(work_id) is not None


def test_follow_reports_last_attempted_and_successful_checks(library, follow, db):
    work_id, track_id = library()
    trust = CatalogTrust(db)
    trust.refresh(track_id, units("u1"), plugin_version="1.0.0")
    follow.follow(work_id, language="en", source_id="mangadex", track_id=track_id)
    follow.record_attempt(work_id, successful=False, category="timeout")
    status = follow.status(work_id)
    assert status.last_attempted_at is not None and status.last_successful_at is None and status.state == "degraded"
    follow.check(work_id)
    status = follow.status(work_id)
    assert status.last_successful_at is not None and status.state == "up_to_date"


def test_due_follows_respect_the_twelve_hour_schedule_with_jitter(library, follow, db):
    work_id, track_id = library()
    CatalogTrust(db).refresh(track_id, units("u1"), plugin_version="1.0.0")
    follow.follow(work_id, language="en", source_id="mangadex", track_id=track_id)
    follow.check(work_id)
    assert follow.due_follows() == []
    intervals = {follow.next_check_delay().total_seconds() for _ in range(20)}
    base = 12 * 3600
    assert min(intervals) >= base and max(intervals) <= base + 3600 and len(intervals) > 1
