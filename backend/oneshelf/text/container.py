"""The stored form of a text reading unit (format `text`, extension `.ostext`).

A zip, so a unit stays one file like every other asset (commit, scan, backup and restore all assume
that): `mimetype` first and uncompressed, as in EPUB, then `unit.json` and one sanitised HTML file per
section. It is the source's own content in its own shape, never an EPUB made from it (Master §34.4).
"""
from __future__ import annotations

import json
import zipfile
from dataclasses import dataclass
from pathlib import Path

from oneshelf.text.sanitise import MAX_TEXT_UNIT_BYTES, Section

TEXT_MIMETYPE = b"application/vnd.oneshelf.text+zip"
TEXT_EXTENSION = "ostext"
UNIT_FILE = "unit.json"
MAX_SECTIONS = 2000
MAX_TITLE = 500


class TextContainerError(ValueError):
    pass


@dataclass(frozen=True)
class TextUnit:
    title: str | None
    language: str | None
    direction: str
    source_url: str | None
    sections: list[Section]


def write_text_container(path: str | Path, unit: TextUnit) -> Path:
    path = Path(path)
    entries = []
    for number, section in enumerate(unit.sections, start=1):
        entries.append({"file": f"sections/{number:04d}.html", "title": section.title,
                        "characters": section.characters})
    meta = {"title": unit.title, "language": unit.language, "direction": unit.direction,
            "source_url": unit.source_url, "sections": entries}
    with zipfile.ZipFile(path, "w") as z:
        z.writestr(zipfile.ZipInfo("mimetype"), TEXT_MIMETYPE, compress_type=zipfile.ZIP_STORED)
        z.writestr(UNIT_FILE, json.dumps(meta, ensure_ascii=False, indent=1), compress_type=zipfile.ZIP_DEFLATED)
        for entry, section in zip(entries, unit.sections):
            z.writestr(entry["file"], section.html.encode("utf-8"), compress_type=zipfile.ZIP_DEFLATED)
    return path


def _text(value, limit: int) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or len(value) > limit:
        raise TextContainerError("unit.json has an invalid text value")
    return value


def read_text_container(z: zipfile.ZipFile) -> TextUnit:
    """Read and shape-check a container. Content checks (sanitised, sizes) belong to the validator."""
    names = set(z.namelist())
    if UNIT_FILE not in names:
        raise TextContainerError("missing unit.json")
    try:
        meta = json.loads(z.read(UNIT_FILE).decode("utf-8"))
    except (UnicodeDecodeError, ValueError) as exc:
        raise TextContainerError("unit.json is not valid JSON") from exc
    if not isinstance(meta, dict) or not isinstance(meta.get("sections"), list):
        raise TextContainerError("unit.json has no section list")
    if not meta["sections"] or len(meta["sections"]) > MAX_SECTIONS:
        raise TextContainerError("unit.json has no sections or too many")
    direction = meta.get("direction")
    if direction not in ("ltr", "rtl"):
        raise TextContainerError("unit.json direction must be ltr or rtl")
    sections = []
    for entry in meta["sections"]:
        if not isinstance(entry, dict) or not isinstance(entry.get("file"), str):
            raise TextContainerError("unit.json has an invalid section entry")
        name = entry["file"]
        if not name.startswith("sections/") or name not in names:
            raise TextContainerError(f"section missing: {name!r}")
        info = z.getinfo(name)
        if info.file_size > MAX_TEXT_UNIT_BYTES:
            raise TextContainerError(f"section too large: {name!r}")
        try:
            html = z.read(name).decode("utf-8")
        except UnicodeDecodeError as exc:
            raise TextContainerError(f"section is not UTF-8: {name!r}") from exc
        characters = entry.get("characters")
        if not isinstance(characters, int) or characters < 0:
            raise TextContainerError(f"section has no character count: {name!r}")
        sections.append(Section(html=html, title=_text(entry.get("title"), MAX_TITLE), characters=characters))
    return TextUnit(title=_text(meta.get("title"), MAX_TITLE), language=_text(meta.get("language"), 35),
                    direction=direction, source_url=_text(meta.get("source_url"), 2048), sections=sections)


def open_text_container(path: str | Path) -> TextUnit:
    with zipfile.ZipFile(path) as z:
        return read_text_container(z)
