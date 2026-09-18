"""Remote Web UI sessions (Master §28.6).

A session is a random token in a cookie; only its hash is stored, so the database never holds anything
that could be replayed. Sessions carry a label the user chose or a plain client hint — never invasive
fingerprinting. Lifetimes are 30 days by default, with shorter, 90-day, one-year and manual options.
"""
from __future__ import annotations

import hashlib
import secrets
import sqlite3
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from oneshelf.db.connection import transaction
from oneshelf.domain.ids import new_id

LIFETIMES: dict[str, timedelta | None] = {
    "7d": timedelta(days=7),
    "30d": timedelta(days=30),
    "90d": timedelta(days=90),
    "1y": timedelta(days=365),
    "manual": None,
}
DEFAULT_LIFETIME = "30d"
COOKIE_NAME = "oneshelf_remote"
TOKEN_BYTES = 32


class SessionError(RuntimeError):
    pass


@dataclass(frozen=True)
class IssuedSession:
    session_id: str
    token: str
    expires_at: str | None


@dataclass(frozen=True)
class RemoteSession:
    id: str
    label: str
    created_at: str
    last_active_at: str
    expires_at: str | None
    current: bool = False


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def cookie_attributes(*, secure: bool) -> dict:
    """§28.6: HttpOnly and SameSite always; Secure on HTTPS. Tokens never go into Web Storage."""
    return {"httponly": True, "secure": secure, "samesite": "lax", "path": "/"}


class RemoteSessions:
    def __init__(self, conn: sqlite3.Connection, *, clock: Callable[[], datetime] = lambda: datetime.now(UTC)) -> None:
        self.conn = conn
        self.clock = clock

    def create(self, *, label: str, lifetime: str = DEFAULT_LIFETIME) -> IssuedSession:
        if lifetime not in LIFETIMES:
            raise SessionError(f"unknown session lifetime {lifetime!r}")
        now = self.clock()
        span = LIFETIMES[lifetime]
        expires = (now + span).isoformat() if span is not None else None
        session_id, token = new_id(), secrets.token_urlsafe(TOKEN_BYTES)
        with transaction(self.conn):
            self.conn.execute(
                "INSERT INTO remote_sessions (id, token_hash, label, created_at, last_active_at, expires_at)"
                " VALUES (?,?,?,?,?,?)",
                (session_id, token_hash(token), label.strip() or "Remote device", now.isoformat(), now.isoformat(),
                 expires))
        return IssuedSession(session_id, token, expires)

    def validate(self, token: str | None) -> RemoteSession | None:
        if not token:
            return None
        now = self.clock()
        row = self.conn.execute(
            "SELECT * FROM remote_sessions WHERE token_hash = ? AND revoked_at IS NULL", (token_hash(token),)
        ).fetchone()
        if row is None:
            return None
        if row["expires_at"] is not None and row["expires_at"] <= now.isoformat():
            return None
        with transaction(self.conn):
            self.conn.execute("UPDATE remote_sessions SET last_active_at = ? WHERE id = ?",
                              (now.isoformat(), row["id"]))
        return RemoteSession(row["id"], row["label"], row["created_at"], now.isoformat(), row["expires_at"], True)

    def list_sessions(self, *, current_token: str | None = None) -> list[RemoteSession]:
        current = token_hash(current_token) if current_token else None
        now = self.clock().isoformat()
        rows = self.conn.execute(
            "SELECT * FROM remote_sessions WHERE revoked_at IS NULL AND (expires_at IS NULL OR expires_at > ?)"
            " ORDER BY created_at", (now,)).fetchall()
        return [RemoteSession(r["id"], r["label"], r["created_at"], r["last_active_at"], r["expires_at"],
                              r["token_hash"] == current) for r in rows]

    def revoke(self, session_id: str) -> bool:
        with transaction(self.conn):
            cursor = self.conn.execute("UPDATE remote_sessions SET revoked_at = ? WHERE id = ? AND revoked_at IS NULL",
                                       (self.clock().isoformat(), session_id))
        return cursor.rowcount > 0

    def revoke_others(self, *, current_token: str | None = None) -> int:
        current = token_hash(current_token) if current_token else ""
        with transaction(self.conn):
            cursor = self.conn.execute(
                "UPDATE remote_sessions SET revoked_at = ? WHERE revoked_at IS NULL AND token_hash != ?",
                (self.clock().isoformat(), current))
        return cursor.rowcount

    def revoke_all(self) -> int:
        return self.revoke_others(current_token=None)
