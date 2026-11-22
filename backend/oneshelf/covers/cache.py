"""Covers kept on this device, sized for display (Master §26.20 pattern; PERFORMANCE_STUDY.md §3.1).

Before this, every browser, device or cleared browser cache asked the source again for every cover, at the
source's own rate limit, and got the full-size image (up to 4 MiB) for a card 200 pixels wide. Now:

- An image is fetched once, through the source's network policy exactly as before, checked, and reduced to
  at most COVER_WIDTH pixels wide (WebP). Only that reduced copy is kept and served.
- A listing whose cover had to be looked up (`listing_key` requests run the source's `work` recipe) keeps the
  answer, so the next request is one image fetch, or none, instead of a page and an image. A listing that has
  no cover is remembered for a day, so it is not asked again on every scroll.

Like the Reader Cache, this is never library state: it is rebuildable, bounded by size and age, and keyed by
a hash, never by a path or a name a source chose. Nothing here widens what can be fetched: the cache only
ever holds what the cover route already fetched and validated.
"""
from __future__ import annotations

import hashlib
import io
import sqlite3
import threading
import time
import warnings
from collections.abc import Callable
from pathlib import Path

from PIL import Image

from oneshelf.integrity.validators import _IMAGE_SLOTS, _looks_like_html

COVER_WIDTH = 600                          # two to three times a card's width: sharp on high-density screens
COVER_MAX_HEIGHT = 6 * COVER_WIDTH
WEBP_QUALITY = 82
DEFAULT_TTL = 30 * 24 * 3600.0
NEGATIVE_TTL = 24 * 3600.0
DEFAULT_CAP_BYTES = 512 * 1024**2
_MEDIA = {"PNG": "image/png", "JPEG": "image/jpeg", "WEBP": "image/webp"}


def cover_key(source_id: str, url: str) -> str:
    return hashlib.sha256(f"{source_id}\0{url}".encode("utf-8")).hexdigest()


