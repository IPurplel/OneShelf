"""Build the official `.osp` packages from plugins/official.

The builder itself lives in `oneshelf.plugins.bundled`, because the application needs it inside the
production image to install these packages on first run. Keeping a single builder means the packages a
developer builds here and the ones a fresh installation builds are byte-for-byte the same.
"""
from __future__ import annotations

from pathlib import Path

from oneshelf.plugins.bundled import build_package, discover

OFFICIAL_DIR = Path(__file__).parent / "official"

__all__ = ["OFFICIAL_DIR", "build_all", "build_package", "official_packages"]


def official_packages() -> list[Path]:
    return discover(OFFICIAL_DIR)


def build_all(destination_dir: str | Path) -> list[Path]:
    destination_dir = Path(destination_dir)
    return [build_package(source, destination_dir / f"{source.name}.osp") for source in official_packages()]
