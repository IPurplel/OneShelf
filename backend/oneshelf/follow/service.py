"""Follow and new-release detection (Master §20; INV-09).

Follow binds Work + Language + Preferred Source + Source Track. Detection compares the last Trusted
Catalog with the follow baseline: never max numbers, never numeric gaps. Metadata changes, reordering
and a unit disappearing and returning are not new releases, and nothing is ever downloaded automatically.
"""
from __future__ import annotations

import random
import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from oneshelf.catalog.trust import CatalogTrust
from oneshelf.db.connection import transaction
from oneshelf.domain.clock import utcnow_iso
from oneshelf.domain.ids import new_id
from oneshelf.settings.defaults import DEFAULTS

JITTER_SECONDS = 3600


@dataclass(frozen=True)
class FollowRecord:
    id: str
    work_id: str
    language: str
    source_id: str
    track_id: str
    baseline_units: int
    baseline_kind: str


@dataclass(frozen=True)
class FollowStatus:
    work_id: str
    track_id: str
    source_id: str
    language: str
    state: str  # up_to_date | new_releases | degraded | catalog_suspicious | checking
    last_attempted_at: str | None
    last_successful_at: str | None
    unseen_releases: int


@dataclass(frozen=True)
class CheckOutcome:
    work_id: str
    state: str
    new_units: list[dict]


