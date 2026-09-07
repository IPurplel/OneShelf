"""Packaging: comics into CBZ archives, books as the file the site serves.

A CBZ is just a ZIP of images read in filename order, so two things matter:
filenames must sort lexically into reading order, and the bytes must be the
originals. Nothing here re-encodes an image — the downloaded bytes go into the
archive verbatim, stored rather than deflated, because JPEG/WebP/PNG payloads
are already compressed and deflating them costs CPU for a rounding error of
space.

A book has no such structure to impose: an EPUB or PDF *is* the artifact, so it
is written through unchanged. What the two share is everything around the file —
atomic writes, a verifier good enough to justify skipping a re-download, and a
delete path that refuses anything it does not recognise as ours.

Everything is written atomically. An interrupted run leaves a ``.tmp`` file that
is discarded on the next pass, never a truncated ``.cbz`` that looks complete to
a library scanner.
"""

from __future__ import annotations

import contextlib
import io
import logging
import os
import shutil
import zipfile
from dataclasses import dataclass
from pathlib import Path
from xml.etree import ElementTree as ET

from PIL import Image

from .models import Chapter, Series, TextChapter, format_chapter_number

log = logging.getLogger(__name__)

# Pillow refuses very large images by default as a decompression-bomb guard.
# Manga long-strips legitimately exceed it, so raise the ceiling rather than
# failing valid pages. None disables the check entirely; a high bound keeps
# some protection.
Image.MAX_IMAGE_PIXELS = 500_000_000


#: Everything the library owns on disk. Membership decides what may be listed,
#: zipped up, swept and — the one that matters — deleted, so it is a closed set
#: rather than "whatever we happened to download".
#:
#: ``.txt`` is deliberately absent even though some sites offer books as plain
#: text: the set doubles as the delete path's allow-list, and a user's own
#: notes.txt sitting in the output directory must never be something this app
#: considers its own.
LIBRARY_EXTENSIONS = frozenset({".cbz", ".epub", ".pdf", ".mobi", ".azw3"})

#: Leading bytes for the formats above. EPUB, AZW3 and CBZ are all ZIP
#: containers, so a matching signature proves the container and no more — which
#: is all that is needed to tell a real download from an error page saved under
#: the wrong name.
_DOCUMENT_SIGNATURES: dict[str, tuple[bytes, ...]] = {
    ".pdf": (b"%PDF-",),
    ".epub": (b"PK\x03\x04",),
    ".azw3": (b"PK\x03\x04", b"TPZ3", b"\xea\x0c"),
    ".cbz": (b"PK\x03\x04",),
    ".mobi": (),   # the identifier sits at offset 60, checked below
}


class PackagingError(RuntimeError):
    """Raised when a chapter archive could not be produced."""


@dataclass(slots=True)
class PageFile:
    index: int
    data: bytes
    extension: str

    @property
    def name(self) -> str:
        # Three digits keeps lexical order == page order for chapters up to 999
        # pages, which no real chapter approaches.
        return f"{self.index:03d}{self.extension}"


def validate_image(data: bytes) -> tuple[int, int]:
    """Confirm ``data`` decodes as an image and return its dimensions.

    A truncated download often still "looks" like a JPEG by its magic bytes, so
    this fully verifies the payload. A corrupt page must fail loudly, not get
    sealed into an archive that only breaks later in a reader.
    """
    try:
        with Image.open(io.BytesIO(data)) as image:
            image.verify()
        # verify() consumes the file object, so reopen to read the size.
        with Image.open(io.BytesIO(data)) as image:
            return image.size
    except Exception as exc:
        raise PackagingError(f"Image failed validation: {exc}") from exc


def build_comicinfo(
    series: Series,
    chapter: Chapter,
    page_count: int,
    *,
    language: str = "ar",
    right_to_left: bool = True,
) -> bytes:
    """Produce ComicInfo.xml — the metadata Komga, Kavita and YACReader read."""
    root = ET.Element("ComicInfo", {
        "xmlns:xsi": "http://www.w3.org/2001/XMLSchema-instance",
        "xmlns:xsd": "http://www.w3.org/2001/XMLSchema",
    })

    def add(tag: str, value) -> None:
        if value in (None, ""):
            return
        ET.SubElement(root, tag).text = str(value)

    add("Series", series.title)
    add("Number", format_chapter_number(chapter.number, chapter.index))
    add("Title", chapter.title)
    add("Writer", series.author)
    add("Summary", series.description)
    add("PageCount", page_count)
    add("LanguageISO", language)
    add("Web", chapter.url)
    # Tells readers to page right-to-left, which is what manga expects.
    add("Manga", "YesAndRightToLeft" if right_to_left else "Yes")

    return ET.tostring(root, encoding="utf-8", xml_declaration=True)


