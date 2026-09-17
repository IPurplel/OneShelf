"""Master §5 / INV-01: only complete snapshots become Trusted; suspicion never erases trusted state."""
import pytest

from oneshelf.catalog.trust import CatalogTrust, TrustRejected
from oneshelf.domain.clock import utcnow_iso
from oneshelf.domain.ids import new_id
from oneshelf.plugins.results import Evidence, Issue, ListResult, UnitDescriptor

NOW = "2026-09-17T00:00:00+00:00"


def units(count, prefix="u", start=1, title=None):
    return [UnitDescriptor(unit_key=f"{prefix}{i}", order_index=i - start, raw_title=title or f"Chapter {i}",
                           number=str(i), unit_type="chapter") for i in range(start, start + count)]


def complete(unit_list):
    return ListResult("catalog", unit_list, True, Evidence(pages=1, stop_reason="single_response"))


def incomplete(unit_list, category="server_error"):
    return ListResult("catalog", unit_list, False,
                      Evidence(pages=1, stop_reason="page_failed", issues=[Issue(category, "HTTP 500", 1)]))


@pytest.fixture
def track(db):
    work, track_id = new_id(), new_id()
    db.execute("INSERT INTO works (id, display_title, created_at, updated_at) VALUES (?, 'W', ?, ?)", (work, NOW, NOW))
    db.execute("INSERT INTO source_tracks (id, work_id, source_id, language, kind, created_at) VALUES (?,?,?,?,?,?)",
               (track_id, work, "example.books", "en", "source", NOW))
    return track_id


@pytest.fixture
def trust(db):
    return CatalogTrust(db)


def unit_rows(db, track):
    return db.execute("SELECT source_unit_key, raw_title, source_number, unit_type, source_order, availability,"
                      " missing_since FROM reading_units WHERE track_id = ? ORDER BY source_order", (track,)).fetchall()


def test_first_complete_catalog_becomes_trusted_and_materializes_units(db, trust, track):
    outcome = trust.refresh(track, complete(units(3)), plugin_version="1.0.0")
    assert outcome.state == "trusted" and outcome.unit_count == 3
    rows = unit_rows(db, track)
    assert [r["source_unit_key"] for r in rows] == ["u1", "u2", "u3"]
    assert [r["source_number"] for r in rows] == ["1", "2", "3"]
    assert trust.trusted_catalog(track).unit_keys == ["u1", "u2", "u3"]


def test_incomplete_refresh_preserves_trusted_state(db, trust, track):
    trust.refresh(track, complete(units(300)), plugin_version="1.0.0")
    outcome = trust.refresh(track, incomplete(units(7)), plugin_version="1.0.0")
    assert outcome.state == "incomplete" and outcome.reason == "server_error"
    assert trust.trusted_catalog(track).unit_count == 300
    assert len(unit_rows(db, track)) == 300
    assert db.execute("SELECT count(*) FROM catalog_snapshots WHERE track_id = ? AND completeness = 'incomplete'",
                      (track,)).fetchone()[0] == 1


def test_incomplete_snapshots_are_bounded(db, trust, track):
    trust.refresh(track, complete(units(10)), plugin_version="1.0.0")
    for _ in range(6):
        trust.refresh(track, incomplete(units(1)), plugin_version="1.0.0")
    assert db.execute("SELECT count(*) FROM catalog_snapshots WHERE track_id = ? AND completeness = 'incomplete'",
                      (track,)).fetchone()[0] <= 3


def test_catalog_300_to_7_is_suspicious_and_keeps_trusted_units(db, trust, track):
    trust.refresh(track, complete(units(300)), plugin_version="1.0.0")
    outcome = trust.refresh(track, complete(units(7)), plugin_version="1.0.0")
    assert outcome.state == "suspicious" and outcome.lost == 293
    assert trust.trusted_catalog(track).unit_count == 300
    assert len(unit_rows(db, track)) == 300
    assert all(r["missing_since"] is None for r in unit_rows(db, track))


def test_two_consecutive_matching_complete_checks_recover_the_new_reality(db, trust, track):
    trust.refresh(track, complete(units(300)), plugin_version="1.0.0")
    trust.refresh(track, complete(units(7)), plugin_version="1.0.0")
    outcome = trust.refresh(track, complete(units(7)), plugin_version="1.0.0")
    assert outcome.state == "recovered"
    trusted = trust.trusted_catalog(track)
    assert trusted.unit_count == 7
    rows = unit_rows(db, track)
    assert len(rows) == 300  # records for missing units are kept, never deleted
    missing = [r for r in rows if r["missing_since"] is not None]
    assert len(missing) == 293 and all(r["availability"] == "unavailable" for r in missing)


def test_a_different_second_candidate_does_not_recover(db, trust, track):
    trust.refresh(track, complete(units(300)), plugin_version="1.0.0")
    trust.refresh(track, complete(units(7)), plugin_version="1.0.0")
    outcome = trust.refresh(track, complete(units(6)), plugin_version="1.0.0")
    assert outcome.state == "suspicious"
    assert trust.trusted_catalog(track).unit_count == 300


def test_recovered_source_stops_suspicion(db, trust, track):
    trust.refresh(track, complete(units(300)), plugin_version="1.0.0")
    trust.refresh(track, complete(units(7)), plugin_version="1.0.0")
    outcome = trust.refresh(track, complete(units(300)), plugin_version="1.0.0")
    assert outcome.state == "unchanged"
    assert trust.trusted_catalog(track).unit_count == 300
    trust.refresh(track, complete(units(7)), plugin_version="1.0.0")
    assert trust.trusted_catalog(track).unit_count == 300  # candidate history did not survive the recovery


