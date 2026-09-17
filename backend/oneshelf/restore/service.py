"""Restore from a OneShelf backup (Master §33.5–33.7).

Preflight first, then forward migration of the backup's database inside a staging copy (the backup file
is never modified). A newer backup is refused by an older application. Replace creates a lightweight
Safety Snapshot first. Merge is deterministic: current manual edits, mappings and settings win, missing
records are added, progress never regresses, healthy files are not replaced, and verified backup files
may repair missing or corrupt local files.
"""
from __future__ import annotations

import hashlib
import json
import shutil
import sqlite3
import tempfile
import zipfile
from contextlib import closing
from dataclasses import dataclass, field
from pathlib import Path

from oneshelf.backup.service import BackupService
from oneshelf.db.connection import transaction
from oneshelf.db.migrate import migrate
from oneshelf.db.schema import MIGRATIONS
from oneshelf.domain.clock import utcnow_iso
from oneshelf.storage.paths import resolve_within
from oneshelf.storage.roots import get_root

READ_ORDER = {"unread": 0, "partial": 1, "read": 2}

# Restored in dependency order; storage roots are machine configuration and only added when missing.
RESTORE_TABLES = ("storage_roots", "works", "work_aliases", "source_listings", "source_tracks", "reading_units",
                  "assets", "shelf_entries", "follows", "follow_baselines", "follow_baseline_units", "release_events",
                  "work_mappings", "user_overrides", "settings", "imports", "download_history")
DELETE_ORDER = ("reading_state", "release_events", "follow_baseline_units", "follow_baselines", "follows",
                "shelf_entries", "assets", "reading_units", "source_tracks", "source_listings", "work_aliases",
                "work_mappings", "user_overrides", "settings", "imports", "download_history", "works")


class RestoreError(RuntimeError):
    pass


class RestoreBlocked(RestoreError):
    """Restore needs an explicit decision (new plugin permissions, replacements)."""


@dataclass(frozen=True)
class PluginRequirement:
    id: str
    version: str
    installed: bool
    installed_version: str | None
    new_permissions: list[str] = field(default_factory=list)


@dataclass
class Preflight:
    ok: bool
    compatible: bool
    kind: str
    schema_version: int
    counts: dict
    plugins: list[PluginRequirement]
    space_needed: int
    issues: list[str] = field(default_factory=list)


@dataclass
class RestoreReport:
    mode: str
    added: dict = field(default_factory=dict)
    kept: dict = field(default_factory=dict)
    repaired_files: int = 0
    safety_snapshot: str | None = None
    plugins_missing: list[str] = field(default_factory=list)
    issues: list[str] = field(default_factory=list)