def series_folder(output_dir: Path, title: str) -> Path:
    """Where one series' archives live."""
    from .models import sanitize_filename

    return output_dir / sanitize_filename(title)


def delete_archives(paths, root: Path) -> tuple[int, int]:
    """Delete downloaded files, refusing anything outside ``root``.

    Returns ``(removed, bytes_freed)`` — what actually went, not what was
    asked for, so callers report a real number rather than assuming success.

    Deliberately narrow, because this is the one operation here that destroys
    data. A caller passes paths derived from a client-supplied series title, so
    containment is re-checked per path rather than trusted: sanitising a name
    is not a boundary check. Only existing regular files with an extension the
    library owns qualify — no directories, no symlinks, nothing else, whatever
    the caller asks for.
    """
    resolved_root = root.resolve()
    removed = 0
    freed = 0

    for path in paths:
        candidate = Path(path)
        try:
            candidate = candidate.resolve()
            candidate.relative_to(resolved_root)
        except (ValueError, OSError):
            log.warning("Refusing to delete outside the output directory: %s", path)
            continue

        if candidate.suffix.lower() not in LIBRARY_EXTENSIONS:
            log.warning("Refusing to delete a file the library does not own: %s",
                        candidate)
            continue
        # is_symlink first: is_file() follows the link and would happily let a
        # symlink inside the output directory point anywhere at all.
        if candidate.is_symlink() or not candidate.is_file():
            continue

        try:
            size = candidate.stat().st_size
            candidate.unlink()
        except OSError as exc:  # pragma: no cover - permissions, races
            log.warning("Could not delete %s: %s", candidate, exc)
            continue

        removed += 1
        freed += size
        log.info("Deleted %s (%.1f MB)", candidate.name, size / (1 << 20))

    return removed, freed


def prune_empty_folder(folder: Path, root: Path) -> bool:
    """Remove ``folder`` if it is empty. Returns True when it went.

    Only when empty: a partly pruned series keeps its directory, so deleting
    two chapters never looks like losing the whole series.
    """
    try:
        resolved = folder.resolve()
        resolved.relative_to(root.resolve())
    except (ValueError, OSError):
        return False
    if resolved == root.resolve() or not resolved.is_dir():
        return False
    if any(resolved.iterdir()):
        return False
    try:
        resolved.rmdir()
    except OSError:  # pragma: no cover - races
        return False
    return True


class _ZipBuffer(io.RawIOBase):
    """Collects what ZipFile writes so it can be handed out as it appears."""

    def __init__(self) -> None:
        self._pending = bytearray()

    def writable(self) -> bool:
        return True

    def write(self, data) -> int:
        self._pending.extend(data)
        return len(data)

    def take(self) -> bytes:
        data = bytes(self._pending)
        self._pending.clear()
        return data


