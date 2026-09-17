"""Master §6.2: local SQLite FTS index over library records; immediate local results."""
import pytest

from oneshelf.domain.clock import utcnow_iso
from oneshelf.domain.ids import new_id
from oneshelf.search.index import index_work, reindex_all, search_local

NOW = utcnow_iso()


def add_work(db, title, *, original=None, content_type="manga", creator=None, aliases=(), listings=()):
    work_id = new_id()
    db.execute("INSERT INTO works (id, display_title, original_title, content_type, creator, created_at, updated_at)"
               " VALUES (?,?,?,?,?,?,?)", (work_id, title, original, content_type, creator, NOW, NOW))
    for alias, language in aliases:
        db.execute("INSERT INTO work_aliases (id, work_id, title, language, kind, created_at) VALUES (?,?,?,?,?,?)",
                   (new_id(), work_id, alias, language, "alias", NOW))
    for source_id, raw_title in listings:
        db.execute("INSERT INTO source_listings (id, source_id, source_listing_key, raw_title, work_id, created_at)"
                   " VALUES (?,?,?,?,?,?)", (new_id(), source_id, f"{source_id}-{raw_title}", raw_title, work_id, NOW))
    index_work(db, work_id)
    return work_id


def test_local_search_finds_titles_aliases_and_source_titles(db):
    work = add_work(db, "Solo Leveling", original="나 혼자만 레벨업", aliases=[("الارتقاء بمفردي", "ar")],
                    listings=[("mangadex", "Solo Leveling"), ("3asq", "سولو ليفلينج")])
    add_work(db, "Berserk")
    assert [r.work_id for r in search_local(db, "solo leveling")] == [work]
    assert [r.work_id for r in search_local(db, "الارتقاء بمفردي")] == [work]
    assert [r.work_id for r in search_local(db, "سولو ليفلينج")] == [work]
    assert [r.work_id for r in search_local(db, "나 혼자만")] == [work]


def test_local_search_is_arabic_normalized_and_loose(db):
    work = add_work(db, "مدرسة الظلام", content_type="manhwa")
    for query in ("مدرسه الظلام", "مَدْرَسَة الظلام", "مدرســة الظلام"):
        assert [r.work_id for r in search_local(db, query)] == [work]


def test_local_search_returns_tiers_and_shelf_boost(db):
    exact = add_work(db, "Moon")
    other = add_work(db, "Moonlight Sonata")
    db.execute("INSERT INTO shelf_entries (work_id, added_at) VALUES (?, ?)", (other, NOW))
    results = search_local(db, "Moon")
    assert [r.work_id for r in results] == [exact, other]
    assert results[0].tier == "exact_title" and results[1].tier == "prefix"


def test_reindex_reflects_updates_and_removals(db):
    work = add_work(db, "Old Title")
    db.execute("UPDATE works SET display_title = 'New Title' WHERE id = ?", (work,))
    index_work(db, work)
    assert [r.work_id for r in search_local(db, "New Title")] == [work]
    assert search_local(db, "Old Title") == []
    db.execute("DELETE FROM work_aliases WHERE work_id = ?", (work,))
    db.execute("DELETE FROM source_listings WHERE work_id = ?", (work,))
    db.execute("DELETE FROM works WHERE id = ?", (work,))
    reindex_all(db)
    assert search_local(db, "New Title") == []


def test_local_search_is_bounded_and_ignores_empty_queries(db):
    for i in range(30):
        add_work(db, f"Volume {i}")
    assert len(search_local(db, "Volume", limit=10)) == 10
    assert search_local(db, "   ") == []


def test_search_queries_are_never_persisted(db):
    add_work(db, "Private Interest")
    search_local(db, "Private Interest")
    tables = [r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")]
    for table in tables:
        if table.startswith("search_index"):
            continue
        rows = db.execute(f"SELECT count(*) FROM {table} WHERE 0").fetchone()
        assert rows is not None
    assert not any("quer" in t or "recent" in t or "history_search" in t for t in tables)
