"""Clean only proven-orphan staging areas (Master §25). Must run after job and commit recovery."""
from __future__ import annotations

import os
import shutil
import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path

from oneshelf.settings.defaults import DEFAULTS
from oneshelf.storage.commit import OPEN_STATES
from oneshelf.storage.roots import check_availability, list_roots, staging_dir
from oneshelf.storage.staging import STAGING_PREFIX, read_area_meta

_TERMINAL_SUCCESS = {"completed", "COMPLETED"}
_TERMINAL_OTHER = {"failed", "rejected", "FAILED", "CANCELED"}


def _owner_state(conn: sqlite3.Connection, meta: dict) -> str | None:
    table = {"import": ("imports", "state"), "download": ("download_jobs", "state")}.get(meta.get("purpose"))
    if table is None:
        return None
    row = conn.execute(f"SELECT {table[1]} FROM {table[0]} WHERE id = ?", (meta.get("owner_id"),)).fetchone()
    return row[0] if row else None


def _ttl(conn: sqlite3.Connection, meta: dict | None) -> timedelta | None:
    """Retention for an area, or None when its owner is still active (never an orphan)."""
    if meta is None:
        return DEFAULTS.staging.resumable_partial_ttl
    state = _owner_state(conn, meta)
    if state in _TERMINAL_SUCCESS:
        return DEFAULTS.staging.success_leftover_ttl
    if state is not None and state not in _TERMINAL_OTHER:
        return None
    if meta.get("resumable"):
        return DEFAULTS.staging.resumable_partial_ttl
    if state is None and meta.get("purpose") not in {"import", "download"}:
        return DEFAULTS.staging.resumable_partial_ttl
    return DEFAULTS.staging.success_leftover_ttl


def _created(area: Path, meta: dict | None) -> datetime:
    if meta and meta.get("created_at"):
        try:
            return datetime.fromisoformat(meta["created_at"])
        except ValueError:
            pass
    return datetime.fromtimestamp(os.lstat(area).st_mtime, UTC)


def clean_orphan_staging(conn: sqlite3.Connection, *, now: datetime | None = None) -> int:
    now = now or datetime.now(UTC)
    removed = 0
    placeholders = ",".join("?" * len(OPEN_STATES))
    for root in list_roots(conn):
        if not check_availability(root).available:
            continue
        base = staging_dir(root.path)
        if not base.is_dir():
            continue
        open_paths = [
            r[0]
            for r in conn.execute(
                f"SELECT staging_relpath FROM commit_journal WHERE storage_root_id = ? AND state IN ({placeholders})",
                (root.id, *OPEN_STATES),
            )
        ]
        for area in base.iterdir():
            prefix = f"{STAGING_PREFIX}{area.name}/"
            if any(p.startswith(prefix) for p in open_paths):
                continue
            if area.is_symlink() or not area.is_dir():
                meta = None
            else:
                meta = read_area_meta(area)
            ttl = _ttl(conn, meta)
            if ttl is None or now - _created(area, meta) < ttl:
                continue
            if area.is_symlink() or not area.is_dir():
                area.unlink()
            else:
                shutil.rmtree(area)
            removed += 1
    return removed
