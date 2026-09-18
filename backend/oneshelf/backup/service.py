"""Backup and restore format and creation (Master §18, §33; INV-19).

Exactly two kinds: Library Backup (state and metadata) and Full Backup (plus selected downloaded
content). The database is captured with the SQLite online backup API, never by copying a live file, and
every secret store is excluded by construction: sessions, tokens, keys, browser profiles, staging,
partial downloads and rebuildable caches live outside the snapshot or are cleared from it.
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import sqlite3
import zipfile
from collections.abc import Callable
from contextlib import closing
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path

from oneshelf.db.connection import open_database, transaction
from oneshelf.db.migrate import current_version
from oneshelf.db.schema import MIGRATIONS
from oneshelf.domain.ids import new_id
from oneshelf.settings.defaults import DEFAULTS
from oneshelf.storage.paths import resolve_within
from oneshelf.storage.roots import get_root

BACKUP_SCHEMA = "oneshelf.backup/1"
SUFFIX = ".osbackup"

# Cleared from the snapshot: secrets, transient job state and anything rebuildable (§33.3).
EXCLUDED_TABLES = ("source_session_refs", "commit_journal", "download_jobs", "download_batches", "search_index",
                   "source_health_signals", "source_health_state", "storage_migrations", "storage_migration_files")
COUNTED_TABLES = ("works", "source_tracks", "reading_units", "assets", "shelf_entries", "follows", "reading_state",
                  "work_mappings", "user_overrides", "settings", "reading_bookmarks", "reading_highlights")


class BackupError(RuntimeError):
    pass


@dataclass(frozen=True)
class BackupRecord:
    id: str
    kind: str
    path: str
    checksum: str
    created_at: str
    verified_at: str | None
    counts: dict = field(default_factory=dict)


@dataclass(frozen=True)
class VerifyResult:
    ok: bool
    reason: str | None = None
    manifest: dict | None = None


class BackupService:
    def __init__(self, conn: sqlite3.Connection, db_path: str | Path, *, backup_dir: str | Path,
                 clock: Callable[[], datetime] = lambda: datetime.now(UTC), fault=None, notifications=None) -> None:
        self.conn = conn
        self.db_path = Path(db_path)
        self.backup_dir = Path(backup_dir)
        self.backup_dir.mkdir(parents=True, exist_ok=True)
        self.clock = clock
        self.fault = fault or (lambda _point: None)
        self.notifications = notifications

    # -- creation ---------------------------------------------------------------------------------

    def _snapshot(self, destination: Path) -> dict:
        """Consistent SQLite snapshot with excluded tables cleared (§18, §33.3)."""
        with closing(sqlite3.connect(destination)) as target:
            self.conn.backup(target)
        with closing(sqlite3.connect(destination)) as snapshot:
            snapshot.row_factory = sqlite3.Row
            for table in EXCLUDED_TABLES:
                exists = snapshot.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name = ?",
                                          (table,)).fetchone()
                if exists:
                    snapshot.execute(f"DELETE FROM {table}")
            snapshot.commit()
            snapshot.execute("VACUUM")
            counts = {table: snapshot.execute(f"SELECT count(*) FROM {table}").fetchone()[0]
                      for table in COUNTED_TABLES}
        return counts

    def _plugins(self) -> list[dict]:
        rows = self.conn.execute(
            "SELECT p.id, p.active_version, v.permissions_json FROM plugins p"
            " LEFT JOIN plugin_versions v ON v.plugin_id = p.id AND v.version = p.active_version"
            " WHERE p.active_version IS NOT NULL ORDER BY p.id").fetchall()
        return [{"id": r["id"], "version": r["active_version"],
                 "permissions": json.loads(r["permissions_json"] or "[]")} for r in rows]

    def _content(self, works: list[str] | None) -> list[sqlite3.Row]:
        if works is None:
            return []
        placeholders = ",".join("?" * len(works))
        return self.conn.execute(
            f"SELECT a.*, t.work_id FROM assets a JOIN reading_units u ON u.id = a.reading_unit_id"
            f" JOIN source_tracks t ON t.id = u.track_id WHERE t.work_id IN ({placeholders}) AND a.integrity = 'ok'",
            works).fetchall()

    def create(self, kind: str = "library", *, works: list[str] | None = None, location: str | Path | None = None) -> BackupRecord:
        if kind not in ("library", "full"):
            raise BackupError("backup kind must be 'library' or 'full'")
        if kind == "full" and not works:
            raise BackupError("a Full Backup needs the Works whose content to include")
        directory = Path(location) if location else self.backup_dir
        directory.mkdir(parents=True, exist_ok=True)
        stamp = self.clock().strftime("%Y%m%dT%H%M%S")
        path = directory / f"oneshelf-{kind}-{stamp}-{new_id()[:6]}{SUFFIX}"
        staging = directory / f".{path.stem}.tmp"
        staging.mkdir(parents=True, exist_ok=True)
        try:
            snapshot_path = staging / "library.db"
            counts = self._snapshot(snapshot_path)
            self.fault("after_snapshot")
            inventory, content = [], []
            with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
                data = snapshot_path.read_bytes()
                archive.writestr("library.db", data)
                inventory.append({"path": "library.db", "sha256": hashlib.sha256(data).hexdigest(), "size": len(data)})
                for asset in self._content(works if kind == "full" else None):
                    root = get_root(self.conn, asset["storage_root_id"])
                    try:
                        source = resolve_within(root.path, asset["relative_path"])
                        payload = source.read_bytes()
                    except (OSError, ValueError):
                        continue
                    name = f"content/{asset['id']}.{asset['format']}"
                    archive.writestr(name, payload)
                    digest = hashlib.sha256(payload).hexdigest()
                    inventory.append({"path": name, "sha256": digest, "size": len(payload)})
                    content.append({"asset_id": asset["id"], "reading_unit_id": asset["reading_unit_id"],
                                    "work_id": asset["work_id"], "relative_path": asset["relative_path"],
                                    "format": asset["format"], "sha256": digest, "size": len(payload), "path": name})
                manifest = {
                    "schema": BACKUP_SCHEMA, "kind": kind, "created_at": self.clock().isoformat(),
                    "schema_version": current_version(self.db_path), "app_schema_version": len(MIGRATIONS),
                    "counts": counts, "plugins": self._plugins(), "inventory": inventory, "content": content,
                    "works": works or [],
                }
                archive.writestr("manifest.json", json.dumps(manifest, indent=1))
            result = self.verify(path)
            if not result.ok:
                path.unlink(missing_ok=True)
                raise BackupError(f"backup verification failed: {result.reason}")
            checksum = hashlib.sha256(path.read_bytes()).hexdigest()
            # The record is stamped from the same clock `due()` reads, so the schedule cannot drift
            # away from the archives it is scheduling.
            record_id, now = new_id(), self.clock().isoformat()
            with transaction(self.conn):
                self.conn.execute(
                    "INSERT INTO backup_records (id, kind, state, location, checksum, created_at, verified_at)"
                    " VALUES (?,?, 'verified', ?, ?, ?, ?)", (record_id, kind, str(path), checksum, now, now))
            self.rotate()
            return BackupRecord(record_id, kind, str(path), checksum, now, now, counts)
        finally:
            shutil.rmtree(staging, ignore_errors=True)

    # -- verification and retention ----------------------------------------------------------------

    def verify(self, path: str | Path) -> VerifyResult:
        path = Path(path)
        if not path.is_file():
            return VerifyResult(False, "backup file is missing")
        try:
            with zipfile.ZipFile(path) as archive:
                manifest = json.loads(archive.read("manifest.json"))
                if manifest.get("schema") != BACKUP_SCHEMA:
                    return VerifyResult(False, "unsupported backup format")
                for entry in manifest["inventory"]:
                    data = archive.read(entry["path"])
                    if hashlib.sha256(data).hexdigest() != entry["sha256"]:
                        return VerifyResult(False, f"checksum mismatch for {entry['path']}")
        except (zipfile.BadZipFile, KeyError, ValueError) as exc:
            return VerifyResult(False, f"unreadable backup ({type(exc).__name__})")
        return VerifyResult(True, None, manifest)

    def list_backups(self, *, kind: str | None = None) -> list[BackupRecord]:
        query = "SELECT * FROM backup_records WHERE state = 'verified'"
        args: tuple = ()
        if kind:
            query += " AND kind = ?"
            args = (kind,)
        rows = self.conn.execute(query + " ORDER BY created_at DESC", args).fetchall()
        return [BackupRecord(r["id"], r["kind"], r["location"], r["checksum"], r["created_at"], r["verified_at"])
                for r in rows]

    def rotate(self) -> int:
        """Keep the last verified backups; a prior verified backup is never removed before a new one verifies."""
        keep = DEFAULTS.backup.retain_verified
        removed = 0
        for record in self.list_backups()[keep:]:
            Path(record.path).unlink(missing_ok=True)
            with transaction(self.conn):
                self.conn.execute("UPDATE backup_records SET state = 'rotated' WHERE id = ?", (record.id,))
            removed += 1
        return removed

    # -- schedule and location ----------------------------------------------------------------------

    def due(self, *, kind: str = "library") -> bool:
        if kind != "library":
            return False        # Full Backup is manual by default (§33.8)
        latest = self.list_backups(kind="library")
        if not latest:
            return True
        last = datetime.fromisoformat(latest[0].created_at)
        return self.clock() - last >= DEFAULTS.backup.library_interval

    def location_warning(self, location: str | Path) -> dict:
        """A backup on the same physical disk does not protect against disk failure (§33.9)."""
        location = Path(location)
        location.mkdir(parents=True, exist_ok=True)
        roots = self.conn.execute("SELECT path FROM storage_roots").fetchall()
        try:
            device = os.stat(location).st_dev
        except OSError:
            return {"same_device_as_library": False, "message": ""}
        same = any(os.path.exists(r[0]) and os.stat(r[0]).st_dev == device for r in roots) or \
            os.stat(self.db_path).st_dev == device
        return {"same_device_as_library": same,
                "message": "A backup on the same physical disk does not protect against disk failure." if same else ""}
