"""Reader backend: local and online pages, progress, and auto-download while reading.

Master §19 (reading ≠ downloading, OFF by default, engagement threshold, bounded read-ahead, leaving
the Work cancels unstarted read-ahead), §26.11–26.15 (progress), §26.20 (Reader Cache), §26.23
(multi-tab progress), §42 (defaults).
"""
from __future__ import annotations

import asyncio
import json
import sqlite3
import time
import zipfile
from collections import OrderedDict
from dataclasses import asdict, dataclass
from pathlib import Path

from oneshelf.db.connection import transaction
from oneshelf.domain.clock import utcnow_iso
from oneshelf.domain.ids import new_id
from oneshelf.downloads.contract import Settings
from oneshelf.downloads.engine import NoStorageLocation
from oneshelf.integrity.validators import _is_image_entry, _natural_key, _validate_image
from oneshelf.library.copies import local_copy
from oneshelf.net.governor import Priority
from oneshelf.plugins.results import ResourceDescriptor
from oneshelf.plugins.runtime import AuthRequired, CapabilityError, PageTemporarilyRefused, PublicReaderExpired, RateLimited
from oneshelf.reader.cache import ReaderCache
from oneshelf.reader.page_image import normalize_page_image
from oneshelf.settings.defaults import DEFAULTS
from oneshelf.storage.paths import resolve_within
from oneshelf.storage.roots import get_root
from oneshelf.text.container import TextUnit, open_text_container
from oneshelf.text.direction import content_direction
from oneshelf.text.sanitise import unit_sections

READ_AHEAD_STATES = ("QUEUED",)
# Page lists of units read online (I-107): a bounded, expiring memory, because the links a source hands out can
# expire (signed CDN links), and a long-running server must not keep every unit it has ever shown.
DESCRIPTOR_CACHE_UNITS = 256
DESCRIPTOR_TTL_SECONDS = 30 * 60


class StaleProgress(RuntimeError):
    """A newer progress revision exists; a stale tab must not undo it (§26.23)."""


class DownloadRequired(RuntimeError):
    """The source has no reader: this unit is read from its downloaded file, which is not here yet."""


class SourceUnavailable(RuntimeError):
    """The unit's source is disabled or not installed, and what was asked for is not cached (§26.21)."""


class MarkOperationConflict(RuntimeError):
    """One mark operation ID cannot be reused for different content."""


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


@dataclass
class _DescriptorGate:
    lock: asyncio.Lock
    waiters: int = 0


@dataclass
class _PageFlight:
    task: asyncio.Task[bytes]
    interests: int = 0
    orphan_timer: asyncio.TimerHandle | None = None


