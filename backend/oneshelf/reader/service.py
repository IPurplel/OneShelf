"""Reader backend: local and online pages, progress, and auto-download while reading.

Master §19 (reading ≠ downloading, OFF by default, engagement threshold, bounded read-ahead, leaving
the Work cancels unstarted read-ahead), §26.11–26.15 (progress), §26.20 (Reader Cache), §26.23
(multi-tab progress), §42 (defaults).
"""
from __future__ import annotations

import asyncio
import json
import sqlite3
import zipfile
from dataclasses import dataclass
from pathlib import Path

from oneshelf.db.connection import transaction
from oneshelf.domain.clock import utcnow_iso
from oneshelf.domain.ids import new_id
from oneshelf.downloads.contract import Settings
from oneshelf.integrity.validators import IMAGE_EXTENSIONS, _natural_key, _validate_image
from oneshelf.net.governor import Priority
from oneshelf.reader.cache import ReaderCache
from oneshelf.settings.defaults import DEFAULTS
from oneshelf.storage.paths import resolve_within
from oneshelf.storage.roots import get_root

READ_AHEAD_STATES = ("QUEUED",)


class StaleProgress(RuntimeError):
    """A newer progress revision exists; a stale tab must not undo it (§26.23)."""


@dataclass(frozen=True)
class PageInfo:
    index: int
    label: str | None = None
    url: str | None = None


@dataclass(frozen=True)
class PageData:
    index: int
    data: bytes
    origin: str  # local | cache | online
    content_type: str = "image/*"


@dataclass(frozen=True)
class LocalArtefact:
    format: str
    data: bytes


@dataclass(frozen=True)
class Bookmark:
    id: str
    locator: dict
    label: str | None
    created_at: str


@dataclass(frozen=True)
class Highlight:
    id: str
    locator: dict
    text: str
    colour: str
    created_at: str


@dataclass(frozen=True)
class Marks:
    bookmarks: list[Bookmark]
    highlights: list[Highlight]


@dataclass(frozen=True)
class ProgressState:
    read_state: str
    fraction: float | None
    locator: dict | None
    revision: int


