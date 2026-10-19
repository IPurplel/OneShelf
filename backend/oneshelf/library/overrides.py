"""User corrections (Master §9.2 tier 1, §4.4, INV-4; I-102).

A correction is stored twice on purpose: in `user_overrides`, which says *that* the user decided and survives
any refresh, and in the column the rest of OneShelf already reads, so every reader sees it without knowing
about overrides. Source refreshes write source columns only and then re-apply the overrides of the units they
touched, so a correction is never silently overwritten (INV-4). Clearing a correction removes the row and puts
back what the source said.
"""
from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass

from oneshelf.db.connection import transaction
from oneshelf.domain.clock import utcnow_iso
from oneshelf.domain.ids import new_id
from oneshelf.plugins.runtime import CONTENT_TYPES, UNIT_TYPES

WORK_FIELDS = ("content_type", "display_title")
UNIT_FIELDS = ("number", "display_title", "unit_type")
MAX_TEXT = 500
MAX_NUMBER = 32


class OverrideError(ValueError):
    pass


class NotFound(LookupError):
    pass


@dataclass(frozen=True)
class Unset:
    """Marks a field the caller did not mention (as opposed to None, which clears a correction)."""


UNSET = Unset()


def _text(value: object, field: str, limit: int) -> str:
    if not isinstance(value, str) or not value.strip():
        raise OverrideError(f"{field} must be non-empty text")
    value = value.strip()
    if len(value) > limit:
        raise OverrideError(f"{field} is longer than {limit} characters")
    return value


def _record(conn: sqlite3.Connection, kind: str, target_id: str, field: str, value: object) -> None:
    now = utcnow_iso()
    if value is None:
        conn.execute("DELETE FROM user_overrides WHERE target_kind = ? AND target_id = ? AND field = ?",
                     (kind, target_id, field))
        return
    conn.execute(
        "INSERT INTO user_overrides (id, target_kind, target_id, field, value_json, created_at, updated_at)"
        " VALUES (?,?,?,?,?,?,?) ON CONFLICT(target_kind, target_id, field)"
        " DO UPDATE SET value_json = excluded.value_json, updated_at = excluded.updated_at",
        (new_id(), kind, target_id, field, json.dumps(value), now, now))


def overrides_for(conn: sqlite3.Connection, kind: str, target_id: str) -> dict[str, object]:
    return {row["field"]: json.loads(row["value_json"]) for row in conn.execute(
        "SELECT field, value_json FROM user_overrides WHERE target_kind = ? AND target_id = ?", (kind, target_id))}


def set_work(conn: sqlite3.Connection, work_id: str, *, content_type: object = UNSET,
             display_title: object = UNSET) -> None:
    """Clearing a correction restores what the user replaced: the source or plugin-default classification."""
    work = conn.execute("SELECT * FROM works WHERE id = ?", (work_id,)).fetchone()
    if work is None:
        raise NotFound("this work is not in your library")
    if content_type is not UNSET and content_type is not None and content_type not in CONTENT_TYPES:
        raise OverrideError(f"content type must be one of {sorted(CONTENT_TYPES)}")
    if display_title is not UNSET and display_title is not None:
        display_title = _text(display_title, "title", MAX_TEXT)
    now = utcnow_iso()
    with transaction(conn):
        if content_type is not UNSET:
            replaced = overrides_for(conn, "work", work_id).get("source_content_type")
            if content_type is None:
                kind, source = replaced or (
                    (work["content_type"], work["content_type_source"]) if work["content_type_source"] != "user"
                    else ("unknown", "unknown"))
                conn.execute("DELETE FROM user_overrides WHERE target_kind = 'work' AND target_id = ?"
                             " AND field IN ('content_type', 'source_content_type')", (work_id,))
            else:
                if replaced is None and work["content_type_source"] != "user":
                    _record(conn, "work", work_id, "source_content_type",
                            [work["content_type"], work["content_type_source"]])
                _record(conn, "work", work_id, "content_type", content_type)
                kind, source = content_type, "user"
            conn.execute("UPDATE works SET content_type = ?, content_type_source = ?, updated_at = ? WHERE id = ?",
                         (kind, source, now, work_id))
        if display_title is not UNSET:
            stored = overrides_for(conn, "work", work_id).get("source_title")
            if display_title is None:
                restored = stored or work["display_title"]
                conn.execute("DELETE FROM user_overrides WHERE target_kind = 'work' AND target_id = ?"
                             " AND field IN ('display_title', 'source_title')", (work_id,))
                conn.execute("UPDATE works SET display_title = ?, updated_at = ? WHERE id = ?",
                             (restored, now, work_id))
            else:
                if stored is None:      # remember the title the source gave, so clearing can restore it
                    _record(conn, "work", work_id, "source_title", work["display_title"])
                _record(conn, "work", work_id, "display_title", display_title)
                conn.execute("UPDATE works SET display_title = ?, updated_at = ? WHERE id = ?",
                             (display_title, now, work_id))
    if display_title is not UNSET:
        from oneshelf.search.index import index_work
        index_work(conn, work_id)