class FollowService:
    def __init__(self, conn: sqlite3.Connection, catalog: CatalogTrust, *, events=None,
                 rng: random.Random | None = None) -> None:
        self.conn = conn
        self.catalog = catalog
        self.events = events
        self.rng = rng or random.Random()
        self._undo: dict[str, dict] = {}

    # -- helpers ----------------------------------------------------------------------------------

    def _row(self, work_id: str) -> sqlite3.Row | None:
        return self.conn.execute("SELECT * FROM follows WHERE work_id = ?", (work_id,)).fetchone()

    def _emit(self, event: str, payload: dict) -> None:
        if self.events is not None:
            self.events.publish(event, payload)

    def next_check_delay(self) -> timedelta:
        """~12 hours with jitter so followed sources are not checked in bursts (§20, §42)."""
        return DEFAULTS.follow.check_interval + timedelta(seconds=self.rng.uniform(0, JITTER_SECONDS))

    def _schedule(self, follow_id: str) -> None:
        due = (datetime.now(UTC) + self.next_check_delay()).isoformat()
        self.conn.execute("UPDATE follows SET next_check_at = ? WHERE id = ?", (due, follow_id))

    def _baseline(self, follow_id: str, track_id: str, kind: str) -> int:
        trusted = self.catalog.trusted_catalog(track_id)
        keys = trusted.unit_keys if trusted else []
        baseline_id, now = new_id(), utcnow_iso()
        self.conn.execute("DELETE FROM follow_baselines WHERE follow_id = ?", (follow_id,))
        self.conn.execute("INSERT INTO follow_baselines (id, follow_id, kind, track_id, created_at) VALUES (?,?,?,?,?)",
                          (baseline_id, follow_id, kind, track_id, now))
        self.conn.executemany("INSERT OR IGNORE INTO follow_baseline_units (baseline_id, unit_key) VALUES (?, ?)",
                              [(baseline_id, key) for key in keys])
        return len(keys)

    def _baseline_keys(self, follow_id: str) -> set[str]:
        return {r[0] for r in self.conn.execute(
            "SELECT u.unit_key FROM follow_baseline_units u JOIN follow_baselines b ON b.id = u.baseline_id"
            " WHERE b.follow_id = ?", (follow_id,))}

    def _baseline_kind(self, follow_id: str) -> str:
        row = self.conn.execute("SELECT kind FROM follow_baselines WHERE follow_id = ?", (follow_id,)).fetchone()
        return row[0] if row else "first_follow"

    # -- lifecycle --------------------------------------------------------------------------------

    def follow(self, work_id: str, *, language: str, source_id: str, track_id: str) -> FollowRecord:
        follow_id, now = new_id(), utcnow_iso()
        with transaction(self.conn):
            self.conn.execute(
                "INSERT INTO follows (id, work_id, language, preferred_source_id, track_id, created_at)"
                " VALUES (?,?,?,?,?,?) ON CONFLICT(work_id, language) DO UPDATE SET preferred_source_id=excluded.preferred_source_id,"
                " track_id=excluded.track_id", (follow_id, work_id, language, source_id, track_id, now))
            row = self._row(work_id)
            count = self._baseline(row["id"], track_id, "first_follow")
            self._schedule(row["id"])
        self._emit("follow.changed", {"work_id": work_id, "action": "followed"})
        return FollowRecord(row["id"], work_id, language, source_id, track_id, count, "first_follow")

    def unfollow(self, work_id: str) -> str:
        row = self._row(work_id)
        if row is None:
            raise ValueError("this work is not followed")
        token = new_id()
        self._undo[token] = {"row": dict(row), "baseline": sorted(self._baseline_keys(row["id"])),
                             "kind": self._baseline_kind(row["id"])}
        with transaction(self.conn):
            self.conn.execute("DELETE FROM release_events WHERE follow_id = ?", (row["id"],))
            self.conn.execute("DELETE FROM follow_baseline_units WHERE baseline_id IN"
                              " (SELECT id FROM follow_baselines WHERE follow_id = ?)", (row["id"],))
            self.conn.execute("DELETE FROM follow_baselines WHERE follow_id = ?", (row["id"],))
            self.conn.execute("DELETE FROM follows WHERE id = ?", (row["id"],))
        self._emit("follow.changed", {"work_id": work_id, "action": "unfollowed", "undo_token": token})
        return token

    def undo_unfollow(self, token: str) -> FollowRecord:
        saved = self._undo.pop(token, None)
        if saved is None:
            raise ValueError("this undo is no longer available")
        row, keys = saved["row"], saved["baseline"]
        with transaction(self.conn):
            self.conn.execute(
                "INSERT INTO follows (id, work_id, language, preferred_source_id, track_id, last_attempted_at,"
                " last_successful_at, next_check_at, created_at) VALUES (?,?,?,?,?,?,?,?,?)",
                (row["id"], row["work_id"], row["language"], row["preferred_source_id"], row["track_id"],
                 row["last_attempted_at"], row["last_successful_at"], row["next_check_at"], row["created_at"]))
            baseline_id = new_id()
            self.conn.execute("INSERT INTO follow_baselines (id, follow_id, kind, track_id, created_at) VALUES (?,?,?,?,?)",
                              (baseline_id, row["id"], saved["kind"], row["track_id"], utcnow_iso()))
            self.conn.executemany("INSERT OR IGNORE INTO follow_baseline_units (baseline_id, unit_key) VALUES (?, ?)",
                                  [(baseline_id, key) for key in keys])
        self._emit("follow.changed", {"work_id": row["work_id"], "action": "restored"})
        return FollowRecord(row["id"], row["work_id"], row["language"], row["preferred_source_id"], row["track_id"],
                            len(keys), saved["kind"])

    def change_preferred_source(self, work_id: str, *, source_id: str, track_id: str) -> FollowRecord:
        """A Source Change Baseline prevents reporting the new source's whole catalog as new (§20)."""
        row = self._row(work_id)
        if row is None:
            raise ValueError("this work is not followed")
        with transaction(self.conn):
            self.conn.execute("UPDATE follows SET preferred_source_id = ?, track_id = ? WHERE id = ?",
                              (source_id, track_id, row["id"]))
            self.conn.execute("DELETE FROM release_events WHERE follow_id = ?", (row["id"],))
            count = self._baseline(row["id"], track_id, "source_change")
            self._schedule(row["id"])
        self._emit("follow.changed", {"work_id": work_id, "action": "source_changed", "source_id": source_id})
        return FollowRecord(row["id"], work_id, row["language"], source_id, track_id, count, "source_change")

    # -- checking ---------------------------------------------------------------------------------

    def record_attempt(self, work_id: str, *, successful: bool, category: str | None = None) -> None:
        row = self._row(work_id)
        if row is None:
            return
        now = utcnow_iso()
        with transaction(self.conn):
            if successful:
                self.conn.execute("UPDATE follows SET last_attempted_at = ?, last_successful_at = ?,"
                                  " last_error_category = NULL WHERE id = ?", (now, now, row["id"]))
            else:
                self.conn.execute("UPDATE follows SET last_attempted_at = ?, last_error_category = ? WHERE id = ?",
                                  (now, category, row["id"]))
            self._schedule(row["id"])

    def check(self, work_id: str) -> CheckOutcome:
        """Compare the last Trusted Catalog with the baseline; suspicious or incomplete states report nothing."""
        row = self._row(work_id)
        if row is None:
            raise ValueError("this work is not followed")
        track_id = row["track_id"]
        if self.catalog.suspicious_candidate(track_id) is not None:
            self.record_attempt(work_id, successful=False, category="catalog_suspicious")
            return CheckOutcome(work_id, "catalog_suspicious", [])
        trusted = self.catalog.trusted_catalog(track_id)
        if trusted is None:
            self.record_attempt(work_id, successful=False, category="no_trusted_catalog")
            return CheckOutcome(work_id, "degraded", [])
        known = self._baseline_keys(row["id"]) | {
            r[0] for r in self.conn.execute("SELECT unit_key FROM release_events WHERE follow_id = ?", (row["id"],))}
        new_keys = [key for key in trusted.unit_keys if key not in known]
        now = utcnow_iso()
        events = []
        with transaction(self.conn):
            for key in new_keys:
                unit = self.conn.execute("SELECT id, raw_title, source_number FROM reading_units"
                                         " WHERE track_id = ? AND source_unit_key = ?", (track_id, key)).fetchone()
                event_id = new_id()
                self.conn.execute(
                    "INSERT OR IGNORE INTO release_events (id, follow_id, work_id, track_id, unit_key, reading_unit_id,"
                    " kind, detected_at) VALUES (?,?,?,?,?,?, 'NEW_RELEASE', ?)",
                    (event_id, row["id"], work_id, track_id, key, unit["id"] if unit else None, now))
                events.append({"unit_key": key, "reading_unit_id": unit["id"] if unit else None,
                               "title": unit["raw_title"] if unit else None,
                               "number": unit["source_number"] if unit else None})
        self.record_attempt(work_id, successful=True)
        if events:
            self._emit("follow.releases", {"work_id": work_id, "count": len(events)})
        return CheckOutcome(work_id, "new_releases" if events else "up_to_date", events)

    def status(self, work_id: str) -> FollowStatus | None:
        row = self._row(work_id)
        if row is None:
            return None
        unseen = self.conn.execute("SELECT count(*) FROM release_events WHERE follow_id = ? AND seen = 0",
                                   (row["id"],)).fetchone()[0]
        if self.catalog.suspicious_candidate(row["track_id"]) is not None:
            state = "catalog_suspicious"
        elif unseen:
            state = "new_releases"
        elif row["last_error_category"] or row["last_successful_at"] is None:
            state = "degraded"
        else:
            state = "up_to_date"
        return FollowStatus(work_id, row["track_id"], row["preferred_source_id"], row["language"], state,
                            row["last_attempted_at"], row["last_successful_at"], unseen)

    def due_follows(self, *, now: str | None = None) -> list[str]:
        now = now or utcnow_iso()
        return [r[0] for r in self.conn.execute(
            "SELECT work_id FROM follows WHERE next_check_at IS NULL OR next_check_at <= ? ORDER BY next_check_at",
            (now,))]

    def mark_releases_seen(self, work_id: str) -> int:
        row = self._row(work_id)
        if row is None:
            return 0
        with transaction(self.conn):
            cursor = self.conn.execute("UPDATE release_events SET seen = 1 WHERE follow_id = ? AND seen = 0",
                                       (row["id"],))
        return cursor.rowcount
