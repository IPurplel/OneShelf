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
from oneshelf.net.http import FetchFailed, ResponseTooLarge, TooManyRedirects
from oneshelf.net.policy import BlockedDestination, DisallowedTarget
from oneshelf.plugins.runtime import AuthRequired, CapabilityError, RateLimited
from oneshelf.plugins.schema import is_text_reader
from oneshelf.settings.defaults import DEFAULTS
from oneshelf.storage.commit import CommitEngine, CommitError, CommitRequest
from oneshelf.storage.hashing import sha256_file
from oneshelf.storage.layout import asset_relative_path, family_for
from oneshelf.storage.roots import StorageRoot, check_availability, get_root, list_roots, preflight
from oneshelf.storage.staging import new_staging_area
from oneshelf.text.container import TEXT_EXTENSION, TextUnit, write_text_container
from oneshelf.text.direction import content_direction
from oneshelf.text.sanitise import TextUnitTooLarge, unit_sections

REGISTRAR_KIND = "download"
ACTIVE_STATES = ("PREPARING", "DOWNLOADING", "VERIFYING", "PACKAGING", "COMMITTING")
WAITING_STATES = ("RETRY_WAIT", "WAITING_FOR_RATE_LIMIT", "WAITING_FOR_SESSION")
RUNNABLE_STATES = ("QUEUED", "RECOVERING", *WAITING_STATES)
SEQUENTIAL_FORMAT = "cbz"
# A text source's reader output is stored as the text container, never converted to EPUB (§34.4).
TEXT_FORMAT = "text"
EXTENSIONS = {TEXT_FORMAT: TEXT_EXTENSION}
MAX_RESOURCE_BYTES = 256 * 1024 * 1024
BACKOFF_BASE_SECONDS = 2


class MediaInvalid(RuntimeError):
    pass


