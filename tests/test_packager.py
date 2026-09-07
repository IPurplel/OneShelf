"""CBZ packaging: ordering, metadata, losslessness, and atomicity."""

from __future__ import annotations

import io
import zipfile
from xml.etree import ElementTree as ET

import pytest

from app.models import Chapter, Series, sanitize_filename
from app.packager import (
    PackagingError,
    delete_archives,
    prune_empty_folder,
    PageFile,
    build_comicinfo,
    chapter_path,
    sweep_partials,
    validate_image,
    verify_cbz,
    write_cbz,
)

from .conftest import make_jpeg, make_png


@pytest.fixture
def series() -> Series:
    return Series(
        url="https://example.net/manga/example-series/",
        title="Example Series",
        source="madara",
        author="Placeholder Author",
    )


@pytest.fixture
def chapter() -> Chapter:
    return Chapter(
        url="https://example.net/manga/example-series/chapter-12/",
        title="Chapter 12",
        number="12",
        index=12,
    )


# --------------------------------------------------------------- archives


def test_pages_are_named_for_lexical_ordering(tmp_path, series, chapter):
    pages = [PageFile(index=i, data=make_png(), extension=".png") for i in (3, 1, 2)]
    destination = write_cbz(tmp_path / "out.cbz", pages)

    with zipfile.ZipFile(destination) as archive:
        names = [n for n in archive.namelist() if n != "ComicInfo.xml"]

    assert names == ["001.png", "002.png", "003.png"]
    assert names == sorted(names)  # lexical order == reading order


def test_pages_beyond_nine_still_sort_correctly(tmp_path):
    pages = [PageFile(index=i, data=make_png(), extension=".jpg") for i in range(1, 13)]
    destination = write_cbz(tmp_path / "out.cbz", pages)

    with zipfile.ZipFile(destination) as archive:
        names = [n for n in archive.namelist() if n != "ComicInfo.xml"]

    # The classic bug: "10.jpg" sorting before "2.jpg".
    assert names == sorted(names)
    assert names[1] == "002.jpg" and names[-1] == "012.jpg"


def test_images_are_stored_byte_identical(tmp_path):
    """The whole point of "best quality": no re-encoding anywhere."""
    original = make_jpeg(64, 96)
    write_cbz(tmp_path / "out.cbz", [PageFile(index=1, data=original, extension=".jpg")])

    with zipfile.ZipFile(tmp_path / "out.cbz") as archive:
        stored = archive.read("001.jpg")
        info = archive.getinfo("001.jpg")

    assert stored == original
    assert info.compress_type == zipfile.ZIP_STORED


def test_empty_archive_is_refused(tmp_path):
    with pytest.raises(PackagingError):
        write_cbz(tmp_path / "empty.cbz", [])


def test_write_is_atomic_and_leaves_no_temp(tmp_path):
    destination = tmp_path / "sub" / "out.cbz"
    write_cbz(destination, [PageFile(index=1, data=make_png(), extension=".png")])

    assert destination.is_file()
    assert not list(tmp_path.rglob("*.tmp"))


def test_failed_write_removes_temp_file(tmp_path, monkeypatch):
    destination = tmp_path / "out.cbz"

    def explode(self, *args, **kwargs):
        raise OSError("disk full")

    monkeypatch.setattr(zipfile.ZipFile, "writestr", explode)

    with pytest.raises(OSError):
        write_cbz(destination, [PageFile(index=1, data=make_png(), extension=".png")])

    assert not destination.exists()
    assert not list(tmp_path.glob("*.tmp"))


# ------------------------------------------------------------- ComicInfo


def test_comicinfo_marks_right_to_left(series, chapter):
    root = ET.fromstring(build_comicinfo(series, chapter, 22, language="ar"))

    assert root.findtext("Series") == "Example Series"
    assert root.findtext("Number") == "012"
    assert root.findtext("PageCount") == "22"
    assert root.findtext("LanguageISO") == "ar"
    assert root.findtext("Manga") == "YesAndRightToLeft"
    assert root.findtext("Web") == chapter.url


def test_comicinfo_omits_empty_fields(chapter):
    bare = Series(url="u", title="T", source="generic")
    root = ET.fromstring(build_comicinfo(bare, chapter, 5))

    assert root.find("Writer") is None
    assert root.find("Summary") is None


def test_comicinfo_left_to_right_when_disabled(series, chapter):
    root = ET.fromstring(build_comicinfo(series, chapter, 5, right_to_left=False))
    assert root.findtext("Manga") == "Yes"


