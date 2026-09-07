"""SQLite persistence.

Holds the library (series/chapters seen), per-chapter download state used for
resuming, and the harvested Cloudflare session. Deliberately schema-light: the
CBZ files on disk are the real artifact, this database only exists so an
interrupted run can pick up where it stopped.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

import aiosqlite

SCHEMA_VERSION = 2

_SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS series (
    url         TEXT PRIMARY KEY,
    title       TEXT NOT NULL,
    source      TEXT NOT NULL,
    cover_url   TEXT,
    author      TEXT,
    description TEXT,
    added_at    REAL NOT NULL,
    updated_at  REAL NOT NULL,
    -- When this series first finished a chapter, and the only thing that puts
    -- it in the Library. Previewing writes a series row too -- that is how the
    -- Add view knows which chapters you already hold -- so row existence cannot
    -- mean "in the library", or merely clicking a search result files a series
    -- you have never downloaded. NULL until a download completes.
    first_download_at REAL
);

CREATE TABLE IF NOT EXISTS chapters (
    url         TEXT PRIMARY KEY,
    series_url  TEXT NOT NULL REFERENCES series(url) ON DELETE CASCADE,
    title       TEXT NOT NULL,
    number      TEXT,
    idx         INTEGER NOT NULL,
    status      TEXT NOT NULL DEFAULT 'pending',
    pages_total INTEGER DEFAULT 0,
    output_path TEXT,
    error       TEXT,
    updated_at  REAL NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_chapters_series ON chapters(series_url);
CREATE INDEX IF NOT EXISTS idx_chapters_status ON chapters(status);

CREATE TABLE IF NOT EXISTS sessions (
    host       TEXT PRIMARY KEY,
    cookies    TEXT NOT NULL,
    user_agent TEXT NOT NULL,
    updated_at REAL NOT NULL
);
"""


