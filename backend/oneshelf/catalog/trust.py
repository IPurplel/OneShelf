"""Catalog trust model (Master §5; INV-01).

Only a complete snapshot can become Trusted. Incomplete results are recorded as evidence and never
replace trusted state, trigger deletion inference or feed Follow/Download Missing. Suspicion is
evaluated only between complete snapshots, and a suspicious new reality becomes trusted after two
consecutive complete checks that agree, or by explicit Trust This Catalog.
"""
from __future__ import annotations

import json
import sqlite3
from dataclasses import asdict, dataclass, field

from oneshelf.db.connection import transaction
from oneshelf.domain.clock import utcnow_iso
from oneshelf.domain.ids import new_id
from oneshelf.plugins.results import ListResult, UnitDescriptor
from oneshelf.settings.defaults import DEFAULTS

MAX_INCOMPLETE_SNAPSHOTS = 3
MAX_CANDIDATE_SNAPSHOTS = 2


class TrustRejected(RuntimeError):
    pass


@dataclass(frozen=True)
class TrustedCatalog:
    snapshot_id: str
    unit_count: int
    unit_keys: list[str]
    fetched_at: str
    plugin_version: str | None


@dataclass(frozen=True)
class RefreshOutcome:
    state: str  # trusted | unchanged | suspicious | recovered | incomplete
    snapshot_id: str
    unit_count: int
    previous_count: int | None = None
    lost: int = 0
    reason: str | None = None
    evidence: dict = field(default_factory=dict)


