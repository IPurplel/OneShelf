"""Local Source Track import slice (Master §4.6, §22, §37; Meta Prompt C1)."""
import os
from pathlib import Path

import pytest

from oneshelf.importer.service import (
    ChooseWork,
    CreateLocalWork,
    ImportRejected,
    import_file,
    inspect_import,
    registrars,
)
from oneshelf.storage.commit import CommitEngine, Crash
from oneshelf.storage.roots import register_root
from tests.fixtures.builders import make_cbz, make_epub, make_pdf


@pytest.fixture
def root(db, tmp_path):
    (tmp_path / "lib").mkdir()
    return register_root(db, "Library", tmp_path / "lib")


@pytest.fixture
def inbox(tmp_path):
    p = tmp_path / "inbox"
    p.mkdir()
    return p


def count(db, table):
    return db.execute(f"SELECT count(*) FROM {table}").fetchone()[0]


def staging_entries(root):
    return [p for p in (Path(root.path) / ".oneshelf" / "staging").rglob("*") if p.is_file()]


def test_inspect_detects_without_writing(db, root, inbox):
    info = inspect_import(make_epub(inbox / "book.epub", title="الكتاب", language="ar"))
    assert info.format == "epub" and info.valid
    assert info.suggested_title == "الكتاب" and info.language == "ar"
    assert count(db, "works") == count(db, "imports") == 0


def test_copy_import_creates_local_work_track_unit_and_asset(db, root, inbox):
    src = make_cbz(inbox / "Chapter 1.cbz")
    out = import_file(db, src, decision=CreateLocalWork(title="سولو ليفلينج", content_type="manhwa", language="ar"),
                      unit_label="Chapter 1", unit_type="chapter")
    assert src.exists()  # Copy is the default and leaves the original
    final = Path(root.path) / out.relative_path
    assert final.read_bytes() == src.read_bytes()
    assert out.relative_path.startswith("Sequential Art/سولو ليفلينج [")
    work = db.execute("SELECT * FROM works WHERE id = ?", (out.work_id,)).fetchone()
    assert work["display_title"] == "سولو ليفلينج" and work["content_type"] == "manhwa"
    track = db.execute("SELECT * FROM source_tracks WHERE work_id = ?", (out.work_id,)).fetchone()
    assert (track["kind"], track["source_id"], track["language"]) == ("local", "local", "ar")
    asset = db.execute("SELECT * FROM assets WHERE id = ?", (out.asset_id,)).fetchone()
    assert asset["integrity"] == "ok" and asset["page_count"] == 3 and asset["format"] == "cbz"
    assert db.execute("SELECT state FROM imports WHERE id = ?", (out.import_id,)).fetchone()[0] == "completed"
    assert count(db, "shelf_entries") == 1
    assert staging_entries(root) == [] or all(p.name == "staging.json" for p in staging_entries(root))


def test_move_import_removes_original_only_after_commit(db, root, inbox):
    src = make_pdf(inbox / "paper.pdf")
    data = src.read_bytes()
    out = import_file(db, src, decision=CreateLocalWork(title="Paper", content_type="paper"), mode="move")
    assert not src.exists()
    assert (Path(root.path) / out.relative_path).read_bytes() == data


def test_invalid_file_is_rejected_without_side_effects(db, root, inbox):
    src = inbox / "chapter.cbz"
    src.write_bytes(b"<!DOCTYPE html><html>Cloudflare</html>")
    with pytest.raises(ImportRejected):
        import_file(db, src, decision=CreateLocalWork(title="X"), mode="move")
    assert src.exists()
    assert count(db, "works") == count(db, "assets") == 0
    assert db.execute("SELECT state FROM imports").fetchone()[0] == "rejected"
    assert [p for p in Path(root.path).rglob("*") if p.is_file() and ".oneshelf" not in p.parts] == []


def test_choose_existing_work_adds_to_it(db, root, inbox):
    first = import_file(db, make_pdf(inbox / "a.pdf"), decision=CreateLocalWork(title="Book", content_type="book"))
    second = import_file(db, make_epub(inbox / "a.epub"), decision=ChooseWork(first.work_id), unit_id=first.unit_id)
    assert count(db, "works") == 1
    assert second.unit_id == first.unit_id  # PDF and EPUB of one book coexist on one unit
    formats = {r[0] for r in db.execute("SELECT format FROM assets WHERE reading_unit_id = ?", (first.unit_id,))}
    assert formats == {"pdf", "epub"}


