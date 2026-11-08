"""Shared fixtures. All test data lives under pytest's tmp_path (isolated; never real library data)."""
import pytest
import os


def _symlink_works():
    import tempfile
    try:
        with tempfile.TemporaryDirectory() as td:
            target = os.path.join(td, "t")
            os.mkdir(target)
            os.symlink(target, os.path.join(td, "l"))
        return True
    except OSError:
        return False


def _browser_available():
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            return os.path.exists(p.chromium.executable_path)
    except Exception:
        return False


@pytest.fixture(autouse=True)
def _skip_without_environment(request):
    node = request.node
    if node.get_closest_marker("browser") and not _browser_available():
        pytest.skip("Playwright Chromium is not installed")
    if node.get_closest_marker("requires_symlink") and not _symlink_works():
        pytest.skip("symlinks not available (Windows privilege)")

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
