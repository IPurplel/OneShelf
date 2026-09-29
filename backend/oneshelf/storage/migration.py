"""Storage Location migration (Master §24.8).

Persistent and resumable: preflight → copy → checksum verify → switch the root mapping → reconcile.
The old copy is kept until the user explicitly discards it. A mount-path change that moves no data is a
remap, not a migration.
"""
from __future__ import annotations

import os
import json
import hashlib
import tempfile
import shutil
import sqlite3
from dataclasses import dataclass
from pathlib import Path

from oneshelf.db.connection import transaction
from oneshelf.domain.clock import utcnow_iso
from oneshelf.domain.ids import new_id
from oneshelf.storage.hashing import sha256_file
from oneshelf.storage.paths import PathSafetyError, resolve_within
from oneshelf.storage.roots import META_DIR, StorageRoot, check_availability, get_root, list_roots, preflight, \
    remap_root, staging_dir
from oneshelf.storage.scanner import reconcile
from oneshelf.storage.safe_write import publish, sync_file


class MigrationError(RuntimeError):
    pass


@dataclass(frozen=True)
class MigrationPlan:
    id: str
    root_id: str
    source_path: str
    destination_path: str
    files: int
    bytes: int


@dataclass(frozen=True)
class MigrationReport:
    id: str
    state: str
    copied: int
    verified: int
    errors: list[str]


