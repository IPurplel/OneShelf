"""A listing-only source (search, work, catalog; no reader and no downloads) offers its own page, not a download.

Noor Book lists and describes books but lets OneShelf neither read nor download them. Its units used to be
treated as download-only, so the reader offered "Download to read" and every download failed (found
2026-10-30).
"""
import asyncio
from contextlib import asynccontextmanager
from pathlib import Path
from types import SimpleNamespace

import pytest

from oneshelf.domain.clock import utcnow_iso
from oneshelf.domain.ids import new_id
from oneshelf.downloads.engine import DownloadEngine
from oneshelf.net.governor import TrafficGovernor
from oneshelf.plugins.bundled import build_package
from oneshelf.plugins.manager import PluginManager
from oneshelf.plugins.package import load_package
from oneshelf.reader.cache import ReaderCache
from oneshelf.reader.service import ReaderService
from oneshelf.sources.service import SourceService
from oneshelf.storage.roots import register_root

NOORBOOK = Path(__file__).resolve().parents[3] / "plugins" / "official" / "oneshelf.noorbook"
SOURCE = "oneshelf.noorbook"
PAGE = "https://www.noor-book.com/كتاب-الليالي-البيضاء-دوستويفسكي-pdf"


@pytest.fixture
def listing_only(db, tmp_path):
    @asynccontextmanager
    async def factory():
        manager = PluginManager(db, store_dir=tmp_path / "app" / "plugins")
        path = build_package(NOORBOOK, tmp_path / "noorbook.osp")
        await manager.install_file(path, approved_permissions=load_package(path).permissions)
        (tmp_path / "library").mkdir(exist_ok=True)
        register_root(db, "Library", tmp_path / "library")
        cache = ReaderCache(tmp_path / "app" / "reader-cache", tmp_path / "app" / "cache.db")
        async with SourceService(db, manager, TrafficGovernor(), None) as service:
            yield SimpleNamespace(db=db, service=service, plugins=manager,
                                  reader=ReaderService(db, service, cache), unit=_book(db))
        cache.close()

    return factory


def _book(db) -> str:
    work, listing, track, unit, now = new_id(), new_id(), new_id(), new_id(), utcnow_iso()
    db.execute("INSERT INTO works (id, display_title, content_type, created_at, updated_at) VALUES (?,?,?,?,?)",
               (work, "الليالي البيضاء", "book", now, now))
    db.execute("INSERT INTO source_listings (id, source_id, source_listing_key, canonical_url, raw_title, work_id,"
               " created_at, last_seen_at) VALUES (?,?,?,?,?,?,?,?)",
               (listing, SOURCE, "كتاب-الليالي-البيضاء-دوستويفسكي-pdf", PAGE, "الليالي البيضاء", work, now, now))
    db.execute("INSERT INTO source_tracks (id, work_id, source_id, language, kind, listing_id, created_at)"
               " VALUES (?,?,?,?, 'source', ?, ?)", (track, work, SOURCE, "ar", listing, now))
    db.execute("INSERT INTO reading_units (id, track_id, source_unit_key, unit_type, source_order, first_seen_at)"
               " VALUES (?,?, 'كتاب-الليالي-البيضاء-دوستويفسكي-pdf', 'one_shot', 1, ?)", (unit, track, now))
    return unit


def test_the_bundled_noor_book_source_offers_neither_reading_nor_files():
    package = load_package(build_package(NOORBOOK, Path(__import__("tempfile").mkdtemp()) / "n.osp"))
    assert "reader" not in package.recipes and "downloads" not in package.recipes


def test_the_reader_offers_the_source_page_instead_of_a_download(listing_only):
    async def scenario():
        async with listing_only() as env:
            context = env.reader.context(env.unit)
            assert context["kind"] == "external" and context["url"] == PAGE
            assert context["formats"] == [] and "download" not in context
            assert env.service.downloads(SOURCE) is False and env.service.reads_online(SOURCE) is False
    asyncio.run(scenario())


def test_downloading_it_is_refused_before_any_job_exists(listing_only):
    async def scenario():
        async with listing_only() as env:
            engine = DownloadEngine(env.db, env.service, env.plugins, TrafficGovernor())
            with pytest.raises(ValueError, match="neither read nor download"):
                engine.enqueue([env.unit])
            assert env.db.execute("SELECT count(*) FROM download_jobs").fetchone()[0] == 0
    asyncio.run(scenario())
