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


def sync_file(path: str | Path) -> None:
    # Windows flushes a file only through a handle that may write to it; a read-only one fails with EBADF.
    with open(path, "r+b" if os.name == "nt" else "rb") as handle:
        os.fsync(handle.fileno())


def fsync_dir(path: str | Path) -> None:
    """Make a rename or link durable. Windows cannot open a directory for fsync (EBADF); NTFS journals
    its directory entries itself, so there is nothing further to flush there."""
    if os.name == "nt":
        return
    fd = os.open(path, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


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
    fsync_dir(target.parent)
    return target
