"""A download-only source (downloads, no reader recipe) is read from its file, never through `reader`.

Before the file exists the reader says so — `kind: "download"`, 409 DOWNLOAD_REQUIRED — instead of asking
the source for a capability it does not have, which surfaced as "unsupported: capability 'reader' is not
provided by this plugin" and was recorded as a source failure (found 2026-10-19).
"""
import asyncio
import hashlib
from contextlib import asynccontextmanager
from pathlib import Path
from types import SimpleNamespace

import pytest

from oneshelf.api.library import reader_context, reader_page, reader_pages
from oneshelf.domain.clock import utcnow_iso
from oneshelf.domain.ids import new_id
from oneshelf.net.governor import TrafficGovernor
from oneshelf.plugins.bundled import build_package
from oneshelf.plugins.manager import PluginManager
from oneshelf.plugins.package import load_package
from oneshelf.reader.cache import ReaderCache
from oneshelf.reader.service import DownloadRequired, ReaderService
from oneshelf.sources.service import SourceService
from oneshelf.storage.roots import register_root

GUTENBERG = Path(__file__).resolve().parents[3] / "plugins" / "official" / "oneshelf.gutenberg"
SOURCE = "oneshelf.gutenberg"


@pytest.fixture
def books(db, tmp_path):
    @asynccontextmanager
    async def factory():
        manager = PluginManager(db, store_dir=tmp_path / "app" / "plugins")
        path = build_package(GUTENBERG, tmp_path / "gutenberg.osp")
        await manager.install_file(path, approved_permissions=load_package(path).permissions)
        (tmp_path / "library").mkdir(exist_ok=True)
        root = register_root(db, "Library", tmp_path / "library")
        cache = ReaderCache(tmp_path / "app" / "reader-cache", tmp_path / "app" / "cache.db")
        async with SourceService(db, manager, TrafficGovernor(), None) as service:
            reader = ReaderService(db, service, cache)
            yield SimpleNamespace(db=db, root=root, service=service, reader=reader, unit=_book(db))
        cache.close()

    return factory


def _book(db) -> str:
    work, track, unit, now = new_id(), new_id(), new_id(), utcnow_iso()
    db.execute("INSERT INTO works (id, display_title, content_type, created_at, updated_at) VALUES (?,?,?,?,?)",
               (work, "Frankenstein", "book", now, now))
    db.execute("INSERT INTO source_tracks (id, work_id, source_id, language, kind, created_at)"
               " VALUES (?,?,?,?, 'source', ?)", (track, work, SOURCE, "en", now))
    db.execute("INSERT INTO reading_units (id, track_id, source_unit_key, unit_type, source_order, first_seen_at)"
               " VALUES (?,?, '84', 'other', 1, ?)", (unit, track, now))
    return unit


def _add_pdf(env) -> None:
    content, relative, now = b"%PDF-1.4 book", "Books/Frankenstein/en/book.pdf", utcnow_iso()
    path = Path(env.root.path) / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    env.db.execute(
        "INSERT INTO assets (id, reading_unit_id, format, storage_root_id, relative_path, size_bytes, sha256,"
        " integrity, created_at, updated_at) VALUES (?,?, 'pdf', ?,?,?,?, 'ok', ?, ?)",
        (new_id(), env.unit, env.root.id, relative, len(content), hashlib.sha256(content).hexdigest(), now, now))


def _request(reader):
    return SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(services=SimpleNamespace(reader=reader))))


def _reader_signals(db) -> list:
    return db.execute("SELECT outcome, category FROM source_health_signals WHERE source_id = ? AND capability = 'reader'",
                      (SOURCE,)).fetchall()


def test_the_bundled_book_source_is_download_only():
    package = load_package(build_package(GUTENBERG, Path(__import__("tempfile").mkdtemp()) / "g.osp"))
    assert "downloads" in package.recipes and "reader" not in package.recipes


def test_an_undownloaded_book_asks_for_its_file(books):
    async def scenario():
        async with books() as env:
            context = env.reader.context(env.unit)
            assert context["kind"] == "download"
            assert context["formats"] == []
            assert context["download"] == {"state": None, "error": None}
    asyncio.run(scenario())


def test_pages_of_an_undownloaded_book_say_download_required_not_unsupported(books):
    async def scenario():
        async with books() as env:
            with pytest.raises(DownloadRequired):
                await env.reader.pages(env.unit)
            response = await reader_pages(_request(env.reader), env.unit)
            assert response.status_code == 409
            assert b"DOWNLOAD_REQUIRED" in response.body
            assert b"unsupported" not in response.body
            page = await reader_page(_request(env.reader), env.unit, 1)
            assert page.status_code == 409
    asyncio.run(scenario())


def test_asking_for_a_book_never_marks_its_source_failed(books):
    async def scenario():
        async with books() as env:
            for _ in range(3):
                await reader_pages(_request(env.reader), env.unit)
            assert _reader_signals(env.db) == []
    asyncio.run(scenario())


def test_a_queued_download_is_reported_with_the_context(books):
    async def scenario():
        async with books() as env:
            now = utcnow_iso()
            batch = new_id()
            env.db.execute("INSERT INTO download_batches (id, created_at, updated_at) VALUES (?,?,?)", (batch, now, now))
            env.db.execute("INSERT INTO download_jobs (id, batch_id, reading_unit_id, state, created_at, updated_at)"
                           " VALUES (?,?,?, 'QUEUED', ?, ?)", (new_id(), batch, env.unit, now, now))
            assert env.reader.context(env.unit)["download"] == {"state": "QUEUED", "error": None}
    asyncio.run(scenario())


def test_once_downloaded_the_book_opens_from_its_file(books):
    async def scenario():
        async with books() as env:
            _add_pdf(env)
            context = await reader_context(_request(env.reader), env.unit)
            assert context["formats"] == ["pdf"]
            assert context["kind"] != "download"
            assert env.reader.local_file(env.unit).format == "pdf"
    asyncio.run(scenario())