@pytest.mark.parametrize("before,after,expected", [
    (300, 297, "trusted"),   # small loss is a normal change
    (6, 2, "trusted"),       # big proportion but fewer than 5 units lost
    (10, 5, "suspicious"),   # half lost and at least 5 units
])
def test_suspicion_heuristic_boundaries(db, trust, track, before, after, expected):
    trust.refresh(track, complete(units(before)), plugin_version="1.0.0")
    assert trust.refresh(track, complete(units(after)), plugin_version="1.0.0").state == expected


def test_growth_and_reordering_are_normal_updates(db, trust, track):
    trust.refresh(track, complete(units(3)), plugin_version="1.0.0")
    grown = units(3) + [UnitDescriptor(unit_key="special", order_index=3, raw_title="Special", unit_type="special")]
    assert trust.refresh(track, complete(grown), plugin_version="1.0.0").state == "trusted"
    reordered = [UnitDescriptor(unit_key=u.unit_key, order_index=i, raw_title=u.raw_title, number=u.number,
                                unit_type=u.unit_type) for i, u in enumerate(reversed(grown))]
    # Reordering alone is not a new reality (Master §20); the stored order still follows the source.
    assert trust.refresh(track, complete(reordered), plugin_version="1.0.0").state == "unchanged"
    assert [r["source_unit_key"] for r in unit_rows(db, track)] == ["special", "u3", "u2", "u1"]


def test_metadata_changes_update_the_same_unit(db, trust, track):
    trust.refresh(track, complete(units(2)), plugin_version="1.0.0")
    renamed = [UnitDescriptor(unit_key="u1", order_index=0, raw_title="Chapter 1: Renamed", number="1", unit_type="chapter"),
               UnitDescriptor(unit_key="u2", order_index=1, raw_title="Chapter 2", number="2", unit_type="chapter")]
    outcome = trust.refresh(track, complete(renamed), plugin_version="1.0.0")
    assert outcome.state == "unchanged"
    rows = unit_rows(db, track)
    assert len(rows) == 2 and rows[0]["raw_title"] == "Chapter 1: Renamed"


def test_reappearing_unit_clears_missing_since_without_duplicating(db, trust, track):
    trust.refresh(track, complete(units(10)), plugin_version="1.0.0")
    trust.refresh(track, complete(units(5)), plugin_version="1.0.0")
    trust.refresh(track, complete(units(5)), plugin_version="1.0.0")  # recovery
    assert len([r for r in unit_rows(db, track) if r["missing_since"]]) == 5
    trust.refresh(track, complete(units(10)), plugin_version="1.0.0")
    rows = unit_rows(db, track)
    assert len(rows) == 10 and all(r["missing_since"] is None for r in rows)
    assert all(r["availability"] == "available" for r in rows)


def test_trust_this_catalog_accepts_only_complete_snapshots(db, trust, track):
    trust.refresh(track, complete(units(300)), plugin_version="1.0.0")
    suspicious = trust.refresh(track, complete(units(7)), plugin_version="1.0.0")
    bad = trust.refresh(track, incomplete(units(2)), plugin_version="1.0.0")
    with pytest.raises(TrustRejected):
        trust.trust_catalog(track, bad.snapshot_id)
    assert trust.trusted_catalog(track).unit_count == 300
    trust.trust_catalog(track, suspicious.snapshot_id)
    assert trust.trusted_catalog(track).unit_count == 7


def test_previous_trusted_catalog_is_retained_and_history_is_bounded(db, trust, track):
    for count in (5, 6, 7, 8):
        trust.refresh(track, complete(units(count)), plugin_version="1.0.0")
    trusted = db.execute("SELECT trust, unit_count FROM catalog_snapshots WHERE track_id = ? AND trust IN"
                         " ('trusted_current','trusted_previous') ORDER BY fetched_at", (track,)).fetchall()
    assert [(r["trust"], r["unit_count"]) for r in trusted] == [("trusted_previous", 7), ("trusted_current", 8)]
    assert db.execute("SELECT count(*) FROM catalog_snapshots WHERE track_id = ?", (track,)).fetchone()[0] <= 6


def test_local_content_survives_a_catalog_collapse(db, trust, track):
    trust.refresh(track, complete(units(10)), plugin_version="1.0.0")
    unit_id = db.execute("SELECT id FROM reading_units WHERE source_unit_key = 'u9'").fetchone()[0]
    db.execute("INSERT INTO storage_roots (id, name, path, is_default, created_at, updated_at) VALUES ('r1','L','/l',1,?,?)",
               (NOW, NOW))
    db.execute("INSERT INTO assets (id, reading_unit_id, format, storage_root_id, relative_path, size_bytes, sha256,"
               " integrity, created_at, updated_at) VALUES (?,?,'cbz','r1','a.cbz',1,?,'ok',?,?)",
               (new_id(), unit_id, "0" * 64, NOW, NOW))
    trust.refresh(track, complete(units(2)), plugin_version="1.0.0")
    trust.refresh(track, complete(units(2)), plugin_version="1.0.0")
    assert db.execute("SELECT count(*) FROM assets WHERE integrity = 'ok'").fetchone()[0] == 1
    assert db.execute("SELECT missing_since IS NOT NULL FROM reading_units WHERE id = ?", (unit_id,)).fetchone()[0] == 1
