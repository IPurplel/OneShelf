"""Encrypted source-session storage (Master §13, §33.3).

- secrets.db is separate from the library database and never part of backups or exports.
- Each session is AES-256-GCM encrypted with a key stored in a separate key file (own directory, 0600),
  and bound to its source id through authenticated data, so rows cannot be swapped between sources.
- secure_delete + rollback journal: disconnect removes the bytes rather than leaving them in free pages.
"""
from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import threading
from dataclasses import dataclass, field
from pathlib import Path

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from oneshelf.domain.clock import utcnow_iso

KEY_BYTES = 32


class SessionUnreadable(RuntimeError):
    """Stored session cannot be decrypted (missing/rotated key or tampering)."""


def load_or_create_key(path: str | Path) -> bytes:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    os.chmod(path.parent, 0o700)
    if path.exists():
        key = path.read_bytes()
        if len(key) != KEY_BYTES:
            raise ValueError("session key file is invalid")
        return key
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        key = os.urandom(KEY_BYTES)
        os.write(fd, key)
        os.fsync(fd)
    finally:
        os.close(fd)
    return key


@dataclass
class SessionState:
    """Browser-compatible storage state (Playwright format) plus captured sessionStorage per origin."""

    storage_state: dict = field(default_factory=lambda: {"cookies": [], "origins": []})
    session_storage: dict[str, dict[str, str]] = field(default_factory=dict)

    def __repr__(self) -> str:
        cookies = len(self.storage_state.get("cookies", []))
        origins = len(self.storage_state.get("origins", []))
        return f"SessionState(<redacted: {cookies} cookies, {origins} origins>)"

    __str__ = __repr__

    def to_json(self) -> bytes:
        return json.dumps({"storage_state": self.storage_state, "session_storage": self.session_storage}).encode()

    @classmethod
    def from_json(cls, data: bytes) -> SessionState:
        raw = json.loads(data)
        return cls(storage_state=raw["storage_state"], session_storage=raw.get("session_storage", {}))


class SecretsStore:
    def __init__(self, path: str | Path, key: bytes) -> None:
        if len(key) != KEY_BYTES:
            raise ValueError("invalid session key")
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self._aead = AESGCM(key)
        self._key_id = hashlib.sha256(key).hexdigest()[:16]
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(str(path), isolation_level=None, check_same_thread=False)
        self._conn.execute("PRAGMA secure_delete = ON")
        self._conn.execute("PRAGMA journal_mode = DELETE")
        self._conn.execute("PRAGMA synchronous = FULL")
        self._conn.execute(
            "CREATE TABLE IF NOT EXISTS source_sessions (source_id TEXT PRIMARY KEY, key_id TEXT NOT NULL,"
            " nonce BLOB NOT NULL, ciphertext BLOB NOT NULL, updated_at TEXT NOT NULL)"
        )
        try:
            os.chmod(path, 0o600)
        except OSError:
            pass

    @staticmethod
    def _aad(source_id: str) -> bytes:
        return b"oneshelf-session-v1:" + source_id.encode("utf-8")

    def put(self, source_id: str, state: SessionState) -> None:
        nonce = os.urandom(12)
        ciphertext = self._aead.encrypt(nonce, state.to_json(), self._aad(source_id))
        with self._lock:
            self._conn.execute("BEGIN IMMEDIATE")
            try:
                self._conn.execute(
                    "INSERT INTO source_sessions (source_id, key_id, nonce, ciphertext, updated_at) VALUES (?,?,?,?,?)"
                    " ON CONFLICT(source_id) DO UPDATE SET key_id=excluded.key_id, nonce=excluded.nonce,"
                    " ciphertext=excluded.ciphertext, updated_at=excluded.updated_at",
                    (source_id, self._key_id, nonce, ciphertext, utcnow_iso()),
                )
            except BaseException:
                self._conn.execute("ROLLBACK")
                raise
            self._conn.execute("COMMIT")

    def get(self, source_id: str) -> SessionState | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT key_id, nonce, ciphertext FROM source_sessions WHERE source_id = ?", (source_id,)
            ).fetchone()
        if row is None:
            return None
        key_id, nonce, ciphertext = row
        if key_id != self._key_id:
            raise SessionUnreadable("session was encrypted with a different key")
        try:
            return SessionState.from_json(self._aead.decrypt(nonce, ciphertext, self._aad(source_id)))
        except (InvalidTag, ValueError, KeyError) as exc:
            raise SessionUnreadable("session data could not be decrypted") from exc

    def delete(self, source_id: str) -> None:
        with self._lock:
            self._conn.execute("DELETE FROM source_sessions WHERE source_id = ?", (source_id,))

    def close(self) -> None:
        with self._lock:
            self._conn.close()
