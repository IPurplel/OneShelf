"""In-app notifications and Needs Attention (Master §30, §35, §44; INV-22).

One notification per logical problem (mandatory dedupe keys), Seen/Unseen kept separate from reading
state, resolved items linger about an hour, history is bounded, and background noise never notifies.
There are no browser notifications in v1 (§30, §49).
"""
from __future__ import annotations

import json
import sqlite3
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

from oneshelf.db.connection import transaction
from oneshelf.domain.ids import new_id
from oneshelf.downloads.contract import Settings
from oneshelf.settings.defaults import DEFAULTS

IMPORTANT = "important"
INFORMATIONAL = "informational"
ATTENTION_PREFIXES = ("source-auth:", "storage-low:", "download-failed:", "catalog-suspicious:")
NEVER_NOTIFY = {"retry_succeeded", "health_probe", "cache_cleanup", "page_repaired", "temporary_timeout",
                "download_progress", "backup_success"}


@dataclass(frozen=True)
class Notification:
    id: str
    dedupe_key: str
    notification_class: str
    state: str
    seen: bool
    count: int
    title: str
    summary: str
    actions: list[str] = field(default_factory=list)
    payload: dict = field(default_factory=dict)
    created_at: str = ""
    updated_at: str = ""


def _format_releases(units: list[dict]) -> str:
    numbers = [u.get("number") for u in units]
    if all(n is not None and str(n).isdigit() for n in numbers) and len(numbers) > 1:
        values = sorted(int(n) for n in numbers)
        if values[-1] - values[0] == len(values) - 1:
            return f"{len(units)} new releases · Ch. {values[0]}–{values[-1]}"
    labels = [f"Chapter {u['number']}" if u.get("number") else (u.get("title") or "New unit") for u in units]
    return f"{len(units)} new release{'s' if len(units) != 1 else ''} · " + ", ".join(labels)


