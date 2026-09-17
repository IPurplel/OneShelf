"""Build the Test Source .osp from testsource/package (deterministic ordering and timestamps)."""
from __future__ import annotations

import zipfile
from pathlib import Path

PACKAGE_DIR = Path(__file__).parent / "package"


def build_package(destination: str | Path) -> Path:
    destination = Path(destination)
    with zipfile.ZipFile(destination, "w", compression=zipfile.ZIP_DEFLATED) as z:
        for path in sorted(p for p in PACKAGE_DIR.rglob("*") if p.is_file()):
            info = zipfile.ZipInfo(path.relative_to(PACKAGE_DIR).as_posix(), date_time=(2026, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            z.writestr(info, path.read_bytes())
    return destination
