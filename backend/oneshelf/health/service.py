"""Capability-level source health (Master §21).

Passive signals recorded by the source service are interpreted here with thresholds and hysteresis.
Rate Limited and Reconnect Required are their own states, one missing item never degrades a source,
recovery needs repeated success, and health only describes: it never rewrites method, source or language.
Active checks are explicit, low priority and never start a browser.
"""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass

from oneshelf.db.connection import transaction
from oneshelf.domain.clock import utcnow_iso
from oneshelf.net.governor import Priority

DEGRADED_AFTER = 3
UNAVAILABLE_AFTER = 6
RECOVERY_SUCCESSES = 2
WINDOW = 20

DIRECT_STATES = {"rate_limit": "rate_limited", "auth_failure": "reconnect_required",
                 "catalog_validation_failure": "catalog_suspicious"}
PLUGIN_HINT_CATEGORIES = {"parser_failure", "selector_missing"}
SEVERITY = ["healthy", "unknown", "rate_limited", "reconnect_required", "catalog_suspicious", "degraded", "unavailable"]


@dataclass(frozen=True)
class CapabilityHealth:
    capability: str
    state: str
    category: str | None = None
    plugin_version: str | None = None
    hint: str | None = None
    consecutive_failures: int = 0


class HealthService:
    def __init__(self, conn: sqlite3.Connection, *, events=None) -> None:
        self.conn = conn
        self.events = events

    def _recent(self, source_id: str, capability: str) -> list[sqlite3.Row]:
        return self.conn.execute(
            "SELECT outcome, category, plugin_version FROM source_health_signals WHERE source_id = ? AND capability = ?"
            " ORDER BY id DESC LIMIT ?", (source_id, capability, WINDOW)).fetchall()

    def _capability_state(self, source_id: str, capability: str) -> CapabilityHealth:
        rows = self._recent(source_id, capability)
        if not rows:
            return CapabilityHealth(capability, "unknown")
        meaningful = [r for r in rows if r["outcome"] != "content_missing"]  # one 404 is not a source failure
        if not meaningful:
            return CapabilityHealth(capability, "healthy")
        failures, successes = 0, 0
        for row in meaningful:
            if row["outcome"] == "failure":
                if successes:
                    break
                failures += 1
            else:
                if failures:
                    break
                successes += 1
        latest = meaningful[0]
        if successes >= RECOVERY_SUCCESSES or (successes and not failures and len(meaningful) < RECOVERY_SUCCESSES):
            return CapabilityHealth(capability, "healthy")
        if failures == 0:
            previous = self.conn.execute("SELECT state FROM source_health_state WHERE source_id = ? AND capability = ?",
                                         (source_id, capability)).fetchone()
            return CapabilityHealth(capability, previous["state"] if previous else "healthy")
        category = latest["category"]
        if category in DIRECT_STATES:
            state = DIRECT_STATES[category]
        elif failures >= UNAVAILABLE_AFTER:
            state = "unavailable"
        elif failures >= DEGRADED_AFTER:
            state = "degraded"
        else:
            state = "healthy"
        hint = "plugin_update_may_be_needed" if category in PLUGIN_HINT_CATEGORIES and failures >= DEGRADED_AFTER else None
        return CapabilityHealth(capability, state, category, latest["plugin_version"], hint, failures)

    def evaluate(self, source_id: str) -> dict[str, CapabilityHealth]:
        capabilities = [r[0] for r in self.conn.execute(
            "SELECT DISTINCT capability FROM source_health_signals WHERE source_id = ?", (source_id,))]
        result = {}
        now = utcnow_iso()
        for capability in capabilities:
            health = self._capability_state(source_id, capability)
            result[capability] = health
            with transaction(self.conn):
                self.conn.execute(
                    "INSERT INTO source_health_state (source_id, capability, state, category, plugin_version, since,"
                    " updated_at) VALUES (?,?,?,?,?,?,?) ON CONFLICT(source_id, capability) DO UPDATE SET"
                    " state=excluded.state, category=excluded.category, plugin_version=excluded.plugin_version,"
                    " since=CASE WHEN source_health_state.state = excluded.state THEN source_health_state.since"
                    " ELSE excluded.since END, updated_at=excluded.updated_at",
                    (source_id, capability, health.state, health.category, health.plugin_version, now, now))
        return result

    def overall(self, source_id: str) -> str:
        states = [h.state for h in self.evaluate(source_id).values()]
        if not states:
            return "unknown"
        return max(states, key=lambda state: SEVERITY.index(state))

    async def active_check(self, source_id: str, capability: str, runner, *, browser_capabilities: set[str] | None = None):
        """Explicit, low-priority probe. Health never spins up a browser (§21)."""
        if capability in (browser_capabilities or set()):
            raise ValueError("health checks never use browser retrieval")
        return await runner.run(source_id, capability, {}, priority=Priority.HEALTH)
