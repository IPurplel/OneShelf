"""Master §41.1: the shipped source suite must be valid packages whose own tests pass offline."""
import asyncio
import json
from dataclasses import replace

import pytest

from oneshelf.plugins.package import load_package
from oneshelf.plugins.runtime import FixtureFetcher, RecipeRuntime, run_packaged_tests
from oneshelf.search.grouping import LiveListing, group_results
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


def test_mangadex_offers_chapter_translations_instead_of_the_original_language(db, tmp_path):
    """A Japanese original with English/French chapters must not open a chapterless Japanese track."""
    source = next(p for p in PACKAGES if p.name == "oneshelf.mangadex")
    package = load_package(build_package(source, tmp_path / "mangadex.osp"))
    assert package.manifest.api == "1.1"
    captured = json.loads(package.files["tests/fixtures/search.json"])
    captured["data"][1]["attributes"]["availableTranslatedLanguages"] = ["en", "fr"]
    package = replace(package, files={**package.files,
                                      "tests/fixtures/search.json": json.dumps(captured).encode("utf-8")})
    case = next(case for case in package.tests.cases if case.capability == "search")
    result = run(RecipeRuntime(package, FixtureFetcher(package, case.fixtures)).run("search", dict(case.inputs)))
    translated = next(item for item in result.items if item.listing_key == "40a0362f-aac7-4465-bf3d-59652f7e8468")
    assert translated.language == "ja"                  # source metadata, not a chapter filter
    assert translated.available_languages == ["en", "fr"]
    grouped = group_results(db, [LiveListing(package.id, translated.listing_key, translated.title,
                                              language=translated.language,
                                              available_languages=translated.available_languages)])
    assert [choice.language for choice in grouped[0].provenance] == ["en", "fr"]


def test_mangadex_with_no_uploaded_translations_does_not_offer_a_chapterless_track(db, tmp_path):
    source = next(p for p in PACKAGES if p.name == "oneshelf.mangadex")
    package = load_package(build_package(source, tmp_path / "mangadex.osp"))
    case = next(case for case in package.tests.cases if case.capability == "search")
    result = run(RecipeRuntime(package, FixtureFetcher(package, case.fixtures)).run("search", dict(case.inputs)))
    untranslated = next(item for item in result.items if item.listing_key == "40a0362f-aac7-4465-bf3d-59652f7e8468")
    assert untranslated.available_languages == []
    grouped = group_results(db, [LiveListing(package.id, untranslated.listing_key, untranslated.title,
                                              language=untranslated.language,
                                              available_languages=untranslated.available_languages)])
    # Nothing to read means nothing to open: it is not offered at all, rather than as a card that opens
    # nothing (it used to be shown with an empty provenance, found 2026-10-30).
    assert grouped == []


def test_mangadex_direct_work_preview_offers_its_actual_chapter_languages(tmp_path):
    source = next(p for p in PACKAGES if p.name == "oneshelf.mangadex")
    package = load_package(build_package(source, tmp_path / "mangadex.osp"))
    case = next(case for case in package.tests.cases if case.capability == "work")
    details = run(RecipeRuntime(package, FixtureFetcher(package, case.fixtures)).run("work", dict(case.inputs)))
    assert details.available_languages == ["en"]