class StorageMigration:
    def __init__(self, conn: sqlite3.Connection, *, fault=None) -> None:
        self.conn = conn
        self.fault = fault or (lambda _point: None)

    # -- planning ---------------------------------------------------------------------------------

    def plan(self, root_id: str, destination: str | Path) -> MigrationPlan:
        root = get_root(self.conn, root_id)
        availability = check_availability(root)
        if not availability.available:
            raise MigrationError(f"storage location unavailable ({availability.reason})")
        destination = Path(destination).absolute()
        real_destination, real_source = os.path.realpath(destination), os.path.realpath(root.path)
        if os.path.commonpath([real_destination, real_source]) in (real_destination, real_source):
            raise MigrationError("destination overlaps the current storage location")
        if not destination.is_dir():
            raise MigrationError("destination does not exist or is not a directory")
        for other in list_roots(self.conn):
            if other.id == root_id:
                continue
            other_real = os.path.realpath(other.path)
            if os.path.commonpath([real_destination, other_real]) in (real_destination, other_real):
                raise MigrationError("destination overlaps another storage location")

        assets = self.conn.execute(
            "SELECT relative_path, size_bytes, sha256 FROM assets WHERE storage_root_id = ?", (root_id,)).fetchall()
        total = sum(a["size_bytes"] for a in assets)
        usage = shutil.disk_usage(destination)
        if not preflight(total=usage.total, free=usage.free, expected_bytes=total).allowed:
            raise MigrationError("destination does not have enough free space above its reserve")

        migration_id, now = new_id(), utcnow_iso()
        with transaction(self.conn):
            self.conn.execute(
                "INSERT INTO storage_migrations (id, root_id, source_path, destination_path, state, files, bytes,"
                " created_at, updated_at) VALUES (?,?,?,?, 'planned', ?, ?, ?, ?)",
                (migration_id, root_id, root.path, str(destination), len(assets), total, now, now))
            self.conn.executemany(
                "INSERT INTO storage_migration_files (migration_id, relative_path, sha256, size, state)"
                " VALUES (?,?,?,?, 'pending')",
                [(migration_id, a["relative_path"], a["sha256"], a["size_bytes"]) for a in assets])
        return MigrationPlan(migration_id, root_id, root.path, str(destination), len(assets), total)

    def state(self, migration_id: str) -> MigrationReport:
        row = self.conn.execute("SELECT * FROM storage_migrations WHERE id = ?", (migration_id,)).fetchone()
        if row is None:
            raise MigrationError("unknown migration")
        return MigrationReport(row["id"], row["state"], row["copied"], row["verified"], [row["error"]] if row["error"] else [])

    def history(self, root_id: str) -> list[MigrationReport]:
        rows = self.conn.execute("SELECT * FROM storage_migrations WHERE root_id = ? ORDER BY created_at", (root_id,))
        return [MigrationReport(r["id"], r["state"], r["copied"], r["verified"], []) for r in rows]

    # -- execution --------------------------------------------------------------------------------

    def run(self, plan: MigrationPlan) -> MigrationReport:
        return self._execute(plan.id)

    def resume(self, migration_id: str) -> MigrationReport:
        return self._execute(migration_id)

    def _set_state(self, migration_id: str, state: str, **columns) -> None:
        assignments = "".join(f", {key} = ?" for key in columns)
        with transaction(self.conn):
            self.conn.execute(f"UPDATE storage_migrations SET state = ?, updated_at = ?{assignments} WHERE id = ?",
                              (state, utcnow_iso(), *columns.values(), migration_id))

    def _execute(self, migration_id: str) -> MigrationReport:
        row = self.conn.execute("SELECT * FROM storage_migrations WHERE id = ?", (migration_id,)).fetchone()
        if row is None:
            raise MigrationError("unknown migration")
        if row["state"] in ("completed", "old_copy_removed"):
            return self.state(migration_id)
        root = get_root(self.conn, row["root_id"])
        source, destination = Path(row["source_path"]), Path(row["destination_path"])
        copied_this_run = 0
        try:
            # A disconnected source must not be interpreted as an empty replacement filesystem.
            source_root = StorageRoot(root.id, root.name, str(source), root.is_default, root.reserve_override_bytes)
            if not check_availability(source_root).available:
                raise MigrationError("source storage location unavailable")
            resolve_within(source, f"{META_DIR}/root.json")
            if not destination.is_dir():
                raise MigrationError("destination storage location unavailable")
            workspace = resolve_within(destination, f".oneshelf-migration-{migration_id}")
            owner = resolve_within(destination, f"{workspace.name}/owner.json")
            if not workspace.exists():
                workspace.mkdir(mode=0o700)
                with owner.open("x") as handle:
                    json.dump({"migration_id": migration_id, "root_id": root.id}, handle)
            if json.loads(owner.read_text()) != {"migration_id": migration_id, "root_id": root.id}:
                raise MigrationError("migration staging ownership mismatch")
            marker = resolve_within(destination, f"{META_DIR}/root.json")
            marker_staged = resolve_within(workspace, "root.json")
            if marker.exists() and not (marker_staged.exists() and marker.samefile(marker_staged)):
                raise MigrationError("destination marker already exists")
            self._set_state(migration_id, "copying", error=None)
            entries = self.conn.execute(
                "SELECT * FROM storage_migration_files WHERE migration_id = ? ORDER BY relative_path",
                (migration_id,)).fetchall()
            copied = 0
            for entry in entries:
                relative = entry["relative_path"]
                origin = resolve_within(source, relative)
                target = resolve_within(destination, relative)
                staged = resolve_within(workspace, hashlib.sha256(relative.encode()).hexdigest())
                if entry["state"] == "pending":
                    # An existing final file belongs to us only while its staging hard link proves it.
                    if target.exists():
                        if not staged.exists() or not target.samefile(staged):
                            raise MigrationError(f"destination already exists: {relative}")
                    else:
                        expected = sha256_file(origin)
                        if entry["sha256"] and expected != (entry["sha256"], entry["size"]):
                            raise MigrationError(f"source checksum mismatch for {relative}")
                        if not staged.exists() or sha256_file(staged) != expected:
                            with tempfile.NamedTemporaryFile(dir=workspace, delete=False) as handle:
                                temporary = Path(handle.name)
                            try:
                                shutil.copyfile(origin, temporary)
                                sync_file(temporary)
                                if sha256_file(temporary) != expected:
                                    raise MigrationError(f"checksum mismatch for {relative}")
                                os.replace(temporary, staged)
                            finally:
                                temporary.unlink(missing_ok=True)
                        with transaction(self.conn):
                            self.conn.execute("UPDATE storage_migration_files SET sha256 = ?, size = ?"
                                              " WHERE migration_id = ? AND relative_path = ?",
                                              (*expected, migration_id, relative))
                        publish(destination, staged, target)
                        self.fault("file_committed")
                    with transaction(self.conn):
                        self.conn.execute("UPDATE storage_migration_files SET state = 'copied'"
                                          " WHERE migration_id = ? AND relative_path = ?", (migration_id, relative))
                        self.conn.execute("UPDATE storage_migrations SET copied = copied + 1 WHERE id = ?",
                                          (migration_id,))
                    copied_this_run += 1
                    self.fault("file_copied")
                copied += 1

            self._set_state(migration_id, "verifying", copied=copied)
            for entry in self.conn.execute(
                    "SELECT * FROM storage_migration_files WHERE migration_id = ?", (migration_id,)).fetchall():
                target = resolve_within(destination, entry["relative_path"])
                if sha256_file(target) != (entry["sha256"], entry["size"]):
                    raise MigrationError(f"checksum mismatch for {entry['relative_path']}")
                with transaction(self.conn):
                    self.conn.execute("UPDATE storage_migration_files SET state = 'verified' WHERE migration_id = ?"
                                      " AND relative_path = ?", (migration_id, entry["relative_path"]))
            # Publish the identity marker with the same ownership and non-replacement rules as content.
            if not marker_staged.exists():
                with marker_staged.open("xb") as handle:
                    handle.write(resolve_within(source, f"{META_DIR}/root.json").read_bytes())
            if not marker.exists():
                publish(destination, marker_staged, marker)
            resolve_within(destination, f"{META_DIR}/staging").mkdir(parents=True, exist_ok=True)
            self._set_state(migration_id, "switched", verified=copied)
            remap_root(self.conn, root.id, destination)
            reconcile(self.conn)
            self._set_state(migration_id, "completed")
        except (OSError, ValueError, MigrationError) as exc:
            self._set_state(migration_id, "failed", error=str(exc))
            raise MigrationError(str(exc)) from exc
        report = self.state(migration_id)
        return MigrationReport(report.id, report.state, copied_this_run, report.verified, report.errors)

    # -- old copy ---------------------------------------------------------------------------------

    def discard_old_copy(self, migration_id: str) -> int:
        """Only ever on an explicit request (§24.8): OneShelf never deletes old storage on its own."""
        row = self.conn.execute("SELECT * FROM storage_migrations WHERE id = ?", (migration_id,)).fetchone()
        if row is None or row["state"] != "completed":
            raise MigrationError("migration is not complete")
        source = Path(row["source_path"])
        root = get_root(self.conn, row["root_id"])
        source_root = StorageRoot(root.id, root.name, str(source), root.is_default, root.reserve_override_bytes)
        if not check_availability(source_root).available:
            raise MigrationError("old storage location unavailable")
        removed = 0
        try:
            resolve_within(source, f"{META_DIR}/root.json")
            entries = self.conn.execute("SELECT * FROM storage_migration_files WHERE migration_id = ?",
                                        (migration_id,)).fetchall()
            paths = []
            for entry in entries:
                path = resolve_within(source, entry["relative_path"])
                if path.exists():
                    if sha256_file(path) != (entry["sha256"], entry["size"]):
                        raise MigrationError(f"old file has changed: {entry['relative_path']}")
                    # Never remove the last verified copy if the destination was lost or changed.
                    target = resolve_within(root.path, entry["relative_path"])
                    if not check_availability(root).available or sha256_file(target) != (entry["sha256"], entry["size"]):
                        raise MigrationError("destination copy is unavailable or changed")
                    paths.append(path)
            for path in paths:
                resolve_within(source, path.relative_to(source).as_posix()).unlink()
                removed += 1
        except (OSError, ValueError) as exc:
            raise MigrationError(str(exc)) from exc
        self._set_state(migration_id, "old_copy_removed")
        return removed

    def remap(self, root_id: str, new_path: str | Path) -> StorageRoot:
        """A Docker mount path change: validate identity and remap, copying nothing (§24.8)."""
        return remap_root(self.conn, root_id, new_path)
