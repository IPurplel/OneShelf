"""Local-first search index over library records (Master §6.1–6.2).

Rows are derived from works, aliases and source listings, so the index is always rebuildable and never
stores search queries (§7). Candidate retrieval uses FTS5 plus a bounded substring pass; ordering comes
from the ranking tiers.
"""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass

from oneshelf.db.connection import transaction
from oneshelf.search.normalize import search_keys
from oneshelf.search.ranking import Boosts, Candidate, Ranked, rank

FTS_CANDIDATE_LIMIT = 500
LIKE_CANDIDATE_LIMIT = 200


@dataclass(frozen=True)
class LocalResult:
    work_id: str
    title: str
    tier: str
    boost: float
    candidate: Candidate


def _rows_for_work(conn: sqlite3.Connection, work_id: str) -> list[tuple]:
    work = conn.execute("SELECT * FROM works WHERE id = ?", (work_id,)).fetchone()
    if work is None:
        return []
    rows = [("work", work["id"], work["display_title"], None)]
    if work["original_title"]:
        rows.append(("original", work["id"], work["original_title"], None))
    rows += [("alias", r["id"], r["title"], r["language"])
             for r in conn.execute("SELECT id, title, language FROM work_aliases WHERE work_id = ?", (work_id,))]
    rows += [("listing", r["id"], r["raw_title"], None)
             for r in conn.execute("SELECT id, raw_title FROM source_listings WHERE work_id = ? AND raw_title IS NOT NULL",
                                   (work_id,))]
    return [(kind, entity_id, title, language) for kind, entity_id, title, language in rows if title]


def write_work_index(conn: sqlite3.Connection, work_id: str) -> None:
    """Rebuilds one work's index rows; the caller owns the transaction (used by commit-journal registrars)."""
    conn.execute("DELETE FROM search_index WHERE work_id = ?", (work_id,))
    for kind, entity_id, title, language in _rows_for_work(conn, work_id):
        keys = search_keys(title)
        conn.execute(
            "INSERT INTO search_index (title, normalized, loose, entity_kind, entity_id, work_id, language)"
            " VALUES (?,?,?,?,?,?,?)", (title, keys.normalized, keys.loose, kind, entity_id, work_id, language))


def index_work(conn: sqlite3.Connection, work_id: str) -> None:
    with transaction(conn):
        write_work_index(conn, work_id)


def reindex_all(conn: sqlite3.Connection) -> int:
    work_ids = [r[0] for r in conn.execute("SELECT id FROM works")]
    with transaction(conn):
        conn.execute("DELETE FROM search_index")
    for work_id in work_ids:
        index_work(conn, work_id)
    return len(work_ids)


def _fts_query(tokens: tuple[str, ...]) -> str:
    return " OR ".join(f'"{token.replace(chr(34), chr(34) * 2)}"*' for token in tokens)


def _candidate_work_ids(conn: sqlite3.Connection, query: str) -> list[str]:
    keys = search_keys(query)
    found: dict[str, None] = {}
    try:
        for row in conn.execute("SELECT DISTINCT work_id FROM search_index WHERE search_index MATCH ? LIMIT ?",
                                (_fts_query(keys.tokens), FTS_CANDIDATE_LIMIT)):
            found[row[0]] = None
    except sqlite3.OperationalError:  # unusual query syntax; substring pass still applies
        pass
    for row in conn.execute("SELECT DISTINCT work_id FROM search_index WHERE normalized LIKE ? OR loose LIKE ? LIMIT ?",
                            (f"%{keys.normalized}%", f"%{keys.loose}%", LIKE_CANDIDATE_LIMIT)):
        found[row[0]] = None
    return list(found)


def _candidate(conn: sqlite3.Connection, work_id: str) -> Candidate | None:
    work = conn.execute("SELECT * FROM works WHERE id = ?", (work_id,)).fetchone()
    if work is None:
        return None
    aliases = [r[0] for r in conn.execute("SELECT title FROM work_aliases WHERE work_id = ?", (work_id,))]
    aliases += [r[0] for r in conn.execute(
        "SELECT raw_title FROM source_listings WHERE work_id = ? AND raw_title IS NOT NULL", (work_id,))]
    on_shelf = conn.execute("SELECT 1 FROM shelf_entries WHERE work_id = ?", (work_id,)).fetchone() is not None
    sources = conn.execute("SELECT count(DISTINCT source_id) FROM source_listings WHERE work_id = ?", (work_id,)).fetchone()[0]
    user_mapping = conn.execute(
        "SELECT 1 FROM work_mappings WHERE work_id = ? AND decided_by = 'user' AND kind = 'merge'"
        " UNION SELECT 1 FROM source_listings WHERE work_id = ? AND mapping_decided_by = 'user'",
        (work_id, work_id)).fetchone()
    return Candidate(entity_id=work_id, work_id=work_id, title=work["display_title"], aliases=aliases,
                     original_title=work["original_title"], creator=work["creator"], content_type=work["content_type"],
                     boosts=Boosts(user_mapping=user_mapping is not None, on_shelf=on_shelf, agreeing_sources=sources))


def search_local(conn: sqlite3.Connection, query: str, *, limit: int = 50) -> list[LocalResult]:
    keys = search_keys(query)
    if not keys.tokens:
        return []
    candidates = [c for c in (_candidate(conn, work_id) for work_id in _candidate_work_ids(conn, query)) if c]
    ranked: list[Ranked] = rank(query, candidates)
    return [LocalResult(r.candidate.work_id, r.candidate.title, r.tier, r.boost, r.candidate) for r in ranked[:limit]]