def set_unit(conn: sqlite3.Connection, unit_id: str, *, number: object = UNSET, display_title: object = UNSET,
             unit_type: object = UNSET) -> None:
    unit = conn.execute("SELECT * FROM reading_units WHERE id = ?", (unit_id,)).fetchone()
    if unit is None:
        raise NotFound("this reading unit is not in your library")
    if number is not UNSET and number is not None:
        number = _text(number, "number", MAX_NUMBER)
    if display_title is not UNSET and display_title is not None:
        display_title = _text(display_title, "title", MAX_TEXT)
    if unit_type is not UNSET and unit_type is not None and unit_type not in UNIT_TYPES:
        raise OverrideError(f"unit type must be one of {sorted(UNIT_TYPES)}")
    with transaction(conn):
        for field, value in (("number", number), ("display_title", display_title), ("unit_type", unit_type)):
            if value is not UNSET:
                _record(conn, "reading_unit", unit_id, field, value)
        if number is not UNSET:
            conn.execute("UPDATE reading_units SET user_number = ? WHERE id = ?", (number, unit_id))
        if display_title is not UNSET and display_title is None:
            conn.execute("UPDATE reading_units SET display_title = raw_title WHERE id = ?", (unit_id,))
        if unit_type is not UNSET and unit_type is None:
            source_type = conn.execute(
                "SELECT su.unit_type FROM snapshot_units su JOIN catalog_snapshots cs ON cs.id = su.snapshot_id"
                " WHERE cs.track_id = ? AND cs.trust = 'trusted_current' AND su.unit_key = ?",
                (unit["track_id"], unit["source_unit_key"])).fetchone()
            conn.execute("UPDATE reading_units SET unit_type = ? WHERE id = ?",
                         (source_type[0] if source_type else "unknown", unit_id))
        apply_unit_overrides(conn, unit["track_id"], unit_ids=[unit_id])


def apply_unit_overrides(conn: sqlite3.Connection, track_id: str, *, unit_ids: list[str] | None = None) -> None:
    """Re-apply unit corrections after the source rewrote its columns. Call inside the writer's transaction."""
    rows = conn.execute(
        "SELECT o.target_id, o.field, o.value_json FROM user_overrides o"
        " JOIN reading_units u ON u.id = o.target_id"
        " WHERE o.target_kind = 'reading_unit' AND u.track_id = ?", (track_id,)).fetchall()
    for row in rows:
        if unit_ids is not None and row["target_id"] not in unit_ids:
            continue
        value = json.loads(row["value_json"])
        column = {"number": "user_number", "display_title": "display_title", "unit_type": "unit_type"}[row["field"]]
        conn.execute(f"UPDATE reading_units SET {column} = ? WHERE id = ?", (value, row["target_id"]))


def apply_all_overrides(conn: sqlite3.Connection) -> None:
    """Make every column agree with the stored corrections (after a restore). Call inside a transaction."""
    for row in conn.execute("SELECT target_id, field, value_json FROM user_overrides WHERE target_kind = 'work'"
                            " AND field IN ('content_type', 'display_title')").fetchall():
        value = json.loads(row["value_json"])
        if row["field"] == "content_type":
            conn.execute("UPDATE works SET content_type = ?, content_type_source = 'user' WHERE id = ?",
                         (value, row["target_id"]))
        else:
            conn.execute("UPDATE works SET display_title = ? WHERE id = ?", (value, row["target_id"]))
    for (track_id,) in conn.execute(
            "SELECT DISTINCT u.track_id FROM user_overrides o JOIN reading_units u ON u.id = o.target_id"
            " WHERE o.target_kind = 'reading_unit'").fetchall():
        apply_unit_overrides(conn, track_id)