def test_same_format_twice_on_one_unit_is_refused_without_overwrite(db, root, inbox):
    first = import_file(db, make_pdf(inbox / "a.pdf"), decision=CreateLocalWork(title="Book", content_type="book"))
    before = (Path(root.path) / first.relative_path).read_bytes()
    with pytest.raises(ImportRejected):
        import_file(db, make_pdf(inbox / "b.pdf", pages=5), decision=ChooseWork(first.work_id), unit_id=first.unit_id)
    assert (Path(root.path) / first.relative_path).read_bytes() == before
    assert count(db, "assets") == 1


def test_same_title_distinct_local_works_do_not_collide(db, root, inbox):
    a = import_file(db, make_cbz(inbox / "1.cbz"), decision=CreateLocalWork(title="Berserk", content_type="manga"))
    b = import_file(db, make_cbz(inbox / "2.cbz"), decision=CreateLocalWork(title="Berserk", content_type="manga"))
    assert a.work_id != b.work_id and a.relative_path != b.relative_path
    assert (Path(root.path) / a.relative_path).exists() and (Path(root.path) / b.relative_path).exists()


def test_languages_get_separate_local_tracks(db, root, inbox):
    en = import_file(db, make_cbz(inbox / "en.cbz"), decision=CreateLocalWork(title="W", content_type="manga", language="en"))
    import_file(db, make_cbz(inbox / "ar.cbz"), decision=ChooseWork(en.work_id), language="ar")
    langs = {r[0] for r in db.execute("SELECT language FROM source_tracks WHERE work_id = ?", (en.work_id,))}
    assert langs == {"en", "ar"}


def test_units_follow_import_order_in_track(db, root, inbox):
    a = import_file(db, make_cbz(inbox / "p.cbz"), decision=CreateLocalWork(title="W", content_type="manga", language="en"),
                    unit_label="Prologue", unit_type="prologue")
    b = import_file(db, make_cbz(inbox / "s.cbz"), decision=ChooseWork(a.work_id), language="en",
                    unit_label="Special", unit_type="special")
    rows = db.execute("SELECT id FROM reading_units ORDER BY source_order").fetchall()
    assert [r[0] for r in rows] == [a.unit_id, b.unit_id]


def test_epub_language_metadata_is_used_when_not_given(db, root, inbox):
    out = import_file(db, make_epub(inbox / "b.epub", language="ar"), decision=CreateLocalWork(title="B", content_type="book"))
    assert db.execute("SELECT language FROM source_tracks WHERE work_id = ?", (out.work_id,)).fetchone()[0] == "ar"


def test_unavailable_root_fails_before_writing(db, root, inbox, tmp_path):
    (tmp_path / "lib" / ".oneshelf" / "root.json").unlink()
    src = make_pdf(inbox / "a.pdf")
    with pytest.raises(ImportRejected, match="unavailable"):
        import_file(db, src, decision=CreateLocalWork(title="A"), mode="move")
    assert src.exists() and count(db, "works") == 0


def test_insufficient_space_is_rejected(db, root, inbox, monkeypatch):
    import shutil
    from collections import namedtuple

    usage = namedtuple("usage", "total used free")
    monkeypatch.setattr(shutil, "disk_usage", lambda _p: usage(100 * 1024**3, 99 * 1024**3, 1024**3))
    with pytest.raises(ImportRejected, match="space"):
        import_file(db, make_pdf(inbox / "a.pdf"), decision=CreateLocalWork(title="A"))
    assert count(db, "works") == 0


def test_crash_mid_commit_recovers_to_one_registration(db, root, inbox):
    src = make_cbz(inbox / "c.cbz")

    def fault(point):
        if point == "after_verify":
            raise Crash(point)

    with pytest.raises(Crash):
        import_file(db, src, decision=CreateLocalWork(title="C", content_type="comic"), fault=fault, mode="move")
    assert src.exists()  # move never deletes the original before the commit completes
    assert count(db, "assets") == 0
    CommitEngine(db, registrars=registrars()).recover()
    CommitEngine(db, registrars=registrars()).recover()
    assert count(db, "assets") == 1 and count(db, "works") == 1
    assert db.execute("SELECT state FROM imports").fetchone()[0] == "completed"
