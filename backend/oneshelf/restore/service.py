"""Restore from a OneShelf backup (Master §33.5–33.7).

Preflight first, then forward migration of the backup's database inside a staging copy (the backup file
is never modified). A newer backup is refused by an older application. Replace creates a lightweight
Safety Snapshot first. Merge is deterministic: current manual edits, mappings and settings win, missing
records are added, progress never regresses, healthy files are not replaced, and verified backup files
may repair missing or corrupt local files.
"""
from __future__ import annotations

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
from oneshelf.library.overrides import apply_all_overrides
from oneshelf.storage.paths import resolve_within
from oneshelf.storage.roots import get_root, check_availability, preflight as storage_preflight
from oneshelf.storage.hashing import sha256_file
from oneshelf.storage.safe_write import publish

READ_ORDER = {"unread": 0, "partial": 1, "read": 2}

# Restored in dependency order; storage roots are machine configuration and only added when missing.
RESTORE_TABLES = ("storage_roots", "works", "work_aliases", "source_listings", "source_tracks", "reading_units",
                  "assets", "shelf_entries", "follows", "follow_baselines", "follow_baseline_units", "release_events",
                  "work_mappings", "user_overrides", "settings", "imports", "download_history",
                  "reading_bookmarks", "reading_highlights",
                  # The person's own labels, collections and notes travel with the works they describe.
                  "tags", "work_tags", "collections", "collection_works", "work_notes")