class NoStorageLocation(ValueError):
    """Nothing can be downloaded until the library has a Storage Location (§24.1, I-95)."""


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
    if asset.get("replaces"):
        # The broken or missing copy's record becomes the new copy's (I-98): one unit, one record per format.
        conn.execute("UPDATE assets SET storage_root_id = ?, relative_path = ?, size_bytes = ?, sha256 = ?,"
                     " page_count = ?, integrity = 'ok', updated_at = ? WHERE id = ?",
                     (asset["storage_root_id"], asset["relative_path"], asset["size_bytes"], asset["sha256"],
                      asset.get("page_count"), now, asset["id"]))
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
        self._tasks: dict[str, asyncio.Task] = {}

    # -- enqueue -----------------------------------------------------------------------------------

    def _unit_context(self, unit_id: str) -> sqlite3.Row:
        row = self.conn.execute(
            "SELECT u.id AS unit_id, u.source_unit_key, u.url_hint, u.display_title, u.raw_title, u.unit_type,"
            " u.source_number,"
            " t.id AS track_id, t.source_id, t.language, t.availability AS track_availability,"
            " w.id AS work_id, w.display_title AS work_title,"
            " w.content_type FROM reading_units u JOIN source_tracks t ON t.id = u.track_id"
            " JOIN works w ON w.id = t.work_id WHERE u.id = ?", (unit_id,)).fetchone()
        if row is None:
            raise ValueError(f"unknown reading unit {unit_id}")
        return row

    def _already_downloaded(self, unit_id: str) -> bool:
        return self.conn.execute("SELECT 1 FROM assets WHERE reading_unit_id = ? AND integrity = 'ok'",
                                 (unit_id,)).fetchone() is not None

    def _active_job(self, unit_id: str) -> bool:
        placeholders = ",".join("?" * (len(ACTIVE_STATES) + len(RUNNABLE_STATES)))
        return self.conn.execute(
            f"SELECT 1 FROM download_jobs WHERE reading_unit_id = ? AND state IN ({placeholders})",
            (unit_id, *ACTIVE_STATES, *RUNNABLE_STATES)).fetchone() is not None

    def enqueue(self, unit_ids: list[str], *, root_id: str | None = None, one_time_method: str | None = None,
                label: str | None = None, repair: bool = False,
                reader_read_ahead: list[str] | None = None) -> str:
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
                # A sound copy is never re-downloaded, repair or not; a broken one is replaced only once the
                # new copy is verified, at commit (I-99). Nothing is deleted here.
                if self._already_downloaded(unit_id) or self._active_job(unit_id):
                    skipped.append(unit_id)
                    continue
                if context["track_availability"] == "unavailable":
                    raise ValueError("this source edition is no longer linked")
                package = self.plugins.load_active(context["source_id"])
                recommendation = "direct" if "downloads" in package.recipes and "reader" not in package.recipes else "html_api"
                resolved = resolve_method(self.settings, context["source_id"], plugin_recommendation=recommendation,
                                          one_time=one_time_method)
                output = required_output(package, resolved.method, context["content_type"])
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
            # Checked after each unit's own reasons, so the more specific refusal is the one reported. A job
            # without anywhere to go would otherwise wait forever (I-95).
            if queued:
                if root_id is not None:
                    get_root(self.conn, root_id)
                elif not any(root.is_default for root in list_roots(self.conn)):
                    raise NoStorageLocation("there is no storage location for downloads yet; add one in Settings")
            self.conn.execute("UPDATE download_batches SET selection_json = ? WHERE id = ?",
                              (json.dumps({"requested": unit_ids, "skipped": skipped, "queued": queued,
                                           "reader_read_ahead": [u for u in (reader_read_ahead or []) if u in queued]}), batch_id))
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
            if row["id"] in self._tasks:
                continue
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
            try:
                async with semaphore:
                    await self._process(job, report)
            except asyncio.CancelledError:
                current = self.job(job["id"])
                if current is None or current["state"] != "CANCELED":
                    raise
                report.canceled += 1
            finally:
                self._tasks.pop(job["id"], None)

        tasks = []
        for job in jobs:
            task = asyncio.create_task(guarded(job))
            self._tasks[job["id"]] = task
            tasks.append(task)
        await asyncio.gather(*tasks)
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
            if self._tasks:
                # Another caller (e.g. the background runner) owns these workers.
                await asyncio.wait(list(self._tasks.values()), timeout=max(0.0, deadline - time.monotonic()),
                                   return_when=asyncio.FIRST_COMPLETED)
                continue
            delay = self._waiting_until()
            if delay is None:
                break
            await asyncio.sleep(min(delay + 0.05, max(0.0, deadline - time.monotonic())))
        return total

    async def recover(self) -> int:
        """Startup/restart recovery: interrupted jobs are re-queued, open commits are replayed (§17)."""
        placeholders = ",".join("?" * len(ACTIVE_STATES))
        # A job whose worker keeps dying (the process killed mid-download, say) has used its retries: it is
        # failed rather than restarted forever (I-95).
        exhausted = self.conn.execute(
            f"SELECT * FROM download_jobs WHERE state IN ({placeholders}) AND attempts > ?",
            (*ACTIVE_STATES, self.retry_budget)).fetchall()
        for job in exhausted:
            self._fail(job["id"], "interrupted", "the download was interrupted too many times")
        with transaction(self.conn):
            cursor = self.conn.execute(
                f"UPDATE download_jobs SET state = 'RECOVERING', updated_at = ? WHERE state IN ({placeholders})",
                (utcnow_iso(), *ACTIVE_STATES))
            recovered = cursor.rowcount
        CommitEngine(self.conn, registrars=registrars()).recover()
        return recovered

    # -- controls ----------------------------------------------------------------------------------

    def _ensure_not_canceled(self, job_id: str) -> None:
        job = self.job(job_id)
        if job is None or job["state"] == "CANCELED":
            raise asyncio.CancelledError()

    def _set_state(self, job_id: str, state: str, *, allow_canceled: bool = False, **columns) -> None:
        if state != "CANCELED" and not allow_canceled:
            self._ensure_not_canceled(job_id)
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
        if job["state"] in ("CANCELED", "COMPLETED"):
            return
        self._set_state(job_id, "CANCELED", finished_at=utcnow_iso())
        task = self._tasks.get(job_id)
        if task is not None and job["state"] in ACTIVE_STATES:
            task.cancel()
        keep = self.settings.get("global", None, "downloads.keep_partial_on_cancel", False)
        if delete_partial is None:
            delete_partial = not keep
        if delete_partial and job["staging_relpath"] and job["storage_root_id"]:
            root = get_root(self.conn, job["storage_root_id"])
            area = Path(root.path) / job["staging_relpath"]
            if area.is_dir():
                shutil.rmtree(area, ignore_errors=True)
        self._record_history(job, "canceled")

    def cancel_batch(self, batch_id: str) -> int:
        jobs = self.conn.execute("SELECT id FROM download_jobs WHERE batch_id = ? AND state NOT IN ('COMPLETED','CANCELED')",
                                 (batch_id,)).fetchall()
        for job in jobs:
            self.cancel_job(job["id"])
        return len(jobs)

    def retry_job(self, job_id: str, *, method: str | None = None) -> None:
        job = self.conn.execute("SELECT * FROM download_jobs WHERE id = ?", (job_id,)).fetchone()
        if job is None:
            raise ValueError("unknown download job")
        if job_id in self._tasks:
            raise ValueError("download worker is still stopping; retry when it has stopped")
        contract = ExtractionContract.from_json(job["extraction_contract_json"])
        if method is not None:
            contract = contract.with_method(method)
        # A retry of a whole-file download starts the file over (I-97): whatever was kept is what failed.
        # Validated image pages stay, since each was checked on its own and resume skips only matching ones.
        manifest = json.loads(job["manifest_json"] or "{}")
        manifest.pop("file", None)
        self._set_state(job_id, "QUEUED", allow_canceled=True, attempts=0, next_attempt_at=None, last_error=None, error_category=None,
                        pending_decision_json=None, extraction_contract_json=contract.to_json(), method=contract.method,
                        manifest_json=json.dumps(manifest))

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
        elif counts.get("CANCELED", 0) and not completed:
            state = "canceled"
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
            if context["track_availability"] == "unavailable":
                raise CapabilityError("source_unlinked", "this source edition is no longer linked")
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
            elif contract.output_format == TEXT_FORMAT and contract.method != "direct":
                artifact, page_count = self._download_text(job_id, contract, resources, area, manifest, context)
                asset_format = TEXT_FORMAT
            else:
                artifact, asset_format = await self._download_file(job_id, contract, resources[0], area, manifest)
                page_count = None
            self._set_state(job_id, "COMMITTING")
            await self._commit(job_id, contract, context, root, staging_rel, artifact, asset_format, page_count,
                               started_at)
            report.completed += 1
        except (AuthRequired, RateLimited, CapabilityError, MediaInvalid, FetchFailed, DisallowedTarget,
                BlockedDestination, OSError, CommitError, ResponseTooLarge, TooManyRedirects) as exc:
            category = self._category(exc)
            self._handle_failure(job_id, contract, context, attempts, category, str(exc), report, started_at)
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001 — anything unforeseen still ends the job, never strands it (I-95)
            logger.exception("download job %s hit an unexpected error", job_id)
            self._handle_failure(job_id, contract, context, attempts, "internal_error",
                                 f"{type(exc).__name__}: {exc}", report, started_at)

    @staticmethod
    def _category(exc: BaseException) -> str:
        if isinstance(exc, AuthRequired):
            return "auth_failure"
        if isinstance(exc, RateLimited):
            return "rate_limit"
        if isinstance(exc, MediaInvalid):
            return "media_invalid"
        if isinstance(exc, ResponseTooLarge):
            return "too_large"
        if isinstance(exc, TooManyRedirects):
            return "transport"
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
        current_indices = {str(index) for index in range(1, len(resources) + 1)}
        stale_indices = set(pages) - current_indices
        if stale_indices:
            for index in stale_indices:
                del pages[index]
            self._save_manifest(job_id, manifest)
        for index, resource in enumerate(resources, start=1):
            self._ensure_not_canceled(job_id)
            name = f"{index:04d}.img"
            target = area / name
            entry = pages.get(str(index))
            if (entry and entry.get("url") == resource.url and target.is_file()
                    and sha256_file(target)[0] == entry["sha256"]):
                self.fault("page_skipped")
                continue
            part = area / f"{name}.part"
            response = await self.sources.fetch_resource_to(contract.source_id, resource.url, part,
                                                            capability="reader", priority=Priority.MANUAL,
                                                            max_bytes=MAX_RESOURCE_BYTES)
            self._ensure_not_canceled(job_id)
            if response.status != 200:
                part.unlink(missing_ok=True)
                raise CapabilityError("unexpected_response", f"page {index} returned HTTP {response.status}")
            problem = _validate_image(part.read_bytes())      # one page: small, and checked before it counts
            if problem:
                part.unlink(missing_ok=True)
                raise MediaInvalid(f"page {index}: {problem}")
            part.replace(target)
            sha, size = sha256_file(target)
            pages[str(index)] = {"url": resource.url, "sha256": sha, "size": size}
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

    def _download_text(self, job_id: str, contract: ExtractionContract, resources: list, area: Path,
                       manifest: dict, context: sqlite3.Row) -> tuple[Path, int]:
        """Package a text unit from the reader's own output: the runtime already fetched and sanitised it.

        Every unit is sanitised again before it is written, and the container is validated before it is
        committed, so only allowlisted markup is ever stored (§27, INV-16).
        """
        self._ensure_not_canceled(job_id)
        for index, resource in enumerate(resources, start=1):
            if not resource.html:
                raise MediaInvalid(f"text item {index} has no text")
        try:
            sections = unit_sections([(r.html, r.title) for r in resources])
        except TextUnitTooLarge as exc:
            raise MediaInvalid(f"text unit: {exc}") from exc
        if not sections:
            raise MediaInvalid("text unit has no text once sanitised")
        self._set_state(job_id, "VERIFYING")
        manifest["text"] = {"units": len(resources), "sections": len(sections)}
        self._save_manifest(job_id, manifest)
        self.fault("after_text_sections")
        self._set_state(job_id, "PACKAGING")
        language = contract.language if contract.language != "und" else None
        title = next((r.title for r in resources if r.title), None) or context["display_title"] or context["raw_title"]
        artifact = write_text_container(area / f"artifact.{TEXT_EXTENSION}", TextUnit(
            title=title, language=language, direction=content_direction(language),
            source_url=context["url_hint"], sections=sections))
        result = validate(artifact)
        if not result.ok:
            raise MediaInvalid(f"packaged text unit failed validation: {result.reason}")
        return artifact, result.page_count or len(sections)

    async def _download_file(self, job_id: str, contract: ExtractionContract, resource, area: Path,
                             manifest: dict) -> tuple[Path, str]:
        target = area / "artifact.bin"
        state = manifest.setdefault("file", {})
        size = target.stat().st_size if target.is_file() else 0
        # Resume only a file that is known to be short of its known total (§16.4, I-97): a complete body
        # that failed later never asks for bytes past its end.
        resumable = bool(state.get("validator") and state.get("expected") and 0 < size < state["expected"])
        response = await self.sources.fetch_resource_to(
            contract.source_id, resource.url, target, capability="downloads", priority=Priority.MANUAL,
            max_bytes=MAX_RESOURCE_BYTES, resume_from=size if resumable else 0,
            validator=state.get("validator") if resumable else None)
        self._ensure_not_canceled(job_id)
        if response.status not in (200, 206):
            raise CapabilityError("unexpected_response", f"file returned HTTP {response.status}")
        state.update(validator=response.headers.get("ETag") or response.headers.get("Last-Modified"),
                     expected=response.total, bytes=target.stat().st_size)
        self._save_manifest(job_id, manifest)
        self.fault("file_partially_downloaded")
        self._set_state(job_id, "VERIFYING")
        result = validate(target)
        if not result.ok:
            # These bytes are known to be bad: the next attempt starts over rather than building on them.
            target.unlink(missing_ok=True)
            manifest["file"] = {}
            self._save_manifest(job_id, manifest)
            raise MediaInvalid(f"downloaded file failed validation: {result.reason}")
        self._set_state(job_id, "PACKAGING")
        return target, result.format

    async def _commit(self, job_id: str, contract: ExtractionContract, context: sqlite3.Row, root: StorageRoot,
                      staging_rel: str, artifact: Path, asset_format: str, page_count: int | None,
                      started_at: str) -> None:
        self._ensure_not_canceled(job_id)
        if self._unit_context(context["unit_id"])["track_availability"] == "unavailable":
            raise CapabilityError("source_unlinked", "this source edition is no longer linked")
        sha, size = sha256_file(artifact)
        existing = self.conn.execute("SELECT * FROM assets WHERE reading_unit_id = ? AND format = ? AND variant = ''",
                                     (context["unit_id"], asset_format)).fetchone()
        if existing is not None and existing["integrity"] == "ok":
            raise CommitError("this reading unit already has a sound copy in that format")
        label = context["display_title"] or context["raw_title"] or context["source_unit_key"]
        relative_path = asset_relative_path(context["content_type"], context["work_title"], context["work_id"],
                                            contract.language, contract.source_id, label, context["unit_id"],
                                            EXTENSIONS.get(asset_format, asset_format))
        payload = {
            "job_id": job_id, "now": utcnow_iso(),
            "asset": {"id": existing["id"] if existing is not None else new_id(), "replaces": existing is not None,
                      "reading_unit_id": context["unit_id"], "format": asset_format, "variant": "",
                      "storage_root_id": root.id, "relative_path": relative_path, "size_bytes": size, "sha256": sha,
                      "page_count": page_count},
            "history": {"work_id": context["work_id"], "source_id": contract.source_id, "language": contract.language,
                        "initial_method": contract.attempted_methods[0], "final_method": contract.method,
                        "fallback_reason": None if len(contract.attempted_methods) == 1 else "method_fallback",
                        "started_at": started_at},
        }
        engine = CommitEngine(self.conn, registrars=registrars(), fault=self.fault)
        registration = {"kind": REGISTRAR_KIND, "payload": payload}
        if existing is not None and existing["storage_root_id"] == root.id:
            registration["replaces"] = {"relative_path": existing["relative_path"]}
        engine.commit(CommitRequest(root_id=root.id, staging_relpath=f"{staging_rel}/{artifact.name}",
                                    final_relpath=relative_path, registration=registration))
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
            try:
                root = self._choose_root(self.job(job_id))
            except (RuntimeError, ValueError):
                root = None
            root_id = root.id if root is not None else "none"
            if category == "storage_unavailable" or root is None:
                self.notifications.storage_unavailable(root_id, name=root.name if root else None)
            else:
                self.notifications.low_storage(root_id, free_bytes=shutil.disk_usage(root.path).free)
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

    def _fail(self, job_id: str, category: str, message: str) -> None:
        """End a job that is not running now: FAILED, recorded and notified like any final failure."""
        self._set_state(job_id, "FAILED", allow_canceled=True, last_error=message, error_category=category,
                        finished_at=utcnow_iso())
        job = self.job(job_id)
        self._record_history(job, "failed", category)
        self._notify_failure(job_id, self._unit_context(job["reading_unit_id"]), category)

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


def required_output(package, method: str, content_type: str) -> str:
    """The Extraction Contract's required output, from what the source delivers (Master §14, I-93).

    A text reader gives the text container; the direct method, or a source without a reader, gives the
    original file; a reader that yields image pages gives a CBZ. The Work's label decides only when a source
    offers both a reader and files and the label says book — never because the label is unknown.
    """
    reader = package.recipes.get("reader")
    if is_text_reader(reader):
        return TEXT_FORMAT
    if method == "direct" or reader is None:
        return "file"
    if "downloads" in package.recipes and family_for(content_type) == "Books":
        return "file"
    return SEQUENTIAL_FORMAT


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