class CatalogTrust:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn

    # -- queries ----------------------------------------------------------------------------------

    def _snapshot(self, track_id: str, trust: str) -> sqlite3.Row | None:
        return self.conn.execute(
            "SELECT * FROM catalog_snapshots WHERE track_id = ? AND trust = ? ORDER BY fetched_at DESC LIMIT 1",
            (track_id, trust)).fetchone()

    def _keys(self, snapshot_id: str) -> list[str]:
        return [r[0] for r in self.conn.execute(
            "SELECT unit_key FROM snapshot_units WHERE snapshot_id = ? ORDER BY order_index", (snapshot_id,))]

    def _as_catalog(self, row: sqlite3.Row | None) -> TrustedCatalog | None:
        if row is None:
            return None
        return TrustedCatalog(row["id"], row["unit_count"], self._keys(row["id"]), row["fetched_at"], row["plugin_version"])

    def trusted_catalog(self, track_id: str) -> TrustedCatalog | None:
        """The only catalog Download Missing, Follow baselines and deletion inference may use (§5.4)."""
        return self._as_catalog(self._snapshot(track_id, "trusted_current"))

    def previous_catalog(self, track_id: str) -> TrustedCatalog | None:
        return self._as_catalog(self._snapshot(track_id, "trusted_previous"))

    def suspicious_candidate(self, track_id: str) -> TrustedCatalog | None:
        return self._as_catalog(self._snapshot(track_id, "suspicious"))

    # -- refresh ----------------------------------------------------------------------------------

    def refresh(self, track_id: str, result: ListResult, *, plugin_version: str | None = None) -> RefreshOutcome:
        units: list[UnitDescriptor] = list(result.entries)
        evidence = asdict(result.evidence)
        with transaction(self.conn):
            snapshot_id = self._insert_snapshot(track_id, units, result.complete, evidence, plugin_version)
            if not result.complete:
                self._prune(track_id, "incomplete", MAX_INCOMPLETE_SNAPSHOTS)
                reason = result.evidence.issues[0].category if result.evidence.issues else result.evidence.stop_reason
                return RefreshOutcome("incomplete", snapshot_id, len(units), reason=reason, evidence=evidence)

            current = self._snapshot(track_id, "trusted_current")
            new_keys = [u.unit_key for u in units]
            if current is None:
                self._promote(track_id, snapshot_id, units)
                return RefreshOutcome("trusted", snapshot_id, len(units), evidence=evidence)

            current_keys = self._keys(current["id"])
            lost = [k for k in current_keys if k not in set(new_keys)]
            if set(current_keys) == set(new_keys):
                self._materialize(track_id, units)
                self.conn.execute("DELETE FROM catalog_snapshots WHERE id = ?", (snapshot_id,))
                self.conn.execute("UPDATE catalog_snapshots SET fetched_at = ?, plugin_version = ?, evidence_json = ?"
                                  " WHERE id = ?", (utcnow_iso(), plugin_version, json.dumps(evidence), current["id"]))
                self._clear_candidates(track_id)
                return RefreshOutcome("unchanged", current["id"], len(units), len(current_keys), 0, evidence=evidence)

            if self._is_suspicious(current_keys, lost):
                candidate = self._snapshot(track_id, "suspicious")
                if candidate is not None and set(self._keys(candidate["id"])) == set(new_keys):
                    self._promote(track_id, snapshot_id, units)
                    return RefreshOutcome("recovered", snapshot_id, len(units), len(current_keys), len(lost), evidence=evidence)
                self.conn.execute("UPDATE catalog_snapshots SET trust = 'suspicious' WHERE id = ?", (snapshot_id,))
                self._prune(track_id, "suspicious", MAX_CANDIDATE_SNAPSHOTS)
                return RefreshOutcome("suspicious", snapshot_id, len(units), len(current_keys), len(lost), evidence=evidence)

            self._promote(track_id, snapshot_id, units)
            return RefreshOutcome("trusted", snapshot_id, len(units), len(current_keys), len(lost), evidence=evidence)

    def trust_catalog(self, track_id: str, snapshot_id: str) -> RefreshOutcome:
        """Advanced 'Trust This Catalog'. Incomplete snapshots can never be trusted (§5.3)."""
        row = self.conn.execute("SELECT * FROM catalog_snapshots WHERE id = ? AND track_id = ?",
                                (snapshot_id, track_id)).fetchone()
        if row is None:
            raise TrustRejected("unknown catalog snapshot")
        if row["completeness"] != "complete":
            raise TrustRejected("an incomplete catalog can never be trusted")
        units = [UnitDescriptor(unit_key=r["unit_key"], order_index=r["order_index"], raw_title=r["raw_title"],
                                number=r["number"], volume=r["volume"], unit_type=r["unit_type"], url=r["url"],
                                release_date=r["release_date"])
                 for r in self.conn.execute("SELECT * FROM snapshot_units WHERE snapshot_id = ? ORDER BY order_index",
                                            (snapshot_id,))]
        with transaction(self.conn):
            self._promote(track_id, snapshot_id, units)
        return RefreshOutcome("trusted", snapshot_id, len(units))

    # -- internals --------------------------------------------------------------------------------

    def _insert_snapshot(self, track_id: str, units: list[UnitDescriptor], complete: bool, evidence: dict,
                         plugin_version: str | None) -> str:
        snapshot_id = new_id()
        self.conn.execute(
            "INSERT INTO catalog_snapshots (id, track_id, completeness, trust, unit_count, evidence_json, plugin_version,"
            " fetched_at) VALUES (?, ?, ?, 'none', ?, ?, ?, ?)",
            (snapshot_id, track_id, "complete" if complete else "incomplete", len(units), json.dumps(evidence),
             plugin_version, utcnow_iso()))
        self.conn.executemany(
            "INSERT OR IGNORE INTO snapshot_units (snapshot_id, unit_key, order_index, raw_title, number, volume,"
            " unit_type, url, release_date) VALUES (?,?,?,?,?,?,?,?,?)",
            [(snapshot_id, u.unit_key, u.order_index, u.raw_title, u.number, u.volume, u.unit_type, u.url, u.release_date)
             for u in units])
        return snapshot_id

    @staticmethod
    def _is_suspicious(current_keys: list[str], lost: list[str]) -> bool:
        if not current_keys:
            return False
        return (len(lost) >= DEFAULTS.catalog.suspicious_min_units_lost
                and len(lost) / len(current_keys) >= DEFAULTS.catalog.suspicious_loss_fraction)

    def _prune(self, track_id: str, trust_or_completeness: str, keep: int) -> None:
        column = "trust" if trust_or_completeness == "suspicious" else "completeness"
        rows = self.conn.execute(
            f"SELECT id FROM catalog_snapshots WHERE track_id = ? AND {column} = ? ORDER BY fetched_at DESC",
            (track_id, trust_or_completeness)).fetchall()
        for row in rows[keep:]:
            self.conn.execute("DELETE FROM snapshot_units WHERE snapshot_id = ?", (row["id"],))
            self.conn.execute("DELETE FROM catalog_snapshots WHERE id = ?", (row["id"],))

    def _clear_candidates(self, track_id: str) -> None:
        self._prune(track_id, "suspicious", 0)

    def _promote(self, track_id: str, snapshot_id: str, units: list[UnitDescriptor]) -> None:
        previous = self._snapshot(track_id, "trusted_previous")
        if previous is not None:
            self.conn.execute("DELETE FROM snapshot_units WHERE snapshot_id = ?", (previous["id"],))
            self.conn.execute("DELETE FROM catalog_snapshots WHERE id = ?", (previous["id"],))
        self.conn.execute("UPDATE catalog_snapshots SET trust = 'trusted_previous' WHERE track_id = ? AND trust = 'trusted_current'",
                          (track_id,))
        self.conn.execute("UPDATE catalog_snapshots SET trust = 'trusted_current' WHERE id = ?", (snapshot_id,))
        self._clear_candidates(track_id)
        self._materialize(track_id, units)

    def _materialize(self, track_id: str, units: list[UnitDescriptor]) -> None:
        """Reading Units reflect the trusted catalog; missing units are retained, never deleted (§5.5)."""
        now = utcnow_iso()
        for unit in units:
            self.conn.execute(
                "INSERT INTO reading_units (id, track_id, source_unit_key, raw_title, display_title, unit_type,"
                " source_number, volume, source_order, url_hint, release_date, availability, first_seen_at, last_seen_at,"
                " missing_since) VALUES (?,?,?,?,?,?,?,?,?,?,?, 'available', ?, ?, NULL)"
                " ON CONFLICT(track_id, source_unit_key) DO UPDATE SET raw_title=excluded.raw_title,"
                " display_title=excluded.display_title, unit_type=excluded.unit_type, source_number=excluded.source_number,"
                " volume=excluded.volume, source_order=excluded.source_order, url_hint=excluded.url_hint,"
                " release_date=excluded.release_date, availability='available', last_seen_at=excluded.last_seen_at,"
                " missing_since=NULL",
                (new_id(), track_id, unit.unit_key, unit.raw_title, unit.raw_title, unit.unit_type, unit.number,
                 unit.volume, unit.order_index, unit.url, unit.release_date, now, now))
        keys = [u.unit_key for u in units]
        placeholders = ",".join("?" * len(keys)) or "NULL"
        self.conn.execute(
            f"UPDATE reading_units SET availability = 'unavailable', missing_since = coalesce(missing_since, ?)"
            f" WHERE track_id = ? AND source_unit_key NOT IN ({placeholders})", (now, track_id, *keys))