class Database:
    def __init__(self, path: Path) -> None:
        self._path = path
        self._conn: aiosqlite.Connection | None = None

    async def connect(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = await aiosqlite.connect(self._path)
        self._conn.row_factory = aiosqlite.Row
        # WAL keeps the UI's reads from blocking on the download workers' writes.
        await self._conn.execute("PRAGMA journal_mode=WAL")
        await self._conn.execute("PRAGMA foreign_keys=ON")
        await self._conn.executescript(_SCHEMA)
        await self._migrate()
        await self._conn.execute(
            "INSERT INTO meta(key, value) VALUES('schema_version', ?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (str(SCHEMA_VERSION),),
        )
        await self._conn.commit()

    async def _migrate(self) -> None:
        """Bring an existing database up to the current schema.

        ``CREATE TABLE IF NOT EXISTS`` does nothing to a table that already
        exists, so a new column has to be added explicitly or every install that
        predates it keeps the old shape and every query naming the column fails.
        """
        cursor = await self.conn.execute("PRAGMA table_info(series)")
        columns = {row["name"] for row in await cursor.fetchall()}

        if "first_download_at" not in columns:
            await self.conn.execute(
                "ALTER TABLE series ADD COLUMN first_download_at REAL"
            )
            # Backfill from what the chapters already record, so an existing
            # library does not empty itself on upgrade. A series whose files
            # were all deleted has neither a 'done' chapter nor a recorded path
            # and is, in the database, indistinguishable from one that was only
            # ever previewed — it drops out of the Library and comes back the
            # first time anything is downloaded again.
            await self.conn.execute(
                """
                UPDATE series
                   SET first_download_at = updated_at
                 WHERE first_download_at IS NULL
                   AND EXISTS (SELECT 1 FROM chapters c
                                WHERE c.series_url = series.url
                                  AND (c.status = 'done'
                                       OR c.output_path IS NOT NULL))
                """
            )
            await self.conn.commit()

    async def close(self) -> None:
        if self._conn is not None:
            await self._conn.close()
            self._conn = None

    @property
    def conn(self) -> aiosqlite.Connection:
        if self._conn is None:
            raise RuntimeError("Database.connect() must be awaited before use")
        return self._conn

    # ------------------------------------------------------------------ series

    async def upsert_series(self, series: Any) -> None:
        now = time.time()
        await self.conn.execute(
            """
            INSERT INTO series(url, title, source, cover_url, author, description,
                               added_at, updated_at)
            VALUES(?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(url) DO UPDATE SET
                title=excluded.title,
                source=excluded.source,
                cover_url=COALESCE(excluded.cover_url, series.cover_url),
                author=COALESCE(excluded.author, series.author),
                description=COALESCE(excluded.description, series.description),
                updated_at=excluded.updated_at
            """,
            (
                series.url, series.title, series.source, series.cover_url,
                series.author, series.description, now, now,
            ),
        )
        await self.conn.commit()

    async def list_series(self, *, downloaded_only: bool = True) -> list[dict[str, Any]]:
        """The Library: series that have finished at least one chapter.

        Previewing a URL writes a series row as well — that is what lets the Add
        view show which chapters you already hold — so listing every row put
        anything you merely *clicked on* into the Library. ``first_download_at``
        is the distinction; pass ``downloaded_only=False`` to see everything the
        database has, which is only useful for diagnostics.
        """
        cursor = await self.conn.execute(
            f"""
            SELECT s.*,
                   (SELECT COUNT(*) FROM chapters c WHERE c.series_url = s.url) AS chapter_count,
                   (SELECT COUNT(*) FROM chapters c WHERE c.series_url = s.url
                      AND c.status = 'done') AS downloaded_count
            FROM series s
            {"WHERE s.first_download_at IS NOT NULL" if downloaded_only else ""}
            ORDER BY s.updated_at DESC
            """
        )
        return [dict(row) for row in await cursor.fetchall()]

    async def delete_series(self, url: str) -> None:
        await self.conn.execute("DELETE FROM series WHERE url = ?", (url,))
        await self.conn.commit()

    # ---------------------------------------------------------------- chapters

    async def upsert_chapters(self, series_url: str, chapters: list[Any]) -> None:
        now = time.time()
        # Preserve existing status so re-scanning a series never resets progress.
        await self.conn.executemany(
            """
            INSERT INTO chapters(url, series_url, title, number, idx, updated_at)
            VALUES(?, ?, ?, ?, ?, ?)
            ON CONFLICT(url) DO UPDATE SET
                title=excluded.title,
                number=excluded.number,
                idx=excluded.idx,
                updated_at=excluded.updated_at
            """,
            [
                (c.url, series_url, c.title, c.number, c.index, now)
                for c in chapters
            ],
        )
        await self.conn.commit()

    async def get_chapter_states(self, series_url: str) -> dict[str, dict[str, Any]]:
        cursor = await self.conn.execute(
            "SELECT * FROM chapters WHERE series_url = ? ORDER BY idx", (series_url,)
        )
        return {row["url"]: dict(row) for row in await cursor.fetchall()}

    async def set_chapter_status(
        self,
        url: str,
        status: str,
        *,
        pages_total: int | None = None,
        output_path: str | None = None,
        error: str | None = None,
    ) -> None:
        await self.conn.execute(
            """
            UPDATE chapters
               SET status = ?,
                   pages_total = COALESCE(?, pages_total),
                   output_path = COALESCE(?, output_path),
                   error = ?,
                   updated_at = ?
             WHERE url = ?
            """,
            (status, pages_total, output_path, error, time.time(), url),
        )
        if status == "done":
            # Stamped here rather than at the five call sites that finish a
            # chapter, so a new download path cannot forget to join the library.
            await self.conn.execute(
                """
                UPDATE series
                   SET first_download_at = COALESCE(first_download_at, ?)
                 WHERE url = (SELECT series_url FROM chapters WHERE url = ?)
                """,
                (time.time(), url),
            )
        await self.conn.commit()

    async def clear_chapter_downloads(self, urls: list[str]) -> int:
        """Mark chapters as no longer downloaded, after their files were deleted.

        A separate method rather than :meth:`set_chapter_status` because that
        one ``COALESCE``s ``output_path``, so it cannot blank a value — it
        would leave a recorded path pointing at a file that no longer exists,
        and the Library would keep counting the chapter as downloaded.
        """
        if not urls:
            return 0
        placeholders = ",".join("?" for _ in urls)
        cursor = await self.conn.execute(
            f"""
            UPDATE chapters
               SET status = 'pending',
                   output_path = NULL,
                   error = NULL,
                   pages_total = 0,
                   updated_at = ?
             WHERE url IN ({placeholders})
            """,
            (time.time(), *urls),
        )
        await self.conn.commit()
        return cursor.rowcount or 0

    async def reset_running_chapters(self) -> int:
        """Recover from an unclean shutdown.

        Anything still marked ``running`` at startup was interrupted mid-flight,
        so demote it to ``pending`` and let the queue redo it.
        """
        cursor = await self.conn.execute(
            "UPDATE chapters SET status = 'pending' WHERE status = 'running'"
        )
        await self.conn.commit()
        return cursor.rowcount or 0

    # ---------------------------------------------------------------- sessions

    async def save_session(self, host: str, cookies: list[dict], user_agent: str) -> None:
        await self.conn.execute(
            """
            INSERT INTO sessions(host, cookies, user_agent, updated_at)
            VALUES(?, ?, ?, ?)
            ON CONFLICT(host) DO UPDATE SET
                cookies=excluded.cookies,
                user_agent=excluded.user_agent,
                updated_at=excluded.updated_at
            """,
            (host, json.dumps(cookies), user_agent, time.time()),
        )
        await self.conn.commit()

    async def load_session(self, host: str) -> dict[str, Any] | None:
        cursor = await self.conn.execute(
            "SELECT * FROM sessions WHERE host = ?", (host,)
        )
        row = await cursor.fetchone()
        if row is None:
            return None
        return {
            "host": row["host"],
            "cookies": json.loads(row["cookies"]),
            "user_agent": row["user_agent"],
            "updated_at": row["updated_at"],
        }