DELETE_ORDER = ("work_tags", "collection_works", "work_notes", "tags", "collections",
                "reading_bookmarks", "reading_highlights", "reading_state", "release_events", "follow_baseline_units", "follow_baselines", "follows",
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
        if not preflight.ok:
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
                with archive.open("library.db") as source, staged.open("wb") as target:
                    shutil.copyfileobj(source, target, length=1024 * 1024)
                migrate(staged, MIGRATIONS, snapshot_dir=Path(workspace) / "snapshots")  # forward migration in staging
                if mode == "replace":
                    record = self.backups.create("library")
                    report.safety_snapshot = record.path
                    self._replace(staged)
                    asset_ids = {}
                else:
                    asset_ids = self._merge(staged, report)
                report.repaired_files = self._restore_content(archive, manifest, replace_all=(mode == "replace"),
                                                              report=report, asset_ids=asset_ids)
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
            row = dict(row)
            if table == "assets":
                # Backup metadata is not evidence that this machine has the corresponding file.
                row["integrity"] = "missing_local_file"
                try:
                    root = get_root(self.conn, row["storage_root_id"])
                    resolve_within(root.path, ".oneshelf/root.json")
                    target = resolve_within(root.path, row["relative_path"])
                    if check_availability(root).available and target.is_file() and sha256_file(target) == (
                            row["sha256"], row["size_bytes"]):
                        row["integrity"] = "ok"
                except (OSError, ValueError, RuntimeError):
                    pass
            columns = list(row.keys())
            placeholders = ",".join("?" * len(columns))
            verb = "INSERT OR IGNORE" if ignore else "INSERT"
            cursor = self.conn.execute(
                f"{verb} INTO {table} ({','.join(columns)}) VALUES ({placeholders})", tuple(row.values()))
            inserted += cursor.rowcount if cursor.rowcount > 0 else 0
        return inserted

    def _replace(self, staged: Path) -> None:
        with transaction(self.conn):
            for table in DELETE_ORDER:
                self.conn.execute(f"DELETE FROM {table}")
            for table in RESTORE_TABLES:
                self._insert(table, self._rows(staged, table))
            self._insert("reading_state", self._rows(staged, "reading_state"))

    def _merge(self, staged: Path, report: RestoreReport) -> dict[str, str]:
        ids: dict[str, dict[str, str]] = {table: {} for table in
                                            ("source_listings", "source_tracks", "reading_units", "assets",
                                             "follows", "follow_baselines", "tags")}
        skipped: dict[str, set[str]] = {"follows": set(), "follow_baselines": set()}
        with transaction(self.conn):
            for table in RESTORE_TABLES:
                added = kept = 0
                for saved in self._rows(staged, table):
                    row = dict(saved)
                    old_id = row.get("id")
                    if table == "source_listings":
                        existing = self.conn.execute(
                            "SELECT id FROM source_listings WHERE source_id = ? AND source_listing_key = ?",
                            (row["source_id"], row["source_listing_key"])).fetchone()
                    else:
                        existing = None
                    if table == "source_tracks":
                        if row["listing_id"] is not None:
                            row["listing_id"] = ids["source_listings"].get(row["listing_id"], row["listing_id"])
                            listing = self.conn.execute("SELECT work_id FROM source_listings WHERE id = ?",
                                                        (row["listing_id"],)).fetchone()
                            if listing is not None and listing["work_id"] is not None:
                                row["work_id"] = listing["work_id"]
                                existing = self.conn.execute(
                                    "SELECT id FROM source_tracks WHERE listing_id = ? AND language = ?",
                                    (row["listing_id"], row["language"])).fetchone()
                            else:
                                row["listing_id"], row["availability"] = None, "unavailable"
                        if row["kind"] == "local":
                            existing = self.conn.execute(
                                "SELECT id FROM source_tracks WHERE kind = 'local' AND work_id = ? AND language = ?",
                                (row["work_id"], row["language"])).fetchone()
                    elif table == "reading_units":
                        row["track_id"] = ids["source_tracks"].get(row["track_id"], row["track_id"])
                        existing = self.conn.execute(
                            "SELECT id FROM reading_units WHERE track_id = ? AND source_unit_key = ?",
                            (row["track_id"], row["source_unit_key"])).fetchone()
                    elif table == "assets":
                        row["reading_unit_id"] = ids["reading_units"].get(row["reading_unit_id"], row["reading_unit_id"])
                        existing = self.conn.execute(
                            "SELECT id FROM assets WHERE reading_unit_id = ? AND format = ? AND variant = ?",
                            (row["reading_unit_id"], row["format"], row["variant"])).fetchone()
                    elif table == "follows":
                        row["track_id"] = ids["source_tracks"].get(row["track_id"], row["track_id"])
                        track = self.conn.execute("SELECT work_id, language, source_id FROM source_tracks WHERE id = ?",
                                                  (row["track_id"],)).fetchone()
                        if track is None or (track["work_id"], track["language"], track["source_id"]) != (
                                row["work_id"], row["language"], row["preferred_source_id"]):
                            skipped["follows"].add(old_id)
                            kept += 1
                            continue
                        existing = self.conn.execute("SELECT id FROM follows WHERE work_id = ? AND language = ?",
                                                     (row["work_id"], row["language"])).fetchone()
                    elif table == "follow_baselines":
                        if row["follow_id"] in skipped["follows"]:
                            skipped["follow_baselines"].add(old_id)
                            kept += 1
                            continue
                        row["follow_id"] = ids["follows"].get(row["follow_id"], row["follow_id"])
                        row["track_id"] = ids["source_tracks"].get(row["track_id"], row["track_id"])
                        owner = self.conn.execute(
                            "SELECT f.work_id, f.language FROM follows f WHERE f.id = ?", (row["follow_id"],)
                        ).fetchone()
                        track = self.conn.execute("SELECT work_id, language FROM source_tracks WHERE id = ?",
                                                  (row["track_id"],)).fetchone()
                        if owner is None or track is None or tuple(owner) != tuple(track):
                            skipped["follow_baselines"].add(old_id)
                            kept += 1
                            continue
                    elif table == "follow_baseline_units":
                        if row["baseline_id"] in skipped["follow_baselines"]:
                            kept += 1
                            continue
                        row["baseline_id"] = ids["follow_baselines"].get(row["baseline_id"], row["baseline_id"])
                    elif table == "release_events":
                        if row["follow_id"] in skipped["follows"]:
                            kept += 1
                            continue
                        row["follow_id"] = ids["follows"].get(row["follow_id"], row["follow_id"])
                        row["track_id"] = ids["source_tracks"].get(row["track_id"], row["track_id"])
                        owner = self.conn.execute(
                            "SELECT work_id, language FROM follows WHERE id = ?", (row["follow_id"],)
                        ).fetchone()
                        track = self.conn.execute("SELECT work_id, language FROM source_tracks WHERE id = ?",
                                                  (row["track_id"],)).fetchone()
                        if owner is None or track is None or tuple(owner) != tuple(track):
                            kept += 1
                            continue
                        if row["reading_unit_id"] is not None:
                            row["reading_unit_id"] = ids["reading_units"].get(row["reading_unit_id"], row["reading_unit_id"])
                    elif table == "work_mappings":
                        if row["listing_id"] is not None:
                            row["listing_id"] = ids["source_listings"].get(row["listing_id"], row["listing_id"])
                            listing = self.conn.execute("SELECT work_id FROM source_listings WHERE id = ?",
                                                        (row["listing_id"],)).fetchone()
                            # A backup's old exclusion must not undo the current library's mapping.
                            if (listing is not None and row["kind"] in ("never_match", "split", "unlink")
                                    and listing["work_id"] == row["work_id"]):
                                kept += 1
                                continue
                        existing = self.conn.execute(
                            "SELECT id FROM work_mappings WHERE kind = ? AND listing_id IS ?"
                            " AND work_id IS ? AND other_work_id IS ?",
                            (row["kind"], row["listing_id"], row["work_id"], row["other_work_id"])
                        ).fetchone()
                    elif table == "user_overrides":
                        target = {"listing": "source_listings", "track": "source_tracks",
                                  "reading_unit": "reading_units"}.get(row["target_kind"])
                        if target:
                            row["target_id"] = ids[target].get(row["target_id"], row["target_id"])
                    elif table == "imports" and row["asset_id"] is not None:
                        row["asset_id"] = ids["assets"].get(row["asset_id"], row["asset_id"])
                    elif table == "download_history":
                        row["reading_unit_id"] = ids["reading_units"].get(row["reading_unit_id"], row["reading_unit_id"])
                    elif table in ("reading_bookmarks", "reading_highlights"):
                        row["reading_unit_id"] = ids["reading_units"].get(row["reading_unit_id"], row["reading_unit_id"])
                    elif table == "tags":
                        # Tag names are unique regardless of case: the current library's tag is the one kept.
                        existing = self.conn.execute("SELECT id FROM tags WHERE name = ? COLLATE NOCASE",
                                                     (row["name"],)).fetchone()
                    elif table in ("work_tags", "collection_works", "work_notes"):
                        if table == "work_tags":
                            row["tag_id"] = ids["tags"].get(row["tag_id"], row["tag_id"])
                        if self.conn.execute("SELECT 1 FROM works WHERE id = ?", (row["work_id"],)).fetchone() is None:
                            kept += 1
                            continue
                        if table == "work_notes":
                            # A note written since the backup is a current decision, and it stays.
                            existing = self.conn.execute("SELECT work_id AS id FROM work_notes WHERE work_id = ?",
                                                         (row["work_id"],)).fetchone()
                    if existing is not None:
                        kept += 1
                        if old_id is not None and table in ids:
                            ids[table][old_id] = existing["id"]
                        continue
                    inserted = self._insert(table, [row])
                    added += inserted
                    kept += 1 - inserted
                    if old_id is not None and table in ids:
                        ids[table][old_id] = row["id"]
                if added:
                    report.added[table] = added
                if kept:
                    report.kept[table] = kept
            self._merge_progress(staged, report, ids["reading_units"])
            # A correction added from the backup must also show where readers look (INV-04, I-102).
            apply_all_overrides(self.conn)
        return ids["assets"]

    def _merge_progress(self, staged: Path, report: RestoreReport, unit_ids: dict[str, str]) -> None:
        for saved in self._rows(staged, "reading_state"):
            row = dict(saved)
            row["reading_unit_id"] = unit_ids.get(row["reading_unit_id"], row["reading_unit_id"])
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

    def _restore_content(self, archive: zipfile.ZipFile, manifest: dict, *, replace_all: bool,
                         report: RestoreReport, asset_ids: dict[str, str] | None = None) -> int:
        repaired = 0
        for entry in manifest.get("content", []):
            asset_id = (asset_ids or {}).get(entry["asset_id"], entry["asset_id"])
            asset = self.conn.execute("SELECT * FROM assets WHERE id = ?", (asset_id,)).fetchone()
            if asset is None:
                report.issues.append(f"{entry['asset_id']}: asset record is unavailable")
                continue
            try:
                root = get_root(self.conn, asset["storage_root_id"])
                resolve_within(root.path, ".oneshelf/root.json")
                if not check_availability(root).available:
                    raise RestoreError("storage location unavailable; reconnect or remap it before restoring content")
                target = resolve_within(root.path, asset["relative_path"])
                healthy = target.is_file() and asset["integrity"] == "ok"
                if healthy and not replace_all:
                    continue
                # Persist an honest state before any fallible write, including process interruption.
                with transaction(self.conn):
                    self.conn.execute("UPDATE assets SET integrity = ?, updated_at = ? WHERE id = ?",
                                      ("corrupt" if target.exists() else "missing_local_file", utcnow_iso(), asset["id"]))
                usage = shutil.disk_usage(root.path)
                if not storage_preflight(total=usage.total, free=usage.free, expected_bytes=entry["size"],
                                         override=root.reserve_override_bytes).allowed:
                    raise RestoreError("not enough free space in storage location")
                staging = resolve_within(root.path, ".oneshelf/staging")
                with tempfile.TemporaryDirectory(prefix="restore-", dir=staging) as workspace:
                    staged = Path(workspace) / "content"
                    with archive.open(entry["path"]) as source, staged.open("wb") as target_file:
                        shutil.copyfileobj(source, target_file, length=1024 * 1024)
                    if sha256_file(staged) != (entry["sha256"], entry["size"]):
                        raise RestoreError("staged content failed verification")
                    resolve_within(root.path, ".oneshelf/root.json")
                    if not check_availability(root).available:
                        raise RestoreError("storage location became unavailable")
                    # Replacement is limited to the recorded corrupt file (or explicit Replace mode).
                    publish(root.path, staged, target, replace=target.exists())
                    if sha256_file(target) != (entry["sha256"], entry["size"]):
                        raise RestoreError("restored content failed verification")
                with transaction(self.conn):
                    self.conn.execute("UPDATE assets SET integrity = 'ok', sha256 = ?, size_bytes = ?, updated_at = ?"
                                      " WHERE id = ?", (entry["sha256"], entry["size"], utcnow_iso(), asset_id))
                repaired += 1
            except (OSError, ValueError, RuntimeError, KeyError, zipfile.BadZipFile) as exc:
                report.issues.append(f"{entry['asset_id']}: {exc}")
        return repaired
