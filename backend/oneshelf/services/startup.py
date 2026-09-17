"""Startup recovery in the order required by Master §17 and §25."""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field
from datetime import datetime

from oneshelf.db.connection import transaction
from oneshelf.domain.clock import utcnow_iso
from oneshelf.services.registrars import all_registrars
from oneshelf.storage.commit import OPEN_STATES, CommitEngine, RecoveryReport
from oneshelf.storage.scanner import ScanReport, reconcile
from oneshelf.storage.staging_cleanup import clean_orphan_staging


@dataclass
class StartupReport:
    order: list[str] = field(default_factory=list)
    jobs_failed: int = 0
    commits: RecoveryReport = field(default_factory=RecoveryReport)
    scan: ScanReport = field(default_factory=ScanReport)
    staging_removed: int = 0


def _fail_interrupted_imports(conn: sqlite3.Connection, states: tuple[str, ...]) -> int:
    placeholders = ",".join("?" * len(states))
    open_placeholders = ",".join("?" * len(OPEN_STATES))
    with transaction(conn):
        cur = conn.execute(
            f"UPDATE imports SET state = 'failed', error = 'interrupted', updated_at = ?"
            f" WHERE state IN ({placeholders}) AND id NOT IN ("
            f"   SELECT json_extract(registration_json, '$.payload.import_id') FROM commit_journal"
            f"   WHERE state IN ({open_placeholders}) AND json_extract(registration_json, '$.payload.import_id') IS NOT NULL)",
            (utcnow_iso(), *states, *OPEN_STATES),
        )
    return cur.rowcount


def run_startup_recovery(conn: sqlite3.Connection, *, now: datetime | None = None) -> StartupReport:
    report = StartupReport()

    report.order.append("recover_jobs")
    report.jobs_failed += _fail_interrupted_imports(conn, ("validating",))

    report.order.append("recover_commits")
    report.commits = CommitEngine(conn, registrars=all_registrars()).recover()
    report.jobs_failed += _fail_interrupted_imports(conn, ("committing",))

    report.order.append("reconcile")
    report.scan = reconcile(conn)

    report.order.append("clean_staging")
    report.staging_removed = clean_orphan_staging(conn, now=now)
    return report
