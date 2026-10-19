"""Repair classification recorded before I-92 (and the twin tracks it caused, I-94).

Before the shared classifier, Works from sources that leave type and language to their plugin's defaults were
stored as `unknown`, their tracks as `und`, and opening the same listing by URL could add a second track. This
module finds those rows and fixes them. It runs only when asked (preview first, then apply), takes a
consistent SQLite snapshot before it changes anything, and is idempotent.

What it never does: touch a user's own classification, rename or move a file (§24.2), delete a downloaded
file, or lose progress, bookmarks, highlights, corrections, history or a Follow.
"""
from __future__ import annotations

import json
import sqlite3
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from oneshelf.db.connection import transaction
from oneshelf.db.migrate import snapshot
from oneshelf.domain.clock import utcnow_iso
from oneshelf.plugins.classification import defaults_for

READ_ORDER = {"unread": 0, "partial": 1, "read": 2}


@dataclass(frozen=True)
class Change:
    kind: str                 # work_type | track_language | track_merge
    work_id: str
    detail: dict


@dataclass
class Report:
    changes: list[Change] = field(default_factory=list)
    snapshot: str | None = None
    applied: bool = False

    def as_dict(self) -> dict:
        return {"applied": self.applied, "snapshot": self.snapshot, "count": len(self.changes),
                "changes": [asdict(c) for c in self.changes]}


def plan(conn: sqlite3.Connection, plugins) -> list[Change]:
    changes: list[Change] = []
    cache: dict[str, object] = {}

    def defaults(source_id):
        if source_id not in cache:
            cache[source_id] = defaults_for(plugins, source_id)
        return cache[source_id]

    for track in conn.execute("SELECT * FROM source_tracks WHERE language = 'und' AND kind = 'source'"
                              " ORDER BY created_at, id").fetchall():
        d = defaults(track["source_id"])
        if d is None or not d.language:
            continue
        sibling = None
        if track["listing_id"] is not None:
            sibling = conn.execute("SELECT id FROM source_tracks WHERE listing_id = ? AND language = ? AND id != ?",
                                   (track["listing_id"], d.language, track["id"])).fetchone()
        if sibling is not None:
            changes.append(Change("track_merge", track["work_id"],
                                  {"from_track": track["id"], "into_track": sibling["id"], "language": d.language,
                                   "source_id": track["source_id"]}))
        else:
            changes.append(Change("track_language", track["work_id"],
                                  {"track": track["id"], "from": "und", "to": d.language,
                                   "source_id": track["source_id"]}))
    for work in conn.execute("SELECT * FROM works WHERE content_type_source = 'unknown' AND content_type = 'unknown'"
                             " ORDER BY created_at, id").fetchall():
        sources = [r[0] for r in conn.execute("SELECT DISTINCT source_id FROM source_tracks WHERE work_id = ?"
                                              " AND kind = 'source'", (work["id"],))]
        kinds = {getattr(defaults(s), "content_type", None) for s in sources} - {None}
        if len(kinds) == 1:          # sources that disagree are left Unknown rather than guessed (§3.2)
            changes.append(Change("work_type", work["id"], {"from": "unknown", "to": kinds.pop()}))
    return changes


def preview(conn: sqlite3.Connection, plugins) -> Report:
    return Report(changes=plan(conn, plugins))


def apply(conn: sqlite3.Connection, plugins, *, snapshot_dir: str | Path) -> Report:
    changes = plan(conn, plugins)
    report = Report(changes=changes, applied=True)
    if not changes:
        return report
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
    report.snapshot = str(snapshot(conn, Path(snapshot_dir) / f"pre-reclassification-{stamp}.db"))
    with transaction(conn):
        for change in changes:
            if change.kind == "work_type":
                conn.execute("UPDATE works SET content_type = ?, content_type_source = 'plugin_default', updated_at = ?"
                             " WHERE id = ? AND content_type_source = 'unknown'",
                             (change.detail["to"], utcnow_iso(), change.work_id))
            elif change.kind == "track_language":
                _relabel(conn, change.detail["track"], change.detail["to"])
            else:
                _merge(conn, change.detail["from_track"], change.detail["into_track"], change.detail["language"])
    return report


# -- internals ------------------------------------------------------------------------------------------

def _relabel(conn: sqlite3.Connection, track_id: str, language: str) -> None:
    conn.execute("UPDATE source_tracks SET language = ? WHERE id = ?", (language, track_id))
    conn.execute("UPDATE follows SET language = ? WHERE track_id = ? AND NOT EXISTS"
                 " (SELECT 1 FROM follows f WHERE f.work_id = follows.work_id AND f.language = ?)",
                 (language, track_id, language))


def _repoint(conn: sqlite3.Connection, table: str, column: str, old: str, new: str) -> None:
    """Move rows to the surviving id; where a unique key would collide, the survivor's row wins."""
    conn.execute(f"UPDATE OR IGNORE {table} SET {column} = ? WHERE {column} = ?", (new, old))
    conn.execute(f"DELETE FROM {table} WHERE {column} = ?", (old,))


def _more_advanced(a: sqlite3.Row, b: sqlite3.Row) -> bool:
    return (READ_ORDER.get(a["read_state"], 0), a["fraction"] or 0.0) > \
        (READ_ORDER.get(b["read_state"], 0), b["fraction"] or 0.0)


