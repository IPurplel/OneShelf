"""Durable user mapping decisions: Merge, Split, Unlink, Never Match (Master §6.6; INV-03, INV-04).

User decisions persist and win: source refreshes, plugin updates and restore merges never silently
overwrite them.
"""
from __future__ import annotations

import sqlite3

from oneshelf.db.connection import transaction
from oneshelf.domain.clock import utcnow_iso
from oneshelf.domain.ids import new_id
from oneshelf.search.index import index_work


class MappingError(RuntimeError):
    pass


class MappingService:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn

    def _record(self, kind: str, *, listing_id: str | None = None, work_id: str | None = None,
                other_work_id: str | None = None, decided_by: str = "user") -> None:
        self.conn.execute(
            "INSERT INTO work_mappings (id, kind, listing_id, work_id, other_work_id, decided_by, created_at)"
            " VALUES (?,?,?,?,?,?,?)", (new_id(), kind, listing_id, work_id, other_work_id, decided_by, utcnow_iso()))

    def never_match(self, listing_id: str, work_id: str) -> None:
        with transaction(self.conn):
            self._record("never_match", listing_id=listing_id, work_id=work_id)

    def unlink(self, listing_id: str) -> None:
        row = self.conn.execute("SELECT work_id FROM source_listings WHERE id = ?", (listing_id,)).fetchone()
        if row is None:
            raise MappingError("unknown source listing")
        with transaction(self.conn):
            if row["work_id"]:
                self._record("unlink", listing_id=listing_id, work_id=row["work_id"])
            self.conn.execute("UPDATE source_listings SET work_id = NULL, mapping_decided_by = NULL WHERE id = ?",
                              (listing_id,))

    def split(self, listing_id: str, *, title: str | None = None) -> str:
        row = self.conn.execute("SELECT * FROM source_listings WHERE id = ?", (listing_id,)).fetchone()
        if row is None:
            raise MappingError("unknown source listing")
        previous_work = row["work_id"]
        new_work = new_id()
        now = utcnow_iso()
        with transaction(self.conn):
            source_work = self.conn.execute("SELECT content_type FROM works WHERE id = ?", (previous_work,)).fetchone()
            self.conn.execute(
                "INSERT INTO works (id, display_title, content_type, created_at, updated_at) VALUES (?,?,?,?,?)",
                (new_work, title or row["raw_title"] or "Untitled",
                 source_work["content_type"] if source_work else "unknown", now, now))
            self.conn.execute("UPDATE source_listings SET work_id = ?, mapping_decided_by = 'user' WHERE id = ?",
                              (new_work, listing_id))
            self.conn.execute("UPDATE source_tracks SET work_id = ? WHERE listing_id = ?", (new_work, listing_id))
            if previous_work:
                self._record("split", listing_id=listing_id, work_id=previous_work, other_work_id=new_work)
        index_work(self.conn, new_work)
        if previous_work:
            index_work(self.conn, previous_work)
        return new_work

    def merge(self, work_id: str, other_work_id: str) -> None:
        if work_id == other_work_id:
            raise MappingError("cannot merge a work with itself")
        works = {r["id"]: r for r in self.conn.execute("SELECT * FROM works WHERE id IN (?, ?)", (work_id, other_work_id))}
        if len(works) != 2:
            raise MappingError("unknown work")
        conflicts = self.conn.execute(
            "SELECT count(*) FROM source_tracks a JOIN source_tracks b ON a.source_id = b.source_id"
            " AND a.language = b.language WHERE a.work_id = ? AND b.work_id = ?", (work_id, other_work_id)).fetchone()[0]
        if conflicts:
            raise MappingError("these works have tracks for the same source and language; unlink or split them first")
        now = utcnow_iso()
        with transaction(self.conn):
            self.conn.execute("INSERT OR IGNORE INTO work_aliases (id, work_id, title, kind, created_at)"
                              " VALUES (?, ?, ?, 'historical', ?)",
                              (new_id(), work_id, works[other_work_id]["display_title"], now))
            for table in ("source_listings", "source_tracks"):
                self.conn.execute(f"UPDATE {table} SET work_id = ? WHERE work_id = ?", (work_id, other_work_id))
            self.conn.execute("UPDATE work_aliases SET work_id = ? WHERE work_id = ?", (work_id, other_work_id))
            self.conn.execute("INSERT OR IGNORE INTO shelf_entries (work_id, added_at) SELECT ?, added_at"
                              " FROM shelf_entries WHERE work_id = ?", (work_id, other_work_id))
            self.conn.execute("DELETE FROM shelf_entries WHERE work_id = ?", (other_work_id,))
            self.conn.execute("UPDATE OR IGNORE follows SET work_id = ? WHERE work_id = ?", (work_id, other_work_id))
            self.conn.execute("DELETE FROM follows WHERE work_id = ?", (other_work_id,))
            self.conn.execute("UPDATE work_mappings SET work_id = ? WHERE work_id = ?", (work_id, other_work_id))
            self.conn.execute("UPDATE work_mappings SET other_work_id = NULL WHERE other_work_id = ?", (other_work_id,))
            self.conn.execute("DELETE FROM works WHERE id = ?", (other_work_id,))
            self._record("merge", work_id=work_id, other_work_id=None)
            self.conn.execute("DELETE FROM search_index WHERE work_id = ?", (other_work_id,))
        index_work(self.conn, work_id)