# ------------------------------------------------------------- validation


def test_validate_image_returns_dimensions():
    assert validate_image(make_png(24, 36)) == (24, 36)


def test_validate_image_rejects_truncated_payload():
    truncated = make_jpeg(64, 64)[:40]
    with pytest.raises(PackagingError):
        validate_image(truncated)


def test_validate_image_rejects_html_error_page():
    with pytest.raises(PackagingError):
        validate_image(b"<html><body>404 Not Found</body></html>")


# ------------------------------------------------------------ verify/skip


def test_verify_cbz_accepts_good_archive(tmp_path):
    path = write_cbz(
        tmp_path / "ok.cbz",
        [PageFile(index=1, data=make_png(), extension=".png")],
        build_comicinfo(
            Series(url="u", title="T", source="madara"),
            Chapter(url="c", title="C", number="1"),
            1,
        ),
    )
    assert verify_cbz(path)


def test_verify_cbz_rejects_missing_or_corrupt(tmp_path):
    assert not verify_cbz(tmp_path / "nope.cbz")

    corrupt = tmp_path / "bad.cbz"
    corrupt.write_bytes(b"not a zip file at all")
    assert not verify_cbz(corrupt)

    empty = tmp_path / "empty.cbz"
    empty.write_bytes(b"")
    assert not verify_cbz(empty)


def test_verify_cbz_rejects_metadata_only_archive(tmp_path):
    path = tmp_path / "meta.cbz"
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("ComicInfo.xml", b"<ComicInfo/>")
    assert not verify_cbz(path)


# ------------------------------------------------------------------ paths


def test_chapter_path_layout(tmp_path, series, chapter):
    path = chapter_path(tmp_path, series, chapter)
    assert path.parent.name == "Example Series"
    assert path.name == "Example Series - c012.cbz"


def test_sanitize_filename_handles_hostile_titles():
    assert "/" not in sanitize_filename("Some/Series: Part 2?")
    assert sanitize_filename("CON") == "_CON"       # reserved on Windows
    assert sanitize_filename("   ") == "untitled"
    assert sanitize_filename("trailing...") == "trailing"


def test_sweep_partials_removes_crash_residue(tmp_path):
    (tmp_path / "Series" / ".part-0003").mkdir(parents=True)
    (tmp_path / "Series" / "Series - c003.cbz.tmp").write_bytes(b"partial")
    keeper = tmp_path / "Series" / "Series - c001.cbz"
    keeper.write_bytes(b"real archive")

    removed = sweep_partials(tmp_path)

    assert removed == 2
    assert keeper.is_file()
    assert not list(tmp_path.rglob(".part-*"))
    assert not list(tmp_path.rglob("*.tmp"))


# ------------------------------------------------------- streaming zip export


def test_iter_zip_produces_a_readable_archive(tmp_path):
    from app.packager import iter_zip

    first = tmp_path / "a.cbz"
    second = tmp_path / "b.cbz"
    first.write_bytes(b"first-archive-bytes")
    second.write_bytes(b"second-archive-bytes" * 100)

    members = [(first, "Series/a.cbz"), (second, "Series/b.cbz")]
    blob = b"".join(iter_zip(members))

    with zipfile.ZipFile(io.BytesIO(blob)) as archive:
        assert archive.namelist() == ["Series/a.cbz", "Series/b.cbz"]
        # Byte-identical: unzip and the CBZs are exactly what is on disk.
        assert archive.read("Series/a.cbz") == first.read_bytes()
        assert archive.read("Series/b.cbz") == second.read_bytes()
        assert archive.testzip() is None


def test_iter_zip_stores_rather_than_deflates(tmp_path):
    # Members are already-compressed image data; deflating spends CPU for
    # nothing and stops the result being a plain container.
    from app.packager import iter_zip

    path = tmp_path / "a.cbz"
    path.write_bytes(b"x" * 5000)

    blob = b"".join(iter_zip([(path, "S/a.cbz")]))
    with zipfile.ZipFile(io.BytesIO(blob)) as archive:
        assert archive.getinfo("S/a.cbz").compress_type == zipfile.ZIP_STORED


def test_iter_zip_streams_instead_of_buffering(tmp_path):
    """It must yield as it goes, or a 30 GB series would need 30 GB of RAM."""
    from app.packager import iter_zip

    path = tmp_path / "big.cbz"
    path.write_bytes(b"y" * (4 << 20))  # 4 MB

    chunks = list(iter_zip([(path, "S/big.cbz")], chunk_size=1 << 20))

    assert len(chunks) > 2
    assert max(len(chunk) for chunk in chunks) < (2 << 20)


