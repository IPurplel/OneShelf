"""Master §24.2 / §24.4: Core-owned safe naming and path containment (INV-14)."""
import os
import unicodedata

import pytest

from oneshelf.storage.layout import asset_relative_path, family_for
from oneshelf.storage.paths import PathSafetyError, delete_managed_file, resolve_within, safe_component


@pytest.mark.parametrize("hostile", ["../../etc/passwd", "a/b\\c", "..", ".", "/abs", "C:\\x", "x\x00y"])
def test_safe_component_never_contains_separators_or_dot_names(hostile):
    out = safe_component(hostile)
    assert "/" not in out and "\\" not in out and "\x00" not in out
    assert out not in {"", ".", ".."}


def test_safe_component_preserves_arabic_and_normalizes_to_nfc():
    title = "سولو ليفلينج: الفصل ١"
    out = safe_component(unicodedata.normalize("NFD", title))
    assert out == unicodedata.normalize("NFC", title).replace(":", "_")


def test_safe_component_strips_bidi_overrides_but_keeps_zwnj():
    out = safe_component("abc\u202egpj.exe\u200cdef")
    assert "\u202e" not in out
    assert "\u200c" in out


def test_safe_component_truncates_by_utf8_bytes_without_breaking_characters():
    out = safe_component("ع" * 500, max_bytes=100)
    assert len(out.encode("utf-8")) <= 100
    out.encode("utf-8").decode("utf-8")  # still valid


def test_safe_component_handles_reserved_and_empty_names():
    assert safe_component("CON").upper() != "CON"
    assert safe_component("nul.txt").split(".")[0].upper() != "NUL"
    assert safe_component("   ...  ") == "untitled"


def test_family_mapping():
    assert family_for("manga") == family_for("manhwa") == family_for("comic") == "Sequential Art"
    assert family_for("book") == family_for("novel") == family_for("paper") == "Books"
    assert family_for("unknown") == family_for("other") == "Other"


def test_same_title_works_get_distinct_paths():
    a = asset_relative_path("manga", "Berserk", "aaaaaaaaaaaa", "en", "local", "Chapter 1", "u1u1u1u1u1u1", "cbz")
    b = asset_relative_path("manga", "Berserk", "bbbbbbbbbbbb", "en", "local", "Chapter 1", "u2u2u2u2u2u2", "cbz")
    assert a != b
    assert a.startswith("Sequential Art/Berserk [aaaaaaaaaaaa]/en/local/")
    assert a.endswith(".cbz")


def test_layout_treats_titles_and_sources_as_untrusted():
    p = asset_relative_path("book", "../../x", "wwwwwwwwwwww", "../en", "../../src", "/etc/passwd", "uuuuuuuuuuuu", "pdf")
    assert ".." not in p.split("/")
    assert not p.startswith("/")


def test_resolve_within_accepts_normal_relative_paths(tmp_path):
    assert resolve_within(tmp_path, "Books/a.pdf") == tmp_path / "Books" / "a.pdf"


@pytest.mark.parametrize("bad", ["", "/etc/passwd", "../x", "a/../../x", "a/..", "a\x00b", "C:/x", "\\\\server\\share"])
def test_resolve_within_rejects_escapes(tmp_path, bad):
    with pytest.raises(PathSafetyError):
        resolve_within(tmp_path, bad)


def test_resolve_within_rejects_symlinked_directory_escape(tmp_path):
    root, outside = tmp_path / "root", tmp_path / "outside"
    root.mkdir()
    outside.mkdir()
    os.symlink(outside, root / "Books")
    with pytest.raises(PathSafetyError):
        resolve_within(root, "Books/a.pdf")


def test_resolve_within_rejects_symlinked_file_even_inside_root(tmp_path):
    (tmp_path / "real.pdf").write_bytes(b"x")
    os.symlink(tmp_path / "real.pdf", tmp_path / "link.pdf")
    with pytest.raises(PathSafetyError):
        resolve_within(tmp_path, "link.pdf")


def test_delete_managed_file_only_deletes_regular_files_inside_root(tmp_path):
    root = tmp_path / "root"
    (root / "Books").mkdir(parents=True)
    victim = tmp_path / "victim.txt"
    victim.write_text("keep me")
    (root / "Books" / "a.pdf").write_bytes(b"x")
    delete_managed_file(root, "Books/a.pdf")
    assert not (root / "Books" / "a.pdf").exists()
    with pytest.raises(PathSafetyError):
        delete_managed_file(root, "../victim.txt")
    os.symlink(victim, root / "Books" / "evil.pdf")
    with pytest.raises(PathSafetyError):
        delete_managed_file(root, "Books/evil.pdf")
    assert victim.read_text() == "keep me"
    with pytest.raises(PathSafetyError):
        delete_managed_file(root, "Books")  # directories are not deleted by this primitive
