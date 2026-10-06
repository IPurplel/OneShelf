"""Text reading units (plugin API 1.2): reader items that are sanitised markup instead of image URLs."""
import asyncio
import copy
import json

import pytest

from oneshelf.plugins.package import PackageError, load_package
from oneshelf.plugins.runtime import RecipeRuntime, run_packaged_tests
from oneshelf.text.sanitise import MAX_TEXT_UNIT_BYTES
from tests.fixtures.osp import MANIFEST, RECIPES, TESTS, build_osp
from tests.unit.plugins.test_runtime import MemoryFetcher

CHAPTER_URL = "https://books.example/chapter/7"
CHAPTER_HTML = ("<html><body><nav>Menu</nav><div id='text'><h2>Chapter 7</h2>"
                "<p onclick='x()'>It was a <a href='/glossary'>dark</a> night.</p><script>alert(1)</script>"
                "</div></body></html>")
API_URL = "https://books.example/api/parse?page=7"


def manifest(api="1.2"):
    m = copy.deepcopy(MANIFEST)
    m["api"] = api
    m["capabilities"] = ["search", "catalog", "reader"]
    return m


def html_reader(**field_overrides):
    fields = {"html": {"css": "#text", "markup": True}, "title": {"css": "#text h2::text"}}
    fields.update(field_overrides)
    return {
        "capability": "reader", "inputs": ["unit_key"],
        "request": {"url": "{base_url}/chapter/{unit_key:path}"},
        "response": {"format": "html"},
        "extract": {"items": {"css": "body"}, "fields": fields},
    }


def json_reader():
    return {
        "capability": "reader", "inputs": ["unit_key"],
        "request": {"url": "{base_url}/api/parse?page={unit_key:url}"},
        "response": {"format": "json"},
        "extract": {"items": {"json": "$.parse"}, "fields": {"html": {"json": "$.text"}, "title": {"json": "$.title"}}},
    }


def package(tmp_path, reader, *, api="1.2", tests=None, extra_files=None):
    recipes = {**copy.deepcopy(RECIPES), "reader": reader}
    return load_package(build_osp(tmp_path / "p.osp", manifest=manifest(api), recipes=recipes, tests=tests,
                                  extra_files=extra_files))


def run(pkg, routes, **inputs):
    return asyncio.run(RecipeRuntime(pkg, MemoryFetcher(routes)).run("reader", inputs))


def test_markup_is_extracted_and_sanitised_before_it_leaves_the_runtime(tmp_path):
    result = run(package(tmp_path, html_reader()), {CHAPTER_URL: (200, CHAPTER_HTML)}, unit_key="7")
    assert result.complete
    [unit] = result.resources
    assert unit.url is None and unit.title == "Chapter 7"
    assert unit.html == ('<h2>Chapter 7</h2><p>It was a <a href="https://books.example/glossary" '
                         'rel="noopener noreferrer">dark</a> night.</p>')


def test_a_json_string_is_markup_already(tmp_path):
    body = json.dumps({"parse": {"title": "Ch", "text": "<p>Hello <script>x()</script>world</p>"}})
    result = run(package(tmp_path, json_reader()), {API_URL: (200, body)}, unit_key="7")
    assert result.resources[0].html == "<p>Hello world</p>"


def test_an_oversized_unit_makes_the_reader_incomplete(tmp_path):
    body = json.dumps({"parse": {"title": "Ch", "text": "<p>" + "x" * MAX_TEXT_UNIT_BYTES + "</p>"}})
    result = run(package(tmp_path, json_reader()), {API_URL: (200, body)}, unit_key="7")
    assert result.resources == [] and not result.complete
    assert any(i.category == "catalog_validation_failure" for i in result.evidence.issues)


def test_markup_that_sanitises_to_nothing_is_a_missing_unit(tmp_path):
    body = json.dumps({"parse": {"title": "Ch", "text": "<script>only()</script>"}})
    result = run(package(tmp_path, json_reader()), {API_URL: (200, body)}, unit_key="7")
    assert result.resources == [] and not result.complete


def test_text_units_need_api_12(tmp_path):
    with pytest.raises(PackageError, match="need api '1.2'"):
        package(tmp_path, html_reader(), api="1.1")


def test_markup_anywhere_needs_api_12(tmp_path):
    reader = copy.deepcopy(RECIPES["catalog"])
    reader["extract"]["fields"]["title"] = {"css": "h1", "markup": True}
    recipes = {**copy.deepcopy(RECIPES), "catalog": reader}
    with pytest.raises(PackageError, match="need api '1.2'"):
        load_package(build_osp(tmp_path / "p.osp", recipes=recipes))


def test_a_reader_extracts_exactly_one_of_url_or_html(tmp_path):
    with pytest.raises(PackageError, match="exactly one of url"):
        package(tmp_path, html_reader(url={"css": "a::attr(href)"}))
    reader = html_reader()
    del reader["extract"]["fields"]["html"]
    with pytest.raises(PackageError, match="exactly one of url"):
        package(tmp_path, reader)


def test_markup_needs_an_element_selector(tmp_path):
    with pytest.raises(PackageError, match="markup applies"):
        package(tmp_path, html_reader(html={"json": "$.text", "markup": True}))


def text_tests(**expect):
    tests = copy.deepcopy(TESTS)
    tests["cases"].append({"capability": "reader", "inputs": {"unit_key": "7"},
                           "fixtures": [{"url": CHAPTER_URL, "file": "fixtures/chapter.html"}],
                           "expect": {"min_items": 1, **expect}})
    return tests


def test_packaged_tests_check_text(tmp_path):
    files = {"tests/fixtures/chapter.html": CHAPTER_HTML}
    good = package(tmp_path, html_reader(), tests=text_tests(text_contains="dark night", min_text_chars=20),
                   extra_files=files)
    assert asyncio.run(run_packaged_tests(good)).passed
    bad = package(tmp_path, html_reader(), tests=text_tests(text_contains="bright day", min_text_chars=5000),
                  extra_files=files)
    report = asyncio.run(run_packaged_tests(bad))
    assert not report.passed and len(report.failures) == 2


def test_text_expectations_only_apply_to_a_text_reader(tmp_path):
    tests = copy.deepcopy(TESTS)
    tests["cases"][0]["expect"]["text_contains"] = "moon"
    with pytest.raises(PackageError, match="only a text reader"):
        load_package(build_osp(tmp_path / "p.osp", tests=tests))


def test_image_readers_are_unchanged(tmp_path):
    reader = {"capability": "reader", "inputs": ["unit_key"],
              "request": {"url": "{base_url}/chapter/{unit_key:path}"}, "response": {"format": "html"},
              "extract": {"items": {"css": "img.page"}, "fields": {"url": {"css": "::attr(src)"}}}}
    result = run(package(tmp_path, reader, api="1.0"),
                 {CHAPTER_URL: (200, "<img class='page' src='/p/1.png'><img class='page' src='/p/2.png'>")},
                 unit_key="7")
    assert [r.url for r in result.resources] == ["https://books.example/p/1.png", "https://books.example/p/2.png"]
    assert all(r.html is None for r in result.resources)