def prepare_cover(data: bytes) -> tuple[bytes, str] | None:
    """The image as it will be shown: checked like any image, and reduced when it is wider than needed.

    None when it is not a usable image. Runs on a worker thread (see `prepare_cover_off_loop`); at most four
    images are decoded at once, shared with every other image check, and Pillow's decompression-bomb guard
    is an error here, as it is in the integrity validator.
    """
    if not data or _looks_like_html(data):
        return None
    with _IMAGE_SLOTS:
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("error", Image.DecompressionBombWarning)
                with Image.open(io.BytesIO(data)) as probe:
                    probe.verify()
                with Image.open(io.BytesIO(data)) as image:
                    media = _MEDIA.get(image.format or "")
                    width, height = image.size
                    if media is None or width < 1 or height < 1:
                        return None
                    if width <= COVER_WIDTH and height <= COVER_MAX_HEIGHT:
                        image.load()                       # a full decode: the bytes are what they claim
                        return data, media
                    image.draft("RGB", (COVER_WIDTH, max(1, height * COVER_WIDTH // width)))   # JPEG: decode small
                    image.load()
                    image.thumbnail((COVER_WIDTH, COVER_MAX_HEIGHT))
                    if image.mode not in ("RGB", "RGBA"):
                        image = image.convert("RGBA" if "A" in image.getbands() or "transparency" in image.info
                                              else "RGB")
                    out = io.BytesIO()
                    image.save(out, "WEBP", quality=WEBP_QUALITY, method=4)
                    return out.getvalue(), "image/webp"
        except Exception:      # Pillow raises many exception types for corrupt or hostile data
            return None


async def prepare_cover_off_loop(data: bytes) -> tuple[bytes, str] | None:
    import asyncio

    return await asyncio.to_thread(prepare_cover, data)


class CoverCache:
    def __init__(self, blob_dir: str | Path, index_path: str | Path, *, ttl_seconds: float = DEFAULT_TTL,
                 cap_bytes: int = DEFAULT_CAP_BYTES, clock: Callable[[], float] = time.time) -> None:
        self.blob_dir = Path(blob_dir)
        self.blob_dir.mkdir(parents=True, exist_ok=True)
        Path(index_path).parent.mkdir(parents=True, exist_ok=True)
        self.ttl, self.cap_bytes, self.clock = ttl_seconds, cap_bytes, clock
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(str(index_path), isolation_level=None, check_same_thread=False)
        self._conn.execute("PRAGMA journal_mode = WAL")
        self._conn.execute(
            "CREATE TABLE IF NOT EXISTS cover_images (key TEXT PRIMARY KEY, path TEXT NOT NULL,"
            " media_type TEXT NOT NULL, size INTEGER NOT NULL, created_at REAL NOT NULL, last_used_at REAL NOT NULL)")
        self._conn.execute("CREATE INDEX IF NOT EXISTS cover_images_used ON cover_images (last_used_at)")
        # A listing's cover address as its `work` recipe gave it; '' records that it has none.
        self._conn.execute(
            "CREATE TABLE IF NOT EXISTS cover_lookups (source_id TEXT NOT NULL, listing_key TEXT NOT NULL,"
            " language TEXT NOT NULL, url TEXT NOT NULL, saved_at REAL NOT NULL,"
            " PRIMARY KEY (source_id, listing_key, language))")
        self._total = self._conn.execute("SELECT coalesce(sum(size), 0) FROM cover_images").fetchone()[0]

    # -- images ------------------------------------------------------------------------------------

    def get(self, key: str) -> tuple[bytes, str] | None:
        now = self.clock()
        with self._lock:
            row = self._conn.execute("SELECT path, media_type, size, created_at FROM cover_images WHERE key = ?",
                                     (key,)).fetchone()
            if row is None:
                return None
            path = Path(row[0])
            if now - row[3] > self.ttl or not path.is_file():
                self._drop(key, path, row[2])
                return None
            self._conn.execute("UPDATE cover_images SET last_used_at = ? WHERE key = ?", (now, key))
        try:
            return path.read_bytes(), row[1]
        except OSError:
            return None

    def put(self, key: str, data: bytes, media_type: str) -> None:
        now = self.clock()
        path = self.blob_dir / key[:2] / key
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".part")
        tmp.write_bytes(data)
        tmp.replace(path)
        with self._lock:
            old = self._conn.execute("SELECT size FROM cover_images WHERE key = ?", (key,)).fetchone()
            self._conn.execute(
                "INSERT INTO cover_images (key, path, media_type, size, created_at, last_used_at) VALUES (?,?,?,?,?,?)"
                " ON CONFLICT(key) DO UPDATE SET path=excluded.path, media_type=excluded.media_type,"
                " size=excluded.size, created_at=excluded.created_at, last_used_at=excluded.last_used_at",
                (key, str(path), media_type, len(data), now, now))
            self._total += len(data) - (old[0] if old else 0)
            self._evict()

    def _drop(self, key: str, path: Path, size: int) -> None:
        path.unlink(missing_ok=True)
        self._conn.execute("DELETE FROM cover_images WHERE key = ?", (key,))
        self._total -= size

    def _evict(self) -> None:
        if self._total <= self.cap_bytes:
            return
        for key, path, size in self._conn.execute(
                "SELECT key, path, size FROM cover_images ORDER BY last_used_at").fetchall():
            if self._total <= self.cap_bytes:
                break
            self._drop(key, Path(path), size)

    # -- listing lookups ---------------------------------------------------------------------------

    def lookup(self, source_id: str, listing_key: str, language: str) -> str | None:
        """The cover address a listing's `work` recipe gave ('' when it gave none), or None if not known."""
        with self._lock:
            row = self._conn.execute("SELECT url, saved_at FROM cover_lookups WHERE source_id = ? AND listing_key = ?"
                                     " AND language = ?", (source_id, listing_key, language)).fetchone()
        if row is None:
            return None
        url, saved = row
        if self.clock() - saved > (self.ttl if url else NEGATIVE_TTL):
            return None
        return url

    def remember_lookup(self, source_id: str, listing_key: str, language: str, url: str) -> None:
        with self._lock:
            self._conn.execute(
                "INSERT INTO cover_lookups (source_id, listing_key, language, url, saved_at) VALUES (?,?,?,?,?)"
                " ON CONFLICT(source_id, listing_key, language) DO UPDATE SET url=excluded.url, saved_at=excluded.saved_at",
                (source_id, listing_key, language, url, self.clock()))

    def total_bytes(self) -> int:
        return self._total

    def close(self) -> None:
        with self._lock:
            self._conn.close()