class RestoreService:
    def __init__(self, conn: sqlite3.Connection, db_path: str | Path, *, backups: BackupService) -> None:
        self.conn = conn
        self.db_path = Path(db_path)
        self.backups = backups

    # -- preflight --------------------------------------------------------------------------------

    def _manifest(self, path: str | Path) -> dict:
        result = self.backups.verify(path)
        if not result.ok:
            raise RestoreError(f"backup cannot be restored: {result.reason}")
        return result.manifest

    def _plugin_requirements(self, manifest: dict) -> list[PluginRequirement]:
        requirements = []
        for entry in manifest.get("plugins", []):
            row = self.conn.execute(
                "SELECT p.active_version, v.approved_permissions_json FROM plugins p"
                " LEFT JOIN plugin_versions v ON v.plugin_id = p.id AND v.version = p.active_version"
                " WHERE p.id = ?", (entry["id"],)).fetchone()
            approved = set(json.loads(row["approved_permissions_json"] or "[]")) if row else set()
            new_permissions = sorted(set(entry.get("permissions", [])) - approved) if row else []
            requirements.append(PluginRequirement(entry["id"], entry["version"], row is not None,
                                                  row["active_version"] if row else None, new_permissions))
        return requirements

    def preflight(self, path: str | Path) -> Preflight:
        manifest = self._manifest(path)
        schema_version = int(manifest.get("schema_version", 0))
        compatible = schema_version <= len(MIGRATIONS)
        issues = [] if compatible else [
            "this backup was made by a newer OneShelf version; update OneShelf before restoring"]
        space = sum(entry["size"] for entry in manifest["inventory"])
        free = shutil.disk_usage(self.db_path.parent).free
        if free < space * 2:
            issues.append("not enough free space to restore this backup safely")
        return Preflight(ok=not issues, compatible=compatible, kind=manifest["kind"], schema_version=schema_version,
                         counts=manifest.get("counts", {}), plugins=self._plugin_requirements(manifest),
                         space_needed=space, issues=issues)

    # -- restore ----------------------------------------------------------------------------------

    def restore(self, path: str | Path, *, mode: str = "merge", approve_new_permissions: bool = False) -> RestoreReport:
        if mode not in ("merge", "replace"):
            raise RestoreError("restore mode must be 'merge' or 'replace'")
        preflight = self.preflight(path)
        if not preflight.compatible:
            raise RestoreError(preflight.issues[0])
        pending = [p for p in preflight.plugins if p.installed and p.new_permissions]
        if pending and not approve_new_permissions:
            raise RestoreBlocked("this backup needs approval for new plugin permissions: "
                                 + ", ".join(sorted(x for p in pending for x in p.new_permissions)))
        manifest = self._manifest(path)
        report = RestoreReport(mode=mode,
                               plugins_missing=[p.id for p in preflight.plugins if not p.installed])
        with tempfile.TemporaryDirectory() as workspace:
            staged = Path(workspace) / "library.db"
            with zipfile.ZipFile(path) as archive:
                staged.write_bytes(archive.read("library.db"))
                migrate(staged, MIGRATIONS, snapshot_dir=Path(workspace) / "snapshots")  # forward migration in staging
                if mode == "replace":
                    record = self.backups.create("library")
                    report.safety_snapshot = record.path
                    self._replace(staged)
                else:
                    self._merge(staged, report)
                report.repaired_files = self._restore_content(archive, manifest, replace_all=(mode == "replace"))
        return report

    # -- table handling ---------------------------------------------------------------------------

    @staticmethod
    def _rows(staged: Path, table: str) -> list[sqlite3.Row]:
        with closing(sqlite3.connect(staged)) as conn:
            conn.row_factory = sqlite3.Row
            exists = conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name = ?", (table,)).fetchone()
            return conn.execute(f"SELECT * FROM {table}").fetchall() if exists else []

    def _insert(self, table: str, rows: list[sqlite3.Row], *, ignore: bool = True) -> int:
        inserted = 0
        for row in rows:
            columns = list(row.keys())
            placeholders = ",".join("?" * len(columns))
            verb = "INSERT OR IGNORE" if ignore else "INSERT"
            cursor = self.conn.execute(
                f"{verb} INTO {table} ({','.join(columns)}) VALUES ({placeholders})", tuple(row))
            inserted += cursor.rowcount if cursor.rowcount > 0 else 0
        return inserted

    def _replace(self, staged: Path) -> None:
        with transaction(self.conn):
            for table in DELETE_ORDER:
                self.conn.execute(f"DELETE FROM {table}")
            for table in RESTORE_TABLES:
                self._insert(table, self._rows(staged, table))
            self._insert("reading_state", self._rows(staged, "reading_state"))

    def _merge(self, staged: Path, report: RestoreReport) -> None:
        with transaction(self.conn):
            for table in RESTORE_TABLES:
                rows = self._rows(staged, table)
                added = self._insert(table, rows)     # current rows always win; only missing ones are added
                if added:
                    report.added[table] = added
                kept = len(rows) - added
                if kept:
                    report.kept[table] = kept
            self._merge_progress(staged, report)

    def _merge_progress(self, staged: Path, report: RestoreReport) -> None:
        for row in self._rows(staged, "reading_state"):
            current = self.conn.execute("SELECT * FROM reading_state WHERE reading_unit_id = ?",
                                        (row["reading_unit_id"],)).fetchone()
            if current is None:
                self._insert("reading_state", [row])
                report.added["reading_state"] = report.added.get("reading_state", 0) + 1
                continue
            backup_fraction = row["fraction"] or 0.0
            current_fraction = current["fraction"] or 0.0
            further = (READ_ORDER.get(row["read_state"], 0), backup_fraction) > \
                      (READ_ORDER.get(current["read_state"], 0), current_fraction)
            if further:   # progress never regresses (§33.7)
                self.conn.execute(
                    "UPDATE reading_state SET read_state = ?, fraction = ?, locator_json = ?, revision = ?,"
                    " updated_at = ? WHERE reading_unit_id = ?",
                    (row["read_state"], row["fraction"], row["locator_json"], current["revision"] + 1, utcnow_iso(),
                     row["reading_unit_id"]))
                report.added["reading_state_advanced"] = report.added.get("reading_state_advanced", 0) + 1
            else:
                report.kept["reading_state"] = report.kept.get("reading_state", 0) + 1

    # -- content ----------------------------------------------------------------------------------

    def _restore_content(self, archive: zipfile.ZipFile, manifest: dict, *, replace_all: bool) -> int:
        repaired = 0
        for entry in manifest.get("content", []):
            asset = self.conn.execute("SELECT * FROM assets WHERE id = ?", (entry["asset_id"],)).fetchone()
            if asset is None:
                continue
            try:
                root = get_root(self.conn, asset["storage_root_id"])
                target = resolve_within(root.path, asset["relative_path"])
            except Exception:
                continue
            healthy = target.is_file() and asset["integrity"] == "ok"
            if healthy and not replace_all:
                continue            # a healthy local file is never replaced without reason (§33.7)
            payload = archive.read(entry["path"])
            if hashlib.sha256(payload).hexdigest() != entry["sha256"]:
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(payload)
            with transaction(self.conn):
                self.conn.execute("UPDATE assets SET integrity = 'ok', sha256 = ?, size_bytes = ?, updated_at = ?"
                                  " WHERE id = ?", (entry["sha256"], entry["size"], utcnow_iso(), entry["asset_id"]))
            repaired += 1
        return repaired
