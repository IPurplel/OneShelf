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
import zipfile
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from oneshelf.db.connection import transaction
from oneshelf.domain.clock import utcnow_iso
from oneshelf.domain.ids import new_id
from oneshelf.search.grouping import SEQUENTIAL_FAMILY
from oneshelf.settings.defaults import DEFAULTS
from oneshelf.storage.paths import resolve_within, safe_component
from oneshelf.storage.roots import get_root, preflight

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
        total = sum(f.size for f in files)
        usage = shutil.disk_usage(destination)
        if not preflight(total=usage.total, free=usage.free, expected_bytes=total).allowed:
            raise ExportError("destination does not have enough free space")
        return ExportPlan(contracts, files, missing, total)

    def _plan_one(self, contract: ExportContract, files: list[PlannedFile], missing: list[str]) -> None:
        work = self._work(contract.work_id)
        target_dir = self._target_directory(contract, work)
        for unit_id in contract.unit_ids:
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
        job_id, now = new_id(), utcnow_iso()
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
                              (utcnow_iso(), job_id))
        return cursor.rowcount

    # -- execution --------------------------------------------------------------------------------

    async def run(self, job_id: str) -> ExportReport:
        job = self.job(job_id)
        contracts = [ExportContract(**c) for c in json.loads(job["contract_json"])]
        contract = contracts[0]
        report = ExportReport(job_id, "running", 0, job["skipped"], job["failed"])
        with transaction(self.conn):
            self.conn.execute("UPDATE export_jobs SET state = 'running', updated_at = ? WHERE id = ?",
                              (utcnow_iso(), job_id))
        items = self.conn.execute("SELECT * FROM export_items WHERE job_id = ? AND state = 'pending'"
                                  " ORDER BY target_path", (job_id,)).fetchall()
        for item in items:
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
            if each.include_metadata:
                self._write_metadata(job_id, each)
            if each.output == "zip":
                self._package_zip(job_id, each)
        remaining_failures = self.conn.execute(
            "SELECT count(*) FROM export_items WHERE job_id = ? AND state = 'failed'", (job_id,)).fetchone()[0]
        state = "completed_with_issues" if remaining_failures else "completed"
        totals = self.conn.execute(
            "SELECT sum(state = 'copied') AS copied, sum(state = 'skipped') AS skipped FROM export_items"
            " WHERE job_id = ?", (job_id,)).fetchone()
        with transaction(self.conn):
            self.conn.execute("UPDATE export_jobs SET state = ?, copied = ?, skipped = ?, failed = ?, finished_at = ?,"
                              " updated_at = ? WHERE id = ?",
                              (state, totals["copied"] or 0, totals["skipped"] or 0, remaining_failures, utcnow_iso(),
                               utcnow_iso(), job_id))
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
        target = Path(item["target_path"])
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
        shutil.copyfile(source, target)
        if item["sha256"] and hashlib.sha256(target.read_bytes()).hexdigest() != item["sha256"]:
            target.unlink(missing_ok=True)
            raise OSError("copied file failed its checksum check")
        return "copied"

    def _write_metadata(self, job_id: str, contract: ExportContract) -> None:
        work = self._work(contract.work_id)
        aliases = [r[0] for r in self.conn.execute("SELECT title FROM work_aliases WHERE work_id = ?",
                                                   (contract.work_id,))]
        units = []
        for unit_id in contract.unit_ids:
            unit = self.conn.execute("SELECT display_title, raw_title, source_number FROM reading_units WHERE id = ?",
                                     (unit_id,)).fetchone()
            files = [{"name": Path(i["target_path"]).name, "sha256": i["sha256"], "size": i["size"]}
                     for i in self.conn.execute("SELECT * FROM export_items WHERE job_id = ? AND reading_unit_id = ?"
                                                " AND state = 'copied'", (job_id, unit_id))]
            if files:
                units.append({"title": (unit["display_title"] or unit["raw_title"]) if unit else None,
                              "number": unit["source_number"] if unit else None, "files": files})
        metadata = {"title": work["display_title"], "aliases": aliases, "language": contract.language,
                    "source": contract.source_id, "content_type": work["content_type"], "units": units,
                    "formats": sorted({Path(f["name"]).suffix.lstrip(".") for u in units for f in u["files"]}),
                    "exported_at": self.clock().isoformat()}
        target = self._target_directory(contract, work)
        target.mkdir(parents=True, exist_ok=True)
        (target / METADATA_NAME).write_text(json.dumps(metadata, indent=1, ensure_ascii=False), encoding="utf-8")

    def _package_zip(self, job_id: str, contract: ExportContract) -> None:
        work = self._work(contract.work_id)
        folder = self._target_directory(contract, work)
        archive_path = Path(contract.destination) / f"{folder.name}.zip"
        with zipfile.ZipFile(archive_path, "w") as archive:
            for path in sorted(folder.rglob("*")):
                if path.is_file():
                    # already-compressed formats are stored, not recompressed (§34.5)
                    compression = zipfile.ZIP_STORED if path.suffix in (".cbz", ".zip", ".epub", ".png", ".jpg") \
                        else zipfile.ZIP_DEFLATED
                    archive.write(path, path.name, compress_type=compression)
        shutil.rmtree(folder, ignore_errors=True)

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
