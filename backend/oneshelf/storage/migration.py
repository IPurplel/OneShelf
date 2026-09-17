"""Storage Location migration (Master §24.8).

Persistent and resumable: preflight → copy → checksum verify → switch the root mapping → reconcile.
The old copy is kept until the user explicitly discards it. A mount-path change that moves no data is a
remap, not a migration.
"""
from __future__ import annotations

import os
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
        destination = Path(destination)
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
        self._set_state(migration_id, "copying")
        copied, copied_this_run = row["copied"], 0
        for entry in self.conn.execute(
                "SELECT * FROM storage_migration_files WHERE migration_id = ? AND state = 'pending'"
                " ORDER BY relative_path", (migration_id,)).fetchall():
            relative = entry["relative_path"]
            try:
                origin = resolve_within(source, relative)
                target = destination / Path(relative)
            except PathSafetyError as exc:
                self._set_state(migration_id, "failed", error=str(exc))
                raise MigrationError(str(exc)) from exc
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(origin, target)
            with open(target, "rb") as handle:
                os.fsync(handle.fileno())
            copied += 1
            copied_this_run += 1
            with transaction(self.conn):
                self.conn.execute("UPDATE storage_migration_files SET state = 'copied' WHERE migration_id = ?"
                                  " AND relative_path = ?", (migration_id, relative))
                self.conn.execute("UPDATE storage_migrations SET copied = ?, updated_at = ? WHERE id = ?",
                                  (copied, utcnow_iso(), migration_id))
            self.fault("file_copied")

        self._set_state(migration_id, "verifying")
        verified = 0
        for entry in self.conn.execute(
                "SELECT * FROM storage_migration_files WHERE migration_id = ?", (migration_id,)).fetchall():
            target = destination / Path(entry["relative_path"])
            digest, size = sha256_file(target)
            if entry["sha256"] and digest != entry["sha256"]:
                self._set_state(migration_id, "failed", error=f"checksum mismatch for {entry['relative_path']}")
                raise MigrationError(f"checksum mismatch for {entry['relative_path']}")
            verified += 1
            with transaction(self.conn):
                self.conn.execute("UPDATE storage_migration_files SET state = 'verified' WHERE migration_id = ?"
                                  " AND relative_path = ?", (migration_id, entry["relative_path"]))
        self._set_state(migration_id, "switched", verified=verified)

        self._prepare_destination(root, destination)
        remap_root(self.conn, root.id, destination)
        reconcile(self.conn)
        self._set_state(migration_id, "completed")
        report = self.state(migration_id)
        return MigrationReport(report.id, report.state, copied_this_run, report.verified, report.errors)

    @staticmethod
    def _prepare_destination(root: StorageRoot, destination: Path) -> None:
        staging_dir(destination).mkdir(parents=True, exist_ok=True)
        marker_source = Path(root.path) / META_DIR / "root.json"
        marker_target = destination / META_DIR / "root.json"
        if marker_source.is_file():
            shutil.copyfile(marker_source, marker_target)

    # -- old copy ---------------------------------------------------------------------------------

    def discard_old_copy(self, migration_id: str) -> int:
        """Only ever on an explicit request (§24.8): OneShelf never deletes old storage on its own."""
        row = self.conn.execute("SELECT * FROM storage_migrations WHERE id = ?", (migration_id,)).fetchone()
        if row is None or row["state"] != "completed":
            raise MigrationError("migration is not complete")
        source = Path(row["source_path"])
        removed = 0
        for entry in self.conn.execute("SELECT relative_path FROM storage_migration_files WHERE migration_id = ?",
                                       (migration_id,)):
            path = source / Path(entry[0])
            if path.is_file():
                path.unlink()
                removed += 1
        for directory in sorted((p for p in source.rglob("*") if p.is_dir()), key=lambda p: -len(p.parts)):
            if not any(directory.iterdir()):
                directory.rmdir()
        self._set_state(migration_id, "old_copy_removed")
        return removed

    def remap(self, root_id: str, new_path: str | Path) -> StorageRoot:
        """A Docker mount path change: validate identity and remap, copying nothing (§24.8)."""
        return remap_root(self.conn, root_id, new_path)
