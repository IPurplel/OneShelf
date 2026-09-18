"""Recovery Code (Master §28.5).

The code is shown once and kept only as a scrypt verifier. It never logs anyone in: it authorizes
registering a new passkey after passkey loss. Regenerating replaces the verifier, so the old code dies.
"""
from __future__ import annotations

import hashlib
import hmac
import secrets
import sqlite3
from collections.abc import Callable
from datetime import UTC, datetime

from oneshelf.db.connection import transaction

ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"   # no look-alike characters; the user reads this off a screen
GROUPS, GROUP_SIZE = 5, 5
SCRYPT = {"n": 2**14, "r": 8, "p": 1, "dklen": 32}


def _normalize(code: str) -> str:
    return "".join(ch for ch in code.upper() if ch.isalnum())


class RecoveryCodes:
    def __init__(self, conn: sqlite3.Connection, *, clock: Callable[[], datetime] = lambda: datetime.now(UTC)) -> None:
        self.conn = conn
        self.clock = clock

    def _row(self) -> sqlite3.Row | None:
        return self.conn.execute("SELECT * FROM remote_recovery WHERE id = 1").fetchone()

    def _verifier(self, code: str, salt: bytes) -> str:
        return hashlib.scrypt(_normalize(code).encode("ascii"), salt=salt, **SCRYPT).hex()

    def generate(self) -> str:
        """Returns the new code once; the previous one stops working immediately."""
        code = "-".join("".join(secrets.choice(ALPHABET) for _ in range(GROUP_SIZE)) for _ in range(GROUPS))
        salt = secrets.token_bytes(16)
        now = self.clock().isoformat()
        with transaction(self.conn):
            self.conn.execute(
                "INSERT INTO remote_recovery (id, verifier, salt, created_at, used_at) VALUES (1, ?, ?, ?, NULL)"
                " ON CONFLICT(id) DO UPDATE SET verifier = excluded.verifier, salt = excluded.salt,"
                " created_at = excluded.created_at, used_at = NULL",
                (self._verifier(code, salt), salt.hex(), now))
        return code

    def verify(self, code: str) -> bool:
        row = self._row()
        if row is None or not _normalize(code or ""):
            return False
        return hmac.compare_digest(self._verifier(code, bytes.fromhex(row["salt"])), row["verifier"])

    def mark_used(self) -> None:
        with transaction(self.conn):
            self.conn.execute("UPDATE remote_recovery SET used_at = ? WHERE id = 1", (self.clock().isoformat(),))

    def status(self) -> dict:
        row = self._row()
        return {"configured": row is not None,
                "created_at": row["created_at"] if row else None,
                "last_used_at": row["used_at"] if row else None}
