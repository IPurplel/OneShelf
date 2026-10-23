"""Passive health signal recording (Master §21). Signals describe; they never change source/method."""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from oneshelf.db.connection import transaction
from oneshelf.domain.clock import utcnow_iso

MAX_SIGNALS_PER_CAPABILITY = 500
MAX_AGE = timedelta(days=7)


@dataclass(frozen=True)
class HealthSignal:
    source_id: str
    capability: str
    outcome: str
    category: str | None
    plugin_version: str
    created_at: str


def record_signal(conn: sqlite3.Connection, source_id: str, capability: str, outcome: str, category: str | None,
                  plugin_version: str) -> None:
    cutoff = (datetime.now(UTC) - MAX_AGE).isoformat()
    now = utcnow_iso()
    with transaction(conn):
        conn.execute(
            "INSERT INTO source_health_signals (source_id, capability, outcome, category, plugin_version, created_at)"
            " VALUES (?, ?, ?, ?, ?, ?)", (source_id, capability, outcome, category, plugin_version, now))
        conn.execute(
            "INSERT INTO source_check_summary (source_id, last_successful_at, last_attempted_at) VALUES (?, ?, ?)"
            " ON CONFLICT(source_id) DO UPDATE SET last_attempted_at = excluded.last_attempted_at,"
            " last_successful_at = coalesce(excluded.last_successful_at, source_check_summary.last_successful_at)",
            (source_id, now if outcome == "success" else None, now))
        conn.execute("DELETE FROM source_health_signals WHERE created_at < ?", (cutoff,))
        conn.execute(
            "DELETE FROM source_health_signals WHERE source_id = ? AND capability = ? AND id <= ("
            " SELECT id FROM source_health_signals WHERE source_id = ? AND capability = ? ORDER BY id DESC LIMIT 1 OFFSET ?)",
            (source_id, capability, source_id, capability, MAX_SIGNALS_PER_CAPABILITY))


def last_successful_check(conn: sqlite3.Connection, source_id: str) -> str | None:
    """The last time any capability of the source succeeded, or None if no success is on record (UI-004)."""
    row = conn.execute("SELECT last_successful_at FROM source_check_summary WHERE source_id = ?",
                       (source_id,)).fetchone()
    return row[0] if row else None


def checks_recorded_since_install(conn: sqlite3.Connection, source_id: str) -> bool:
    """Whether every check of the source is on record, so that no success on record means it never succeeded.

    The record began with migration 0021, from signals pruned after seven days: a source installed before
    then may have succeeded earlier, and for it "never" would be a guess (UI-004).
    """
    began = conn.execute("SELECT applied_at FROM schema_migrations WHERE version = 21").fetchone()
    installed = conn.execute("SELECT installed_at FROM plugins WHERE id = ?", (source_id,)).fetchone()
    if began is None or installed is None:
        return False
    return datetime.fromisoformat(installed[0]) >= datetime.fromisoformat(began[0])


def recent_signals(conn: sqlite3.Connection, source_id: str, limit: int = 200) -> list[HealthSignal]:
    rows = conn.execute(
        "SELECT source_id, capability, outcome, category, plugin_version, created_at FROM source_health_signals"
        " WHERE source_id = ? ORDER BY id DESC LIMIT ?", (source_id, limit)).fetchall()
    return [HealthSignal(*tuple(r)) for r in rows]
