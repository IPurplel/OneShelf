"""Migration 0014: official adapters can be recorded as bundled, and the bootstrap has somewhere durable
to remember what it did (release requirement, 2026-09-21).

The plugins table had to be rebuilt to widen its channel constraint. That is the one kind of migration
that can quietly lose rows or orphan children, so this checks both, against a database that already
holds plugins and versions from the previous schema.
"""
import sqlite3
from contextlib import closing

import pytest

from oneshelf.db.migrate import migrate
from oneshelf.db.schema import MIGRATIONS

NOW = "2026-01-01T00:00:00+00:00"


def at_version(path, version):
    migrate(path, MIGRATIONS[:version], snapshot_dir=path.parent / "snap")


@pytest.fixture
def v13_with_plugins(tmp_path):
    path = tmp_path / "oneshelf.db"
    at_version(path, 13)
    with closing(sqlite3.connect(path)) as conn:
        conn.execute("PRAGMA foreign_keys = ON")
        for pid, state, active in (("oneshelf.a", "active", "1.0.0"), ("oneshelf.b", "uninstalled", None)):
            conn.execute("INSERT INTO plugins (id, name, state, active_version, trust_label, channel, installed_at,"
                         " updated_at) VALUES (?,?,?,?, 'official', 'upload', ?, ?)",
                         (pid, pid, state, active, NOW, NOW))
        conn.execute("INSERT INTO plugin_versions (plugin_id, version, sha256, permissions_json,"
                     " approved_permissions_json, status, trust_label, test_report_json, store_relpath,"
                     " installed_at) VALUES ('oneshelf.a', '1.0.0', ?, '[]', '[]', 'active', 'official', '{}',"
                     " 'oneshelf.a/1.0.0.osp', ?)", ("a" * 64, NOW))
        conn.commit()
    return path


def test_existing_plugins_and_versions_survive_the_rebuild(v13_with_plugins):
    migrate(v13_with_plugins, MIGRATIONS, snapshot_dir=v13_with_plugins.parent / "snap")
    with closing(sqlite3.connect(v13_with_plugins)) as conn:
        rows = conn.execute("SELECT id, state, active_version, channel FROM plugins ORDER BY id").fetchall()
        assert rows == [("oneshelf.a", "active", "1.0.0", "upload"), ("oneshelf.b", "uninstalled", None, "upload")]
        assert conn.execute("SELECT plugin_id, version, status FROM plugin_versions").fetchall() == [
            ("oneshelf.a", "1.0.0", "active")]


def test_the_rebuilt_tables_still_enforce_their_relationships(v13_with_plugins):
    migrate(v13_with_plugins, MIGRATIONS, snapshot_dir=v13_with_plugins.parent / "snap")
    with closing(sqlite3.connect(v13_with_plugins)) as conn:
        conn.execute("PRAGMA foreign_keys = ON")
        assert conn.execute("PRAGMA foreign_key_check").fetchall() == []
        fk = conn.execute("PRAGMA foreign_key_list(plugin_versions)").fetchall()
        assert [(row[2], row[3], row[4]) for row in fk] == [("plugins", "plugin_id", "id")]
        with pytest.raises(sqlite3.IntegrityError):                       # a version needs its plugin
            conn.execute("INSERT INTO plugin_versions (plugin_id, version, sha256, permissions_json, status,"
                         " trust_label, test_report_json, store_relpath, installed_at) VALUES"
                         " ('nobody', '1.0.0', ?, '[]', 'active', 'official', '{}', 'x', ?)", ("b" * 64, NOW))
        with pytest.raises(sqlite3.IntegrityError):                       # still one active version each
            conn.execute("INSERT INTO plugin_versions (plugin_id, version, sha256, permissions_json, status,"
                         " trust_label, test_report_json, store_relpath, installed_at) VALUES"
                         " ('oneshelf.a', '2.0.0', ?, '[]', 'active', 'official', '{}', 'x', ?)", ("c" * 64, NOW))


def test_bundled_is_now_a_channel_and_nothing_else_is(tmp_path):
    path = tmp_path / "oneshelf.db"
    migrate(path, MIGRATIONS, snapshot_dir=tmp_path / "snap")
    with closing(sqlite3.connect(path)) as conn:
        conn.execute("INSERT INTO plugins (id, name, state, active_version, trust_label, channel, installed_at,"
                     " updated_at) VALUES ('oneshelf.x', 'x', 'active', '1.0.0', 'official', 'bundled', ?, ?)",
                     (NOW, NOW))
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute("INSERT INTO plugins (id, name, state, active_version, trust_label, channel,"
                         " installed_at, updated_at) VALUES ('oneshelf.y', 'y', 'active', '1.0.0', 'official',"
                         " 'sideloaded', ?, ?)", (NOW, NOW))


def test_the_bootstrap_has_a_durable_marker_and_a_record_per_source(tmp_path):
    path = tmp_path / "oneshelf.db"
    migrate(path, MIGRATIONS, snapshot_dir=tmp_path / "snap")
    with closing(sqlite3.connect(path)) as conn:
        tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
        assert {"app_meta", "bundled_plugins"} <= tables
        # A fresh database has never bootstrapped anything: there is no marker yet.
        assert conn.execute("SELECT count(*) FROM app_meta").fetchone()[0] == 0
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute("INSERT INTO bundled_plugins (plugin_id, status, bundled_version, updated_at)"
                         " VALUES ('oneshelf.x', 'invented', '1.0.0', ?)", (NOW,))
