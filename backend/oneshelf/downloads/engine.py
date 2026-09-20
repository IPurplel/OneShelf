"""Download Engine (Master §16, §17, §14, §39).

Persistent per-Reading-Unit jobs under logical batches, windowed scheduling, Smart Retry inside the
contracted method, session and rate-limit waits, streamed transport with resume, integrity verification
before packaging, and crash-safe commit through the commit journal. Only verified artifacts ever become
downloaded content (INV-16) and every step is recoverable (INV-17).
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import shutil
import sqlite3
import time
import zipfile
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path

from oneshelf.db.connection import transaction
from oneshelf.domain.clock import utcnow_iso
from oneshelf.domain.ids import new_id
from oneshelf.downloads.contract import ExtractionContract, Settings, next_method, resolve_method
from oneshelf.integrity.validators import _validate_image, detect_format, validate
from oneshelf.net.governor import Priority, TrafficGovernor
from oneshelf.net.http import FetchFailed
from oneshelf.net.policy import BlockedDestination, DisallowedTarget
from oneshelf.plugins.runtime import AuthRequired, CapabilityError, RateLimited
from oneshelf.settings.defaults import DEFAULTS
from oneshelf.storage.commit import CommitEngine, CommitError, CommitRequest
from oneshelf.storage.hashing import sha256_file
from oneshelf.storage.layout import asset_relative_path, family_for
from oneshelf.storage.paths import PathSafetyError, delete_managed_file
from oneshelf.storage.roots import StorageRoot, check_availability, get_root, list_roots, preflight
from oneshelf.storage.staging import new_staging_area

REGISTRAR_KIND = "download"
ACTIVE_STATES = ("PREPARING", "DOWNLOADING", "VERIFYING", "PACKAGING", "COMMITTING")
WAITING_STATES = ("RETRY_WAIT", "WAITING_FOR_RATE_LIMIT", "WAITING_FOR_SESSION")
RUNNABLE_STATES = ("QUEUED", "RECOVERING", *WAITING_STATES)
SEQUENTIAL_FORMAT = "cbz"
MAX_RESOURCE_BYTES = 256 * 1024 * 1024
BACKOFF_BASE_SECONDS = 2


class MediaInvalid(RuntimeError):
    pass


@dataclass
class RunReport:
    completed: int = 0
    failed: int = 0
    waiting: int = 0
    canceled: int = 0
    errors: list[str] = field(default_factory=list)


def register_download(conn: sqlite3.Connection, payload: dict) -> None:
    """Idempotent registration replayed by the commit journal."""
    asset, job_id, now = payload["asset"], payload["job_id"], payload["now"]
    conn.execute(
        "INSERT OR IGNORE INTO assets (id, reading_unit_id, format, variant, storage_root_id, relative_path, size_bytes,"
        " sha256, page_count, integrity, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?, 'ok', ?, ?)",
        (asset["id"], asset["reading_unit_id"], asset["format"], asset.get("variant", ""), asset["storage_root_id"],
         asset["relative_path"], asset["size_bytes"], asset["sha256"], asset.get("page_count"), now, now))
    if conn.execute("SELECT 1 FROM assets WHERE id = ?", (asset["id"],)).fetchone() is None:
        raise CommitError("asset registration conflicted with an existing record")
    conn.execute("UPDATE download_jobs SET state = 'COMPLETED', asset_id = ?, finished_at = ?, updated_at = ?,"
                 " last_error = NULL, error_category = NULL WHERE id = ?", (asset["id"], now, now, job_id))
    history = payload["history"]
    conn.execute(
        "INSERT OR IGNORE INTO download_history (id, reading_unit_id, work_id, source_id, language, outcome,"
        " initial_method, final_method, fallback_reason, error_category, bytes, started_at, finished_at)"
        " VALUES (?,?,?,?,?, 'completed', ?,?,?,NULL,?,?,?)",
        (job_id, asset["reading_unit_id"], history["work_id"], history["source_id"], history["language"],
         history["initial_method"], history["final_method"], history.get("fallback_reason"), asset["size_bytes"],
         history.get("started_at"), now))


def registrars() -> dict:
    return {REGISTRAR_KIND: register_download}


logger = logging.getLogger(__name__)


class DownloadEngine:
    def __init__(self, conn: sqlite3.Connection, sources, plugins, governor: TrafficGovernor, *,
                 settings: Settings | None = None, events=None, fault=None, concurrency: int | None = None,
                 backoff_base_seconds: float = BACKOFF_BASE_SECONDS, notifications=None) -> None:
        self.conn = conn
        self.sources = sources
        self.plugins = plugins
        self.governor = governor
        self.settings = settings or Settings(conn)
        self.events = events
        self.fault = fault or (lambda _point: None)
        self.concurrency = concurrency or DEFAULTS.downloads.http_concurrency
        self.retry_budget = DEFAULTS.downloads.max_retries
        self.backoff_base_seconds = backoff_base_seconds
        self.notifications = notifications

    # -- enqueue -----------------------------------------------------------------------------------

    def _unit_context(self, unit_id: str) -> sqlite3.Row:
        row = self.conn.execute(
            "SELECT u.id AS unit_id, u.source_unit_key, u.url_hint, u.display_title, u.raw_title, u.unit_type,"
            " u.source_number,"
            " t.id AS track_id, t.source_id, t.language, w.id AS work_id, w.display_title AS work_title,"
            " w.content_type FROM reading_units u JOIN source_tracks t ON t.id = u.track_id"
            " JOIN works w ON w.id = t.work_id WHERE u.id = ?", (unit_id,)).fetchone()
        if row is None:
            raise ValueError(f"unknown reading unit {unit_id}")
        return row

    def _clear_broken_copy(self, unit_id: str) -> int:
        """Make room for a repair (§16.5, §26.21).

        A copy that is not sound is being replaced, so its record goes and, if the file is still there,
        it goes too — otherwise the commit would refuse to overwrite its own final path and the repair
        would fail on every attempt. A sound copy is never touched: it is not what repair is for.
        """
        removed = 0
        rows = self.conn.execute(
            "SELECT * FROM assets WHERE reading_unit_id = ? AND integrity != 'ok'", (unit_id,)).fetchall()
        for asset in rows:
            try:
                root = get_root(self.conn, asset["storage_root_id"])
                delete_managed_file(root.path, asset["relative_path"])
            except (PathSafetyError, FileNotFoundError, ValueError):
                pass                    # already gone, or never ours to delete
            # A finished job and its journal entry point at the asset they produced; the copy is going,
            # so those pointers go with it rather than dangling.
            self.conn.execute("UPDATE download_jobs SET asset_id = NULL WHERE asset_id = ?", (asset["id"],))
            self.conn.execute("UPDATE imports SET asset_id = NULL WHERE asset_id = ?", (asset["id"],))
            self.conn.execute("DELETE FROM assets WHERE id = ?", (asset["id"],))
            removed += 1
        return removed

    def _already_downloaded(self, unit_id: str) -> bool:
        return self.conn.execute("SELECT 1 FROM assets WHERE reading_unit_id = ? AND integrity = 'ok'",
                                 (unit_id,)).fetchone() is not None

    def _active_job(self, unit_id: str) -> bool:
        placeholders = ",".join("?" * (len(ACTIVE_STATES) + len(RUNNABLE_STATES)))
        return self.conn.execute(
            f"SELECT 1 FROM download_jobs WHERE reading_unit_id = ? AND state IN ({placeholders})",
            (unit_id, *ACTIVE_STATES, *RUNNABLE_STATES)).fetchone() is not None

    def enqueue(self, unit_ids: list[str], *, root_id: str | None = None, one_time_method: str | None = None,
                label: str | None = None, repair: bool = False) -> str:
        """`repair` re-downloads a unit whose local copy is broken (§16.5, §26.21).

        It is the same contract, the same method and the same validated commit as any other download —
        never a side path — so a repaired unit is sound in exactly the way a fresh one is (INV-02).
        """
        batch_id, now = new_id(), utcnow_iso()
        skipped, queued = [], []
        with transaction(self.conn):
            self.conn.execute("INSERT INTO download_batches (id, label, selection_json, created_at, updated_at)"
                              " VALUES (?,?,?,?,?)", (batch_id, label, json.dumps({"requested": unit_ids}), now, now))
            position = self.conn.execute("SELECT coalesce(max(queue_position), 0) FROM download_jobs").fetchone()[0]
            for unit_id in unit_ids:
                context = self._unit_context(unit_id)
                if repair:
                    self._clear_broken_copy(unit_id)
                if (self._already_downloaded(unit_id) and not repair) or self._active_job(unit_id):
                    skipped.append(unit_id)
                    continue
                package = self.plugins.load_active(context["source_id"])
                recommendation = "direct" if "downloads" in package.recipes and "reader" not in package.recipes else "html_api"
                resolved = resolve_method(self.settings, context["source_id"], plugin_recommendation=recommendation,
                                          one_time=one_time_method)
                output = SEQUENTIAL_FORMAT if family_for(context["content_type"]) == "Sequential Art" else "file"
                contract = ExtractionContract(source_id=context["source_id"], language=context["language"],
                                              reading_unit_id=unit_id, output_format=output, method=resolved.method,
                                              mode=resolved.mode, fallback_order=resolved.fallback_order)
                position += 1
                queued.append(unit_id)
                self.conn.execute(
                    "INSERT INTO download_jobs (id, batch_id, reading_unit_id, state, queue_position, attempts,"
                    " extraction_contract_json, method, storage_root_id, created_at, updated_at)"
                    " VALUES (?,?,?, 'QUEUED', ?, 0, ?, ?, ?, ?, ?)",
                    (new_id(), batch_id, unit_id, position, contract.to_json(), contract.method, root_id, now, now))
            self.conn.execute("UPDATE download_batches SET selection_json = ? WHERE id = ?",
                              (json.dumps({"requested": unit_ids, "skipped": skipped, "queued": queued}), batch_id))
        self._emit("download.batch", {"batch_id": batch_id, "queued": len(queued), "skipped": len(skipped)})
        return batch_id

    # -- scheduling --------------------------------------------------------------------------------

    def _runnable_jobs(self, limit: int) -> list[sqlite3.Row]:
        now = utcnow_iso()
        placeholders = ",".join("?" * len(RUNNABLE_STATES))
        rows = self.conn.execute(
            f"SELECT j.* FROM download_jobs j JOIN download_batches b ON b.id = j.batch_id"
            f" WHERE j.state IN ({placeholders}) AND b.paused = 0"
            f" AND (j.next_attempt_at IS NULL OR j.next_attempt_at <= ?)"
            f" ORDER BY j.queue_position LIMIT ?", (*RUNNABLE_STATES, now, limit)).fetchall()
        runnable = []
        for row in rows:
            if row["state"] == "WAITING_FOR_SESSION" and not self._session_ready(row):
                continue
            runnable.append(row)
        return runnable

    def _session_ready(self, job: sqlite3.Row) -> bool:
        contract = ExtractionContract.from_json(job["extraction_contract_json"])
        sessions = getattr(self.sources, "sessions", None)
        return sessions is None or sessions.state(contract.source_id) == "connected"

    def _waiting_until(self) -> float | None:
        row = self.conn.execute(
            "SELECT min(next_attempt_at) FROM download_jobs j JOIN download_batches b ON b.id = j.batch_id"
            " WHERE b.paused = 0 AND j.next_attempt_at IS NOT NULL AND j.state IN (?, ?, ?)", WAITING_STATES).fetchone()
        if row is None or row[0] is None:
            return None
        return max(0.0, (datetime.fromisoformat(row[0]) - datetime.now(UTC)).total_seconds())

    async def run_once(self, limit: int | None = None) -> RunReport:
        report = RunReport()
        jobs = self._runnable_jobs(limit or self.concurrency)
        if not jobs:
            return report
        semaphore = asyncio.Semaphore(self.concurrency)

        async def guarded(job):
            async with semaphore:
                await self._process(job, report)

        await asyncio.gather(*(guarded(job) for job in jobs))
        return report

    async def run_until_idle(self, *, max_seconds: float = 30) -> RunReport:
        total = RunReport()
        deadline = time.monotonic() + max_seconds
        while time.monotonic() < deadline:
            report = await self.run_once()
            for attribute in ("completed", "failed", "waiting", "canceled"):
                setattr(total, attribute, getattr(total, attribute) + getattr(report, attribute))
            total.errors.extend(report.errors)
            if self._runnable_jobs(1):
                continue
            delay = self._waiting_until()
            if delay is None:
                break
            await asyncio.sleep(min(delay + 0.05, max(0.0, deadline - time.monotonic())))
        return total

    async def recover(self) -> int:
        """Startup/restart recovery: interrupted jobs are re-queued, open commits are replayed (§17)."""
        placeholders = ",".join("?" * len(ACTIVE_STATES))
        with transaction(self.conn):
            cursor = self.conn.execute(
                f"UPDATE download_jobs SET state = 'RECOVERING', updated_at = ? WHERE state IN ({placeholders})",
                (utcnow_iso(), *ACTIVE_STATES))
            recovered = cursor.rowcount
        CommitEngine(self.conn, registrars=registrars()).recover()
        return recovered

    # -- controls ----------------------------------------------------------------------------------

    def _set_state(self, job_id: str, state: str, **columns) -> None:
        assignments = ", ".join(f"{k} = ?" for k in columns)
        prefix = f", {assignments}" if columns else ""
        with transaction(self.conn):
            self.conn.execute(f"UPDATE download_jobs SET state = ?, updated_at = ?{prefix} WHERE id = ?",
                              (state, utcnow_iso(), *columns.values(), job_id))
        self._emit("download.job", {"job_id": job_id, "state": state})

    def pause(self, batch_id: str) -> None:
        with transaction(self.conn):
            self.conn.execute("UPDATE download_batches SET paused = 1, updated_at = ? WHERE id = ?",
                              (utcnow_iso(), batch_id))

    def resume(self, batch_id: str) -> None:
        with transaction(self.conn):
            self.conn.execute("UPDATE download_batches SET paused = 0, updated_at = ? WHERE id = ?",
                              (utcnow_iso(), batch_id))

    def reorder(self, batch_id: str, job_ids: list[str]) -> None:
        with transaction(self.conn):
            for position, job_id in enumerate(job_ids, start=1):
                self.conn.execute("UPDATE download_jobs SET queue_position = ?, updated_at = ? WHERE id = ? AND batch_id = ?",
                                  (position, utcnow_iso(), job_id, batch_id))

    def cancel_job(self, job_id: str, *, delete_partial: bool | None = None) -> None:
        job = self.conn.execute("SELECT * FROM download_jobs WHERE id = ?", (job_id,)).fetchone()
        if job is None:
            raise ValueError("unknown download job")
        keep = self.settings.get("global", None, "downloads.keep_partial_on_cancel", False)
        if delete_partial is None:
            delete_partial = not keep
        if delete_partial and job["staging_relpath"] and job["storage_root_id"]:
            root = get_root(self.conn, job["storage_root_id"])
            area = Path(root.path) / job["staging_relpath"]
            if area.is_dir():
                shutil.rmtree(area, ignore_errors=True)
        self._set_state(job_id, "CANCELED", finished_at=utcnow_iso())
        self._record_history(job, "canceled")

    def cancel_batch(self, batch_id: str) -> int:
        jobs = self.conn.execute("SELECT id FROM download_jobs WHERE batch_id = ? AND state NOT IN ('COMPLETED','CANCELED')",
                                 (batch_id,)).fetchall()
        for job in jobs:
            self.cancel_job(job["id"])
        return len(jobs)

    def retry_job(self, job_id: str, *, method: str | None = None) -> None:
        job = self.conn.execute("SELECT * FROM download_jobs WHERE id = ?", (job_id,)).fetchone()
        contract = ExtractionContract.from_json(job["extraction_contract_json"])
        if method is not None:
            contract = contract.with_method(method)
        self._set_state(job_id, "QUEUED", attempts=0, next_attempt_at=None, last_error=None, error_category=None,
                        pending_decision_json=None, extraction_contract_json=contract.to_json(), method=contract.method)

    def retry_all_failed(self, batch_id: str) -> int:
        jobs = self.conn.execute("SELECT id FROM download_jobs WHERE batch_id = ? AND state = 'FAILED'",
                                 (batch_id,)).fetchall()
        for job in jobs:
            self.retry_job(job["id"])
        return len(jobs)

    def clear_history(self, *, before: str | None = None) -> int:
        """Clearing history never deletes content or progress (§16.7, INV-23)."""
        with transaction(self.conn):
            cursor = (self.conn.execute("DELETE FROM download_history WHERE finished_at < ?", (before,)) if before
                      else self.conn.execute("DELETE FROM download_history"))
        return cursor.rowcount

    def job(self, job_id: str) -> sqlite3.Row:
        return self.conn.execute("SELECT * FROM download_jobs WHERE id = ?", (job_id,)).fetchone()

    def batch(self, batch_id: str) -> dict:
        rows = self.conn.execute("SELECT state, count(*) AS n FROM download_jobs WHERE batch_id = ? GROUP BY state",
                                 (batch_id,)).fetchall()
        counts = {r["state"]: r["n"] for r in rows}
        selection = json.loads(self.conn.execute("SELECT selection_json FROM download_batches WHERE id = ?",
                                                 (batch_id,)).fetchone()[0] or "{}")
        paused = self.conn.execute("SELECT paused FROM download_batches WHERE id = ?", (batch_id,)).fetchone()[0]
        completed, failed = counts.get("COMPLETED", 0), counts.get("FAILED", 0)
        pending = sum(n for state, n in counts.items() if state not in ("COMPLETED", "FAILED", "CANCELED"))
        if paused:
            state = "paused"
        elif pending:
            state = "active"
        elif failed and completed:
            state = "completed_with_issues"
        elif failed:
            state = "failed"
        else:
            state = "completed"
        return {"batch_id": batch_id, "state": state, "completed": completed, "failed": failed, "pending": pending,
                "canceled": counts.get("CANCELED", 0), "skipped": len(selection.get("skipped", [])), "counts": counts}

    # -- pipeline ----------------------------------------------------------------------------------

    def _emit(self, event: str, payload: dict) -> None:
        if self.events is not None:
            self.events.publish(event, payload)

    def _choose_root(self, job: sqlite3.Row) -> StorageRoot:
        if job["storage_root_id"]:
            return get_root(self.conn, job["storage_root_id"])
        for root in list_roots(self.conn):
            if root.is_default:
                return root
        raise RuntimeError("no storage location configured")

    async def _resources(self, contract: ExtractionContract, context: sqlite3.Row) -> list:
        capability = "downloads" if contract.method == "direct" else "reader"
        result = await self.sources.run(contract.source_id, capability,
                                        {"unit_key": context["source_unit_key"], "url": context["url_hint"],
                                         "language": contract.language},
                                        priority=Priority.MANUAL)
        if not result.complete or not result.entries:
            raise CapabilityError("resource_missing", f"{capability} returned no usable resources")
        return list(result.entries)

    def _manifest(self, job: sqlite3.Row) -> dict:
        return json.loads(job["manifest_json"] or "{}")

    def _save_manifest(self, job_id: str, manifest: dict) -> None:
        with transaction(self.conn):
            self.conn.execute("UPDATE download_jobs SET manifest_json = ?, updated_at = ? WHERE id = ?",
                              (json.dumps(manifest), utcnow_iso(), job_id))

    async def _process(self, job: sqlite3.Row, report: RunReport) -> None:
        job_id = job["id"]
        contract = ExtractionContract.from_json(job["extraction_contract_json"])
        context = self._unit_context(job["reading_unit_id"])
        attempts = job["attempts"] + 1
        started_at = job["started_at"] or utcnow_iso()
        self._set_state(job_id, "PREPARING", attempts=attempts, started_at=started_at, method=contract.method)
        try:
            root = self._choose_root(job)
            availability = check_availability(root)
            if not availability.available:
                raise CapabilityError("storage_unavailable", f"storage location unavailable ({availability.reason})")
            usage = shutil.disk_usage(root.path)
            if not preflight(total=usage.total, free=usage.free, expected_bytes=0,
                             override=root.reserve_override_bytes).allowed:
                raise CapabilityError("storage_full", "not enough free space above the storage reserve")
            staging_rel = job["staging_relpath"]
            if staging_rel and not (Path(root.path) / staging_rel).is_dir():
                staging_rel = None
            if staging_rel is None:
                area, staging_rel = new_staging_area(root, purpose="download", owner_id=job_id, resumable=True)
                with transaction(self.conn):
                    self.conn.execute("UPDATE download_jobs SET staging_relpath = ?, storage_root_id = ? WHERE id = ?",
                                      (staging_rel, root.id, job_id))
            area = Path(root.path) / staging_rel
            resources = await self._resources(contract, context)
            self._set_state(job_id, "DOWNLOADING")
            manifest = self._manifest(job)
            if contract.output_format == SEQUENTIAL_FORMAT:
                artifact, page_count = await self._download_pages(job_id, contract, resources, area, manifest, context)
                asset_format = SEQUENTIAL_FORMAT
            else:
                artifact, asset_format = await self._download_file(job_id, contract, resources[0], area, manifest)
                page_count = None
            self._set_state(job_id, "COMMITTING")
            await self._commit(job_id, contract, context, root, staging_rel, artifact, asset_format, page_count,
                               started_at)
            report.completed += 1
        except (AuthRequired, RateLimited, CapabilityError, MediaInvalid, FetchFailed, DisallowedTarget,
                BlockedDestination, OSError, CommitError) as exc:
            category = self._category(exc)
            self._handle_failure(job_id, contract, context, attempts, category, str(exc), report, started_at)

    @staticmethod
    def _category(exc: BaseException) -> str:
        if isinstance(exc, AuthRequired):
            return "auth_failure"
        if isinstance(exc, RateLimited):
            return "rate_limit"
        if isinstance(exc, MediaInvalid):
            return "media_invalid"
        if isinstance(exc, CapabilityError):
            return exc.category
        if isinstance(exc, (DisallowedTarget, BlockedDestination)):
            return "blocked"
        if isinstance(exc, FetchFailed):
            return "transport"
        return "storage_error"

    async def _download_pages(self, job_id: str, contract: ExtractionContract, resources: list, area: Path,
                              manifest: dict, context: sqlite3.Row) -> tuple[Path, int]:
        pages = manifest.setdefault("pages", {})
        for index, resource in enumerate(resources, start=1):
            name = f"{index:04d}.img"
            target = area / name
            entry = pages.get(str(index))
            if entry and target.is_file() and sha256_file(target)[0] == entry["sha256"]:
                self.fault("page_skipped")
                continue
            response = await self.sources.fetch_resource(contract.source_id, resource.url, capability="reader",
                                                         priority=Priority.MANUAL, max_bytes=MAX_RESOURCE_BYTES)
            if response.status != 200:
                raise CapabilityError("unexpected_response", f"page {index} returned HTTP {response.status}")
            problem = _validate_image(response.body)
            if problem:
                raise MediaInvalid(f"page {index}: {problem}")
            target.write_bytes(response.body)
            pages[str(index)] = {"url": resource.url, "sha256": sha256_file(target)[0], "size": len(response.body)}
            self._save_manifest(job_id, manifest)
            self.fault("page_downloaded")
        self.fault("after_pages_downloaded")
        self._set_state(job_id, "VERIFYING")
        if len(pages) != len(resources):
            raise MediaInvalid("page coverage does not match the source resource list")
        self._set_state(job_id, "PACKAGING")
        artifact = area / "artifact.cbz"
        with zipfile.ZipFile(artifact, "w", compression=zipfile.ZIP_STORED) as archive:
            for index in range(1, len(resources) + 1):
                page = area / f"{index:04d}.img"
                suffix = detect_image_suffix(page.read_bytes())
                archive.write(page, f"{index:04d}{suffix}")   # original bytes preserved (§39)
            archive.writestr("ComicInfo.xml", comic_info(context))
        result = validate(artifact)
        if not result.ok:
            raise MediaInvalid(f"packaged archive failed validation: {result.reason}")
        return artifact, result.page_count or len(resources)

    async def _download_file(self, job_id: str, contract: ExtractionContract, resource, area: Path,
                             manifest: dict) -> tuple[Path, str]:
        target = area / "artifact.bin"
        state = manifest.setdefault("file", {})
        headers = {}
        if state.get("validator") and target.is_file():
            headers = {"Range": f"bytes={target.stat().st_size}-", "If-Range": state["validator"]}
        response = await self.sources.fetch_resource(contract.source_id, resource.url, capability="downloads",
                                                     priority=Priority.MANUAL, max_bytes=MAX_RESOURCE_BYTES,
                                                     headers=headers or None)
        validator = response.headers.get("ETag") or response.headers.get("Last-Modified")
        if response.status == 206 and state.get("validator") == validator:
            with open(target, "ab") as handle:
                handle.write(response.body)
        elif response.status in (200, 206):
            target.write_bytes(response.body)  # changed validator or fresh start: never splice versions
        else:
            raise CapabilityError("unexpected_response", f"file returned HTTP {response.status}")
        state["validator"] = validator
        state["bytes"] = target.stat().st_size
        self._save_manifest(job_id, manifest)
        self.fault("file_partially_downloaded")
        self._set_state(job_id, "VERIFYING")
        result = validate(target)
        if not result.ok:
            raise MediaInvalid(f"downloaded file failed validation: {result.reason}")
        self._set_state(job_id, "PACKAGING")
        return target, result.format

    async def _commit(self, job_id: str, contract: ExtractionContract, context: sqlite3.Row, root: StorageRoot,
                      staging_rel: str, artifact: Path, asset_format: str, page_count: int | None,
                      started_at: str) -> None:
        sha, size = sha256_file(artifact)
        label = context["display_title"] or context["raw_title"] or context["source_unit_key"]
        relative_path = asset_relative_path(context["content_type"], context["work_title"], context["work_id"],
                                            contract.language, contract.source_id, label, context["unit_id"],
                                            asset_format)
        payload = {
            "job_id": job_id, "now": utcnow_iso(),
            "asset": {"id": new_id(), "reading_unit_id": context["unit_id"], "format": asset_format, "variant": "",
                      "storage_root_id": root.id, "relative_path": relative_path, "size_bytes": size, "sha256": sha,
                      "page_count": page_count},
            "history": {"work_id": context["work_id"], "source_id": contract.source_id, "language": contract.language,
                        "initial_method": contract.attempted_methods[0], "final_method": contract.method,
                        "fallback_reason": None if len(contract.attempted_methods) == 1 else "method_fallback",
                        "started_at": started_at},
        }
        engine = CommitEngine(self.conn, registrars=registrars(), fault=self.fault)
        engine.commit(CommitRequest(root_id=root.id, staging_relpath=f"{staging_rel}/{artifact.name}",
                                    final_relpath=relative_path,
                                    registration={"kind": REGISTRAR_KIND, "payload": payload}))
        area = Path(root.path) / staging_rel
        if area.is_dir():
            shutil.rmtree(area, ignore_errors=True)
        with transaction(self.conn):
            self.conn.execute("UPDATE download_jobs SET staging_relpath = NULL WHERE id = ?", (job_id,))
        self._emit("download.job", {"job_id": job_id, "state": "COMPLETED"})

    def _notify_failure(self, job_id: str, context: sqlite3.Row, category: str) -> None:
        """Only final failures notify; Smart Retry stays silent (§30.4)."""
        if self.notifications is None:
            return
        title = context["display_title"] or context["raw_title"] or context["source_unit_key"]
        if category == "auth_failure":
            self.notifications.reconnect_required(context["source_id"])
        elif category in ("storage_full", "storage_unavailable"):
            self.notifications.low_storage(self.job(job_id)["storage_root_id"] or "default", free_bytes=0)
        else:
            self.notifications.download_failed(context["unit_id"], title, category=category)

    def _record_history(self, job: sqlite3.Row, outcome: str, category: str | None = None) -> None:
        context = self._unit_context(job["reading_unit_id"])
        contract = ExtractionContract.from_json(job["extraction_contract_json"])
        with transaction(self.conn):
            self.conn.execute(
                "INSERT OR IGNORE INTO download_history (id, reading_unit_id, work_id, source_id, language, outcome,"
                " initial_method, final_method, fallback_reason, error_category, bytes, started_at, finished_at)"
                " VALUES (?,?,?,?,?,?,?,?,NULL,?,?,?,?)",
                (job["id"], job["reading_unit_id"], context["work_id"], contract.source_id, contract.language, outcome,
                 contract.attempted_methods[0], contract.method, category, job["bytes_done"], job["started_at"],
                 utcnow_iso()))

    def _handle_failure(self, job_id: str, contract: ExtractionContract, context: sqlite3.Row, attempts: int,
                        category: str, message: str, report: RunReport, started_at: str) -> None:
        decision = next_method(contract, attempts=attempts, retry_budget=self.retry_budget, category=category)
        job = self.job(job_id)
        if decision.action == "retry":
            delay = self.backoff_base_seconds ** attempts
            self._set_state(job_id, "RETRY_WAIT", last_error=message, error_category=category,
                            next_attempt_at=(datetime.now(UTC) + timedelta(seconds=delay)).isoformat())
            report.waiting += 1
        elif decision.action == "wait_for_session":
            self._set_state(job_id, "WAITING_FOR_SESSION", last_error=message, error_category=category,
                            next_attempt_at=None, attempts=0)
            report.waiting += 1
        elif decision.action == "wait_for_rate_limit":
            delay = 1.0
            self._set_state(job_id, "WAITING_FOR_RATE_LIMIT", last_error=message, error_category=category, attempts=0,
                            next_attempt_at=(datetime.now(UTC) + timedelta(seconds=delay)).isoformat())
            report.waiting += 1
        elif decision.action == "fallback":
            switched = contract.with_method(decision.method)
            self._set_state(job_id, "QUEUED", attempts=0, extraction_contract_json=switched.to_json(),
                            method=switched.method, manifest_json=None, staging_relpath=None, last_error=message,
                            error_category=category)
            report.waiting += 1
        else:
            pending = json.dumps({"reason": category, "options": list(contract.fallback_order)}) if decision.action == "ask" else None
            self._set_state(job_id, "FAILED", last_error=message, error_category=category, finished_at=utcnow_iso(),
                            pending_decision_json=pending)
            # §43: the job that failed and why, kept locally with no content of its own.
            logger.warning("download job %s failed: %s", job_id, category)
            self._record_history(self.job(job_id), "failed", category)
            self._notify_failure(job_id, context, category)
            report.failed += 1
            report.errors.append(f"{job_id}: {category}: {message}")


def detect_image_suffix(data: bytes) -> str:
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return ".png"
    if data[:3] == b"\xff\xd8\xff":
        return ".jpg"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return ".webp"
    return ".img"


def comic_info(context: sqlite3.Row) -> str:
    def escape(value: str | None) -> str:
        return (value or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

    return ("<?xml version='1.0' encoding='utf-8'?>\n<ComicInfo>"
            f"<Series>{escape(context['work_title'])}</Series>"
            f"<Title>{escape(context['display_title'] or context['raw_title'])}</Title>"
            f"<Number>{escape(context['source_number'])}</Number>"
            f"<LanguageISO>{escape(context['language'])}</LanguageISO>"
            "</ComicInfo>")
