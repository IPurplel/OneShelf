"""Discovery Cache (Master §7): rebuildable, namespaced by source + plugin version, TTL and size capped.

Only hashed keys are stored, so cached search results never become a persistent query history (§7, C15).
The cache lives in its own database file and never holds authoritative state, so cleanup can never remove
Shelf, Follow, Downloads, mappings or manual corrections.
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
import threading
import time
from collections.abc import Callable
from pathlib import Path

from oneshelf.settings.defaults import DEFAULTS


class DiscoveryCache:
    def __init__(self, path: str | Path, *, ttl_seconds: float | None = None, cap_bytes: int | None = None,
                 clock: Callable[[], float] = time.time) -> None:
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.ttl = ttl_seconds if ttl_seconds is not None else DEFAULTS.discovery_cache.ttl.total_seconds()
        self.cap_bytes = cap_bytes if cap_bytes is not None else DEFAULTS.discovery_cache.cap_bytes
        self.clock = clock
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(str(path), isolation_level=None, check_same_thread=False)
        self._conn.execute("PRAGMA journal_mode = WAL")
        self._conn.execute(
            "CREATE TABLE IF NOT EXISTS entries (namespace TEXT NOT NULL, kind TEXT NOT NULL, key_hash TEXT NOT NULL,"
            " payload BLOB NOT NULL, size INTEGER NOT NULL, created_at REAL NOT NULL, last_used_at REAL NOT NULL,"
            " PRIMARY KEY (namespace, kind, key_hash))")

    @staticmethod
    def namespace(source_id: str, plugin_version: str) -> str:
        return f"{source_id}@{plugin_version}"

    @staticmethod
    def _hash(key: str) -> str:
        return hashlib.sha256(key.encode("utf-8")).hexdigest()

    def put(self, source_id: str, plugin_version: str, kind: str, key: str, payload: dict) -> None:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        now = self.clock()
        with self._lock:
            self._conn.execute(
                "INSERT INTO entries (namespace, kind, key_hash, payload, size, created_at, last_used_at)"
                " VALUES (?,?,?,?,?,?,?) ON CONFLICT(namespace, kind, key_hash) DO UPDATE SET payload=excluded.payload,"
                " size=excluded.size, created_at=excluded.created_at, last_used_at=excluded.last_used_at",
                (self.namespace(source_id, plugin_version), kind, self._hash(key), data, len(data), now, now))
            self._evict()

    def get(self, source_id: str, plugin_version: str, kind: str, key: str) -> dict | None:
        namespace, key_hash, now = self.namespace(source_id, plugin_version), self._hash(key), self.clock()
        with self._lock:
            row = self._conn.execute(
                "SELECT payload, created_at FROM entries WHERE namespace = ? AND kind = ? AND key_hash = ?",
                (namespace, kind, key_hash)).fetchone()
            if row is None:
                return None
            if now - row[1] > self.ttl:
                self._conn.execute("DELETE FROM entries WHERE namespace = ? AND kind = ? AND key_hash = ?",
                                   (namespace, kind, key_hash))
                return None
            self._conn.execute("UPDATE entries SET last_used_at = ? WHERE namespace = ? AND kind = ? AND key_hash = ?",
                               (now, namespace, kind, key_hash))
            return json.loads(row[0])

    def _evict(self) -> None:
        total = self._conn.execute("SELECT coalesce(sum(size), 0) FROM entries").fetchone()[0]
        while total > self.cap_bytes:
            row = self._conn.execute(
                "SELECT namespace, kind, key_hash, size FROM entries ORDER BY last_used_at LIMIT 1").fetchone()
            if row is None:
                return
            self._conn.execute("DELETE FROM entries WHERE namespace = ? AND kind = ? AND key_hash = ?", tuple(row[:3]))
            total -= row[3]

    def clear_source(self, source_id: str) -> None:
        with self._lock:
            self._conn.execute("DELETE FROM entries WHERE namespace LIKE ?", (f"{source_id}@%",))

    def clear(self) -> None:
        with self._lock:
            self._conn.execute("DELETE FROM entries")

    def count(self) -> int:
        with self._lock:
            return self._conn.execute("SELECT count(*) FROM entries").fetchone()[0]

    def total_bytes(self) -> int:
        with self._lock:
            return self._conn.execute("SELECT coalesce(sum(size), 0) FROM entries").fetchone()[0]

    def close(self) -> None:
        with self._lock:
            self._conn.close()
