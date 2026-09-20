"""INV-29 / Master §6.10, §49: matching diagnostics never become telemetry or central collection.

The Master removes central matcher telemetry, a cloud matcher dataset, a matcher-decision collector and
shared matcher logging, and says local operational diagnostics must not recreate any of them under
another name. This audit is a standing guard rather than a one-off review: it reads the schema OneShelf
actually ships, the code it actually runs, and what a real matching pass actually writes and logs.
"""
from __future__ import annotations

import logging

import pytest
import re
import sqlite3
from pathlib import Path

from oneshelf.api.app import AppConfig
from oneshelf.db.schema import MIGRATIONS
from oneshelf.domain.clock import utcnow_iso
from oneshelf.domain.ids import new_id
from oneshelf.search.grouping import LiveListing, group_results, persist_listing
from oneshelf.search.index import index_work
from oneshelf.search.mapping import MappingService

SOURCE_ROOT = Path(__file__).resolve().parents[2] / "oneshelf"

# The vocabulary a decision collector needs: a score for a candidate, kept for later analysis.
DECISION_WORDS = ("telemetry", "analytics", "match_decision", "matcher_decision", "match_score",
                  "decision_log", "match_log", "candidate_score", "match_event", "match_history")


def _schema_sql() -> str:
    return "\n".join(migration.sql for migration in MIGRATIONS).lower()


def test_no_shipped_table_or_column_collects_matcher_decisions():
    sql = _schema_sql()
    for word in DECISION_WORDS:
        assert word not in sql, f"schema mentions {word!r}"


def test_the_mapping_table_holds_a_decision_the_user_relies_on_not_a_dataset():
    """A mapping is state the library needs; a collector would keep candidates, scores and rejects."""
    conn = sqlite3.connect(":memory:")
    for migration in MIGRATIONS:
        conn.executescript(migration.sql)
    columns = {row[1] for row in conn.execute("PRAGMA table_info(work_mappings)")}
    assert columns == {"id", "kind", "listing_id", "work_id", "other_work_id", "decided_by", "created_at"}
    conn.close()


def test_a_default_install_has_nowhere_to_report_to(tmp_path):
    """No registry, and so no endpoint at all, unless the person configures one (ledger A1, §49)."""
    config = AppConfig.from_env({"ONESHELF_DATA_DIR": str(tmp_path)})
    assert config.registry_url is None
    assert config.registry_trusted_keys is None


def test_no_module_carries_a_hardcoded_endpoint():
    """A literal host in the code would be the one place a report could be sent from."""
    offenders = []
    for path in SOURCE_ROOT.rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        for match in re.finditer(r"https?://([A-Za-z0-9.\-]+)", text):
            host = match.group(1)
            if host in ("127.0.0.1", "localhost") or host.endswith(".example") or "example." in host:
                continue
            if host.endswith(("{host}", "{authority}")) or "{" in host:
                continue
            offenders.append(f"{path.relative_to(SOURCE_ROOT)}: {host}")
    assert offenders == [], offenders


def test_a_matching_pass_writes_only_the_library_state_it_is_for(db):
    """Grouping presents; mapping records what was decided. Neither leaves a trail of decisions."""
    now = utcnow_iso()
    work_id = new_id()
    db.execute("INSERT INTO works (id, display_title, content_type, created_at, updated_at) VALUES (?,?,?,?,?)",
               (work_id, "Solo Leveling", "manga", now, now))
    index_work(db, work_id)

    tables = [row[0] for row in db.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%'")]
    before = {table: db.execute(f"SELECT count(*) FROM {table}").fetchone()[0] for table in tables}

    listings = [LiveListing(source_id="mangadex", listing_key="sl", title="Solo Leveling",
                            url="https://mangadex.example/sl", content_type="manga", language="en", cover_url=None),
                LiveListing(source_id="3asq", listing_key="sl-ar", title="Solo Leveling",
                            url="https://3asq.example/sl", content_type="manga", language="ar", cover_url=None)]
    group_results(db, listings)                       # presentation only (INV-03)
    binding = persist_listing(db, listings[0], work_id=work_id)
    MappingService(db).never_match(binding.listing_id, work_id)   # a decision the user made, kept as itself

    after = {table: db.execute(f"SELECT count(*) FROM {table}").fetchone()[0] for table in tables}
    grew = {table for table in tables if after[table] > before[table]}
    assert grew <= {"source_listings", "source_tracks", "work_mappings", "search_index", "works"}, grew


def test_matching_writes_no_decision_record_to_the_diagnostics_log(db, caplog):
    now = utcnow_iso()
    work_id = new_id()
    db.execute("INSERT INTO works (id, display_title, content_type, created_at, updated_at) VALUES (?,?,?,?,?)",
               (work_id, "Solo Leveling", "manga", now, now))
    index_work(db, work_id)

    with caplog.at_level(logging.DEBUG):
        group_results(db, [LiveListing(source_id="mangadex", listing_key="sl", title="Solo Leveling",
                                       url="https://mangadex.example/sl", content_type="manga",
                                       language="en", cover_url=None)])
    assert caplog.records == []


def test_the_diagnostics_store_takes_operational_records_only(tmp_path):
    """§43, §6.10: parser, network, job and health — there is no category a matcher could file under."""
    from oneshelf.diagnostics.store import CATEGORIES, DiagnosticsStore

    store = DiagnosticsStore(tmp_path / "diagnostics")
    assert set(CATEGORIES) == {"parser", "network", "job", "health"}
    for invented in ("match", "matching", "decision", "telemetry", "analytics"):
        with pytest.raises(ValueError):
            store.record(invented, "a match decision", {"score": 0.9})


def test_a_matching_pass_writes_nothing_to_the_diagnostics_store(db, tmp_path):
    from oneshelf.diagnostics.store import DiagnosticsStore

    store = DiagnosticsStore(tmp_path / "diagnostics")
    now = utcnow_iso()
    work_id = new_id()
    db.execute("INSERT INTO works (id, display_title, content_type, created_at, updated_at) VALUES (?,?,?,?,?)",
               (work_id, "Solo Leveling", "manga", now, now))
    index_work(db, work_id)

    group_results(db, [LiveListing(source_id="mangadex", listing_key="sl", title="Solo Leveling",
                                   url="https://mangadex.example/sl", content_type="manga",
                                   language="en", cover_url=None)])

    assert store.recent() == [] and store.size_bytes() == 0
