"""My Shelf (Master §22, §23; INV-10).

Adding is immediate and needs no files. Shelf, Follow, files and progress are independent: removing a
Work from the Shelf never unfollows or deletes files unless asked, and Delete Files keeps Shelf, Follow
and reading progress. Completed stays Completed when new releases appear (§5.6).
"""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass

from oneshelf.db.connection import transaction
from oneshelf.search.presentation import work_cover, work_covers
from oneshelf.domain.clock import utcnow_iso
from oneshelf.search.index import search_local
from oneshelf.storage.paths import PathSafetyError, delete_managed_file
from oneshelf.storage.roots import get_root

VIEWS = ("all", "saved", "reading", "completed", "favorites", "pinned")


@dataclass(frozen=True)
class ShelfEntry:
    work_id: str
    title: str
    added_at: str
    is_favorite: bool
    is_pinned: bool
    completed_at: str | None
    releases_since_completion: int = 0
    cover_url: str | None = None          # presentation only (INV-28)
    last_read_at: str | None = None
    read_fraction: float = 0.0
    total_bytes: int = 0


class ShelfService:
    def __init__(self, conn: sqlite3.Connection, *, events=None) -> None:
        self.conn = conn
        self.events = events

    # -- queries ----------------------------------------------------------------------------------

    def _entry(self, row: sqlite3.Row) -> ShelfEntry:
        wid = row["work_id"]
        releases = 0
        if row["completed_at"]:
            releases = self.conn.execute(
                "SELECT count(*) FROM release_events WHERE work_id = ? AND detected_at > ?",
                (wid, row["completed_at"])).fetchone()[0]
        last_read = self.conn.execute(
            "SELECT max(rs.updated_at) FROM reading_state rs"
            " JOIN reading_units u ON u.id = rs.reading_unit_id"
            " JOIN source_tracks t ON t.id = u.track_id"
            " WHERE t.work_id = ? AND rs.read_state != 'unread'", (wid,)).fetchone()[0]
        progress = self.conn.execute(
            "SELECT count(CASE WHEN rs.read_state = 'read' THEN 1 END),"
            " count(*) FROM reading_units u"
            " JOIN source_tracks t ON t.id = u.track_id"
            " LEFT JOIN reading_state rs ON rs.reading_unit_id = u.id"
            " WHERE t.work_id = ?", (wid,)).fetchone()
        read_fraction = (progress[0] / progress[1]) if progress[1] > 0 else 0.0
        total_bytes = self.conn.execute(
            "SELECT coalesce(sum(a.size_bytes), 0) FROM assets a"
            " JOIN reading_units u ON u.id = a.reading_unit_id"
            " JOIN source_tracks t ON t.id = u.track_id"
            " WHERE t.work_id = ?", (wid,)).fetchone()[0]
        return ShelfEntry(wid, row["display_title"], row["added_at"], bool(row["is_favorite"]),
                          bool(row["is_pinned"]), row["completed_at"], releases, work_cover(self.conn, wid),
                          last_read, read_fraction, total_bytes)

    def _row(self, work_id: str) -> sqlite3.Row | None:
        return self.conn.execute(
            "SELECT s.*, w.display_title FROM shelf_entries s JOIN works w ON w.id = s.work_id WHERE s.work_id = ?",
            (work_id,)).fetchone()

    def get(self, work_id: str) -> ShelfEntry | None:
        row = self._row(work_id)
        return self._entry(row) if row else None

    def _batch_entries(self, rows: list[sqlite3.Row]) -> list[ShelfEntry]:
        if not rows:
            return []
        work_ids = [r["work_id"] for r in rows]
        ph = ",".join("?" * len(work_ids))

        releases_map: dict[str, int] = {wid: 0 for wid in work_ids}
        completed = {r["work_id"]: r["completed_at"] for r in rows if r["completed_at"]}
        if completed:
            c_ids = list(completed)
            c_ph = ",".join("?" * len(c_ids))
            for ev in self.conn.execute(
                    f"SELECT work_id, detected_at FROM release_events WHERE work_id IN ({c_ph})",
                    c_ids).fetchall():
                if ev["detected_at"] > completed[ev["work_id"]]:
                    releases_map[ev["work_id"]] = releases_map.get(ev["work_id"], 0) + 1

        last_read_map: dict[str, str | None] = {wid: None for wid in work_ids}
        for row in self.conn.execute(
                f"SELECT t.work_id, max(rs.updated_at) AS last_read FROM reading_state rs"
                f" JOIN reading_units u ON u.id = rs.reading_unit_id"
                f" JOIN source_tracks t ON t.id = u.track_id"
                f" WHERE t.work_id IN ({ph}) AND rs.read_state != 'unread'"
                f" GROUP BY t.work_id", work_ids).fetchall():
            last_read_map[row["work_id"]] = row["last_read"]

        fraction_map: dict[str, float] = {wid: 0.0 for wid in work_ids}
        for row in self.conn.execute(
                f"SELECT t.work_id,"
                f" count(CASE WHEN rs.read_state = 'read' THEN 1 END) AS read_count,"
                f" count(*) AS total"
                f" FROM reading_units u"
                f" JOIN source_tracks t ON t.id = u.track_id"
                f" LEFT JOIN reading_state rs ON rs.reading_unit_id = u.id"
                f" WHERE t.work_id IN ({ph})"
                f" GROUP BY t.work_id", work_ids).fetchall():
            fraction_map[row["work_id"]] = (row["read_count"] / row["total"]) if row["total"] > 0 else 0.0

        bytes_map: dict[str, int] = {wid: 0 for wid in work_ids}
        for row in self.conn.execute(
                f"SELECT t.work_id, coalesce(sum(a.size_bytes), 0) AS total_bytes FROM assets a"
                f" JOIN reading_units u ON u.id = a.reading_unit_id"
                f" JOIN source_tracks t ON t.id = u.track_id"
                f" WHERE t.work_id IN ({ph})"
                f" GROUP BY t.work_id", work_ids).fetchall():
            bytes_map[row["work_id"]] = row["total_bytes"]

        covers = work_covers(self.conn, work_ids)

        return [ShelfEntry(
            r["work_id"], r["display_title"], r["added_at"],
            bool(r["is_favorite"]), bool(r["is_pinned"]), r["completed_at"],
            releases_map.get(r["work_id"], 0), covers.get(r["work_id"]),
            last_read_map.get(r["work_id"]), fraction_map.get(r["work_id"], 0.0),
            bytes_map.get(r["work_id"], 0),
        ) for r in rows]

    def view(self, name: str = "all") -> list[ShelfEntry]:
        if name not in VIEWS:
            raise ValueError(f"unknown shelf view {name!r}")
        clauses = {
            "all": "",
            "favorites": " AND s.is_favorite = 1",
            "pinned": " AND s.is_pinned = 1",
            "completed": " AND s.completed_at IS NOT NULL",
            "reading": " AND s.completed_at IS NULL AND EXISTS (SELECT 1 FROM reading_state rs"
                       " JOIN reading_units u ON u.id = rs.reading_unit_id JOIN source_tracks t ON t.id = u.track_id"
                       " WHERE t.work_id = s.work_id AND rs.read_state IN ('partial', 'read'))",
            "saved": " AND s.completed_at IS NULL AND NOT EXISTS (SELECT 1 FROM reading_state rs"
                     " JOIN reading_units u ON u.id = rs.reading_unit_id JOIN source_tracks t ON t.id = u.track_id"
                     " WHERE t.work_id = s.work_id AND rs.read_state IN ('partial', 'read'))",
        }[name]
        rows = self.conn.execute(
            "SELECT s.*, w.display_title FROM shelf_entries s JOIN works w ON w.id = s.work_id"
            f" WHERE 1 = 1{clauses} ORDER BY s.is_pinned DESC, s.added_at DESC").fetchall()
        return self._batch_entries(rows)

    def search(self, query: str, *, limit: int = 50) -> list[ShelfEntry]:
        """Shelf search is local only: the same index and ranking, no live source requests (§22)."""
        matched_rows = []
        for result in search_local(self.conn, query, limit=limit):
            row = self._row(result.work_id)
            if row is not None:
                matched_rows.append(row)
        return self._batch_entries(matched_rows)

    # -- mutations --------------------------------------------------------------------------------

    def _emit(self, event: str, payload: dict) -> None:
        if self.events is not None:
            self.events.publish(event, payload)

    def add(self, work_id: str) -> ShelfEntry:
        with transaction(self.conn):
            self.conn.execute("INSERT OR IGNORE INTO shelf_entries (work_id, added_at) VALUES (?, ?)",
                              (work_id, utcnow_iso()))
        self._emit("shelf.changed", {"work_id": work_id, "action": "added"})
        entry = self.get(work_id)
        if entry is None:
            raise ValueError(f"unknown work {work_id}")
        return entry

    def _set_flag(self, work_id: str, column: str, value) -> ShelfEntry:
        with transaction(self.conn):
            self.conn.execute(f"UPDATE shelf_entries SET {column} = ? WHERE work_id = ?", (value, work_id))
        self._emit("shelf.changed", {"work_id": work_id, "action": column})
        return self.get(work_id)

    def set_favorite(self, work_id: str, value: bool) -> ShelfEntry:
        return self._set_flag(work_id, "is_favorite", int(value))

    def set_pinned(self, work_id: str, value: bool) -> ShelfEntry:
        return self._set_flag(work_id, "is_pinned", int(value))

    def set_completed(self, work_id: str, value: bool) -> ShelfEntry:
        return self._set_flag(work_id, "completed_at", utcnow_iso() if value else None)

    # -- removal ----------------------------------------------------------------------------------

    def _assets(self, work_id: str) -> list[sqlite3.Row]:
        return self.conn.execute(
            "SELECT a.* FROM assets a JOIN reading_units u ON u.id = a.reading_unit_id"
            " JOIN source_tracks t ON t.id = u.track_id WHERE t.work_id = ?", (work_id,)).fetchall()

    def removal_summary(self, work_id: str) -> dict:
        """What a destructive dialog must state before removing (§47)."""
        assets = self._assets(work_id)
        progress = self.conn.execute(
            "SELECT count(*) FROM reading_state rs JOIN reading_units u ON u.id = rs.reading_unit_id"
            " JOIN source_tracks t ON t.id = u.track_id WHERE t.work_id = ? AND rs.read_state != 'unread'",
            (work_id,)).fetchone()[0]
        followed = self.conn.execute("SELECT count(*) FROM follows WHERE work_id = ?", (work_id,)).fetchone()[0]
        return {"work_id": work_id, "files": len(assets), "bytes": sum(a["size_bytes"] for a in assets),
                "has_progress": progress > 0, "is_followed": followed > 0}

    def delete_files(self, work_id: str) -> int:
        """Deletes managed files only: Shelf, Follow and progress stay (§23, INV-10).

        A file OneShelf refuses to touch — a symlink standing where a managed file should be, or anything
        else that is not a regular file inside the root — keeps its record and is not counted. Reporting
        a deletion that did not happen would be a lie on a destructive path, and forgetting the asset
        would leave a file on disk that the library no longer knows about (§24.4, §47).
        """
        removed = 0
        for asset in self._assets(work_id):
            root = get_root(self.conn, asset["storage_root_id"])
            try:
                delete_managed_file(root.path, asset["relative_path"])
            except PathSafetyError:
                continue                    # not ours to delete: keep the record, count nothing
            except FileNotFoundError:
                pass                        # already gone: the record should follow it
            with transaction(self.conn):
                # The download or import that made the file stays in history, no longer pointing at it (I-110).
                self.conn.execute("UPDATE download_jobs SET asset_id = NULL WHERE asset_id = ?", (asset["id"],))
                self.conn.execute("UPDATE imports SET asset_id = NULL WHERE asset_id = ?", (asset["id"],))
                self.conn.execute("DELETE FROM assets WHERE id = ?", (asset["id"],))
            removed += 1
        if removed:
            self._emit("shelf.changed", {"work_id": work_id, "action": "files_deleted", "files": removed})
        return removed

    def remove(self, work_id: str, *, delete_files: bool = False) -> dict:
        summary = self.removal_summary(work_id)
        if delete_files:
            summary["deleted_files"] = self.delete_files(work_id)
        with transaction(self.conn):
            self.conn.execute("DELETE FROM shelf_entries WHERE work_id = ?", (work_id,))
        self._emit("shelf.changed", {"work_id": work_id, "action": "removed"})
        return summary
