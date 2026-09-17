"""Synthetic test artifacts (no real copyrighted content)."""
from __future__ import annotations

import io
import zipfile
from pathlib import Path

from PIL import Image
from pypdf import PdfWriter


def png_bytes(width=64, height=96, color=(120, 90, 60)) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (width, height), color).save(buf, format="PNG")
    return buf.getvalue()


def make_cbz(path: Path, pages: list[tuple[str, bytes]] | None = None, comicinfo: str | None = None) -> Path:
    if pages is None:
        pages = [(f"{i:03d}.png", png_bytes()) for i in range(1, 4)]
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_STORED) as z:
        for name, data in pages:
            z.writestr(name, data)
        if comicinfo is not None:
            z.writestr("ComicInfo.xml", comicinfo)
    return path


def make_pdf(path: Path, pages: int = 2) -> Path:
    writer = PdfWriter()
    for _ in range(pages):
        writer.add_blank_page(width=200, height=300)
    with open(path, "wb") as f:
        writer.write(f)
    return path


CONTAINER = """<?xml version="1.0"?>
<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">
  <rootfiles><rootfile full-path="OEBPS/content.opf" media-type="application/oebps-package+xml"/></rootfiles>
</container>"""


def opf(title="Test Book", spine_items=("ch1",), language="en") -> str:
    manifest = "".join(f'<item id="{i}" href="{i}.xhtml" media-type="application/xhtml+xml"/>' for i in spine_items)
    spine = "".join(f'<itemref idref="{i}"/>' for i in spine_items)
    return f"""<?xml version="1.0"?>
<package xmlns="http://www.idpf.org/2007/opf" version="3.0" unique-identifier="uid">
  <metadata xmlns:dc="http://purl.org/dc/elements/1.1/">
    <dc:identifier id="uid">urn:uuid:test</dc:identifier><dc:title>{title}</dc:title><dc:language>{language}</dc:language>
  </metadata>
  <manifest>{manifest}</manifest>
  <spine>{spine}</spine>
</package>"""


def make_epub(path: Path, *, title="Test Book", language="en", files=None, container=CONTAINER, package=None,
              mimetype="application/epub+zip") -> Path:
    if files is None:
        files = {"OEBPS/ch1.xhtml": "<html xmlns='http://www.w3.org/1999/xhtml'><body><p>Hello</p></body></html>"}
    with zipfile.ZipFile(path, "w") as z:
        if mimetype is not None:
            z.writestr(zipfile.ZipInfo("mimetype"), mimetype, compress_type=zipfile.ZIP_STORED)
        z.writestr("META-INF/container.xml", container)
        z.writestr("OEBPS/content.opf", package if package is not None else opf(title, language=language))
        for name, data in files.items():
            z.writestr(name, data)
    return path
