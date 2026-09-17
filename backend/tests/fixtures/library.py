"""Shared on-disk library fixture used by backup, restore and export tests."""
import hashlib
import zipfile
from datetime import UTC, datetime
from pathlib import Path

import pytest

from oneshelf.db.connection import open_database
from oneshelf.db.migrate import migrate
from oneshelf.db.schema import MIGRATIONS
from oneshelf.domain.clock import utcnow_iso
from oneshelf.domain.ids import new_id
from oneshelf.search.index import index_work
from oneshelf.storage.roots import register_root

NOW = utcnow_iso()


class Library:
    """A small library on disk: one root, works with assets, shelf, follow, progress and settings."""

    def __init__(self, conn, path: Path, root):
        self.conn, self.path, self.root = conn, path, root
        self.works: dict[str, dict] = {}

    def add_work(self, title, *, source="mangadex", language="en", content_type="manga", content=b"chapter one",
                 relative=None, progress=None, shelf=True, fmt="cbz"):
        work, track, unit, asset = new_id(), new_id(), new_id(), new_id()
        relative = relative or f"Sequential Art/{title}/{language}/{source}/one.{fmt}"
        self.conn.execute("INSERT INTO works (id, display_title, content_type, created_at, updated_at)"
                          " VALUES (?,?,?,?,?)", (work, title, content_type, NOW, NOW))
        kind = "local" if source == "local" else "source"
        self.conn.execute("INSERT INTO source_tracks (id, work_id, source_id, language, kind, created_at)"
                          " VALUES (?,?,?,?,?,?)", (track, work, source, language, kind, NOW))
        self.conn.execute("INSERT INTO reading_units (id, track_id, source_unit_key, unit_type, source_order,"
                          " first_seen_at) VALUES (?,?,?,'chapter',1,?)", (unit, track, f"{title}-1", NOW))
        if content is not None:
            file_path = self.root_path / relative
            file_path.parent.mkdir(parents=True, exist_ok=True)
            file_path.write_bytes(content)
            self.conn.execute(
                "INSERT INTO assets (id, reading_unit_id, format, storage_root_id, relative_path, size_bytes, sha256,"
                " integrity, created_at, updated_at) VALUES (?,?,?,?,?,?,?, 'ok', ?, ?)",
                (asset, unit, fmt, self.root.id, relative, len(content), hashlib.sha256(content).hexdigest(), NOW, NOW))
        if shelf:
            self.conn.execute("INSERT INTO shelf_entries (work_id, added_at) VALUES (?, ?)", (work, NOW))
        if progress is not None:
            self.conn.execute("INSERT INTO reading_state (reading_unit_id, read_state, fraction, revision, updated_at)"
                              " VALUES (?,?,?,?,?)", (unit, "partial", progress, 1, NOW))
        index_work(self.conn, work)
        self.works[title] = {"work_id": work, "track_id": track, "unit_id": unit, "asset_id": asset,
                             "relative": relative}
        return self.works[title]

    def add_asset(self, unit_id, *, fmt, content=b"other format", relative=None):
        """A second format for an existing unit (PDF and CBZ coexist, §22)."""
        asset = new_id()
        relative = relative or f"Sequential Art/{unit_id}/alternate.{fmt}"
        file_path = self.root_path / relative
        file_path.parent.mkdir(parents=True, exist_ok=True)
        file_path.write_bytes(content)
        self.conn.execute(
            "INSERT INTO assets (id, reading_unit_id, format, storage_root_id, relative_path, size_bytes, sha256,"
            " integrity, created_at, updated_at) VALUES (?,?,?,?,?,?,?, 'ok', ?, ?)",
            (asset, unit_id, fmt, self.root.id, relative, len(content), hashlib.sha256(content).hexdigest(), NOW, NOW))
        return asset

    @property
    def root_path(self) -> Path:
        return Path(self.root.path)

    def add_plugin(self, plugin_id="mangadex", version="1.2.0", permissions=("network:domain:mangadex.org",)):
        import json
        self.conn.execute("INSERT INTO plugins (id, name, state, active_version, trust_label, channel, installed_at,"
                          " updated_at) VALUES (?,?, 'active', ?, 'community', 'registry', ?, ?)",
                          (plugin_id, plugin_id, version, NOW, NOW))
        self.conn.execute("INSERT INTO plugin_versions (plugin_id, version, sha256, permissions_json,"
                          " approved_permissions_json, status, trust_label, test_report_json, store_relpath,"
                          " installed_at) VALUES (?,?,?,?,?, 'active', 'community', '{}', ?, ?)",
                          (plugin_id, version, "0" * 64, json.dumps(sorted(permissions)), json.dumps(sorted(permissions)),
                           f"{plugin_id}/{version}.osp", NOW))

    def add_secret_session(self, source_id="mangadex", secret="SUPER-SECRET-COOKIE"):
        self.conn.execute("INSERT INTO source_session_refs (source_id, state, secret_ref, updated_at)"
                          " VALUES (?, 'connected', ?, ?)", (source_id, f"secrets.db:{source_id}", NOW))
        return secret


@pytest.fixture
def library(tmp_path):
    data = tmp_path / "data"
    data.mkdir()
    db_path = data / "oneshelf.db"
    migrate(db_path, MIGRATIONS, snapshot_dir=data / "snapshots")
    conn = open_database(db_path)
    (tmp_path / "library").mkdir()
    root = register_root(conn, "Library", tmp_path / "library")
    yield Library(conn, tmp_path, root)
    conn.close()


@pytest.fixture
def clock():
    state = {"now": datetime(2026, 9, 17, 12, 0, tzinfo=UTC)}
    return state


def archive_names(path: Path) -> list[str]:
    with zipfile.ZipFile(path) as z:
        return sorted(z.namelist())


def read_manifest(path: Path) -> dict:
    import json
    with zipfile.ZipFile(path) as z:
        return json.loads(z.read("manifest.json"))
