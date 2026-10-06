"""Build the Test Source .osp from testsource/package (deterministic ordering and timestamps)."""
from __future__ import annotations

import zipfile
from pathlib import Path

PACKAGE_DIR = Path(__file__).parent / "package"
# The same source as a text source (plugin API 1.2): these files replace the package's own.
TEXT_OVERLAY_DIR = Path(__file__).parent / "text_overlay"


def _files(directory: Path) -> dict[str, bytes]:
    return {p.relative_to(directory).as_posix(): p.read_bytes() for p in directory.rglob("*") if p.is_file()}


def build_package(destination: str | Path, *, text: bool = False) -> Path:
    destination = Path(destination)
    files = _files(PACKAGE_DIR) | (_files(TEXT_OVERLAY_DIR) if text else {})
    with zipfile.ZipFile(destination, "w", compression=zipfile.ZIP_DEFLATED) as z:
        for name in sorted(files):
            info = zipfile.ZipInfo(name, date_time=(2026, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            z.writestr(info, files[name])
    return destination
