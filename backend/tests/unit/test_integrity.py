"""Master §16.5 / §39 content validation: only genuinely readable artifacts pass (INV-16)."""
import zipfile

import pytest

from oneshelf.integrity.validators import detect_format, validate
from tests.fixtures.builders import CONTAINER, make_cbz, make_epub, make_pdf, opf, png_bytes

HTML_PAGE = b"<!DOCTYPE html><html><body>403 Forbidden</body></html>"


def test_valid_cbz(tmp_path):
    result = validate(make_cbz(tmp_path / "a.cbz"))
    assert result.ok and result.format == "cbz" and result.page_count == 3


def test_cbz_page_order_is_natural(tmp_path):
    pages = [(n, png_bytes()) for n in ("10.png", "2.png", "1.png")]
    result = validate(make_cbz(tmp_path / "a.cbz", pages))
    assert result.page_names == ["1.png", "2.png", "10.png"]


def test_cbz_with_html_instead_of_image_is_rejected(tmp_path):
    path = make_cbz(tmp_path / "a.cbz", [("001.png", png_bytes()), ("002.jpg", HTML_PAGE)])
    result = validate(path)
    assert not result.ok and "html" in result.reason


@pytest.mark.parametrize("bad", [b"", b"\x89PNG\r\n\x1a\n" + b"\x00" * 20])
def test_cbz_with_empty_or_corrupt_image_is_rejected(tmp_path, bad):
    path = make_cbz(tmp_path / "a.cbz", [("001.png", png_bytes()), ("002.png", bad)])
    assert not validate(path).ok


def test_cbz_without_images_is_rejected(tmp_path):
    path = make_cbz(tmp_path / "a.cbz", [("readme.txt", b"hello")])
    assert validate(path).format is None  # not recognizable as CBZ


def test_cbz_with_unsafe_entry_names_is_rejected(tmp_path):
    path = make_cbz(tmp_path / "a.cbz", [("001.png", png_bytes()), ("../../evil.png", png_bytes())])
    assert not validate(path).ok


def test_zip_bomb_is_rejected(tmp_path):
    path = tmp_path / "bomb.cbz"
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as z:
        z.writestr("001.png", png_bytes())
        z.writestr("002.png", b"\x00" * (60 * 1024 * 1024))
    result = validate(path)
    assert not result.ok and "compression" in result.reason


def test_cbz_with_malformed_comicinfo_still_valid_with_warning(tmp_path):
    result = validate(make_cbz(tmp_path / "a.cbz", comicinfo="<ComicInfo><Title>x</Title>"))
    assert result.ok and result.warnings


def test_valid_pdf(tmp_path):
    result = validate(make_pdf(tmp_path / "a.pdf", pages=3))
    assert result.ok and result.format == "pdf" and result.page_count == 3


def test_truncated_pdf_is_rejected(tmp_path):
    good = make_pdf(tmp_path / "a.pdf").read_bytes()
    bad = tmp_path / "b.pdf"
    bad.write_bytes(good[:40])
    assert not validate(bad).ok


def test_html_named_pdf_is_not_a_pdf(tmp_path):
    p = tmp_path / "c.pdf"
    p.write_bytes(HTML_PAGE)
    result = validate(p)
    assert not result.ok and result.format is None


def test_valid_epub_reports_metadata(tmp_path):
    result = validate(make_epub(tmp_path / "a.epub", title="كتاب الاختبار", language="ar"))
    assert result.ok and result.format == "epub"
    assert result.metadata == {"title": "كتاب الاختبار", "language": "ar"}


def test_epub_with_missing_spine_document_is_rejected(tmp_path):
    result = validate(make_epub(tmp_path / "a.epub", package=opf(spine_items=("ch1", "ch2"))))
    assert not result.ok and "spine" in result.reason


def test_epub_with_missing_container_rootfile_is_rejected(tmp_path):
    container = CONTAINER.replace("OEBPS/content.opf", "OEBPS/missing.opf")
    assert not validate(make_epub(tmp_path / "a.epub", container=container)).ok


def test_epub_with_xml_entity_attack_is_rejected(tmp_path):
    evil = '<?xml version="1.0"?><!DOCTYPE c [<!ENTITY x SYSTEM "file:///etc/passwd">]>' + CONTAINER.split("?>", 1)[1]
    assert not validate(make_epub(tmp_path / "a.epub", container=evil)).ok


def test_detect_format_ignores_extension(tmp_path):
    pdf_named_cbz = tmp_path / "x.cbz"
    pdf_named_cbz.write_bytes(make_pdf(tmp_path / "y.pdf").read_bytes())
    assert detect_format(pdf_named_cbz) == "pdf"
    assert detect_format(make_epub(tmp_path / "z.cbz")) == "epub"
    random = tmp_path / "r.epub"
    random.write_bytes(b"not a document")
    assert detect_format(random) is None
