"""Build the official `.osp` packages from plugins/official (deterministic ordering and timestamps)."""
from __future__ import annotations

import zipfile
from pathlib import Path

OFFICIAL_DIR = Path(__file__).parent / "official"


def official_packages() -> list[Path]:
    return sorted(p for p in OFFICIAL_DIR.iterdir() if p.is_dir() and (p / "manifest.yaml").is_file())


def build_package(source_dir: str | Path, destination: str | Path) -> Path:
    source_dir, destination = Path(source_dir), Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(destination, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(p for p in source_dir.rglob("*") if p.is_file()):
            info = zipfile.ZipInfo(path.relative_to(source_dir).as_posix(), date_time=(2026, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            archive.writestr(info, path.read_bytes())
    return destination


def build_all(destination_dir: str | Path) -> list[Path]:
    destination_dir = Path(destination_dir)
    return [build_package(source, destination_dir / f"{source.name}.osp") for source in official_packages()]
