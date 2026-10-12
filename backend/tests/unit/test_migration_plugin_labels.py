"""Existing plugin rows acquire durable label metadata after schema 18 migration."""
import hashlib

from oneshelf.db.connection import open_database
from oneshelf.db.migrate import migrate
from oneshelf.db.schema import MIGRATIONS
from oneshelf.plugins.manager import PluginManager
from tests.fixtures.osp import MANIFEST, build_osp


def test_existing_installed_label_is_backfilled_once(tmp_path):
    path = tmp_path / "old.db"
    migrate(path, MIGRATIONS[:17], snapshot_dir=tmp_path / "snap")
    with open_database(path) as conn:
        conn.execute("INSERT INTO plugins (id, name, state, active_version, trust_label, channel, installed_at,"
                     " updated_at) VALUES ('old.source', 'Old · Journal · FA/AR', 'uninstalled', NULL,"
                     " 'local', 'upload', '2026-01-01', '2026-01-01')")
    assert migrate(path, MIGRATIONS, snapshot_dir=tmp_path / "snap") == [18]
    with open_database(path) as conn:
        manager = PluginManager(conn, store_dir=tmp_path / "plugins")
        record = manager.get("old.source")
        assert record.category == "Journal"
        assert record.languages == ("FA", "AR")
        assert conn.execute("SELECT metadata_ready FROM plugins WHERE id = 'old.source'").fetchone()[0] == 1


def test_existing_unlabelled_package_backfills_default_language(tmp_path):
    path = tmp_path / "old.db"
    migrate(path, MIGRATIONS[:17], snapshot_dir=tmp_path / "snap")
    package_path = tmp_path / "plugins" / "example.books" / "1.0.0.osp"
    package_path.parent.mkdir(parents=True)
    build_osp(package_path, manifest=MANIFEST)
    sha256 = hashlib.sha256(package_path.read_bytes()).hexdigest()
    with open_database(path) as conn:
        conn.execute("INSERT INTO plugins (id, name, state, active_version, trust_label, channel, installed_at,"
                     " updated_at) VALUES ('example.books', 'Example Books', 'active', '1.0.0', 'local', 'upload',"
                     " '2026-01-01', '2026-01-01')")
        conn.execute("INSERT INTO plugin_versions (plugin_id, version, sha256, permissions_json,"
                     " approved_permissions_json, status, trust_label, test_report_json, store_relpath, installed_at)"
                     " VALUES ('example.books', '1.0.0', ?, '[]', '[]', 'active', 'local', '{}',"
                     " 'example.books/1.0.0.osp', '2026-01-01')", (sha256,))
    migrate(path, MIGRATIONS, snapshot_dir=tmp_path / "snap")
    with open_database(path) as conn:
        record = PluginManager(conn, store_dir=tmp_path / "plugins").get("example.books")
        assert (record.category, record.languages) == (None, ("EN",))
