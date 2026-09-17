"""Idempotent commit journal for final content commits (Master §17).

SQLite and the filesystem are not one atomic transaction, so each commit advances a persisted state:

    pending → moved → verified → registered → done      (or aborted)

Every step can be replayed after a crash. Only a verified final artifact is ever registered
(INV-16), existing files are never overwritten, and unavailable roots are skipped untouched (§24.6).
"""
from __future__ import annotations

import errno
import json
import os
import sqlite3
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Any

from oneshelf.db.connection import transaction
from oneshelf.domain.clock import utcnow_iso
from oneshelf.domain.ids import new_id
from oneshelf.storage.hashing import sha256_file
from oneshelf.storage.paths import PathSafetyError, resolve_within
from oneshelf.storage.roots import check_availability, get_root
from oneshelf.storage.staging import STAGING_PREFIX

FAULT_POINTS = ("after_journal", "after_move", "after_verify", "after_register")
OPEN_STATES = ("pending", "moved", "verified", "registered")

Registrar = Callable[[sqlite3.Connection, dict[str, Any]], None]


class CommitError(RuntimeError):
    pass


class Crash(BaseException):
    """Injected process crash used by tests; deliberately not an Exception subclass."""


@dataclass(frozen=True)
class CommitRequest:
    root_id: str
    staging_relpath: str
    final_relpath: str
    registration: dict[str, Any]  # {"kind": <registrar name>, "payload": {...}}; registrar must be idempotent


@dataclass
class RecoveryReport:
    changed: int = 0
    done: int = 0
    aborted: int = 0
    skipped_unavailable: int = 0
    errors: list[str] = field(default_factory=list)


