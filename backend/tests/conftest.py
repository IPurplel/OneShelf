"""Shared fixtures. All test data lives under pytest's tmp_path (isolated; never real library data)."""
import pytest

from oneshelf.db.connection import open_database
from oneshelf.db.migrate import migrate
from oneshelf.db.schema import MIGRATIONS


@pytest.fixture
def db(tmp_path):
    path = tmp_path / "app" / "oneshelf.db"
    path.parent.mkdir(parents=True)
    migrate(path, MIGRATIONS, snapshot_dir=tmp_path / "app" / "snapshots")
    conn = open_database(path)
    yield conn
    conn.close()