def test_iter_zip_handles_an_empty_selection():
    from app.packager import iter_zip

    blob = b"".join(iter_zip([]))
    with zipfile.ZipFile(io.BytesIO(blob)) as archive:
        assert archive.namelist() == []


def test_series_folder_sanitises_the_title(tmp_path):
    from app.packager import series_folder

    folder = series_folder(tmp_path, 'Bad/Name: "quoted"')
    assert folder.parent == tmp_path
    assert "/" not in folder.name and ":" not in folder.name


def test_a_member_that_grows_mid_stream_stays_its_declared_size(tmp_path):
    """The queue can replace a .cbz while the archive is streaming.

    The size goes into the header before the read, so writing whatever the file
    happens to hold at read time produces an archive whose declared and actual
    sizes disagree — corrupt, and only discovered at the very end.
    """
    from app.packager import iter_zip

    path = tmp_path / "a.cbz"
    path.write_bytes(b"a" * 1000)
    members = [(path, "S/a.cbz")]
    info_size = path.stat().st_size

    chunks = []
    stream = iter_zip(members, chunk_size=256)
    for chunk in stream:
        chunks.append(chunk)
        path.write_bytes(b"b" * 9000)  # grows underneath us

    with zipfile.ZipFile(io.BytesIO(b"".join(chunks))) as archive:
        assert archive.testzip() is None
        assert archive.getinfo("S/a.cbz").file_size == info_size
        assert len(archive.read("S/a.cbz")) == info_size


def test_a_member_that_shrinks_mid_stream_is_padded(tmp_path):
    # Short is worse than odd: a truncated member makes the archive unopenable.
    from app.packager import iter_zip

    path = tmp_path / "a.cbz"
    path.write_bytes(b"a" * 8000)
    declared = path.stat().st_size

    stream = iter_zip([(path, "S/a.cbz")], chunk_size=1024)
    first = next(stream)
    path.write_bytes(b"a" * 16)  # shrinks underneath us
    blob = first + b"".join(stream)

    with zipfile.ZipFile(io.BytesIO(blob)) as archive:
        assert archive.testzip() is None
        assert len(archive.read("S/a.cbz")) == declared


# ---------------------------------------------------------- deleting archives


def test_delete_archives_removes_and_reports(tmp_path):
    first = tmp_path / "a.cbz"
    second = tmp_path / "b.cbz"
    first.write_bytes(b"x" * 500)
    second.write_bytes(b"y" * 1500)

    removed, freed = delete_archives([first, second], tmp_path)

    assert (removed, freed) == (2, 2000)
    assert not first.exists() and not second.exists()


def test_delete_archives_refuses_paths_outside_the_root(tmp_path):
    """The series title comes from the client, so containment is re-checked.

    Sanitising a name is not a boundary check.
    """
    root = tmp_path / "out"
    root.mkdir()
    outsider = tmp_path / "precious.cbz"
    outsider.write_bytes(b"do not touch")

    removed, freed = delete_archives([outsider], root)

    assert (removed, freed) == (0, 0)
    assert outsider.exists()


def test_delete_archives_refuses_traversal(tmp_path):
    root = tmp_path / "out"
    root.mkdir()
    outsider = tmp_path / "escape.cbz"
    outsider.write_bytes(b"still here")

    removed, _ = delete_archives([root / ".." / "escape.cbz"], root)

    assert removed == 0
    assert outsider.exists()


def test_delete_archives_only_touches_what_the_library_owns(tmp_path):
    keep = tmp_path / "notes.txt"
    keep.write_bytes(b"not an archive")
    folder = tmp_path / "subdir.cbz"      # a directory wearing the extension
    folder.mkdir()

    removed, freed = delete_archives([keep, folder], tmp_path)

    assert (removed, freed) == (0, 0)
    assert keep.exists() and folder.is_dir()


def test_delete_archives_covers_book_formats(tmp_path):
    """A downloaded book is ours to delete, exactly like a chapter archive."""
    book = tmp_path / "agnes-grey.epub"
    book.write_bytes(b"PK\x03\x04" + b"\x00" * 100)
    size = book.stat().st_size

    removed, freed = delete_archives([book], tmp_path)

    assert (removed, freed) == (1, size)
    assert not book.exists()


