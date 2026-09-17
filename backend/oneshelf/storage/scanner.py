"""Library scanner / reconciliation (Master §24.6, §24.7, §38).

Never deletes records. Unavailable roots are marked unavailable and skipped entirely; manual deletions
become Missing Local File; manual moves inside a root are recovered by the OneShelf ID embedded in the
filename plus a checksum match. Checksums are integrity evidence only, never Work-matching evidence.
"""
from __future__ import annotations

import os
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path

from oneshelf.db.connection import transaction
from oneshelf.domain.clock import utcnow_iso
from oneshelf.storage.hashing import sha256_file
from oneshelf.storage.paths import PathSafetyError, resolve_within
from oneshelf.storage.roots import META_DIR, StorageRoot, check_availability, list_roots


@dataclass
class ScanReport:
    changed: int = 0
    missing: int = 0
    corrupt: int = 0
    restored: int = 0
    relocated: int = 0
    unavailable_roots: list[str] = field(default_factory=list)


def _untracked_files(root: StorageRoot, tracked: set[str]) -> dict[str, list[str]]:
    by_name: dict[str, list[str]] = {}
    for dirpath, dirnames, filenames in os.walk(root.path, followlinks=False):
        rel_dir = os.path.relpath(dirpath, root.path)
        if rel_dir == ".":
            dirnames[:] = [d for d in dirnames if d != META_DIR]
            rel_dir = ""
        for name in filenames:
            rel = f"{rel_dir}/{name}" if rel_dir else name
            full = os.path.join(dirpath, name)
            if rel not in tracked and os.path.isfile(full) and not os.path.islink(full):
                by_name.setdefault(name, []).append(rel)
    return by_name


def _set_root_availability(conn: sqlite3.Connection, root: StorageRoot, value: str) -> None:
    with transaction(conn):
        conn.execute(
            "UPDATE storage_roots SET last_availability = ?, updated_at = ? WHERE id = ? AND last_availability <> ?",
            (value, utcnow_iso(), root.id, value),
        )


def reconcile(conn: sqlite3.Connection, *, verify_checksums: bool = False) -> ScanReport:
    report = ScanReport()
    for root in list_roots(conn):
        if not check_availability(root).available:
            report.unavailable_roots.append(root.id)
            _set_root_availability(conn, root, "unavailable")
            continue
        _set_root_availability(conn, root, "available")
        assets = conn.execute(
            "SELECT id, relative_path, size_bytes, sha256, integrity FROM assets WHERE storage_root_id = ?", (root.id,)
        ).fetchall()
        tracked = {a["relative_path"] for a in assets}
        untracked: dict[str, list[str]] | None = None
        updates: list[tuple[str, str, str]] = []  # (asset_id, integrity, relative_path)

        for asset in assets:
            rel = asset["relative_path"]
            try:
                path = resolve_within(root.path, rel)
                present = path.is_file() and not path.is_symlink()
            except PathSafetyError:
                present = False
            if present:
                size_ok = path.stat().st_size == asset["size_bytes"]
                if not size_ok:
                    new_state = "corrupt"
                elif asset["integrity"] != "ok" or verify_checksums:
                    new_state = "ok" if sha256_file(path)[0] == asset["sha256"] else "corrupt"
                else:
                    new_state = "ok"
                if new_state != asset["integrity"]:
                    updates.append((asset["id"], new_state, rel))
                    if new_state == "ok":
                        report.restored += 1
                    else:
                        report.corrupt += 1
                continue

            if untracked is None:
                untracked = _untracked_files(root, tracked)
            candidates = [
                c for c in untracked.get(Path(rel).name, [])
                if sha256_file(os.path.join(root.path, c)) == (asset["sha256"], asset["size_bytes"])
            ]
            if len(candidates) == 1:
                updates.append((asset["id"], "ok", candidates[0]))
                untracked[Path(rel).name].remove(candidates[0])
                report.relocated += 1
            elif asset["integrity"] != "missing_local_file":
                updates.append((asset["id"], "missing_local_file", rel))
                report.missing += 1

        if updates:
            now = utcnow_iso()
            with transaction(conn):
                for asset_id, integrity, rel in updates:
                    conn.execute(
                        "UPDATE assets SET integrity = ?, relative_path = ?, updated_at = ? WHERE id = ?",
                        (integrity, rel, now, asset_id),
                    )
            report.changed += len(updates)
    return report
