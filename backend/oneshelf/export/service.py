"""Export: a persistent, resumable, one-way portable copy (Master §34; INV-20, INV-21).

Export never modifies the library, prefers local originals and never converts formats. Missing content
offers exactly the Master's three choices, and Download Missing Then Export requires an explicit notice
that those items will be permanently downloaded into the library first.
"""
from __future__ import annotations

import hashlib
import json
import shutil
import sqlite3
import tempfile
import zipfile
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from pathlib import Path

from oneshelf.db.connection import transaction
from oneshelf.domain.ids import new_id
from oneshelf.search.grouping import SEQUENTIAL_FAMILY
from oneshelf.settings.defaults import DEFAULTS
from oneshelf.storage.paths import resolve_within, safe_component
from oneshelf.storage.roots import get_root, preflight
from oneshelf.storage.hashing import sha256_file
from oneshelf.storage.safe_write import destination_path, publish

CHOICES = ["export_downloaded_only", "download_missing_then_export", "cancel"]
DISCLOSURE = "This will also permanently download these items into your OneShelf library before exporting them."
METADATA_NAME = "oneshelf-export.json"


class ExportError(RuntimeError):
    pass


class ExportBlocked(ExportError):
    """An explicit user decision is required (permanent downloads)."""


@dataclass(frozen=True)
class ExportContract:
    work_id: str
    language: str
    source_id: str
    unit_ids: list[str]
    destination: str
    formats: list[str] | None = None
    output: str = "folder"
    conflict: str = "skip_identical"
    include_metadata: bool = True


@dataclass(frozen=True)
class PlannedFile:
    asset_id: str
    reading_unit_id: str
    source_root_id: str
    source_relative_path: str
    target_path: str
    sha256: str
    size: int


@dataclass
class ExportPlan:
    """One job may cover several selected works; each keeps its own contract, so nothing is mixed (§34.1)."""
    contracts: list[ExportContract]
    files: list[PlannedFile]
    missing_units: list[str]
    total_bytes: int
    choices: list[str] = field(default_factory=lambda: list(CHOICES))

    @property
    def contract(self) -> ExportContract:
        return self.contracts[0]


@dataclass
class ExportReport:
    job_id: str
    state: str
    copied: int = 0
    skipped: int = 0
    failed: int = 0
    errors: list[str] = field(default_factory=list)


def _preferred_formats(rows: list[sqlite3.Row], content_type: str | None) -> list[sqlite3.Row]:
    """§34.4: CBZ is the default for sequential content; books export in the format they already are.

    Only the choice of which existing file to copy changes — nothing is ever converted.
    """
    if content_type in SEQUENTIAL_FAMILY:
        preferred = [r for r in rows if r["format"] == "cbz"]
        return preferred or rows
    return rows


