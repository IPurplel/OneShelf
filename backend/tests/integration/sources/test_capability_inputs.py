"""Master §4, §41.3: a multi-language source needs the track's language; others must not be disturbed."""
import asyncio

import pytest

from oneshelf.net.governor import TrafficGovernor
from oneshelf.plugins.manager import PluginManager
from oneshelf.plugins.package import load_package
from oneshelf.sessions.manager import SessionManager
from oneshelf.sessions.store import SecretsStore, load_or_create_key
from oneshelf.sources.service import SourceService
from testsource.build import build_package
from testsource.server import TestSourceServer

TS = "oneshelf.test-source"


def run(coro):
    return asyncio.run(asyncio.wait_for(coro, 60))


@pytest.fixture
def manager(db, tmp_path):
    manager = PluginManager(db, store_dir=tmp_path / "plugins")
    path = build_package(tmp_path / "ts.osp")
    run(manager.install_file(path, approved_permissions=load_package(path).permissions))
    return manager


async def capability(db, tmp_path, manager, name, inputs):
    store = SecretsStore(tmp_path / "secrets.db", load_or_create_key(tmp_path / "key"))
    try:
        sessions = SessionManager(db, store, events=None)
        async with TestSourceServer() as server:
            async with SourceService(db, manager, TrafficGovernor(), sessions, dev_test_source=True,
                                     dev_hosts=server.hosts()) as service:
                return await service.run(TS, name, inputs)
    finally:
        store.close()


def test_inputs_a_recipe_does_not_declare_are_dropped_rather_than_failing(db, tmp_path, manager):
    """The core may offer `language`; a source that ignores it still works (§3.1: nothing changes silently)."""
    result = run(capability(db, tmp_path, manager, "catalog", {"listing_key": "irregular", "language": "en"}))
    assert result.items and result.items[0].unit_key == "irr-prologue"


def test_declared_inputs_are_passed_through(db, tmp_path, manager):
    result = run(capability(db, tmp_path, manager, "search", {"query": "chronicle", "language": "en"}))
    assert [item.title for item in result.items] == ["The Irregular Chronicle"]