@dataclass(frozen=True)
class LocalArtefact:
    format: str
    path: Path


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
        self._descriptors: OrderedDict[str, tuple[float, list]] = OrderedDict()
        self._descriptor_gates: dict[str, _DescriptorGate] = {}
        self._public_refusals: OrderedDict[str, float] = OrderedDict()
        self._refusal_clock = time.monotonic
        self._page_fetches: dict[tuple[str, str, str], _PageFlight] = {}

    # -- unit context ------------------------------------------------------------------------------

    def _unit(self, unit_id: str) -> sqlite3.Row:
        row = self.conn.execute(
            "SELECT u.id AS unit_id, u.source_unit_key, u.url_hint, u.track_id, u.source_order, t.source_id,"
            " t.language, t.work_id, t.availability AS track_availability FROM reading_units u"
            " JOIN source_tracks t ON t.id = u.track_id WHERE u.id = ?",
            (unit_id,)).fetchone()
        if row is None:
            raise ValueError(f"unknown reading unit {unit_id}")
        return row

    def context(self, unit_id: str) -> dict:
        unit = self._unit(unit_id)
        formats = [row[0] for row in self.conn.execute(
            "SELECT DISTINCT format FROM assets WHERE reading_unit_id = ? AND integrity = 'ok' ORDER BY format",
            (unit_id,))]
        context = {"work_id": unit["work_id"], "track_id": unit["track_id"], "formats": formats}
        if not formats and self._file_only(unit["source_id"]):
            job = self.conn.execute(
                "SELECT state, last_error FROM download_jobs WHERE reading_unit_id = ?"
                " ORDER BY created_at DESC, id DESC LIMIT 1", (unit_id,)).fetchone()
            return {**context, "kind": "download",
                    "download": {"state": job["state"] if job else None, "error": job["last_error"] if job else None}}
        kind = "text" if "text" in formats or self._reads_text(unit["source_id"]) else "images"
        return {**context, "kind": kind}

    def _reads_text(self, source_id: str) -> bool:
        reads_text = getattr(self.sources, "reads_text", None)
        return bool(reads_text and source_id != "local" and reads_text(source_id))

    def _file_only(self, source_id: str) -> bool:
        """A download-only source: its units are read from their file, never through a `reader` recipe.

        A source that is disabled or not installed is not "download only": it is unavailable, and says so.
        """
        reads_online = getattr(self.sources, "reads_online", None)
        if source_id == "local" or not self._source_available(source_id):
            return False
        return bool(reads_online and not reads_online(source_id))

    def _source_available(self, source_id: str) -> bool:
        available = getattr(self.sources, "available", None)
        return available is None or source_id == "local" or available(source_id)

    def _record(self, source_id: str, outcome: str, category: str | None) -> None:
        record = getattr(self.sources, "record_outcome", None)
        if record is not None:
            record(source_id, "reader", outcome, category)

    def _local_asset(self, unit_id: str, format: str | None = None) -> sqlite3.Row | None:
        return local_copy(self.conn, unit_id, format)        # the copy Downloads calls openable (UI-003)

    def _local_path(self, asset: sqlite3.Row) -> Path:
        root = get_root(self.conn, asset["storage_root_id"])
        return resolve_within(root.path, asset["relative_path"])

    @staticmethod
    def _archive_pages(path: Path) -> list[zipfile.ZipInfo]:
        with zipfile.ZipFile(path) as archive:
            entries = [info for info in archive.infolist() if _is_image_entry(info)]
        return sorted(entries, key=lambda info: _natural_key(info.filename))

    # -- pages -------------------------------------------------------------------------------------

    # -- text units ----------------------------------------------------------------------------------

    async def text(self, unit_id: str) -> tuple[TextUnit, str]:
        """A text unit's sanitised sections: the downloaded container, else the source's reader output.

        Online markup was sanitised by the runtime; it is sanitised again here, as stored markup is
        by the validator, so the reader never depends on one layer alone (Master §27).
        """
        asset = self._local_asset(unit_id, "text")
        if asset is not None:
            path = self._local_path(asset)
            if path.is_file():
                return open_text_container(path), "local"
        unit = self._unit(unit_id)
        if self._source_available(unit["source_id"]) and not self._reads_text(unit["source_id"]):
            raise FileNotFoundError("this reading unit has no text")
        descriptors = await self._online_descriptors(unit_id)
        sections = unit_sections([(d.html, d.title) for d in descriptors])
        if not sections:
            raise FileNotFoundError("the source returned no text for this reading unit")
        title = next((d.title for d in descriptors if d.title), None)
        language = unit["language"] if unit["language"] != "und" else None
        return TextUnit(title=title, language=language, direction=content_direction(language),
                        source_url=unit["url_hint"], sections=sections), "online"

    async def pages(self, unit_id: str) -> list[PageInfo]:
        asset = self._local_asset(unit_id, "cbz")
        if asset is not None:
            names = self._archive_pages(self._local_path(asset))
            return [PageInfo(index=i, label=str(i)) for i, _ in enumerate(names, start=1)]
        if self._unit(unit_id)["source_id"] == "local":
            raise FileNotFoundError("this local reading unit has no image pages; open its file instead")
        descriptors = await self._online_descriptors(unit_id)
        if any(d.url is None for d in descriptors):
            raise ValueError("this reading unit is text, not pages; open it in the Book Reader")
        return [PageInfo(index=i, label=d.page_label, url=d.url) for i, d in enumerate(descriptors, start=1)]

    def _check_public_refusal(self, unit_id: str) -> None:
        now = self._refusal_clock()
        for key, deadline in list(self._public_refusals.items()):
            if deadline <= now:
                self._public_refusals.pop(key, None)
        deadline = self._public_refusals.get(unit_id)
        if deadline is not None:
            raise PageTemporarilyRefused(deadline - now)

    def _remember_public_refusal(self, unit) -> None:
        try:
            self._check_public_refusal(unit["unit_id"])
        except PageTemporarilyRefused:
            return  # concurrent failures neither extend the window nor duplicate health signals
        self._public_refusals[unit["unit_id"]] = self._refusal_clock() + 120
        while len(self._public_refusals) > DESCRIPTOR_CACHE_UNITS:
            self._public_refusals.popitem(last=False)
        self._record(unit["source_id"], "failure", "expired_link")

    async def _online_descriptors(self, unit_id: str, *, stale: list | None = None) -> list:
        gate = self._descriptor_gates.setdefault(unit_id, _DescriptorGate(asyncio.Lock()))
        gate.waiters += 1
        try:
            async with gate.lock:
                return await self._load_online_descriptors(unit_id, stale=stale)
        finally:
            gate.waiters -= 1
            if gate.waiters == 0:
                self._descriptor_gates.pop(unit_id, None)

    async def _load_online_descriptors(self, unit_id: str, *, stale: list | None) -> list:
        if stale is not None:
            self._check_public_refusal(unit_id)
        unit = self._unit(unit_id)
        if unit["track_availability"] == "unavailable":
            raise FileNotFoundError("this source edition is no longer linked")
        if not self._source_available(unit["source_id"]):
            # §26.21: cached online pages stay usable while the source cannot be asked.
            stored = (self.cache.get_descriptors(unit["source_id"], unit["source_unit_key"])
                      if self.cache is not None else None)
            if stored is not None:
                return [ResourceDescriptor(**d) for d in stored]
            raise SourceUnavailable("this unit's source is disabled or not installed; enable it to read online")
        if self._file_only(unit["source_id"]):
            # Asking anyway fails as "unsupported" and is recorded against the source's health.
            raise DownloadRequired("this book has to be downloaded before it can be read")
        held = self._descriptors.get(unit_id)
        try:
            self._check_public_refusal(unit_id)
        except PageTemporarilyRefused:
            # Keep cached pages readable without reopening the source when the
            # descriptor TTL expires or the in-memory list has been evicted.
            if held is not None:
                return held[1]
            stored = (self.cache.get_descriptors(unit["source_id"], unit["source_unit_key"])
                      if self.cache is not None else None)
            if stored is not None:
                return [ResourceDescriptor(**d) for d in stored]
            raise
        # A late failure from an older list must reuse the renewal already performed.
        # Compare list identity: sources can renew a list without changing every URL.
        if held is not None and ((stale is None and time.monotonic() - held[0] < DESCRIPTOR_TTL_SECONDS)
                                 or (stale is not None and held[1] is not stale)):
            self._descriptors.move_to_end(unit_id)
            return held[1]
        result = await self.sources.run(unit["source_id"], "reader",
                                        {"unit_key": unit["source_unit_key"], "url": unit["url_hint"],
                                         "language": unit["language"]},
                                        priority=Priority.READER)
        entries = list(result.entries)
        if not entries:
            # Never remembered: the next request asks again rather than showing an empty unit until restart.
            issue = result.evidence.issues[0] if result.evidence.issues else None
            raise CapabilityError(issue.category if issue else "resource_missing",
                                  f"the source listed nothing for this unit ({issue.detail if issue else result.evidence.stop_reason})")
        if not result.complete:
            raise CapabilityError("incomplete_result",
                                  f"the source returned {len(entries)} entries but could not confirm completeness "
                                  f"({result.evidence.stop_reason})")
        self._descriptors[unit_id] = (time.monotonic(), entries)
        self._descriptors.move_to_end(unit_id)
        while len(self._descriptors) > DESCRIPTOR_CACHE_UNITS:
            self._descriptors.popitem(last=False)
        if self.cache is not None:
            self.cache.put_descriptors(unit["source_id"], unit["source_unit_key"], [asdict(e) for e in entries])
        return entries

    async def page(self, unit_id: str, index: int, *, timeout: float | None = None,
                   prefetch: bool = False) -> PageData:
        if index < 1:
            raise IndexError("page index must be at least 1")
        asset = self._local_asset(unit_id, "cbz")
        if asset is not None:
            path = self._local_path(asset)
            names = self._archive_pages(path)
            if index > len(names):
                raise IndexError("page index exceeds page count")
            with zipfile.ZipFile(path) as archive:
                return PageData(index, archive.read(names[index - 1]), "local")
        unit = self._unit(unit_id)
        if unit["source_id"] == "local":
            raise FileNotFoundError("this local reading unit has no image pages; open its file instead")
        descriptors = await self._online_descriptors(unit_id)
        if index > len(descriptors):
            raise IndexError("page index exceeds page count")
        descriptor = descriptors[index - 1]
        if descriptor.url is None:
            raise ValueError("this reading unit is text, not pages; open it in the Book Reader")
        cached = self.cache.get(unit["source_id"], unit["source_unit_key"], descriptor.url)
        if cached is not None:
            return PageData(index, cached, "cache")
        if not self._source_available(unit["source_id"]):
            raise SourceUnavailable("this page was never cached, and its source is disabled or not installed")
        self._check_public_refusal(unit_id)
        key = (unit["source_id"], unit["source_unit_key"], descriptor.url)
        flight = self._page_fetches.get(key)
        if flight is None:
            task = asyncio.create_task(self._fetch_online_page(unit, descriptor.url, index,
                                       Priority.READ_AHEAD if prefetch else Priority.READER, descriptors))
            flight = _PageFlight(task)
            self._page_fetches[key] = flight

            def clear(done: asyncio.Task[bytes]) -> None:
                if flight.orphan_timer is not None:
                    flight.orphan_timer.cancel()
                    flight.orphan_timer = None
                if self._page_fetches.get(key) is flight:
                    self._page_fetches.pop(key, None)
                if not done.cancelled():
                    done.exception()  # consume an error when the HTTP waiter has gone away

            task.add_done_callback(clear)
        elif not prefetch:
            governor = getattr(self.sources, "governor", None)
            if governor is not None:
                governor.promote(flight.task, Priority.READER)
        if flight.orphan_timer is not None:
            flight.orphan_timer.cancel()
            flight.orphan_timer = None
        flight.interests += 1
        try:
            data = await (asyncio.wait_for(asyncio.shield(flight.task), timeout)
                          if timeout else asyncio.shield(flight.task))
        finally:
            flight.interests -= 1
            if flight.interests == 0 and not flight.task.done():
                flight.orphan_timer = asyncio.get_running_loop().call_later(
                    0.15, self._cancel_orphan_page, key, flight)
        return PageData(index, data, "online")

    def _cancel_orphan_page(self, key: tuple[str, str, str], flight: _PageFlight) -> None:
        flight.orphan_timer = None
        if self._page_fetches.get(key) is flight and flight.interests == 0 and not flight.task.done():
            self._page_fetches.pop(key)
            flight.task.cancel()

    async def _fetch_online_page(self, unit: sqlite3.Row, url: str, index: int, priority: Priority,
                                 seen: list) -> bytes:
        source = unit["source_id"]
        self._check_public_refusal(unit["unit_id"])
        public_expiry = False
        try:
            response = await self.sources.fetch_resource(source, url, capability="reader", priority=priority)
            status = response.status
        except (AuthRequired, PublicReaderExpired) as exc:
            public_expiry = isinstance(exc, PublicReaderExpired)
            response, status = None, 403
        if status in (403, 404, 410):
            # A refused or vanished link may simply have expired (signed CDN links): ask the source once for
            # its current page list, and try the page's new link if it changed (Meta Prompt G4; I-107).
            try:
                fresh = await self._online_descriptors(unit["unit_id"], stale=seen)
            except CapabilityError as exc:
                if public_expiry and not isinstance(exc, RateLimited):
                    self._remember_public_refusal(unit)
                raise
            if index <= len(fresh) and fresh[index - 1].url and fresh[index - 1].url != url:
                url = fresh[index - 1].url
                try:
                    response = await self.sources.fetch_resource(source, url, capability="reader", priority=priority)
                except PublicReaderExpired:
                    self._remember_public_refusal(unit)
                    self._check_public_refusal(unit["unit_id"])
                status = response.status
            elif public_expiry:
                self._remember_public_refusal(unit)
                self._check_public_refusal(unit["unit_id"])
            elif response is None:
                raise AuthRequired()
        if status != 200:
            # One missing page is not a broken source (§21): a 404 counts as content missing, not a failure.
            category = ("not_found" if status in (404, 410) else "server_error" if status >= 500
                        else "unexpected_response")
            self._record(source, "content_missing" if category == "not_found" else "failure", category)
            raise CapabilityError(category, f"page {index}: the source answered HTTP {status}")
        data = await normalize_page_image(response.body)
        problem = _validate_image(data)
        if problem:
            raise ValueError(f"page {index}: {problem}")
        self.cache.put(source, unit["source_unit_key"], url, data)
        self._public_refusals.pop(unit["unit_id"], None)
        return data

    def local_file(self, unit_id: str, *, format: str | None = None) -> LocalArtefact:
        """Where the downloaded artefact is, for readers that render a whole document (§26.22).

        A path, not the bytes: the API streams it in ranges, so a large PDF is never read into memory (I-101).
        """
        self._unit(unit_id)
        asset = self._local_asset(unit_id, format)
        if asset is None:
            raise FileNotFoundError("this reading unit has no downloaded file on this device")
        path = self._local_path(asset)
        if not path.is_file():
            raise FileNotFoundError("the local file is missing; run a storage scan or download it again")
        return LocalArtefact(asset["format"], path)

    def set_open_units(self, unit_ids: list[str]) -> None:
        keys = [self._unit(u)["source_unit_key"] for u in unit_ids]
        self.cache.protect(keys)

    # -- progress ----------------------------------------------------------------------------------

    def progress(self, unit_id: str) -> ProgressState:
        self._unit(unit_id)          # a unit that does not exist has no progress, rather than empty progress
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

    def add_bookmark(self, unit_id: str, *, locator: dict, label: str | None = None,
                     operation_id: str | None = None) -> Bookmark:
        self._unit(unit_id)
        key = self._locator_key(locator)
        with transaction(self.conn):
            if operation_id is not None:
                prior = self.conn.execute(
                    "SELECT * FROM reading_bookmarks WHERE operation_id = ?", (operation_id,)).fetchone()
                if prior is not None:
                    if (prior["reading_unit_id"] != unit_id or prior["locator_key"] != key
                            or prior["label"] != label):
                        raise MarkOperationConflict("mark operation ID was used for another bookmark")
                    return Bookmark(prior["id"], json.loads(prior["locator_json"]), prior["label"],
                                    prior["created_at"])
            existing = self.conn.execute(
                "SELECT * FROM reading_bookmarks WHERE reading_unit_id = ? AND locator_key = ?",
                (unit_id, key)).fetchone()
            if existing is not None:  # the same place is never bookmarked twice
                return Bookmark(existing["id"], json.loads(existing["locator_json"]), existing["label"],
                                existing["created_at"])
            record = Bookmark(new_id(), locator, label, utcnow_iso())
            self.conn.execute(
                "INSERT INTO reading_bookmarks (id, reading_unit_id, locator_json, locator_key, label, created_at, operation_id)"
                " VALUES (?,?,?,?,?,?,?)",
                (record.id, unit_id, json.dumps(locator), key, label, record.created_at, operation_id))
        return record

    def add_highlight(self, unit_id: str, *, locator: dict, text: str, colour: str = "yellow",
                      operation_id: str | None = None) -> Highlight:
        self._unit(unit_id)
        with transaction(self.conn):
            if operation_id is not None:
                prior = self.conn.execute(
                    "SELECT * FROM reading_highlights WHERE operation_id = ?", (operation_id,)).fetchone()
                if prior is not None:
                    if (prior["reading_unit_id"] != unit_id
                            or self._locator_key(json.loads(prior["locator_json"])) != self._locator_key(locator)
                            or prior["text"] != text or prior["colour"] != colour):
                        raise MarkOperationConflict("mark operation ID was used for another highlight")
                    return Highlight(prior["id"], json.loads(prior["locator_json"]), prior["text"],
                                     prior["colour"], prior["created_at"])
            record = Highlight(new_id(), locator, text, colour, utcnow_iso())
            self.conn.execute(
                "INSERT INTO reading_highlights (id, reading_unit_id, locator_json, text, colour, created_at, operation_id)"
                " VALUES (?,?,?,?,?,?,?)",
                (record.id, unit_id, json.dumps(locator), text, colour, record.created_at, operation_id))
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
        if not self.sources.supports_download(unit["source_id"]):
            return []
        units = [unit_id] if self._needs_download(unit_id) else []
        if mode in ("read_ahead", "current_plus_read_ahead"):
            following = self.conn.execute(
                "SELECT id FROM reading_units WHERE track_id = ? AND source_order > ? AND availability != 'unavailable'"
                " ORDER BY source_order LIMIT ?", (unit["track_id"], unit["source_order"], read_ahead)).fetchall()
            units += [r[0] for r in following if self._needs_download(r[0])]
        if not units:
            return []
        try:
            self.downloads.enqueue(units, label="auto-download while reading",
                                   reader_read_ahead=[u for u in units if u != unit_id])
        except NoStorageLocation:
            return []          # reading goes on; the Downloads screen says what is missing (I-95)
        return units

    async def leaving_work(self, work_id: str) -> int:
        """Not-yet-started read-ahead jobs are cancelled; the current unit may finish (§19)."""
        if self.downloads is None:
            return 0
        current = self._reading.pop(work_id, None)
        placeholders = ",".join("?" * len(READ_AHEAD_STATES))
        rows = self.conn.execute(
            f"SELECT j.id FROM download_jobs j JOIN reading_units u ON u.id = j.reading_unit_id"
            f" JOIN source_tracks t ON t.id = u.track_id JOIN download_batches b ON b.id = j.batch_id"
            f" WHERE t.work_id = ? AND j.state IN ({placeholders})"
            f" AND j.reading_unit_id IN (SELECT value FROM json_each(b.selection_json, '$.reader_read_ahead'))"
            f" AND j.reading_unit_id IS NOT ?", (work_id, *READ_AHEAD_STATES, current)).fetchall()
        for row in rows:
            self.downloads.cancel_job(row["id"])
        return len(rows)
