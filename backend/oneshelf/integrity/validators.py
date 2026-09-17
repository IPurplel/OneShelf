"""Content integrity validation (Master §16.5, §37, §39; INV-16).

Formats are detected from content, never from untrusted extensions. Archives are inspected without
extraction and with bomb/zip-slip guards. XML is parsed with defusedxml.
"""
from __future__ import annotations

import io
import posixpath
import re
import warnings
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import unquote

from defusedxml import ElementTree as SafeET
from PIL import Image, features
from pypdf import PdfReader

MAX_ENTRIES = 20_000
MAX_TOTAL_UNCOMPRESSED = 8 * 1024**3
MAX_ENTRY_BYTES = 256 * 1024**2
RATIO_CHECK_MIN_BYTES = 10 * 1024**2
MAX_COMPRESSION_RATIO = 100
EPUB_MIMETYPE = b"application/epub+zip"

IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp"} | (
    {".avif"} if features.check("avif") else set()
)
_IGNORED_PREFIXES = ("__MACOSX/",)


@dataclass
class ValidationResult:
    ok: bool
    format: str | None
    reason: str | None = None
    page_count: int | None = None
    page_names: list[str] = field(default_factory=list)
    metadata: dict[str, str] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)


def _natural_key(name: str) -> list:
    return [int(part) if part.isdigit() else part.casefold() for part in re.split(r"(\d+)", name)]


def _unsafe_entry_name(name: str) -> bool:
    return (
        "\x00" in name
        or "\\" in name
        or name.startswith("/")
        or re.match(r"^[A-Za-z]:", name) is not None
        or ".." in name.split("/")
    )


def _is_image_entry(info: zipfile.ZipInfo) -> bool:
    name = info.filename
    return (
        not info.is_dir()
        and not name.startswith(_IGNORED_PREFIXES)
        and not posixpath.basename(name).startswith(".")
        and posixpath.splitext(name)[1].lower() in IMAGE_EXTENSIONS
    )


def _looks_like_html(data: bytes) -> bool:
    head = data[:1024].lstrip().lower()
    return head.startswith((b"<!doctype html", b"<html", b"<?xml")) or b"<html" in head[:256]


def _check_archive(z: zipfile.ZipFile) -> str | None:
    infos = z.infolist()
    if len(infos) > MAX_ENTRIES:
        return "too many archive entries"
    total = 0
    for info in infos:
        if _unsafe_entry_name(info.filename):
            return f"unsafe archive entry name: {info.filename!r}"
        total += info.file_size
        if info.file_size > MAX_ENTRY_BYTES:
            return f"archive entry too large: {info.filename!r}"
        if info.file_size >= RATIO_CHECK_MIN_BYTES and info.file_size / max(info.compress_size, 1) > MAX_COMPRESSION_RATIO:
            return f"suspicious compression ratio: {info.filename!r}"
    if total > MAX_TOTAL_UNCOMPRESSED:
        return "archive uncompressed size too large"
    return None


def detect_format(path: str | Path) -> str | None:
    path = Path(path)
    try:
        with open(path, "rb") as f:
            head = f.read(1024)
    except OSError:
        return None
    if b"%PDF-" in head:
        return "pdf"
    if not zipfile.is_zipfile(path):
        return None
    try:
        with zipfile.ZipFile(path) as z:
            names = set(z.namelist())
            if "mimetype" in names and z.read("mimetype").strip() == EPUB_MIMETYPE:
                return "epub"
            if any(_is_image_entry(info) for info in z.infolist()):
                return "cbz"
    except (zipfile.BadZipFile, OSError, RuntimeError):
        return None
    return None


def validate(path: str | Path) -> ValidationResult:
    fmt = detect_format(path)
    if fmt is None:
        return ValidationResult(False, None, "unrecognized or unsupported format")
    return {"cbz": _validate_cbz, "pdf": _validate_pdf, "epub": _validate_epub}[fmt](Path(path))