class NotificationService:
    def __init__(self, conn: sqlite3.Connection, *, events=None,
                 clock: Callable[[], datetime] = lambda: datetime.now(UTC)) -> None:
        self.conn = conn
        self.events = events
        self.clock = clock

    # -- core -------------------------------------------------------------------------------------

    def _now(self) -> str:
        return self.clock().isoformat()

    def _row(self, row: sqlite3.Row) -> Notification:
        payload = json.loads(row["payload_json"] or "{}")
        return Notification(row["id"], row["dedupe_key"], row["class"], row["state"], bool(row["seen"]), row["count"],
                            payload.get("title", ""), payload.get("summary", ""), payload.get("actions", []),
                            payload.get("data", {}), row["created_at"], row["updated_at"])

    @staticmethod
    def should_notify(event_kind: str) -> bool:
        """Background and success noise never becomes a notification (§30.1, §30.4)."""
        return event_kind not in NEVER_NOTIFY

    def notify(self, notification_class: str, *, dedupe_key: str, title: str, summary: str,
               actions: list[str] | None = None, data: dict | None = None, accumulate: bool = True) -> Notification:
        now = self._now()
        payload = json.dumps({"title": title, "summary": summary, "actions": (actions or [])[:2], "data": data or {}})
        with transaction(self.conn):
            existing = self.conn.execute("SELECT * FROM notifications WHERE dedupe_key = ?", (dedupe_key,)).fetchone()
            if existing is None:
                self.conn.execute(
                    "INSERT INTO notifications (id, dedupe_key, class, state, seen, count, payload_json, created_at,"
                    " updated_at) VALUES (?,?,?, 'active', 0, 1, ?, ?, ?)",
                    (new_id(), dedupe_key, notification_class, payload, now, now))
            else:
                self.conn.execute(
                    "UPDATE notifications SET class = ?, state = 'active', count = count + ?, payload_json = ?,"
                    " updated_at = ?, resolved_at = NULL WHERE dedupe_key = ?",
                    (notification_class, 1 if accumulate else 0, payload, now, dedupe_key))
        notification = self._row(self.conn.execute("SELECT * FROM notifications WHERE dedupe_key = ?",
                                                   (dedupe_key,)).fetchone())
        if self.events is not None:
            self.events.publish("notifications.changed", {"dedupe_key": dedupe_key, "class": notification_class})
        return notification

    def resolve(self, dedupe_key: str) -> None:
        now = self._now()
        with transaction(self.conn):
            self.conn.execute("UPDATE notifications SET state = 'resolved', resolved_at = ?, updated_at = ?"
                              " WHERE dedupe_key = ? AND state = 'active'", (now, now, dedupe_key))
        if self.events is not None:
            self.events.publish("notifications.changed", {"dedupe_key": dedupe_key, "state": "resolved"})

    # -- reads ------------------------------------------------------------------------------------

    def active(self) -> list[Notification]:
        cutoff = (self.clock() - DEFAULTS.notifications.resolved_visible_for).isoformat()
        rows = self.conn.execute(
            "SELECT * FROM notifications WHERE state = 'active' OR (state = 'resolved' AND resolved_at > ?)"
            " ORDER BY updated_at DESC", (cutoff,)).fetchall()
        return [self._row(r) for r in rows]

    def all(self) -> list[Notification]:
        return [self._row(r) for r in self.conn.execute("SELECT * FROM notifications ORDER BY updated_at DESC")]

    def needs_attention(self) -> list[Notification]:
        """A filtered shortcut over unresolved actionable problems (§32.2, §44)."""
        return [n for n in self.active()
                if n.state == "active" and n.dedupe_key.startswith(ATTENTION_PREFIXES)]

    # -- seen / cleanup ----------------------------------------------------------------------------

    def mark_all_seen(self) -> int:
        with transaction(self.conn):
            cursor = self.conn.execute("UPDATE notifications SET seen = 1, updated_at = ? WHERE seen = 0", (self._now(),))
        return cursor.rowcount

    def clear_seen(self) -> int:
        with transaction(self.conn):
            cursor = self.conn.execute("DELETE FROM notifications WHERE seen = 1")
        return cursor.rowcount

    def cleanup(self) -> int:
        """Bounded history: 30 days or 500 entries, whichever comes first (§30.15, §42)."""
        cutoff = (self.clock() - DEFAULTS.notifications.history_max_age).isoformat()
        with transaction(self.conn):
            removed = self.conn.execute("DELETE FROM notifications WHERE updated_at < ?", (cutoff,)).rowcount
            removed += self.conn.execute(
                "DELETE FROM notifications WHERE id NOT IN (SELECT id FROM notifications ORDER BY updated_at DESC"
                " LIMIT ?)", (DEFAULTS.notifications.history_max_entries,)).rowcount
        return removed

    # -- typed helpers -----------------------------------------------------------------------------

    def new_releases(self, work_id: str, work_title: str, units: list[dict]) -> Notification:
        return self.notify(IMPORTANT, dedupe_key=f"new-release:{work_id}", title=work_title,
                           summary=_format_releases(units), actions=["view_releases"],
                           data={"work_id": work_id, "units": units}, accumulate=False)

    def download_failed(self, unit_id: str, unit_title: str, *, category: str) -> Notification:
        return self.notify(IMPORTANT, dedupe_key=f"download-failed:{unit_id}", title="Download failed",
                           summary=f"{unit_title} could not be downloaded ({category}).", actions=["retry", "view"],
                           data={"reading_unit_id": unit_id, "category": category})

    def reconnect_required(self, source_id: str, *, detail: str | None = None) -> Notification:
        return self.notify(IMPORTANT, dedupe_key=f"source-auth:{source_id}", title="Reconnect required",
                           summary=f"{source_id} needs you to sign in again.", actions=["reconnect"],
                           data={"source_id": source_id, "detail": detail})

    def low_storage(self, root_id: str, *, free_bytes: int) -> Notification:
        return self.notify(IMPORTANT, dedupe_key=f"storage-low:{root_id}", title="Storage is running low",
                           summary=f"{free_bytes} bytes remain. Automatic downloads are paused.",
                           actions=["manage_storage"], data={"storage_root_id": root_id, "free_bytes": free_bytes})

    def catalog_suspicious(self, source_id: str, work_title: str) -> Notification:
        return self.notify(IMPORTANT, dedupe_key=f"catalog-suspicious:{source_id}", title="Source catalog looks unusual",
                           summary=f"OneShelf kept the last trusted catalog for {work_title}.",
                           actions=["view_source"], data={"source_id": source_id})

    def plugin_update_available(self, source_id: str, version: str) -> Notification:
        return self.notify(INFORMATIONAL, dedupe_key=f"plugin-update:{source_id}", title="Source update available",
                           summary=f"{source_id} {version} is available.", actions=["review_update"],
                           data={"source_id": source_id, "version": version})

    def source_recovered(self, source_id: str) -> Notification | None:
        """§30.10: a source coming back is good news, not an interruption. Silent unless asked for."""
        if not Settings(self.conn).get("global", None, "notifications.source_recovered", False):
            return None
        return self.notify(INFORMATIONAL, dedupe_key=f"source-recovered:{source_id}", title="Source recovered",
                           summary=f"{source_id} is working again.", data={"source_id": source_id})