def test_delete_archives_skips_missing_files(tmp_path):
    removed, freed = delete_archives([tmp_path / "gone.cbz"], tmp_path)
    assert (removed, freed) == (0, 0)


def test_prune_empty_folder_only_when_empty(tmp_path):
    folder = tmp_path / "Series"
    folder.mkdir()
    survivor = folder / "keep.cbz"
    survivor.write_bytes(b"still downloaded")

    # A partly pruned series keeps its directory.
    assert prune_empty_folder(folder, tmp_path) is False
    assert folder.is_dir()

    survivor.unlink()
    assert prune_empty_folder(folder, tmp_path) is True
    assert not folder.exists()


def test_prune_never_removes_the_output_root(tmp_path):
    assert prune_empty_folder(tmp_path, tmp_path) is False
    assert tmp_path.is_dir()


# ------------------------------------------------------------ binding a PDF
# For a source that serves a book only through a page-by-page reader (Noor).
# A CBZ would be cheaper to write and the wrong artifact: a novel belongs in
# something that knows about pages, not in a comic viewer.

from app.packager import verify_pdf, write_pdf  # noqa: E402


# Pillow writes PDFs but cannot read them back -- it has no PDF decoder -- so
# these read the file's own structure rather than reopening it as an image.
import re as _re  # noqa: E402

_PAGE_OBJECTS = _re.compile(rb"/Type\s*/Page(?![s/\w])")
_WIDTHS = _re.compile(rb"/Width\s+(\d+)")


def test_pages_are_bound_into_one_pdf(tmp_path):
    pages = [PageFile(index=i, data=make_png(), extension=".png") for i in (3, 1, 2)]
    out = write_pdf(tmp_path / "book.pdf", pages)

    body = out.read_bytes()
    assert body.startswith(b"%PDF-")
    assert body.rstrip().endswith(b"%%EOF")
    assert len(_PAGE_OBJECTS.findall(body)) == 3


def test_the_page_order_is_the_index_not_the_argument_order(tmp_path):
    """Pages arrive from a concurrent fetch, so the list order means nothing."""
    sizes = {1: (40, 60), 2: (41, 60), 3: (42, 60)}
    pages = [
        PageFile(index=i, data=make_png(*sizes[i]), extension=".png")
        for i in (2, 3, 1)
    ]
    out = write_pdf(tmp_path / "ordered.pdf", pages)

    widths = [int(w) for w in _WIDTHS.findall(out.read_bytes())]
    assert widths == [40, 41, 42], f"pages came out in the wrong order: {widths}"


def test_a_jpeg_and_a_png_can_share_one_book(tmp_path):
    out = write_pdf(tmp_path / "mixed.pdf", [
        PageFile(index=1, data=make_png(), extension=".png"),
        PageFile(index=2, data=make_jpeg(), extension=".jpg"),
    ])
    assert verify_pdf(out)


def test_an_empty_pdf_is_refused(tmp_path):
    with pytest.raises(PackagingError, match="empty"):
        write_pdf(tmp_path / "nothing.pdf", [])


def test_a_page_that_is_not_an_image_names_itself(tmp_path):
    with pytest.raises(PackagingError, match="Page 2"):
        write_pdf(tmp_path / "broken.pdf", [
            PageFile(index=1, data=make_png(), extension=".png"),
            PageFile(index=2, data=b"<html>not an image</html>", extension=".png"),
        ])


def test_nothing_is_left_behind_when_binding_fails(tmp_path):
    with pytest.raises(PackagingError):
        write_pdf(tmp_path / "broken.pdf", [
            PageFile(index=1, data=b"not an image", extension=".png"),
        ])
    assert list(tmp_path.iterdir()) == [], "a .tmp survived a failed write"


def test_a_truncated_pdf_is_not_accepted_as_finished(tmp_path):
    """Header alone is not enough: resuming past a half-written book would
    leave it permanently broken."""
    good = write_pdf(tmp_path / "good.pdf", [
        PageFile(index=1, data=make_png(), extension=".png")])
    assert verify_pdf(good)

    truncated = tmp_path / "truncated.pdf"
    truncated.write_bytes(good.read_bytes()[: len(good.read_bytes()) // 2])
    assert not verify_pdf(truncated)


def test_something_that_is_not_a_pdf_at_all_is_rejected(tmp_path):
    imposter = tmp_path / "imposter.pdf"
    imposter.write_bytes(b"PK\x03\x04" + b"0" * 4096)
    assert not verify_pdf(imposter)
