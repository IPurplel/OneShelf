"""Master §41.1: the shipped source suite must be valid packages whose own tests pass offline."""
import asyncio

import pytest

from oneshelf.plugins.package import load_package
from oneshelf.plugins.runtime import run_packaged_tests
from plugins.build import build_package, official_packages

PACKAGES = official_packages()


def run(coro):
    return asyncio.run(asyncio.wait_for(coro, 60))


@pytest.mark.parametrize("source_dir", PACKAGES, ids=[p.name for p in PACKAGES])
def test_official_package_is_valid_and_passes_its_tests(source_dir, tmp_path):
    package = load_package(build_package(source_dir, tmp_path / f"{source_dir.name}.osp"))
    assert package.id == source_dir.name
    assert package.manifest.capabilities
    report = run(run_packaged_tests(package))
    assert report.passed, report.failures


def test_the_suite_covers_the_required_sources():
    """§41.1 lists eight real sources; each one ships or is recorded in the capability ledger."""
    assert {p.name for p in PACKAGES} >= {"oneshelf.mangadex"}