class ExportService:
    def __init__(self, conn: sqlite3.Connection, *, downloads=None, fault=None,
                 clock: Callable[[], datetime] = lambda: datetime.now(UTC)) -> None:
        self.conn = conn
        self.downloads = downloads
        self.fault = fault or (lambda _point: None)
        self.clock = clock

    # -- planning ---------------------------------------------------------------------------------

    def _work(self, work_id: str) -> sqlite3.Row:
        row = self.conn.execute("SELECT * FROM works WHERE id = ?", (work_id,)).fetchone()
        if row is None:
            raise ExportError("unknown work")
        return row

    def _target_directory(self, contract: ExportContract, work: sqlite3.Row) -> Path:
        base = Path(contract.destination)
        return base / f"{safe_component(work['display_title'])} ({safe_component(contract.language, max_bytes=35)})"

    def plan(self, contract: ExportContract) -> ExportPlan:
        return self.plan_selection([contract])

    def plan_selection(self, contracts: list[ExportContract]) -> ExportPlan:
        if not contracts:
            raise ExportError("nothing selected to export")
        first = contracts[0]
        if any((c.destination, c.output, c.conflict) != (first.destination, first.output, first.conflict)
               for c in contracts):
            raise ExportError("one export job uses one destination, output and conflict policy")
        if first.output not in ("folder", "zip"):
            raise ExportError("output must be 'folder' or 'zip'")
        if first.conflict not in ("skip_identical", "replace", "keep_both"):
            raise ExportError("unknown conflict policy")
        destination = Path(first.destination)
        if not destination.is_dir():
            raise ExportError("destination folder does not exist")
        probe = destination / f".oneshelf-write-test-{new_id()[:6]}"
        try:
            probe.write_bytes(b"")
            probe.unlink()
        except OSError as exc:
            raise ExportError("destination is not writable") from exc

        files: list[PlannedFile] = []
        missing: list[str] = []
        for contract in contracts:
            self._plan_one(contract, files, missing)
        # Give different works distinct directories even when their titles sanitize to the same name.
        owners: dict[Path, str] = {}
        for contract in contracts:
            folder = self._target_directory(contract, self._work(contract.work_id))
            if folder in owners and owners[folder] != contract.work_id:
                unique = folder.with_name(f"{folder.name} ({contract.work_id})")
                files = [replace(f, target_path=str(unique / Path(f.target_path).name))
                         if f.reading_unit_id in contract.unit_ids else f for f in files]
            else:
                owners[folder] = contract.work_id
        # Distinct units may share a title, or sanitize to the same filename.
        counts = Counter(file.target_path for file in files)
        used = {file.target_path for file in files}
        for index in sorted(range(len(files)), key=lambda i: (files[i].target_path, files[i].reading_unit_id,
                                                               files[i].asset_id)):
            file = files[index]
            if counts[file.target_path] == 1:
                continue
            original = Path(file.target_path)
            suffix = f" (unit {file.reading_unit_id})"
            candidate = original.with_name(f"{original.stem}{suffix}{original.suffix}")
            if str(candidate) in used:
                candidate = original.with_name(f"{original.stem}{suffix} ({file.asset_id}){original.suffix}")
            if str(candidate) in used:
                raise ExportError("selected files cannot be given distinct names")
            used.add(str(candidate))
            files[index] = replace(file, target_path=str(candidate))
        total = sum(f.size for f in files)
        usage = shutil.disk_usage(destination)
        if not preflight(total=usage.total, free=usage.free, expected_bytes=total).allowed:
            raise ExportError("destination does not have enough free space")
        return ExportPlan(contracts, files, missing, total)

    def _plan_one(self, contract: ExportContract, files: list[PlannedFile], missing: list[str]) -> None:
        work = self._work(contract.work_id)
        target_dir = self._target_directory(contract, work)
        for unit_id in contract.unit_ids:
            unit = self.conn.execute(
                "SELECT u.* FROM reading_units u JOIN source_tracks t ON t.id = u.track_id"
                " WHERE u.id = ? AND t.work_id = ? AND t.source_id = ? AND t.language = ?",
                (unit_id, contract.work_id, contract.source_id, contract.language)).fetchone()
            if unit is None:
                raise ExportError("reading unit does not belong to the selected work, source and language")
            rows = self.conn.execute(
                "SELECT a.* FROM assets a JOIN reading_units u ON u.id = a.reading_unit_id"
                " JOIN source_tracks t ON t.id = u.track_id WHERE a.reading_unit_id = ? AND t.source_id = ?"
                " AND t.language = ? AND a.integrity = 'ok'",
                (unit_id, contract.source_id, contract.language)).fetchall()
            if contract.formats:
                rows = [r for r in rows if r["format"] in contract.formats]   # never converted (§34.4)
            else:
                rows = _preferred_formats(rows, work["content_type"])
            if not rows:
                missing.append(unit_id)
                continue
            unit = self.conn.execute("SELECT display_title, raw_title, source_unit_key FROM reading_units WHERE id = ?",
                                     (unit_id,)).fetchone()
            label = unit["display_title"] or unit["raw_title"] or unit["source_unit_key"]
            for asset in rows:
                name = f"{safe_component(label)}.{asset['format']}"
                files.append(PlannedFile(asset["id"], unit_id, asset["storage_root_id"], asset["relative_path"],
                                         str(target_dir / name), asset["sha256"], asset["size_bytes"]))

    def disclosure(self, plan: ExportPlan) -> dict:
        return {"message": DISCLOSURE, "units": plan.missing_units, "choices": plan.choices}

    # -- job lifecycle ----------------------------------------------------------------------------

    def start(self, plan: ExportPlan, *, missing_policy: str = "export_downloaded_only",
              acknowledge_permanent_download: bool = False) -> str:
        if missing_policy not in CHOICES:
            raise ExportError("unknown missing-content choice")
        if missing_policy == "cancel":
            raise ExportError("export cancelled")
        if missing_policy == "download_missing_then_export" and plan.missing_units and not acknowledge_permanent_download:
            raise ExportBlocked(DISCLOSURE)   # INV-21
        job_id, now = new_id(), self.clock().isoformat()
        with transaction(self.conn):
            self.conn.execute(
                "INSERT INTO export_jobs (id, state, contract_json, destination, output, conflict_policy,"
                " missing_policy, created_at, updated_at) VALUES (?, 'queued', ?, ?, ?, ?, ?, ?, ?)",
                (job_id, json.dumps([c.__dict__ for c in plan.contracts]), plan.contract.destination,
                 plan.contract.output, plan.contract.conflict, missing_policy, now, now))
            for file in plan.files:
                self.conn.execute(
                    "INSERT INTO export_items (job_id, asset_id, reading_unit_id, source_root_id,"
                    " source_relative_path, target_path, sha256, size, state) VALUES (?,?,?,?,?,?,?,?, 'pending')",
                    (job_id, file.asset_id, file.reading_unit_id, file.source_root_id, file.source_relative_path,
                     file.target_path, file.sha256, file.size))
        return job_id

    def job(self, job_id: str) -> sqlite3.Row:
        row = self.conn.execute("SELECT * FROM export_jobs WHERE id = ?", (job_id,)).fetchone()
        if row is None:
            raise ExportError("unknown export job")
        return row

    def retry_failed(self, job_id: str) -> int:
        with transaction(self.conn):
            cursor = self.conn.execute("UPDATE export_items SET state = 'pending', error = NULL"
                                       " WHERE job_id = ? AND state = 'failed'", (job_id,))
            self.conn.execute("UPDATE export_jobs SET state = 'queued', failed = 0, updated_at = ? WHERE id = ?",
                              (self.clock().isoformat(), job_id))
        return cursor.rowcount

    # -- execution --------------------------------------------------------------------------------

    async def run(self, job_id: str) -> ExportReport:
        job = self.job(job_id)
        contracts = [ExportContract(**c) for c in json.loads(job["contract_json"])]
        contract = contracts[0]
        report = ExportReport(job_id, "running")
        missing_units: set[str] = set()
        with transaction(self.conn):
            self.conn.execute("UPDATE export_jobs SET state = 'running', updated_at = ? WHERE id = ?",
                              (self.clock().isoformat(), job_id))
        if job["missing_policy"] == "download_missing_then_export":
            refreshed = self.plan_selection(contracts)
            missing_units = set(refreshed.missing_units)
            with transaction(self.conn):
                for file in refreshed.files:
                    self.conn.execute(
                        "INSERT OR IGNORE INTO export_items (job_id, asset_id, reading_unit_id, source_root_id,"
                        " source_relative_path, target_path, sha256, size, state) VALUES (?,?,?,?,?,?,?,?, 'pending')",
                        (job_id, file.asset_id, file.reading_unit_id, file.source_root_id, file.source_relative_path,
                         file.target_path, file.sha256, file.size))
            for unit_id in refreshed.missing_units:
                report.errors.append(f"{unit_id}: content must finish downloading before it can be exported")
            report.failed += len(refreshed.missing_units)
        items = self.conn.execute("SELECT * FROM export_items WHERE job_id = ? AND state = 'pending'"
                                  " ORDER BY target_path", (job_id,)).fetchall()
        for item in items if contract.output == "folder" else []:
            try:
                outcome = self._copy_item(item, contract)
            except (OSError, ValueError) as exc:
                self._item_state(job_id, item["asset_id"], "failed", str(exc))
                report.failed += 1
                report.errors.append(f"{item['target_path']}: {exc}")
                continue
            self._item_state(job_id, item["asset_id"], outcome)
            if outcome == "copied":
                report.copied += 1
                self.fault("file_copied")
            else:
                report.skipped += 1
        for each in contracts:
            try:
                if each.output == "zip":
                    if missing_units.intersection(each.unit_ids):
                        continue
                    self._package_zip(job_id, each, report)
                elif each.include_metadata:
                    self._write_metadata(job_id, each)
            except (OSError, ValueError, zipfile.BadZipFile) as exc:
                report.failed += 1
                report.errors.append(f"{each.work_id}: {exc}")
        remaining_failures = self.conn.execute(
            "SELECT count(*) FROM export_items WHERE job_id = ? AND state = 'failed'", (job_id,)).fetchone()[0]
        state = "completed_with_issues" if remaining_failures or report.failed else "completed"
        totals = self.conn.execute(
            "SELECT sum(state = 'copied') AS copied, sum(state = 'skipped') AS skipped FROM export_items"
            " WHERE job_id = ?", (job_id,)).fetchone()
        with transaction(self.conn):
            self.conn.execute("UPDATE export_jobs SET state = ?, copied = ?, skipped = ?, failed = ?, finished_at = ?,"
                              " updated_at = ? WHERE id = ?",
                              (state, totals["copied"] or 0, totals["skipped"] or 0,
                               max(remaining_failures, report.failed), self.clock().isoformat(),
                               self.clock().isoformat(), job_id))
        report.state = state
        return report

    def _item_state(self, job_id: str, asset_id: str, state: str, error: str | None = None) -> None:
        with transaction(self.conn):
            self.conn.execute("UPDATE export_items SET state = ?, error = ? WHERE job_id = ? AND asset_id = ?",
                              (state, error, job_id, asset_id))

    def _copy_item(self, item: sqlite3.Row, contract: ExportContract) -> str:
        root = get_root(self.conn, item["source_root_id"])
        source = resolve_within(root.path, item["source_relative_path"])
        if not source.is_file():
            raise OSError("local file is missing")
        target = destination_path(contract.destination, item["target_path"])
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists():
            if contract.conflict == "skip_identical":
                if hashlib.sha256(target.read_bytes()).hexdigest() == item["sha256"]:
                    return "skipped"
                raise OSError("a different file already exists at the destination")
            if contract.conflict == "keep_both":
                index = 2
                while target.exists():
                    target = Path(item["target_path"])
                    target = target.with_name(f"{target.stem} ({index}){target.suffix}")
                    index += 1
        with tempfile.TemporaryDirectory(prefix=".oneshelf-export-", dir=contract.destination) as temporary:
            staged = Path(temporary) / "content"
            shutil.copyfile(source, staged)
            if sha256_file(staged) != (item["sha256"], item["size"]):
                raise OSError("copied file failed its checksum check")
            publish(contract.destination, staged, target, replace=contract.conflict == "replace")
        with transaction(self.conn):
            self.conn.execute("UPDATE export_items SET target_path = ? WHERE job_id = ? AND asset_id = ?",
                              (str(target), item["job_id"], item["asset_id"]))
        return "copied"

    def _metadata(self, job_id: str, contract: ExportContract, *, pending: bool = False) -> dict:
        work = self._work(contract.work_id)
        aliases = [r[0] for r in self.conn.execute("SELECT title FROM work_aliases WHERE work_id = ?",
                                                   (contract.work_id,))]
        units = []
        for unit_id in contract.unit_ids:
            unit = self.conn.execute("SELECT display_title, raw_title, source_number FROM reading_units WHERE id = ?",
                                     (unit_id,)).fetchone()
            files = [{"name": Path(i["target_path"]).name, "sha256": i["sha256"], "size": i["size"]}
                     for i in self.conn.execute("SELECT * FROM export_items WHERE job_id = ? AND reading_unit_id = ?"
                                                " AND (state IN ('copied', 'skipped') OR (? AND state = 'pending'))",
                                                (job_id, unit_id, pending))]
            if files:
                units.append({"title": (unit["display_title"] or unit["raw_title"]) if unit else None,
                              "number": unit["source_number"] if unit else None, "files": files})
        return {"title": work["display_title"], "aliases": aliases, "language": contract.language,
                    "source": contract.source_id, "content_type": work["content_type"], "units": units,
                    "formats": sorted({Path(f["name"]).suffix.lstrip(".") for u in units for f in u["files"]}),
                    "exported_at": self.clock().isoformat()}
    def _job_directory(self, job_id: str, contract: ExportContract) -> Path:
        for row in self.conn.execute("SELECT reading_unit_id, target_path FROM export_items WHERE job_id = ?", (job_id,)):
            if row["reading_unit_id"] in contract.unit_ids:
                return Path(row["target_path"]).parent
        return self._target_directory(contract, self._work(contract.work_id))

    def _write_metadata(self, job_id: str, contract: ExportContract) -> None:
        metadata = self._metadata(job_id, contract)
        target = destination_path(contract.destination, self._job_directory(job_id, contract))
        target.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix=".oneshelf-export-", dir=contract.destination) as temporary:
            staged = Path(temporary) / "metadata"
            staged.write_text(json.dumps(metadata, indent=1, ensure_ascii=False), encoding="utf-8")
            publish(contract.destination, staged, target / METADATA_NAME, replace=True)

    def _package_zip(self, job_id: str, contract: ExportContract, report: ExportReport) -> None:
        folder = self._job_directory(job_id, contract)
        archive_path = destination_path(contract.destination, Path(contract.destination) / f"{folder.name}.zip")
        items = [row for row in self.conn.execute("SELECT * FROM export_items WHERE job_id = ?", (job_id,))
                 if row["reading_unit_id"] in contract.unit_ids and row["state"] != "failed"]
        if not items:
            return
        included = []
        with tempfile.TemporaryDirectory(prefix=".oneshelf-export-", dir=contract.destination) as temporary:
            staged = Path(temporary) / "archive.zip"
            with zipfile.ZipFile(staged, "w") as archive:
                for item in items:
                    try:
                        root = get_root(self.conn, item["source_root_id"])
                        source = resolve_within(root.path, item["source_relative_path"])
                        # Verify the exact bytes put in the archive, even if the original changes.
                        copy = Path(temporary) / item["asset_id"]
                        shutil.copyfile(source, copy)
                        if sha256_file(copy) != (item["sha256"], item["size"]):
                            raise OSError("local file failed its checksum check")
                        name = Path(item["target_path"]).name
                        archive.write(copy, name, compress_type=zipfile.ZIP_STORED
                                      if Path(name).suffix in (".cbz", ".zip", ".epub", ".png", ".jpg")
                                      else zipfile.ZIP_DEFLATED)
                        included.append(item)
                    except (OSError, ValueError) as exc:
                        self._item_state(job_id, item["asset_id"], "failed", str(exc))
                        report.failed += 1
                        report.errors.append(f"{item['target_path']}: {exc}")
                if contract.include_metadata:
                    archive.writestr(METADATA_NAME, json.dumps(self._metadata(job_id, contract, pending=True),
                                                              ensure_ascii=False, indent=1))
            if not included or len(included) != len(items):
                return
            outcome = "copied"
            if archive_path.exists():
                if contract.conflict == "keep_both":
                    original, index = archive_path, 2
                    while archive_path.exists():
                        archive_path = destination_path(contract.destination,
                            original.with_name(f"{original.stem} ({index}){original.suffix}"))
                        index += 1
                elif contract.conflict == "skip_identical":
                    # ZIP timestamps vary; compare member names and bytes, not container bytes.
                    with zipfile.ZipFile(archive_path) as old, zipfile.ZipFile(staged) as fresh:
                        names = set(fresh.namelist()) - {METADATA_NAME}
                        if set(old.namelist()) - {METADATA_NAME} != names or any(
                                old.read(name) != fresh.read(name) for name in names):
                            raise OSError("a different archive already exists at the destination")
                    outcome = "skipped"
            if outcome == "copied":
                publish(contract.destination, staged, archive_path, replace=contract.conflict == "replace")
            for item in included:
                self._item_state(job_id, item["asset_id"], outcome)
                if outcome == "copied":
                    report.copied += 1
                else:
                    report.skipped += 1

    # -- history ----------------------------------------------------------------------------------

    def cleanup_history(self) -> int:
        """Recent activity only; cleaning history never deletes exported files (§34.11)."""
        cutoff = (self.clock() - DEFAULTS.export.activity_max_age).isoformat()
        with transaction(self.conn):
            removed = self.conn.execute("DELETE FROM export_jobs WHERE created_at < ?", (cutoff,)).rowcount
            removed += self.conn.execute(
                "DELETE FROM export_jobs WHERE id NOT IN (SELECT id FROM export_jobs ORDER BY created_at DESC LIMIT ?)",
                (DEFAULTS.export.activity_max_jobs,)).rowcount
        return removed