def _merge_unit(conn: sqlite3.Connection, old: str, new: str) -> None:
    for asset in conn.execute("SELECT * FROM assets WHERE reading_unit_id = ?", (old,)).fetchall():
        clash = conn.execute("SELECT id FROM assets WHERE reading_unit_id = ? AND format = ? AND variant = ?",
                             (new, asset["format"], asset["variant"])).fetchone()
        # A second copy of the same format is kept, under its own variant, rather than forgotten.
        variant = asset["variant"] if clash is None else f"{asset['variant']}merged-{asset['id']}"
        conn.execute("UPDATE assets SET reading_unit_id = ?, variant = ? WHERE id = ?", (new, variant, asset["id"]))
    theirs = conn.execute("SELECT * FROM reading_state WHERE reading_unit_id = ?", (old,)).fetchone()
    ours = conn.execute("SELECT * FROM reading_state WHERE reading_unit_id = ?", (new,)).fetchone()
    if theirs is not None:
        if ours is None:
            conn.execute("UPDATE reading_state SET reading_unit_id = ? WHERE reading_unit_id = ?", (new, old))
        else:
            if _more_advanced(theirs, ours):      # progress never regresses (§33.7 spirit, INV-23)
                conn.execute("UPDATE reading_state SET read_state = ?, fraction = ?, locator_json = ?,"
                             " revision = revision + 1, updated_at = ? WHERE reading_unit_id = ?",
                             (theirs["read_state"], theirs["fraction"], theirs["locator_json"], utcnow_iso(), new))
            conn.execute("DELETE FROM reading_state WHERE reading_unit_id = ?", (old,))
    for table in ("reading_bookmarks", "reading_highlights", "download_jobs", "download_history", "export_items",
                  "release_events"):
        _repoint(conn, table, "reading_unit_id", old, new)
    conn.execute("UPDATE OR IGNORE user_overrides SET target_id = ? WHERE target_kind = 'reading_unit'"
                 " AND target_id = ?", (new, old))
    conn.execute("DELETE FROM user_overrides WHERE target_kind = 'reading_unit' AND target_id = ?", (old,))
    conn.execute("DELETE FROM reading_units WHERE id = ?", (old,))


def _merge(conn: sqlite3.Connection, old_track: str, new_track: str, language: str) -> None:
    for unit in conn.execute("SELECT id, source_unit_key FROM reading_units WHERE track_id = ?",
                             (old_track,)).fetchall():
        twin = conn.execute("SELECT id FROM reading_units WHERE track_id = ? AND source_unit_key = ?",
                            (new_track, unit["source_unit_key"])).fetchone()
        if twin is None:
            conn.execute("UPDATE reading_units SET track_id = ? WHERE id = ?", (new_track, unit["id"]))
        else:
            _merge_unit(conn, unit["id"], twin["id"])
    survivor_trusted = conn.execute("SELECT 1 FROM catalog_snapshots WHERE track_id = ? AND trust = 'trusted_current'",
                                    (new_track,)).fetchone()
    for snap in conn.execute("SELECT id FROM catalog_snapshots WHERE track_id = ?", (old_track,)).fetchall():
        if survivor_trusted:
            conn.execute("DELETE FROM snapshot_units WHERE snapshot_id = ?", (snap["id"],))
            conn.execute("DELETE FROM catalog_snapshots WHERE id = ?", (snap["id"],))
        else:
            conn.execute("UPDATE catalog_snapshots SET track_id = ? WHERE id = ?", (new_track, snap["id"]))
    follow = conn.execute("SELECT * FROM follows WHERE track_id = ?", (old_track,)).fetchone()
    if follow is not None:
        kept = conn.execute("SELECT id FROM follows WHERE work_id = ? AND language = ? AND id != ?",
                            (follow["work_id"], language, follow["id"])).fetchone()
        if kept is None:
            conn.execute("UPDATE follows SET track_id = ?, language = ? WHERE id = ?", (new_track, language, follow["id"]))
        else:
            # The survivor's Follow already exists; the twin's events join it and its baseline goes.
            conn.execute("UPDATE OR IGNORE release_events SET follow_id = ? WHERE follow_id = ?", (kept["id"], follow["id"]))
            conn.execute("DELETE FROM release_events WHERE follow_id = ?", (follow["id"],))
            conn.execute("DELETE FROM follow_baseline_units WHERE baseline_id IN"
                         " (SELECT id FROM follow_baselines WHERE follow_id = ?)", (follow["id"],))
            conn.execute("DELETE FROM follow_baselines WHERE follow_id = ?", (follow["id"],))
            conn.execute("DELETE FROM follows WHERE id = ?", (follow["id"],))
    conn.execute("UPDATE follow_baselines SET track_id = ? WHERE track_id = ?", (new_track, old_track))
    conn.execute("UPDATE release_events SET track_id = ? WHERE track_id = ?", (new_track, old_track))
    conn.execute("UPDATE OR IGNORE user_overrides SET target_id = ? WHERE target_kind = 'track' AND target_id = ?",
                 (new_track, old_track))
    conn.execute("DELETE FROM user_overrides WHERE target_kind = 'track' AND target_id = ?", (old_track,))
    conn.execute("DELETE FROM source_tracks WHERE id = ?", (old_track,))


def as_json(report: Report) -> str:
    return json.dumps(report.as_dict(), ensure_ascii=False)
