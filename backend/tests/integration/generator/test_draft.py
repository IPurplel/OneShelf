"""Master §12.2–12.3: the draft is a real declarative package, and Generate is not Install."""
import asyncio
import zipfile

import pytest

from oneshelf.generator.discovery import discover
from oneshelf.generator.draft import build_draft, write_package
from oneshelf.plugins.manager import PluginManager
from oneshelf.plugins.package import load_package
from testsource.server import CDN_HOST, HOST, TestSourceServer


def run(coro):
    return asyncio.run(asyncio.wait_for(coro, 60))


def mapped(path="/gen/search?q=a"):
    async def go():
        async with TestSourceServer() as server:
            return await discover(f"http://{HOST}{path}", dev_hosts=server.hosts(), allow_http=True)
    return run(go())


@pytest.fixture
def draft():
    return build_draft(mapped(), name="Test Source (generated)")


def test_the_draft_describes_only_what_discovery_confirmed(draft):
    manifest = draft.manifest
    assert manifest["id"].startswith("generated.") and manifest["version"] == "0.1.0"
    assert set(manifest["capabilities"]) == {"search", "work", "catalog", "reader"}
    assert manifest["network"]["domains"] == [HOST] and manifest["network"]["cdn_domains"] == [CDN_HOST]
    assert set(draft.recipes) == {"search", "work", "catalog", "reader"}
    assert draft.confidence["search"] in ("confirmed", "probable")


def test_the_draft_is_a_valid_package_that_the_runtime_accepts(draft, tmp_path):
    path = write_package(draft, tmp_path / "draft.osp")
    with zipfile.ZipFile(path) as archive:
        names = set(archive.namelist())
    assert {"manifest.yaml", "source.yaml", "recipes/search.yaml", "tests/tests.yaml"} <= names
    package = load_package(path)                       # strict schema validation, RE2 patterns, safe transforms
    assert package.manifest.name == "Test Source (generated)"
    assert [str(rule) for rule in package.manifest.network.domains] == [HOST]


def test_generating_never_installs(db, draft, tmp_path):
    manager = PluginManager(db, store_dir=tmp_path / "plugins")
    write_package(draft, tmp_path / "draft.osp")
    assert manager.list() == []                # §12.3: Generate != Install
    assert db.execute("SELECT count(*) FROM plugins").fetchone()[0] == 0


def test_the_draft_carries_offline_tests_with_captured_fixtures(draft, tmp_path):
    path = write_package(draft, tmp_path / "draft.osp")
    with zipfile.ZipFile(path) as archive:
        cases = archive.read("tests/tests.yaml").decode()
        fixtures = [n for n in archive.namelist() if n.startswith("tests/fixtures/")]
    assert "capability: search" in cases and fixtures
    assert any(name.endswith(".html") for name in fixtures)


def test_unsupported_capabilities_are_left_out_rather_than_guessed():
    site = mapped("/js-search?q=a")
    draft = build_draft(site, name="JavaScript only")
    assert "search" not in draft.manifest["capabilities"]
    assert draft.unsupported and "search" in draft.unsupported
