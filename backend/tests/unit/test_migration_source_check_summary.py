"""Migration 0021 (UI-004): the last successful check of each source survives the signal pruning."""
from oneshelf.db.connection import open_database
from oneshelf.db.migrate import migrate
from oneshelf.db.schema import MIGRATIONS
from oneshelf.sources.health import checks_recorded_since_install, last_successful_check, record_signal


def test_upgrade_backfills_last_success_from_the_signals_still_held(tmp_path):
    path = tmp_path / "library.db"
    migrate(path, MIGRATIONS[:20], snapshot_dir=tmp_path / "snapshots")
    with open_database(path) as conn:
        for source, outcome, at in (("a", "success", "2026-10-10T00:00:00+00:00"), ("a", "failure", "2026-10-12T00:00:00+00:00"),
                                    ("b", "failure", "2026-10-11T00:00:00+00:00")):
            conn.execute("INSERT INTO source_health_signals (source_id, capability, outcome, category, plugin_version,"
                         " created_at) VALUES (?, 'search', ?, NULL, '1', ?)", (source, outcome, at))
    assert migrate(path, MIGRATIONS[:21], snapshot_dir=tmp_path / "snapshots") == [21]
    with open_database(path) as conn:
        assert last_successful_check(conn, "a") == "2026-10-10T00:00:00+00:00"   # the later failure does not erase it
        assert last_successful_check(conn, "b") is None                         # never succeeded
        assert last_successful_check(conn, "c") is None                         # never checked
        record_signal(conn, "b", "catalog", "success", None, "1")
        assert last_successful_check(conn, "b") is not None
        conn.execute("DELETE FROM source_health_signals")                         # pruning cannot take it away
        assert last_successful_check(conn, "b") is not None


def test_never_is_claimed_only_for_sources_installed_once_checks_were_kept(tmp_path):
    path = tmp_path / "library.db"
    migrate(path, MIGRATIONS[:20], snapshot_dir=tmp_path / "snapshots")
    with open_database(path) as conn:
        conn.execute("INSERT INTO plugins (id, name, state, active_version, trust_label, channel, installed_at,"
                     " updated_at) VALUES ('old', 'Old', 'disabled', NULL, 'official', 'bundled', ?, ?)",
                     ("2026-01-01T00:00:00+00:00", "2026-01-01T00:00:00+00:00"))
    migrate(path, MIGRATIONS, snapshot_dir=tmp_path / "snapshots")
    with open_database(path) as conn:
        conn.execute("INSERT INTO plugins (id, name, state, active_version, trust_label, channel, installed_at,"
                     " updated_at) VALUES ('new', 'New', 'disabled', NULL, 'official', 'bundled', ?, ?)",
                     ("2999-01-01T00:00:00+00:00", "2999-01-01T00:00:00+00:00"))
        assert checks_recorded_since_install(conn, "new") is True       # no success on record means never
        assert checks_recorded_since_install(conn, "old") is False      # its successes may have been pruned
        assert checks_recorded_since_install(conn, "absent") is False