class ReaderService:
    def __init__(self, conn: sqlite3.Connection, sources, cache: ReaderCache, downloads=None, *,
                 settings: Settings | None = None, events=None) -> None:
        self.conn = conn
        self.sources = sources
        self.cache = cache
        self.downloads = downloads
        self.settings = settings or Settings(conn)
        self.events = events
        self._reading: dict[str, str] = {}   # work_id -> unit currently being read
        self._descriptors: dict[str, list] = {}

    # -- unit context ------------------------------------------------------------------------------

    def _unit(self, unit_id: str) -> sqlite3.Row:
        row = self.conn.execute(
            "SELECT u.id AS unit_id, u.source_unit_key, u.url_hint, u.track_id, u.source_order, t.source_id,"
            " t.language, t.work_id FROM reading_units u JOIN source_tracks t ON t.id = u.track_id WHERE u.id = ?",
            (unit_id,)).fetchone()
        if row is None:
            raise ValueError(f"unknown reading unit {unit_id}")
        return row

    def _local_asset(self, unit_id: str) -> sqlite3.Row | None:
        return self.conn.execute(
            "SELECT * FROM assets WHERE reading_unit_id = ? AND integrity = 'ok' ORDER BY created_at LIMIT 1",
            (unit_id,)).fetchone()

    def _local_path(self, asset: sqlite3.Row) -> Path:
        root = get_root(self.conn, asset["storage_root_id"])
        return resolve_within(root.path, asset["relative_path"])

    @staticmethod
    def _archive_pages(path: Path) -> list[str]:
        with zipfile.ZipFile(path) as archive:
            names = [i.filename for i in archive.infolist()
                     if not i.is_dir() and Path(i.filename).suffix.lower() in IMAGE_EXTENSIONS]
        return sorted(names, key=_natural_key)

    # -- pages -------------------------------------------------------------------------------------

    async def pages(self, unit_id: str) -> list[PageInfo]:
        asset = self._local_asset(unit_id)
        if asset is not None and asset["format"] == "cbz":
            names = self._archive_pages(self._local_path(asset))
            return [PageInfo(index=i, label=str(i)) for i, _ in enumerate(names, start=1)]
        descriptors = await self._online_descriptors(unit_id)
        return [PageInfo(index=i, label=d.page_label, url=d.url) for i, d in enumerate(descriptors, start=1)]

    async def _online_descriptors(self, unit_id: str) -> list:
        unit = self._unit(unit_id)
        if unit_id not in self._descriptors:
            result = await self.sources.run(unit["source_id"], "reader",
                                            {"unit_key": unit["source_unit_key"], "url": unit["url_hint"],
                                             "language": unit["language"]},
                                            priority=Priority.READER)
            self._descriptors[unit_id] = list(result.entries)
        return self._descriptors[unit_id]

    async def page(self, unit_id: str, index: int, *, timeout: float | None = None) -> PageData:
        asset = self._local_asset(unit_id)
        if asset is not None and asset["format"] == "cbz":
            path = self._local_path(asset)
            names = self._archive_pages(path)
            with zipfile.ZipFile(path) as archive:
                return PageData(index, archive.read(names[index - 1]), "local")
        unit = self._unit(unit_id)
        descriptors = await self._online_descriptors(unit_id)
        descriptor = descriptors[index - 1]
        cached = self.cache.get(unit["source_id"], unit["source_unit_key"], descriptor.url)
        if cached is not None:
            return PageData(index, cached, "cache")
        coro = self.sources.fetch_resource(unit["source_id"], descriptor.url, capability="reader",
                                           priority=Priority.READER)
        response = await (asyncio.wait_for(coro, timeout) if timeout else coro)
        problem = _validate_image(response.body)
        if problem:
            raise ValueError(f"page {index}: {problem}")
        self.cache.put(unit["source_id"], unit["source_unit_key"], descriptor.url, response.body)
        return PageData(index, response.body, "online")

    def local_file(self, unit_id: str) -> LocalArtefact:
        """The downloaded artefact itself, for readers that render a whole document (§26.22)."""
        asset = self._local_asset(unit_id)
        if asset is None:
            raise FileNotFoundError("this reading unit has no downloaded file on this device")
        path = self._local_path(asset)
        if not path.is_file():
            raise FileNotFoundError("the local file is missing; run a storage scan or download it again")
        return LocalArtefact(asset["format"], path.read_bytes())

    def set_open_units(self, unit_ids: list[str]) -> None:
        keys = [self._unit(u)["source_unit_key"] for u in unit_ids]
        self.cache.protect(keys)

    # -- progress ----------------------------------------------------------------------------------

    def progress(self, unit_id: str) -> ProgressState:
        row = self.conn.execute("SELECT * FROM reading_state WHERE reading_unit_id = ?", (unit_id,)).fetchone()
        if row is None:
            return ProgressState("unread", None, None, 0)
        return ProgressState(row["read_state"], row["fraction"], json.loads(row["locator_json"] or "null"), row["revision"])

    def _write(self, unit_id: str, read_state: str, fraction: float | None, locator: dict | None,
               revision: int | None) -> ProgressState:
        current = self.progress(unit_id)
        if revision is not None and revision != current.revision:
            raise StaleProgress(f"progress revision {revision} does not match the stored revision "
                                f"{current.revision}; reload before writing")
        new_revision = current.revision + 1
        with transaction(self.conn):
            self.conn.execute(
                "INSERT INTO reading_state (reading_unit_id, read_state, locator_json, fraction, revision, updated_at)"
                " VALUES (?,?,?,?,?,?) ON CONFLICT(reading_unit_id) DO UPDATE SET read_state=excluded.read_state,"
                " locator_json=excluded.locator_json, fraction=excluded.fraction, revision=excluded.revision,"
                " updated_at=excluded.updated_at",
                (unit_id, read_state, json.dumps(locator) if locator is not None else None, fraction, new_revision,
                 utcnow_iso()))
        if self.events is not None:
            self.events.publish("reader.progress", {"reading_unit_id": unit_id, "read_state": read_state,
                                                    "fraction": fraction, "revision": new_revision})
        return ProgressState(read_state, fraction, locator, new_revision)

    def set_progress(self, unit_id: str, *, locator: dict | None = None, fraction: float | None = None,
                     revision: int | None = None) -> ProgressState:
        threshold = self.settings.get("global", None, "reader.auto_read_threshold",
                                      DEFAULTS.reader.auto_mark_read_threshold)
        read_state = "read" if fraction is not None and fraction >= threshold else "partial"
        return self._write(unit_id, read_state, fraction, locator, revision)

    def mark_read(self, unit_id: str, *, revision: int | None = None) -> ProgressState:
        return self._write(unit_id, "read", 1.0, self.progress(unit_id).locator, revision)

    def mark_unread(self, unit_id: str, *, revision: int | None = None) -> ProgressState:
        return self._write(unit_id, "unread", None, None, revision)

    # -- bookmarks and highlights (§26.22) ---------------------------------------------------------

    @staticmethod
    def _locator_key(locator: dict) -> str:
        """Two bookmarks are the same place when their locator is the same, however it was written."""
        return json.dumps(locator, sort_keys=True, separators=(",", ":"), ensure_ascii=False)

    def marks(self, unit_id: str) -> Marks:
        self._unit(unit_id)
        bookmarks = [Bookmark(r["id"], json.loads(r["locator_json"]), r["label"], r["created_at"])
                     for r in self.conn.execute(
                         "SELECT * FROM reading_bookmarks WHERE reading_unit_id = ? ORDER BY created_at, id",
                         (unit_id,))]
        highlights = [Highlight(r["id"], json.loads(r["locator_json"]), r["text"], r["colour"], r["created_at"])
                      for r in self.conn.execute(
                          "SELECT * FROM reading_highlights WHERE reading_unit_id = ? ORDER BY created_at, id",
                          (unit_id,))]
        return Marks(bookmarks, highlights)

    def add_bookmark(self, unit_id: str, *, locator: dict, label: str | None = None) -> Bookmark:
        self._unit(unit_id)
        key = self._locator_key(locator)
        existing = self.conn.execute(
            "SELECT * FROM reading_bookmarks WHERE reading_unit_id = ? AND locator_key = ?", (unit_id, key)).fetchone()
        if existing is not None:      # the same place is never bookmarked twice
            return Bookmark(existing["id"], json.loads(existing["locator_json"]), existing["label"],
                            existing["created_at"])
        record = Bookmark(new_id(), locator, label, utcnow_iso())
        with transaction(self.conn):
            self.conn.execute(
                "INSERT INTO reading_bookmarks (id, reading_unit_id, locator_json, locator_key, label, created_at)"
                " VALUES (?,?,?,?,?,?)",
                (record.id, unit_id, json.dumps(locator), key, label, record.created_at))
        return record

    def add_highlight(self, unit_id: str, *, locator: dict, text: str, colour: str = "yellow") -> Highlight:
        self._unit(unit_id)
        record = Highlight(new_id(), locator, text, colour, utcnow_iso())
        with transaction(self.conn):
            self.conn.execute(
                "INSERT INTO reading_highlights (id, reading_unit_id, locator_json, text, colour, created_at)"
                " VALUES (?,?,?,?,?,?)",
                (record.id, unit_id, json.dumps(locator), text, colour, record.created_at))
        return record

    def remove_mark(self, kind: str, mark_id: str) -> bool:
        table = "reading_bookmarks" if kind == "bookmark" else "reading_highlights"
        with transaction(self.conn):
            cursor = self.conn.execute(f"DELETE FROM {table} WHERE id = ?", (mark_id,))
        return cursor.rowcount > 0

    # -- auto-download while reading (§19) ---------------------------------------------------------

    def _auto_download_settings(self) -> tuple[bool, str, int, float]:
        enabled = self.settings.get("global", None, "reader.auto_download.enabled", DEFAULTS.auto_download.enabled)
        mode = self.settings.get("global", None, "reader.auto_download.mode", "current")
        read_ahead = self.settings.get("global", None, "reader.auto_download.read_ahead",
                                       DEFAULTS.auto_download.read_ahead_units)
        threshold = self.settings.get("global", None, "reader.auto_download.threshold",
                                      DEFAULTS.auto_download.engagement_threshold)
        return bool(enabled), mode, int(read_ahead), float(threshold)

    def _needs_download(self, unit_id: str) -> bool:
        if self.conn.execute("SELECT 1 FROM assets WHERE reading_unit_id = ? AND integrity = 'ok'",
                             (unit_id,)).fetchone():
            return False
        return self.conn.execute(
            "SELECT 1 FROM download_jobs WHERE reading_unit_id = ? AND state NOT IN ('FAILED','CANCELED')",
            (unit_id,)).fetchone() is None

    async def record_engagement(self, unit_id: str, *, fraction: float, interacted: bool) -> list[str]:
        """Genuine engagement may start a permanent download when the user enabled it (§19)."""
        enabled, mode, read_ahead, threshold = self._auto_download_settings()
        unit = self._unit(unit_id)
        self._reading[unit["work_id"]] = unit_id
        if not enabled or not interacted or fraction < threshold or self.downloads is None:
            return []
        units = [unit_id] if self._needs_download(unit_id) else []
        if mode == "current_plus_read_ahead":
            following = self.conn.execute(
                "SELECT id FROM reading_units WHERE track_id = ? AND source_order > ? AND availability != 'unavailable'"
                " ORDER BY source_order LIMIT ?", (unit["track_id"], unit["source_order"], read_ahead)).fetchall()
            units += [r[0] for r in following if self._needs_download(r[0])]
        if not units:
            return []
        self.downloads.enqueue(units, label="auto-download while reading")
        return units

    async def leaving_work(self, work_id: str) -> int:
        """Not-yet-started read-ahead jobs are cancelled; the current unit may finish (§19)."""
        if self.downloads is None:
            return 0
        current = self._reading.pop(work_id, None)
        placeholders = ",".join("?" * len(READ_AHEAD_STATES))
        rows = self.conn.execute(
            f"SELECT j.id FROM download_jobs j JOIN reading_units u ON u.id = j.reading_unit_id"
            f" JOIN source_tracks t ON t.id = u.track_id WHERE t.work_id = ? AND j.state IN ({placeholders})"
            f" AND j.reading_unit_id IS NOT ?", (work_id, *READ_AHEAD_STATES, current)).fetchall()
        for row in rows:
            self.downloads.cancel_job(row["id"])
        return len(rows)
