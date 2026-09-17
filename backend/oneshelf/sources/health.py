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
    with transaction(conn):
        conn.execute(
            "INSERT INTO source_health_signals (source_id, capability, outcome, category, plugin_version, created_at)"
            " VALUES (?, ?, ?, ?, ?, ?)", (source_id, capability, outcome, category, plugin_version, utcnow_iso()))
        conn.execute("DELETE FROM source_health_signals WHERE created_at < ?", (cutoff,))
        conn.execute(
            "DELETE FROM source_health_signals WHERE source_id = ? AND capability = ? AND id <= ("
            " SELECT id FROM source_health_signals WHERE source_id = ? AND capability = ? ORDER BY id DESC LIMIT 1 OFFSET ?)",
            (source_id, capability, source_id, capability, MAX_SIGNALS_PER_CAPABILITY))


def recent_signals(conn: sqlite3.Connection, source_id: str, limit: int = 200) -> list[HealthSignal]:
    rows = conn.execute(
        "SELECT source_id, capability, outcome, category, plugin_version, created_at FROM source_health_signals"
        " WHERE source_id = ? ORDER BY id DESC LIMIT ?", (source_id, limit)).fetchall()
    return [HealthSignal(*tuple(r)) for r in rows]