def iter_zip(members: list[tuple[Path, str]], chunk_size: int = 1 << 20):
    """Yield a ZIP of ``members`` (path, name-inside-archive) as it is built.

    Streamed rather than assembled. A series runs to tens of gigabytes, and
    neither the container's RAM nor its disk should have to hold a second copy
    just to hand one to a browser. Nothing is buffered beyond a chunk.

    Stored, not deflated: the members are CBZ files whose contents are already
    compressed image data, so deflating would spend CPU to save nothing. It also
    keeps the outer archive a plain container — unzip it and the CBZs inside are
    byte-identical to the ones on disk.

    The caller cannot send a Content-Length for this, so browsers report the
    download as an unknown size. Computing the total up front means reproducing
    the ZIP64 and data-descriptor arithmetic zipfile performs internally for a
    non-seekable stream, and an error there truncates a multi-gigabyte archive.
    A progress bar is not worth that; the UI states the expected size instead.
    """
    buffer = _ZipBuffer()
    # allowZip64 because a full series comfortably exceeds the 4 GB limit.
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_STORED, allowZip64=True) as archive:
        for path, arcname in members:
            info = zipfile.ZipInfo.from_file(path, arcname)
            info.compress_type = zipfile.ZIP_STORED
            # Exactly info.file_size bytes, no more and no less. The size was
            # recorded when the header was built, and the download queue may
            # replace this very .cbz while the stream is in flight — a
            # mismatch between the declared and written size is a corrupt
            # archive, discovered at the end of a multi-gigabyte download.
            with archive.open(info, "w") as target, path.open("rb") as source:
                remaining = info.file_size
                while remaining > 0:
                    chunk = source.read(min(chunk_size, remaining))
                    if not chunk:
                        # It shrank. Pad rather than leave the member short:
                        # one odd file beats an archive that will not open.
                        target.write(b"\0" * remaining)
                        break
                    remaining -= len(chunk)
                    target.write(chunk)
                    data = buffer.take()
                    if data:
                        yield data
            data = buffer.take()
            if data:
                yield data
    # The central directory is written when the ZipFile closes.
    data = buffer.take()
    if data:
        yield data


def chapter_path(output_dir: Path, series: Series, chapter: Chapter) -> Path:
    return output_dir / series.folder_name / chapter.filename(series.title)


def write_cbz(
    destination: Path,
    pages: list[PageFile],
    comicinfo: bytes | None = None,
) -> Path:
    """Write ``pages`` to ``destination`` atomically."""
    if not pages:
        raise PackagingError("Refusing to write an empty archive")

    destination.parent.mkdir(parents=True, exist_ok=True)
    temp_path = destination.with_suffix(destination.suffix + ".tmp")

    try:
        # ZIP_STORED: the payloads are already-compressed image formats.
        with zipfile.ZipFile(temp_path, "w", compression=zipfile.ZIP_STORED) as archive:
            for page in sorted(pages, key=lambda p: p.index):
                archive.writestr(page.name, page.data)
            if comicinfo:
                archive.writestr("ComicInfo.xml", comicinfo)

        os.replace(temp_path, destination)
    except Exception:
        temp_path.unlink(missing_ok=True)
        raise

    return destination


def write_pdf(destination: Path, pages: list[PageFile]) -> Path:
    """Assemble page images into one PDF, atomically.

    For a source that serves a book as page images rather than as a file. A CBZ
    would be the cheaper thing to write and the wrong thing to hand someone: a
    novel belongs in a reader that knows about pages, not in a comic viewer.

    Pages are converted to RGB because PDF has no alpha channel and Pillow
    refuses a mode it cannot encode — scanned pages routinely arrive as
    palette or LA PNGs.
    """
    if not pages:
        raise PackagingError("Refusing to write an empty PDF")

    from PIL import Image

    ordered = sorted(pages, key=lambda p: p.index)
    images: list[Image.Image] = []
    try:
        for page in ordered:
            try:
                image = Image.open(io.BytesIO(page.data))
                image.load()
            except Exception as exc:
                raise PackagingError(
                    f"Page {page.index} is not a readable image: {exc}"
                ) from exc
            images.append(image.convert("RGB") if image.mode != "RGB" else image)

        destination.parent.mkdir(parents=True, exist_ok=True)
        temp_path = destination.with_suffix(destination.suffix + ".tmp")
        try:
            images[0].save(temp_path, "PDF", save_all=True,
                           append_images=images[1:], resolution=150.0)
            os.replace(temp_path, destination)
        except Exception:
            temp_path.unlink(missing_ok=True)
            raise
    finally:
        for image in images:
            with contextlib.suppress(Exception):
                image.close()

    return destination


def looks_like_document(data: bytes, extension: str) -> bool:
    """Whether ``data`` plausibly is a document of ``extension``'s type.

    Deliberately shallow. The job is to catch the common failure — a login
    wall, a rate-limit notice or an HTML error page saved as ``book.pdf`` — not
    to validate a format. Anything without a signature to check (``.txt``, and
    the sites that serve odd extensions) passes on size alone, because inventing
    a stricter test would reject files that are perfectly good.
    """
    if not data:
        return False
    extension = extension.lower()
    if extension == ".mobi":
        # "BOOKMOBI" lives at offset 60 of a PalmDOC header.
        return data[60:68] in (b"BOOKMOBI", b"TEXtREAd")
    signatures = _DOCUMENT_SIGNATURES.get(extension)
    if not signatures:
        # Unknown or signature-less type: reject only what is obviously markup.
        return not data.lstrip()[:14].lower().startswith((b"<!doctype", b"<html"))
    return data.startswith(signatures)


