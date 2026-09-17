"""Temporary Reader Cache (Master §26.20, §42).

A cache entry is never a permanent download. Identity is source + Reading Unit identity + resource
identity/validator, never a title or display number. Eviction is LRU within the cap and never evicts
the units the Reader is currently showing.
"""
from __future__ import annotations

import hashlib
import sqlite3
import threading
import time
from collections.abc import Callable
from pathlib import Path

from oneshelf.settings.defaults import DEFAULTS


class ReaderCache:
    def __init__(self, blob_dir: str | Path, index_path: str | Path, *, ttl_seconds: float | None = None,
                 cap_bytes: int | None = None, clock: Callable[[], float] = time.time) -> None:
        self.blob_dir = Path(blob_dir)
        self.blob_dir.mkdir(parents=True, exist_ok=True)
        Path(index_path).parent.mkdir(parents=True, exist_ok=True)
        self.ttl = ttl_seconds if ttl_seconds is not None else DEFAULTS.reader_cache.ttl.total_seconds()
        self.cap_bytes = cap_bytes if cap_bytes is not None else DEFAULTS.reader_cache.cap_bytes
        self.clock = clock
        self._protected: set[str] = set()
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(str(index_path), isolation_level=None, check_same_thread=False)
        self._conn.execute("PRAGMA journal_mode = WAL")
        self._conn.execute(
            "CREATE TABLE IF NOT EXISTS reader_cache (key TEXT PRIMARY KEY, source_id TEXT NOT NULL,"
            " unit_key TEXT NOT NULL, path TEXT NOT NULL, size INTEGER NOT NULL, created_at REAL NOT NULL,"
            " last_used_at REAL NOT NULL)")

    @staticmethod
    def key(source_id: str, unit_key: str, url: str, validator: str | None) -> str:
        digest = hashlib.sha256(url.encode("utf-8")).hexdigest()[:16]
        return f"{source_id}|{unit_key}|{digest}|{validator or ''}"

    def protect(self, unit_keys: list[str] | set[str]) -> None:
        """Units currently open in the Reader are never evicted (§42 Reader Cache)."""
        self._protected = set(unit_keys)

    def get(self, source_id: str, unit_key: str, url: str, validator: str | None = None) -> bytes | None:
        key, now = self.key(source_id, unit_key, url, validator), self.clock()
        with self._lock:
            row = self._conn.execute("SELECT path, created_at FROM reader_cache WHERE key = ?", (key,)).fetchone()
            if row is None:
                return None
            path = Path(row[0])
            if now - row[1] > self.ttl or not path.is_file():
                self._conn.execute("DELETE FROM reader_cache WHERE key = ?", (key,))
                path.unlink(missing_ok=True)
                return None
            self._conn.execute("UPDATE reader_cache SET last_used_at = ? WHERE key = ?", (now, key))
            return path.read_bytes()

    def put(self, source_id: str, unit_key: str, url: str, data: bytes, validator: str | None = None) -> None:
        key, now = self.key(source_id, unit_key, url, validator), self.clock()
        digest = hashlib.sha256(key.encode("utf-8")).hexdigest()
        path = self.blob_dir / digest[:2] / digest
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        with self._lock:
            self._conn.execute(
                "INSERT INTO reader_cache (key, source_id, unit_key, path, size, created_at, last_used_at)"
                " VALUES (?,?,?,?,?,?,?) ON CONFLICT(key) DO UPDATE SET path=excluded.path, size=excluded.size,"
                " created_at=excluded.created_at, last_used_at=excluded.last_used_at",
                (key, source_id, unit_key, str(path), len(data), now, now))
        self.evict()

    def evict(self) -> int:
        removed = 0
        with self._lock:
            total = self._conn.execute("SELECT coalesce(sum(size), 0) FROM reader_cache").fetchone()[0]
            if total <= self.cap_bytes:
                return 0
            rows = self._conn.execute("SELECT key, unit_key, path, size FROM reader_cache ORDER BY last_used_at").fetchall()
            for key, unit_key, path, size in rows:
                if total <= self.cap_bytes:
                    break
                if unit_key in self._protected:
                    continue
                Path(path).unlink(missing_ok=True)
                self._conn.execute("DELETE FROM reader_cache WHERE key = ?", (key,))
                total -= size
                removed += 1
        return removed

    def keys(self) -> list[str]:
        with self._lock:
            return [r[0] for r in self._conn.execute("SELECT key FROM reader_cache ORDER BY last_used_at")]

    def count(self) -> int:
        with self._lock:
            return self._conn.execute("SELECT count(*) FROM reader_cache").fetchone()[0]

    def total_bytes(self) -> int:
        with self._lock:
            return self._conn.execute("SELECT coalesce(sum(size), 0) FROM reader_cache").fetchone()[0]

    def clear(self) -> None:
        with self._lock:
            for (path,) in self._conn.execute("SELECT path FROM reader_cache"):
                Path(path).unlink(missing_ok=True)
            self._conn.execute("DELETE FROM reader_cache")

    def close(self) -> None:
        with self._lock:
            self._conn.close()