def _validate_image(data: bytes) -> str | None:
    if not data:
        return "empty image"
    if _looks_like_html(data):
        return "html returned instead of image"
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(data)) as img:
                img.verify()
            with Image.open(io.BytesIO(data)) as img:
                img.load()
                width, height = img.size
    except Exception as exc:  # Pillow raises many exception types for corrupt data
        return f"undecodable image ({type(exc).__name__})"
    if width < 1 or height < 1:
        return "image has no dimensions"
    return None


def _validate_cbz(path: Path) -> ValidationResult:
    try:
        with zipfile.ZipFile(path) as z:
            problem = _check_archive(z)
            if problem:
                return ValidationResult(False, "cbz", problem)
            if z.testzip() is not None:
                return ValidationResult(False, "cbz", "archive CRC check failed")
            pages = sorted((i for i in z.infolist() if _is_image_entry(i)), key=lambda i: _natural_key(i.filename))
            if not pages:
                return ValidationResult(False, "cbz", "no images")
            for info in pages:
                problem = _validate_image(z.read(info))
                if problem:
                    return ValidationResult(False, "cbz", f"{info.filename}: {problem}")
            result = ValidationResult(True, "cbz", page_count=len(pages), page_names=[p.filename for p in pages])
            if "ComicInfo.xml" in z.namelist():
                try:
                    SafeET.fromstring(z.read("ComicInfo.xml"))
                except Exception:
                    result.warnings.append("ComicInfo.xml is malformed and was ignored")
            return result
    except (zipfile.BadZipFile, OSError, RuntimeError) as exc:
        return ValidationResult(False, "cbz", f"unreadable archive ({type(exc).__name__})")


def _validate_pdf(path: Path) -> ValidationResult:
    try:
        reader = PdfReader(str(path), strict=False)
        if reader.is_encrypted and not reader.decrypt(""):
            return ValidationResult(False, "pdf", "encrypted pdf cannot be opened")
        count = len(reader.pages)
        if count < 1:
            return ValidationResult(False, "pdf", "pdf has no pages")
        reader.pages[0].mediabox  # forces the first page object to parse
    except Exception as exc:  # pypdf raises varied exceptions on malformed files
        return ValidationResult(False, "pdf", f"unreadable pdf ({type(exc).__name__})")
    return ValidationResult(True, "pdf", page_count=count)


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _validate_epub(path: Path) -> ValidationResult:
    result = ValidationResult(False, "epub")
    try:
        with zipfile.ZipFile(path) as z:
            problem = _check_archive(z)
            if problem:
                result.reason = problem
                return result
            names = set(z.namelist())
            if z.infolist()[0].filename != "mimetype":
                result.warnings.append("mimetype is not the first archive entry")
            if "META-INF/container.xml" not in names:
                result.reason = "missing META-INF/container.xml"
                return result
            container = SafeET.fromstring(z.read("META-INF/container.xml"))
            rootfile = next((el for el in container.iter() if _local(el.tag) == "rootfile"), None)
            opf_path = rootfile.get("full-path") if rootfile is not None else None
            if not opf_path or opf_path not in names:
                result.reason = "container rootfile missing"
                return result
            package = SafeET.fromstring(z.read(opf_path))
            opf_dir = posixpath.dirname(opf_path)
            manifest = {
                el.get("id"): el.get("href") for el in package.iter() if _local(el.tag) == "item" and el.get("id")
            }
            spine = [el.get("idref") for el in package.iter() if _local(el.tag) == "itemref"]
            if not spine:
                result.reason = "spine is empty"
                return result
            for idref in spine:
                href = manifest.get(idref)
                target = posixpath.normpath(posixpath.join(opf_dir, unquote(href.split("#")[0]))) if href else None
                if target is None or target not in names:
                    result.reason = f"spine item missing: {idref!r}"
                    return result
            for el in package.iter():
                name = _local(el.tag)
                if name in {"title", "language"} and name not in result.metadata and (el.text or "").strip():
                    result.metadata[name] = el.text.strip()
    except (zipfile.BadZipFile, OSError, RuntimeError, KeyError) as exc:
        result.reason = f"unreadable archive ({type(exc).__name__})"
        return result
    except Exception as exc:  # defusedxml / XML parse errors
        result.reason = f"invalid epub xml ({type(exc).__name__})"
        return result
    result.ok = True
    return result