def book_path(output_dir: Path, series: Series, chapter: Chapter) -> Path:
    """Where one downloaded book file belongs.

    Named from the chapter's own label, which for a book adapter is the file
    the site serves (``agnes-grey.epub``). Keeping the site's filename means a
    book that exists in three formats lands as three obvious files instead of
    three collisions, and a collection of numbered PDFs stays numbered.
    """
    from .models import sanitize_filename

    return output_dir / series.folder_name / sanitize_filename(chapter.title)


def write_file(destination: Path, data: bytes) -> Path:
    """Write ``data`` to ``destination`` atomically."""
    if not data:
        raise PackagingError("Refusing to write an empty file")

    destination.parent.mkdir(parents=True, exist_ok=True)
    temp_path = destination.with_suffix(destination.suffix + ".tmp")
    try:
        temp_path.write_bytes(data)
        os.replace(temp_path, destination)
    except Exception:
        temp_path.unlink(missing_ok=True)
        raise
    return destination


def verify_file(path: Path, *, min_bytes: int = 1024) -> bool:
    """Check a downloaded book well enough to justify skipping a re-download.

    The floor exists because the failure this guards against is not an empty
    file but a small one: a 300-byte "access denied" page left behind by an
    interrupted run would otherwise count as a finished book forever.
    """
    if not path.is_file() or path.stat().st_size < min_bytes:
        return False
    try:
        with path.open("rb") as handle:
            head = handle.read(68)
    except OSError:  # pragma: no cover - permissions, races
        return False
    return looks_like_document(head, path.suffix)


def verify_pdf(path: Path, *, min_bytes: int = 1024) -> bool:
    """Check a PDF well enough to justify skipping a re-download.

    Header *and* trailer: a PDF truncated mid-write still starts with ``%PDF``,
    and resuming past a half-written book would leave it permanently broken.
    """
    if not verify_file(path, min_bytes=min_bytes):
        return False
    try:
        with path.open("rb") as handle:
            if handle.read(5) != b"%PDF-":
                return False
            handle.seek(max(0, path.stat().st_size - 1024))
            return b"%%EOF" in handle.read()
    except OSError:
        return False


def verify_cbz(path: Path, *, min_pages: int = 1) -> bool:
    """Check an existing archive well enough to justify skipping a re-download."""
    if not path.is_file() or path.stat().st_size == 0:
        return False
    try:
        with zipfile.ZipFile(path) as archive:
            if archive.testzip() is not None:
                return False
            images = [
                n for n in archive.namelist()
                if not n.endswith("/") and not n.endswith("ComicInfo.xml")
            ]
            return len(images) >= min_pages
    except (zipfile.BadZipFile, OSError):
        return False


class ChapterWorkspace:
    """Scratch directory for one chapter's in-flight downloads.

    Pages land here first so a crash mid-chapter leaves an obvious ``.part``
    directory to clean up rather than a partial archive.
    """

    def __init__(self, root: Path, key: str) -> None:
        self.path = root / f".part-{key}"

    def __enter__(self) -> "ChapterWorkspace":
        self.path.mkdir(parents=True, exist_ok=True)
        return self

    def __exit__(self, *exc_info) -> None:
        self.cleanup()

    def cleanup(self) -> None:
        shutil.rmtree(self.path, ignore_errors=True)


def sweep_partials(output_dir: Path) -> int:
    """Remove leftover ``.part-*`` dirs and half-written files from a crash."""
    removed = 0
    if not output_dir.is_dir():
        return 0
    for entry in output_dir.rglob(".part-*"):
        if entry.is_dir():
            shutil.rmtree(entry, ignore_errors=True)
            removed += 1
    for entry in output_dir.rglob("*.tmp"):
        # Only our own leavings: the name under the .tmp must be something the
        # library writes, so an unrelated file parked here is left alone.
        if Path(entry.stem).suffix.lower() in LIBRARY_EXTENSIONS:
            entry.unlink(missing_ok=True)
            removed += 1
    if removed:
        log.info("Cleaned up %d partial artefact(s) under %s", removed, output_dir)
    return removed


