"""Storage Locations (Master §24.1, §24.5, §24.6, §24.8).

A root is identified by its stable ID, recorded both in the database and in a marker file inside the
root. A missing or foreign marker means the location is unavailable (e.g. unmounted), never that its
content was deleted.
"""
from __future__ import annotations

import json
import os
import shutil
import sqlite3
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

from oneshelf.db.connection import transaction
from oneshelf.domain.clock import utcnow_iso
from oneshelf.domain.ids import new_id
from oneshelf.settings.defaults import DEFAULTS, GiB

__all__ = ["GiB"]

META_DIR = ".oneshelf"
MARKER = "root.json"
STAGING = "staging"


class RootError(RuntimeError):
    pass


@dataclass(frozen=True)
class StorageRoot:
    id: str
    name: str
    path: str
    is_default: bool
    reserve_override_bytes: int | None


@dataclass(frozen=True)
class Availability:
    available: bool
    reason: str | None = None  # path_missing | not_directory | marker_missing | marker_mismatch | not_writable


class SpaceState(Enum):
    OK = "ok"
    LOW = "low"
    AT_RESERVE = "at_reserve"


@dataclass(frozen=True)
class SpaceStatus:
    state: SpaceState
    total: int
    free: int
    reserve: int


@dataclass(frozen=True)
class PreflightDecision:
    allowed: bool
    reason: str | None = None


def _row_to_root(row: sqlite3.Row) -> StorageRoot:
    return StorageRoot(row["id"], row["name"], row["path"], bool(row["is_default"]), row["reserve_override_bytes"])


def staging_dir(root_path: str | Path) -> Path:
    return Path(root_path) / META_DIR / STAGING


def _read_marker(path: Path) -> str | None:
    try:
        return json.loads((path / META_DIR / MARKER).read_text(encoding="utf-8")).get("root_id")
    except (FileNotFoundError, NotADirectoryError, json.JSONDecodeError, AttributeError):
        return None


def list_roots(conn: sqlite3.Connection) -> list[StorageRoot]:
    return [_row_to_root(r) for r in conn.execute("SELECT * FROM storage_roots ORDER BY created_at, id")]


def get_root(conn: sqlite3.Connection, root_id: str) -> StorageRoot:
    row = conn.execute("SELECT * FROM storage_roots WHERE id = ?", (root_id,)).fetchone()
    if row is None:
        raise RootError(f"unknown storage root {root_id}")
    return _row_to_root(row)


def _overlaps(a: str, b: str) -> bool:
    return os.path.commonpath([a, b]) in {a, b}


def register_root(conn: sqlite3.Connection, name: str, path: str | Path) -> StorageRoot:
    path = Path(path)
    if not path.is_dir():
        raise RootError(f"storage location does not exist or is not a directory: {path}")
    real = os.path.realpath(path)
    for existing in list_roots(conn):
        if _overlaps(real, os.path.realpath(existing.path)):
            raise RootError(f"storage location overlaps existing root {existing.name!r}")
    if _read_marker(path) is not None:
        raise RootError("directory is already a OneShelf storage location; remap or restore it instead")
    root_id = new_id()
    now = utcnow_iso()
    staging_dir(path).mkdir(parents=True, exist_ok=True)
    marker_tmp = path / META_DIR / f".{MARKER}.tmp"
    marker_tmp.write_text(json.dumps({"root_id": root_id, "created_at": now}), encoding="utf-8")
    os.replace(marker_tmp, path / META_DIR / MARKER)
    with transaction(conn):
        is_default = conn.execute("SELECT count(*) FROM storage_roots WHERE is_default = 1").fetchone()[0] == 0
        conn.execute(
            "INSERT INTO storage_roots (id, name, path, is_default, last_availability, created_at, updated_at)"
            " VALUES (?, ?, ?, ?, 'available', ?, ?)",
            (root_id, name, str(path), int(is_default), now, now),
        )
    return get_root(conn, root_id)


def set_default_root(conn: sqlite3.Connection, root_id: str) -> None:
    get_root(conn, root_id)
    with transaction(conn):
        conn.execute("UPDATE storage_roots SET is_default = (id = ?), updated_at = ?", (root_id, utcnow_iso()))


def check_availability(root: StorageRoot) -> Availability:
    path = Path(root.path)
    if not path.exists():
        return Availability(False, "path_missing")
    if not path.is_dir():
        return Availability(False, "not_directory")
    marker = _read_marker(path)
    if marker is None:
        return Availability(False, "marker_missing")
    if marker != root.id:
        return Availability(False, "marker_mismatch")
    if not os.access(staging_dir(path), os.W_OK):
        return Availability(False, "not_writable")
    return Availability(True)


def reserve_bytes(*, total: int, override: int | None = None) -> int:
    if override is not None:
        return override
    return min(int(total * DEFAULTS.storage.reserve_fraction), DEFAULTS.storage.reserve_cap_bytes)


def space_status(*, total: int, free: int, override: int | None = None) -> SpaceStatus:
    reserve = reserve_bytes(total=total, override=override)
    if free <= reserve:
        state = SpaceState.AT_RESERVE
    elif free <= reserve * DEFAULTS.storage.warning_multiplier:
        state = SpaceState.LOW
    else:
        state = SpaceState.OK
    return SpaceStatus(state, total, free, reserve)


def root_space(root: StorageRoot) -> SpaceStatus:
    usage = shutil.disk_usage(root.path)
    return space_status(total=usage.total, free=usage.free, override=root.reserve_override_bytes)


def preflight(*, total: int, free: int, expected_bytes: int, override: int | None = None) -> PreflightDecision:
    reserve = reserve_bytes(total=total, override=override)
    if free - expected_bytes < reserve:
        return PreflightDecision(False, "would_breach_reserve")
    return PreflightDecision(True)


def remap_root(conn: sqlite3.Connection, root_id: str, new_path: str | Path) -> StorageRoot:
    """Point a root at a new mount path holding the same data; validates identity, copies nothing."""
    root = get_root(conn, root_id)
    new_path = Path(new_path)
    if _read_marker(new_path) != root.id:
        raise RootError("the new location does not contain this storage root's data")
    with transaction(conn):
        conn.execute(
            "UPDATE storage_roots SET path = ?, last_availability = 'available', updated_at = ? WHERE id = ?",
            (str(new_path), utcnow_iso(), root_id),
        )
    return get_root(conn, root_id)
