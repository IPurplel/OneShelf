"""Verified staging and atomic publication for user-selected destinations.

No-replace publication uses a hard link: unsupported filesystems fail safely rather than falling back
to a check-then-rename that can overwrite another writer's file.
"""
from __future__ import annotations

import os
from pathlib import Path

from oneshelf.storage.paths import resolve_within


def destination_path(root: str | Path, path: str | Path) -> Path:
    root, path = Path(root).absolute(), Path(path).absolute()
    return resolve_within(root, path.relative_to(root).as_posix())


def sync_file(path: Path) -> None:
    with path.open('rb') as handle:
        os.fsync(handle.fileno())


def publish(root: str | Path, staged: Path, target: Path, *, replace: bool = False) -> Path:
    target = destination_path(root, target)
    target.parent.mkdir(parents=True, exist_ok=True)
    target = destination_path(root, target)
    sync_file(staged)
    if replace:
        os.replace(staged, target)
    else:
        os.link(staged, target)
        # Migration recovery uses this staging link to prove ownership after interruption.
        # The caller owns staging cleanup; no two library assets share this file.
    fd = os.open(target.parent, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)
    return target