def _fsync_dir(path: str) -> None:
    fd = os.open(path, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def _matches(path: str, sha: str, size: int) -> bool:
    if not os.path.isfile(path) or os.path.islink(path):
        return False
    return sha256_file(path) == (sha, size)


def _move_no_replace(src: str, dst: str) -> None:
    try:
        os.link(src, dst)
    except FileExistsError:
        raise
    except OSError as exc:
        if exc.errno not in {errno.EPERM, errno.EOPNOTSUPP, errno.ENOTSUP, errno.EMLINK}:
            raise
        if os.path.lexists(dst):
            raise FileExistsError(dst) from exc
        os.rename(src, dst)
        return
    os.unlink(src)


class CommitEngine:
    def __init__(
        self,
        conn: sqlite3.Connection,
        registrars: Mapping[str, Registrar],
        fault: Callable[[str], None] | None = None,
    ) -> None:
        self.conn = conn
        self.registrars = registrars
        self.fault = fault or (lambda _point: None)

    # -- public API ---------------------------------------------------------------------------

    def commit(self, request: CommitRequest) -> str:
        root = get_root(self.conn, request.root_id)
        availability = check_availability(root)
        if not availability.available:
            raise CommitError(f"storage location unavailable ({availability.reason})")
        if not request.staging_relpath.startswith(STAGING_PREFIX):
            raise CommitError("staged artifact must live in the root's staging area")
        if request.registration.get("kind") not in self.registrars:
            raise CommitError(f"no registrar for {request.registration.get('kind')!r}")
        try:
            staged = str(resolve_within(root.path, request.staging_relpath))
            final = str(resolve_within(root.path, request.final_relpath))
        except PathSafetyError as exc:
            raise CommitError(str(exc)) from exc
        if not os.path.isfile(staged) or os.path.islink(staged):
            raise CommitError("staged artifact is missing or not a regular file")
        if os.path.lexists(final):
            raise CommitError("final path already exists; refusing to overwrite")
        with open(staged, "rb") as f:
            os.fsync(f.fileno())
        sha, size = sha256_file(staged)

        journal_id = new_id()
        now = utcnow_iso()
        with transaction(self.conn):
            self.conn.execute(
                "INSERT INTO commit_journal (id, storage_root_id, staging_relpath, final_relpath, expected_sha256,"
                " expected_size, registration_json, state, created_at, updated_at)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, 'pending', ?, ?)",
                (journal_id, root.id, request.staging_relpath, request.final_relpath, sha, size,
                 json.dumps(request.registration), now, now),
            )
        self.fault("after_journal")
        state = self._advance(journal_id)
        if state != "done":
            row = self._row(journal_id)
            raise CommitError(f"commit {state}: {row['error']}")
        return journal_id

    def recover(self) -> RecoveryReport:
        report = RecoveryReport()
        placeholders = ",".join("?" * len(OPEN_STATES))
        rows = self.conn.execute(
            f"SELECT id, storage_root_id, state FROM commit_journal WHERE state IN ({placeholders}) ORDER BY created_at",
            OPEN_STATES,
        ).fetchall()
        for row in rows:
            root = get_root(self.conn, row["storage_root_id"])
            if not check_availability(root).available:
                report.skipped_unavailable += 1
                continue
            try:
                final_state = self._advance(row["id"])
            except Exception as exc:  # one bad entry must not block recovery of the others or startup
                report.errors.append(f"{row['id']}: {exc}")
                with transaction(self.conn):
                    self.conn.execute(
                        "UPDATE commit_journal SET error = ?, updated_at = ? WHERE id = ?",
                        (f"recovery failed: {exc}", utcnow_iso(), row["id"]),
                    )
                continue
            if final_state != row["state"]:
                report.changed += 1
            if final_state == "done":
                report.done += 1
            elif final_state == "aborted":
                report.aborted += 1
        return report

    # -- state machine ------------------------------------------------------------------------

    def _row(self, journal_id: str) -> sqlite3.Row:
        return self.conn.execute("SELECT * FROM commit_journal WHERE id = ?", (journal_id,)).fetchone()

    def _set_state(self, journal_id: str, state: str, error: str | None = None) -> None:
        with transaction(self.conn):
            self.conn.execute(
                "UPDATE commit_journal SET state = ?, error = ?, updated_at = ? WHERE id = ?",
                (state, error, utcnow_iso(), journal_id),
            )

    def _advance(self, journal_id: str) -> str:
        while True:
            row = self._row(journal_id)
            state = row["state"]
            if state in ("done", "aborted"):
                return state
            root = get_root(self.conn, row["storage_root_id"])
            staged = str(resolve_within(root.path, row["staging_relpath"]))
            final = str(resolve_within(root.path, row["final_relpath"]))
            sha, size = row["expected_sha256"], row["expected_size"]

            if state == "pending":
                if _matches(final, sha, size):
                    if os.path.lexists(staged):
                        os.unlink(staged)  # crash between link and unlink; final copy is verified
                    self._set_state(journal_id, "moved")
                elif os.path.lexists(final):
                    self._set_state(journal_id, "aborted", "final path occupied by different content")
                elif _matches(staged, sha, size):
                    parent = os.path.dirname(final)
                    os.makedirs(parent, exist_ok=True)
                    resolve_within(root.path, row["final_relpath"])  # re-check: no symlink appeared
                    _move_no_replace(staged, final)
                    _fsync_dir(parent)
                    self._set_state(journal_id, "moved")
                    self.fault("after_move")
                else:
                    self._set_state(journal_id, "aborted", "staged artifact missing or changed before move")
            elif state == "moved":
                if _matches(final, sha, size):
                    self._set_state(journal_id, "verified")
                    self.fault("after_verify")
                else:
                    self._set_state(journal_id, "aborted", "final artifact failed verification; not registered")
            elif state == "verified":
                registration = json.loads(row["registration_json"])
                registrar = self.registrars.get(registration["kind"])
                if registrar is None:
                    raise CommitError(f"no registrar for {registration['kind']!r}")
                with transaction(self.conn):
                    registrar(self.conn, registration["payload"])
                    self.conn.execute(
                        "UPDATE commit_journal SET state = 'registered', error = NULL, updated_at = ? WHERE id = ?",
                        (utcnow_iso(), journal_id),
                    )
                self.fault("after_register")
            elif state == "registered":
                if os.path.lexists(staged) and not os.path.islink(staged):
                    os.unlink(staged)
                self._set_state(journal_id, "done")
