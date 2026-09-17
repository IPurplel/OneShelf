"""Shared environment for download engine tests: live Test Source + installed plugin + storage root."""
import asyncio
import zipfile
from contextlib import asynccontextmanager
from pathlib import Path

import aiohttp
import pytest

from oneshelf.catalog.trust import CatalogTrust
from oneshelf.downloads.engine import DownloadEngine
from oneshelf.net.governor import TrafficGovernor
from oneshelf.plugins.manager import PluginManager
from oneshelf.plugins.package import load_package
from oneshelf.search.grouping import LiveListing, persist_listing
from oneshelf.sessions.manager import SessionManager
from oneshelf.sessions.store import SecretsStore, SessionState, load_or_create_key
from oneshelf.sources.service import SourceService
from oneshelf.storage.roots import register_root
from testsource.build import build_package
from testsource.server import HOST, SESSION_COOKIE, TestSourceServer

TS = "oneshelf.test-source"


def run(coro, timeout=60):
    return asyncio.run(asyncio.wait_for(coro, timeout))


@pytest.fixture
def plugins(db, tmp_path):
    manager = PluginManager(db, store_dir=tmp_path / "app" / "plugins")
    path = build_package(tmp_path / "ts.osp")
    asyncio.run(manager.install_file(path, approved_permissions=load_package(path).permissions))
    return manager


@pytest.fixture
def root(db, tmp_path):
    (tmp_path / "library").mkdir()
    return register_root(db, "Library", tmp_path / "library")


class Environment:
    def __init__(self, db, service, engine, server, sessions, governor, root):
        self.db, self.service, self.engine, self.server = db, service, engine, server, 
        self.sessions, self.governor, self.root = sessions, governor, root

    async def add_work(self, listing_key, title, *, content_type="manga", language="en"):
        binding = persist_listing(self.db, LiveListing(source_id=TS, listing_key=listing_key, title=title,
                                                       content_type=content_type, language=language,
                                                       url=f"http://{HOST}/work/{listing_key}"),
                                  work_id=None, decided_by="user")
        if binding.work_id is None:
            from oneshelf.domain.clock import utcnow_iso
            from oneshelf.domain.ids import new_id
            work_id, now = new_id(), utcnow_iso()
            self.db.execute("INSERT INTO works (id, display_title, content_type, created_at, updated_at)"
                            " VALUES (?,?,?,?,?)", (work_id, title, content_type, now, now))
            binding = persist_listing(self.db, LiveListing(source_id=TS, listing_key=listing_key, title=title,
                                                           content_type=content_type, language=language),
                                      work_id=work_id, decided_by="user")
        result = await self.service.run(TS, "catalog", {"listing_key": listing_key})
        CatalogTrust(self.db).refresh(binding.track_id, result, plugin_version="1.0.0")
        return binding

    def unit_id(self, unit_key):
        return self.db.execute("SELECT id FROM reading_units WHERE source_unit_key = ?", (unit_key,)).fetchone()[0]

    def job_rows(self, batch_id=None):
        query = "SELECT * FROM download_jobs"
        args = ()
        if batch_id:
            query += " WHERE batch_id = ?"
            args = (batch_id,)
        return self.db.execute(query + " ORDER BY queue_position, created_at", args).fetchall()

    def assets(self):
        return self.db.execute("SELECT * FROM assets ORDER BY created_at").fetchall()

    def files(self):
        return sorted(p for p in Path(self.root.path).rglob("*") if p.is_file() and ".oneshelf" not in p.parts)

    def requests_for(self, needle):
        return [r for r in self.server.scenario.request_log if needle in r]

    async def control(self, **changes):
        async with aiohttp.ClientSession() as s:
            async with s.post(f"http://127.0.0.1:{self.server.port}/__control", json=changes) as r:
                assert r.status == 200

    async def connect_session(self):
        async with aiohttp.ClientSession() as s:
            async with s.post(f"http://127.0.0.1:{self.server.port}/login",
                              data={"username": "reader", "password": "correct horse"}, allow_redirects=False) as r:
                token = r.cookies[SESSION_COOKIE].value
        self.sessions.connect(TS, SessionState(storage_state={"cookies": [
            {"name": SESSION_COOKIE, "value": token, "domain": HOST, "path": "/", "secure": False, "httpOnly": True,
             "expires": -1, "sameSite": "Lax"}], "origins": []}))


@pytest.fixture
def environment(db, tmp_path, plugins, root):
    @asynccontextmanager
    async def factory(*, fault=None):
        store = SecretsStore(tmp_path / "app" / "secrets.db", load_or_create_key(tmp_path / "keys" / "session.key"))
        sessions = SessionManager(db, store, events=None)
        governor = TrafficGovernor()
        async with TestSourceServer() as server:
            async with SourceService(db, plugins, governor, sessions, dev_test_source=True,
                                     dev_hosts=server.hosts()) as service:
                engine = DownloadEngine(db, service, plugins, governor, fault=fault, backoff_base_seconds=1.05)
                yield Environment(db, service, engine, server, sessions, governor, root)
        store.close()

    return factory


def cbz_pages(path):
    with zipfile.ZipFile(path) as z:
        return [n for n in z.namelist() if n.lower().endswith((".png", ".jpg", ".jpeg", ".webp"))]