# ------------------------------------------------------------------- prose
#
# A novel site serves neither pages nor a finished file: it serves marked-up
# prose, one chapter per URL. Storing that as a CBZ is meaningless and storing
# it as a PDF throws away everything a reader wants (reflow, font size, and —
# for Arabic — the reading direction the text itself asks for). EPUB is the
# format that keeps all three, and it is a ZIP container this module already
# knows how to write atomically.
#
# The EPUB built here is deliberately minimal: one XHTML document, one spine
# item, one nav. It is not a typesetting engine. What it must get right is what
# the extraction actually captured — block order, heading level, and the
# encoding of every non-Latin character in it.

#: The XHTML skeleton. ``xml:lang`` and ``dir`` are both set, because an Arabic
#: chapter rendered left-to-right is unreadable even though every character in
#: it survived the round trip.
_EPUB_XHTML = """<?xml version="1.0" encoding="utf-8"?>
<!DOCTYPE html>
<html xmlns="http://www.w3.org/1999/xhtml" xmlns:epub="http://www.idpf.org/2007/ops"\
 xml:lang="{lang}" lang="{lang}" dir="{dir}">
<head><meta charset="utf-8"/><title>{title}</title>
<style>
body {{ font-family: serif; line-height: 1.6; margin: 1em; }}
h1, h2, h3, h4, h5, h6 {{ line-height: 1.3; }}
p {{ margin: 0 0 0.9em 0; text-indent: 0; }}
</style></head>
<body><section epub:type="chapter">
{body}
</section></body></html>
"""

_EPUB_OPF = """<?xml version="1.0" encoding="utf-8"?>
<package xmlns="http://www.idpf.org/2007/opf" version="3.0" unique-identifier="bookid"\
 xml:lang="{lang}" dir="{dir}">
<metadata xmlns:dc="http://purl.org/dc/elements/1.1/">
<dc:identifier id="bookid">{identifier}</dc:identifier>
<dc:title>{title}</dc:title>
<dc:language>{lang}</dc:language>
{creator}<meta property="dcterms:modified">{modified}</meta>
</metadata>
<manifest>
<item id="nav" href="nav.xhtml" media-type="application/xhtml+xml" properties="nav"/>
<item id="chapter" href="chapter.xhtml" media-type="application/xhtml+xml"/>
</manifest>
<spine page-progression-direction="{direction}">
<itemref idref="chapter"/>
</spine>
</package>
"""

_EPUB_NAV = """<?xml version="1.0" encoding="utf-8"?>
<!DOCTYPE html>
<html xmlns="http://www.w3.org/1999/xhtml" xmlns:epub="http://www.idpf.org/2007/ops"\
 xml:lang="{lang}" lang="{lang}">
<head><meta charset="utf-8"/><title>{title}</title></head>
<body><nav epub:type="toc" id="toc"><ol><li><a href="chapter.xhtml">{title}</a></li></ol></nav></body>
</html>
"""

_EPUB_CONTAINER = """<?xml version="1.0" encoding="utf-8"?>
<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">
<rootfiles><rootfile full-path="OEBPS/content.opf" media-type="application/oebps-package+xml"/></rootfiles>
</container>
"""

#: Scripts whose text reads right-to-left. Used only to pick a default when the
#: adapter did not state a language.
_RTL_LANGS = frozenset({"ar", "he", "fa", "ur", "ps", "sd", "ug", "yi"})


def _xml_escape(text: str) -> str:
    """Escape for XML character data *and* attribute values.

    ``xml.sax.saxutils.escape`` leaves quotes alone, which is wrong for the
    ``title`` that goes into an attribute here.
    """
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
        .replace("'", "&apos;")
    )


def is_rtl_language(language: str | None) -> bool:
    """Whether ``language`` is written right-to-left."""
    if not language:
        return False
    return language.strip().lower().split("-")[0] in _RTL_LANGS


