"""Master §22/§37: import associates confidently or asks; it never merges aggressively."""
import pytest

from oneshelf.domain.clock import utcnow_iso
from oneshelf.domain.ids import new_id
from oneshelf.importer.suggest import suggest_targets
from oneshelf.search.index import index_work

NOW = utcnow_iso()


def add_work(db, title, content_type="manga"):
    work_id = new_id()
    db.execute("INSERT INTO works (id, display_title, content_type, created_at, updated_at) VALUES (?,?,?,?,?)",
               (work_id, title, content_type, NOW, NOW))
    index_work(db, work_id)
    return work_id


def test_exact_title_with_compatible_type_is_confident(db):
    work = add_work(db, "Solo Leveling", "manhwa")
    suggestions = suggest_targets(db, "Solo Leveling", content_type="manga")
    assert [s.work_id for s in suggestions] == [work]
    assert suggestions[0].confident is True and suggestions[0].tier == "exact_title"


def test_two_candidates_are_never_auto_associated(db):
    add_work(db, "Solo Leveling", "manhwa")
    add_work(db, "Solo Leveling", "manga")
    suggestions = suggest_targets(db, "Solo Leveling", content_type="manga")
    assert len(suggestions) == 2 and not any(s.confident for s in suggestions)


def test_incompatible_types_are_not_suggested(db):
    add_work(db, "Solo Leveling", "novel")
    assert suggest_targets(db, "Solo Leveling", content_type="manga") == []


def test_weak_matches_are_offered_but_never_confident(db):
    add_work(db, "Solo Leveling: Ragnarok", "manhwa")
    suggestions = suggest_targets(db, "Solo Leveling", content_type="manhwa")
    assert suggestions and suggestions[0].confident is False


def test_unknown_type_stays_compatible_without_being_confident_alone(db):
    work = add_work(db, "كتاب", content_type=None or "unknown")
    suggestions = suggest_targets(db, "كتاب", content_type=None)
    assert [s.work_id for s in suggestions] == [work] and suggestions[0].confident is True


def test_locally_imported_work_is_searchable(db, tmp_path):
    """A local import is a first-class Work: local-first search and the next import must both find it."""
    from oneshelf.importer.service import CreateLocalWork, import_file
    from oneshelf.search.index import search_local
    from oneshelf.storage.roots import register_root
    from tests.fixtures.builders import make_cbz

    root = tmp_path / "library"
    root.mkdir()
    register_root(db, "Library", str(root))
    outcome = import_file(db, make_cbz(tmp_path / "vol1.cbz"),
                          decision=CreateLocalWork(title="Imported Work", content_type="manga", language="en"))

    assert [r.work_id for r in search_local(db, "Imported Work")] == [outcome.work_id]
    suggestions = suggest_targets(db, "Imported Work", content_type="manga")
    assert [s.work_id for s in suggestions] == [outcome.work_id] and suggestions[0].confident is True
