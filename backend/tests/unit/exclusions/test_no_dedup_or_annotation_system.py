"""§49 EX-14, EX-15: files are not shared between works, and the Reader keeps marks, not a notebook.

Deduplication would make one work's file another work's file, so deleting one work could quietly empty
another (INV-23). And the Reader's marks are bookmarks and highlights — a drawing and note system is a
different product, and not this one.
"""
import re

from .conftest import BACKEND, code_lines, python_sources

# `dedup_store` is still dedup, so these match the stem — but a notification's `dedupe_key` is about
# not saying the same thing twice, which has nothing to do with storing a file once.
DEDUP = re.compile(r"\b(?!dedupe\b|dedupe_key\b)(dedup\w*|deduplicat\w*|content_address\w*|shared_blob\w*|"
                   r"blob_store\w*|hardlink\w*|reflink\w*|clone_file\w*)", re.IGNORECASE)
# `from __future__ import annotations` is Python's own word for type hints, not a notebook.
ANNOTATION = re.compile(r"\b(annotation_\w+|user_annotation\w*|ink_stroke\w*|drawing\w*|freehand\w*|"
                        r"sticky_note\w*|notebook\w*|handwriting\w*|canvas_draw\w*)", re.IGNORECASE)


def test_nothing_deduplicates_stored_files():
    offenders = [f"{path.name}:{number}: {line.strip()}"
                 for path, number, line in code_lines(python_sources()) if DEDUP.search(line)]
    assert offenders == []


def test_no_table_maps_one_stored_file_to_many_owners(schema):
    """An asset belongs to one reading unit and has its own path; that is what makes deletion honest."""
    assets = re.search(r"CREATE TABLE assets \((.*?)\n\);", schema, re.DOTALL)
    assert assets is not None
    body = assets.group(1)
    assert "reading_unit_id" in body and "relative_path" in body
    # A dedup store would need the checksum to be unique across assets. It must not be.
    assert not re.search(r"(UNIQUE\s*\(\s*checksum|checksum\s+TEXT[^,]*UNIQUE)", body, re.IGNORECASE)
    assert not re.search(r"CREATE UNIQUE INDEX \w+ ON assets ?\(checksum", schema, re.IGNORECASE)


def test_the_reader_keeps_bookmarks_and_highlights_and_nothing_more(schema):
    """Two tables of marks, and no third one: a note or a drawing would need somewhere to live."""
    tables = set(re.findall(r"CREATE TABLE (?:IF NOT EXISTS )?(reading_\w+)", schema))
    assert {"reading_bookmarks", "reading_highlights"} <= tables
    assert not [t for t in tables if ANNOTATION.search(t) or t.endswith(("_notes", "_drawings", "_ink"))]


def test_nothing_in_the_product_builds_an_annotation_system():
    offenders = [f"{path.name}:{number}: {line.strip()}"
                 for path, number, line in code_lines(python_sources()) if ANNOTATION.search(line)]
    assert offenders == []


def test_linking_is_only_how_a_file_is_moved_into_place():
    """`os.link` appears once, as the atomic half of a same-filesystem move — not as a shared copy."""
    users = {path.relative_to(BACKEND).as_posix() for path, _, line in code_lines(python_sources())
             if re.search(r"\bos\.link\s*\(", line)}
    assert users == {"oneshelf/storage/commit.py"}
    commit = (BACKEND / "oneshelf" / "storage" / "commit.py").read_text(encoding="utf-8")
    assert "os.unlink(src)" in commit or "os.remove(src)" in commit    # the link is not left behind