def write_epub(
    destination: Path,
    chapter: "TextChapter",
    *,
    series_title: str,
    author: str | None = None,
    language: str | None = None,
    identifier: str | None = None,
) -> Path:
    """Write one prose chapter as an EPUB, atomically.

    ``language`` is the fallback for a chapter that did not carry one of its
    own; the resulting tag drives both ``dc:language`` and the reading
    direction, which is the difference between a readable Arabic chapter and an
    unreadable one.

    Raises :class:`PackagingError` for a chapter with nothing in it. That is not
    a defensive nicety: a reader that returned an empty container — a removed
    chapter, a login wall, a changed selector — parses perfectly and would
    otherwise be stored as a valid, empty book.
    """
    if not chapter.blocks:
        raise PackagingError(
            "Refusing to write an empty book: the chapter yielded no text. "
            "Either the chapter is unavailable or the reader's markup changed."
        )

    lang = (chapter.language or language or "en").strip() or "en"
    rtl = is_rtl_language(lang)
    direction = "rtl" if rtl else "ltr"
    title = chapter.title or series_title

    body = "\n".join(
        f"<{block.kind}>{_xml_escape(block.text)}</{block.kind}>"
        for block in chapter.blocks
        if block.text.strip()
    )
    if not body:
        raise PackagingError(
            "Refusing to write an empty book: every block was blank."
        )

    fields = {
        "lang": _xml_escape(lang),
        "dir": direction,
        "direction": direction,
        "title": _xml_escape(title),
    }
    xhtml = _EPUB_XHTML.format(body=body, **fields)
    nav = _EPUB_NAV.format(**fields)
    opf = _EPUB_OPF.format(
        identifier=_xml_escape(identifier or f"urn:uuid:{abs(hash((series_title, title))):032x}"),
        creator=(f"<dc:creator>{_xml_escape(author)}</dc:creator>\n" if author else ""),
        # A fixed timestamp keeps the same chapter byte-identical across runs,
        # so re-downloading one does not churn a synced library.
        modified="1970-01-01T00:00:00Z",
        **fields,
    )

    destination.parent.mkdir(parents=True, exist_ok=True)
    temp_path = destination.with_suffix(destination.suffix + ".tmp")
    try:
        with zipfile.ZipFile(temp_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            # "mimetype" must be first and stored uncompressed; readers that
            # sniff the container by byte offset reject an EPUB that deflates it.
            archive.writestr(
                zipfile.ZipInfo("mimetype"), "application/epub+zip",
                compress_type=zipfile.ZIP_STORED,
            )
            archive.writestr("META-INF/container.xml", _EPUB_CONTAINER)
            archive.writestr("OEBPS/content.opf", opf)
            archive.writestr("OEBPS/nav.xhtml", nav)
            archive.writestr("OEBPS/chapter.xhtml", xhtml)
        os.replace(temp_path, destination)
    except Exception:
        temp_path.unlink(missing_ok=True)
        raise

    return destination


def verify_epub(path: Path, *, min_bytes: int = 512) -> bool:
    """Check an EPUB well enough to justify skipping a re-download.

    A lower floor than :func:`verify_file`'s 1 KB: a short chapter compresses
    below a kilobyte, and treating that as a failed download would re-fetch it
    on every run forever.
    """
    if not path.is_file() or path.stat().st_size < min_bytes:
        return False
    try:
        with zipfile.ZipFile(path) as archive:
            if archive.testzip() is not None:
                return False
            names = set(archive.namelist())
            if not {"mimetype", "META-INF/container.xml"} <= names:
                return False
            # An empty chapter document is the failure this is really for: the
            # container is valid and the book is unreadable.
            return len(archive.read("OEBPS/chapter.xhtml")) > 200
    except (zipfile.BadZipFile, KeyError, OSError):
        return False


def text_path(output_dir: Path, series: Series, chapter: Chapter) -> Path:
    """Where one prose chapter belongs.

    Named like a CBZ chapter rather than like a book file: a novel arrives one
    chapter at a time, and the zero-padded number is what keeps two hundred of
    them in reading order in a file manager.
    """
    label = format_chapter_number(chapter.number, chapter.index)
    from .models import sanitize_filename

    name = f"{sanitize_filename(series.title)} - c{label}.epub"
    return output_dir / series.folder_name / name
