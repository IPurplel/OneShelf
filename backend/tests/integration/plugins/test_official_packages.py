"""Every shipped §41 adapter, checked against its own packaged fixtures.

These are the packages OneShelf installs by default, so their recipes are held to the same standard as
any other: each one builds, validates, and passes the tests it ships with — offline, against captured
pages, so a change to a recipe or to shared extraction is caught here rather than on a live site.
"""
import asyncio

import pytest

from oneshelf.plugins.package import load_package
from oneshelf.plugins.runtime import run_packaged_tests
from plugins.build import build_package, official_packages

PACKAGES = sorted(p.name for p in official_packages())


def test_the_expected_adapters_ship():
    assert PACKAGES == ["oneshelf.arxiv", "oneshelf.gutenberg", "oneshelf.mangadex",
                        "oneshelf.standard-ebooks", "oneshelf.tapas", "oneshelf.webtoon"]


@pytest.mark.parametrize("name", PACKAGES)
def test_an_official_adapter_passes_the_tests_it_ships_with(name, tmp_path):
    source = next(p for p in official_packages() if p.name == name)
    package = load_package(build_package(source, tmp_path / f"{name}.osp"))
    report = asyncio.run(run_packaged_tests(package))
    assert report.passed, f"{name}: {report.failures}"
    assert report.cases >= 2, f"{name} ships too few cases to prove anything"


@pytest.mark.parametrize("name", PACKAGES)
def test_an_official_adapter_declares_what_it_can_and_cannot_do(name, tmp_path):
    """A capability is either declared and exercised, or absent — never declared and hoped for (§41.5)."""
    source = next(p for p in official_packages() if p.name == name)
    package = load_package(build_package(source, tmp_path / f"{name}.osp"))
    declared = set(package.manifest.capabilities)
    assert declared == set(package.recipes), f"{name}: manifest and recipes disagree"
    exercised = {case.capability for case in package.tests.cases}
    assert declared - {"health", "check_session"} <= exercised, \
        f"{name}: declared but never exercised: {sorted(declared - exercised)}"
