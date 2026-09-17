"""Forward-only, transactional schema migrations with a consistent pre-migration snapshot.

- Each migration runs in its own transaction (SQLite DDL is transactional), so a failure leaves the
  database at the previous version and a re-run resumes cleanly.
- Before changing an existing database, a consistent copy is taken with the SQLite online backup API
  (never a raw copy of a live file, Master §18).
- A database whose schema is newer than this build knows is refused unchanged (Master §33.5).
"""
from __future__ import annotations

import sqlite3
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from oneshelf.db.connection import open_database


class MigrationError(RuntimeError):
    pass


class NewerSchemaError(MigrationError):
    pass


@dataclass(frozen=True)
class Migration:
    version: int
    name: str
    sql: str


_META_DDL = """CREATE TABLE IF NOT EXISTS schema_migrations (
    version INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    applied_at TEXT NOT NULL
)"""


def split_statements(sql: str) -> list[str]:
    statements, buffer = [], ""
    for line in sql.splitlines(keepends=True):
        buffer += line
        if sqlite3.complete_statement(buffer):
            if buffer.strip():
                statements.append(buffer.strip())
            buffer = ""
    if buffer.strip():
        raise MigrationError(f"incomplete SQL statement: {buffer.strip()[:80]!r}")
    return statements


def _read_version(conn: sqlite3.Connection) -> int:
    exists = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='schema_migrations'"
    ).fetchone()
    if not exists:
        return 0
    return conn.execute("SELECT coalesce(max(version), 0) FROM schema_migrations").fetchone()[0]


def current_version(db_path: str | Path) -> int:
    with open_database(db_path) as conn:
        return _read_version(conn)


def _validate(migrations: Sequence[Migration]) -> None:
    for expected, migration in enumerate(migrations, start=1):
        if migration.version != expected:
            raise MigrationError(
                f"migrations must be contiguous from 1; expected {expected}, got {migration.version}"
            )


def snapshot(conn: sqlite3.Connection, destination: Path) -> Path:
    destination.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(str(destination)) as target:
        conn.backup(target)
    target.close()
    return destination


def migrate(db_path: str | Path, migrations: Sequence[Migration], *, snapshot_dir: Path) -> list[int]:
    _validate(migrations)
    latest = len(migrations)
    applied: list[int] = []
    with open_database(db_path) as conn:
        current = _read_version(conn)
        if current > latest:
            raise NewerSchemaError(
                f"database schema v{current} is newer than this OneShelf build (v{latest}); update OneShelf"
            )
        pending = migrations[current:]
        if not pending:
            return applied
        if current > 0:
            stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
            snapshot(conn, snapshot_dir / f"pre-migration-v{current}-{stamp}.db")
        conn.execute(_META_DDL)
        for migration in pending:
            conn.execute("BEGIN IMMEDIATE")
            try:
                for statement in split_statements(migration.sql):
                    conn.execute(statement)
                conn.execute(
                    "INSERT INTO schema_migrations (version, name, applied_at) VALUES (?, ?, ?)",
                    (migration.version, migration.name, datetime.now(UTC).isoformat()),
                )
            except Exception as exc:
                conn.execute("ROLLBACK")
                raise MigrationError(
                    f"migration v{migration.version} ({migration.name}) failed: {exc}"
                ) from exc
            conn.execute("COMMIT")
            applied.append(migration.version)
    return applied
