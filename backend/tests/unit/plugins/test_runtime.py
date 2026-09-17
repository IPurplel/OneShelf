"""Recipe runtime: typed results, Unknown preservation, completeness evidence (Master §5.1, §9, G3/G4)."""
import asyncio
import copy
import json

import pytest

from oneshelf.net.http import FetchFailed
from oneshelf.net.policy import DisallowedTarget
from oneshelf.plugins.package import load_package
from oneshelf.plugins.runtime import (
    AuthRequired,
    CapabilityError,
    FetchedResponse,
    RateLimited,
    RecipeRuntime,
    run_packaged_tests,
)
from tests.fixtures.osp import MANIFEST, RECIPES, SOURCE, build_osp


class MemoryFetcher:
    """url -> (status, body, headers) or an exception instance; records requests."""

    def __init__(self, routes):
        self.routes = routes
        self.requests = []

    async def fetch(self, request):
        self.requests.append(request)
        route = self.routes.get(request.url)
        if route is None:
            raise FetchFailed(f"no route for {request.url}")
        if isinstance(route, Exception):
            raise route
        status, body, *rest = route
        headers = rest[0] if rest else {}
        final_url = headers.pop("x-final-url", request.url) if headers else request.url
        return FetchedResponse(url=final_url, status=status, headers=headers,
                               body=body.encode() if isinstance(body, str) else body)


def package(tmp_path, manifest=None, recipes=None, source=None, tests=None, **kw):
    return load_package(build_osp(tmp_path / "p.osp", manifest=manifest, recipes=recipes, source=source, tests=tests, **kw))


def run(runtime, capability, **inputs):
    return asyncio.run(runtime.run(capability, inputs))


def search_page(*titles_ids):
    return "<ul>" + "".join(f"<li class='result'><a href='/work/{i}'> {t} </a></li>" for t, i in titles_ids) + "</ul>"


S = "https://books.example/search?q=moon&page="


def test_search_paginates_until_empty_page_and_dedupes(tmp_path):
    fetcher = MemoryFetcher({
        S + "1": (200, search_page(("Moon", 1), ("Moonlight", 2))),
        S + "2": (200, search_page(("Moonlight", 2), ("قمر", 3))),
        S + "3": (200, "<ul></ul>"),
    })
    result = run(RecipeRuntime(package(tmp_path), fetcher), "search", query="moon", page=None)
    assert [i.listing_key for i in result.items] == ["1", "2", "3"]
    assert result.items[2].title == "قمر"
    assert result.items[0].url == "https://books.example/work/1"
    assert result.items[0].creator is None  # Unknown, not empty string
    assert result.complete and result.evidence.stop_reason == "empty_page" and result.evidence.pages == 3
    assert result.evidence.duplicates == 1


def test_page_cap_without_stop_evidence_is_incomplete(tmp_path):
    routes = {S + str(p): (200, search_page((f"T{p}", p))) for p in range(1, 6)}
    result = run(RecipeRuntime(package(tmp_path), MemoryFetcher(routes)), "search", query="moon", page=None)
    assert len(result.items) == 5 and not result.complete
    assert result.evidence.stop_reason == "page_cap_reached"


def test_repeated_page_is_incomplete(tmp_path):
    routes = {S + "1": (200, search_page(("A", 1))), S + "2": (200, search_page(("A", 1)))}
    result = run(RecipeRuntime(package(tmp_path), MemoryFetcher(routes)), "search", query="moon", page=None)
    assert not result.complete and result.evidence.stop_reason == "repeated_page"


def test_failure_mid_pagination_keeps_partial_items_but_is_incomplete(tmp_path):
    routes = {S + "1": (200, search_page(("A", 1))), S + "2": (500, "oops")}
    result = run(RecipeRuntime(package(tmp_path), MemoryFetcher(routes)), "search", query="moon", page=None)
    assert [i.listing_key for i in result.items] == ["1"]
    assert not result.complete and result.evidence.issues[0].category == "server_error"


def test_blocked_redirect_or_transport_error_is_incomplete(tmp_path):
    routes = {S + "1": (200, search_page(("A", 1))), S + "2": DisallowedTarget("domain not allowlisted")}
    result = run(RecipeRuntime(package(tmp_path), MemoryFetcher(routes)), "search", query="moon", page=None)
    assert not result.complete and result.evidence.issues[0].category == "blocked"


def test_rate_limit_is_reported_with_retry_after(tmp_path):
    routes = {S + "1": (429, "slow down", {"Retry-After": "120"})}
    with pytest.raises(RateLimited) as info:
        run(RecipeRuntime(package(tmp_path), MemoryFetcher(routes)), "search", query="moon", page=None)
    assert info.value.retry_after == 120


def catalog_json(units):
    return json.dumps({"units": units})


C = "https://books.example/api/work/42/units"


def test_catalog_units_preserve_raw_titles_numbers_and_unknowns(tmp_path):
    units = [
        {"id": "u1", "title": "Prologue", "label": "Prologue"},
        {"id": "u2", "title": "الفصل ٣٫٥", "label": "الفصل ٣٫٥"},
        {"id": "u3", "title": "Chapter 4", "label": "Chapter 4"},
        {"id": "u4", "title": None, "label": None},
    ]
    result = run(RecipeRuntime(package(tmp_path), MemoryFetcher({C: (200, catalog_json(units))})), "catalog", listing_key="42")
    assert result.complete and result.evidence.stop_reason == "single_response"
    assert [u.unit_key for u in result.units] == ["u1", "u2", "u3", "u4"]
    assert [u.number for u in result.units] == [None, "3.5", "4", None]
    assert result.units[1].raw_title == "الفصل ٣٫٥"
    assert result.units[3].raw_title is None and result.units[3].unit_type == "unknown"
    assert [u.order_index for u in result.units] == [0, 1, 2, 3]


def test_catalog_item_missing_identity_makes_catalog_incomplete(tmp_path):
    units = [{"id": "u1", "title": "One"}, {"title": "no id"}]
    result = run(RecipeRuntime(package(tmp_path), MemoryFetcher({C: (200, catalog_json(units))})), "catalog", listing_key="42")
    assert not result.complete and [u.unit_key for u in result.units] == ["u1"]
    assert result.evidence.issues[0].category == "catalog_validation_failure"


def test_reverse_order_catalog(tmp_path):
    recipes = copy.deepcopy(RECIPES)
    recipes["catalog"]["extract"]["order"] = "reverse"
    units = [{"id": "newest"}, {"id": "middle"}, {"id": "oldest"}]
    result = run(RecipeRuntime(package(tmp_path, recipes=recipes), MemoryFetcher({C: (200, catalog_json(units))})),
                 "catalog", listing_key="42")
    assert [u.unit_key for u in result.units] == ["oldest", "middle", "newest"]


def test_invalid_json_is_parser_failure(tmp_path):
    result = run(RecipeRuntime(package(tmp_path), MemoryFetcher({C: (200, "<html>Just a moment...</html>")})),
                 "catalog", listing_key="42")
    assert not result.complete and result.evidence.issues[0].category == "parser_failure"


def test_total_count_completion(tmp_path):
    recipes = copy.deepcopy(RECIPES)
    recipes["catalog"]["inputs"] = ["listing_key", "page"]
    recipes["catalog"]["request"]["url"] = "{base_url}/api/work/{listing_key:path}/units?page={page}"
    recipes["catalog"]["pagination"] = {"mode": "page_number", "start": 1, "max_pages": 10, "stop_when": "total_count",
                                        "total": {"json": "$.total"}}
    base = "https://books.example/api/work/42/units?page="

    def page(ids, total=3):
        return json.dumps({"total": total, "units": [{"id": i} for i in ids]})

    full = MemoryFetcher({base + "1": (200, page(["a", "b"])), base + "2": (200, page(["c"]))})
    result = run(RecipeRuntime(package(tmp_path, recipes=recipes), full), "catalog", listing_key="42", page=None)
    assert result.complete and result.evidence.stop_reason == "total_reached"
    short = MemoryFetcher({base + "1": (200, page(["a", "b"])), base + "2": (200, page([]))})
    result = run(RecipeRuntime(package(tmp_path, recipes=recipes), short), "catalog", listing_key="42", page=None)
    assert not result.complete and result.evidence.stop_reason == "total_not_reached"


def test_next_link_pagination_and_loop_detection(tmp_path):
    recipes = copy.deepcopy(RECIPES)
    recipes["search"]["pagination"] = {"mode": "next_link", "max_pages": 10, "stop_when": "no_next",
                                       "next": {"css": "a.next::attr(href)", "transforms": ["normalize_url"]}}
    p1 = search_page(("A", 1)) + "<a class='next' href='/search?q=moon&page=2'>next</a>"
    p2 = search_page(("B", 2))
    result = run(RecipeRuntime(package(tmp_path, recipes=recipes), MemoryFetcher({S + "1": (200, p1), S + "2": (200, p2)})),
                 "search", query="moon", page=1)
    assert [i.listing_key for i in result.items] == ["1", "2"] and result.complete
    loop = search_page(("A", 1)) + "<a class='next' href='/search?q=moon&page=1'>again</a>"
    result = run(RecipeRuntime(package(tmp_path, recipes=recipes), MemoryFetcher({S + "1": (200, loop)})),
                 "search", query="moon", page=1)
    assert not result.complete and result.evidence.stop_reason == "pagination_loop"


def test_auth_required_capability_detects_login_redirect(tmp_path):
    manifest = copy.deepcopy(MANIFEST)
    manifest["auth"] = {"login_url": "https://books.example/login", "session_domains": ["books.example"],
                        "required_for": ["catalog"]}
    recipes = copy.deepcopy(RECIPES)
    recipes["catalog"]["request"]["auth"] = "required"
    routes = {C: (200, "<form>login</form>", {"x-final-url": "https://books.example/login?next=/api"})}
    with pytest.raises(AuthRequired):
        run(RecipeRuntime(package(tmp_path, manifest=manifest, recipes=recipes), MemoryFetcher(routes)),
            "catalog", listing_key="42")
    with pytest.raises(AuthRequired):
        run(RecipeRuntime(package(tmp_path, manifest=manifest, recipes=recipes), MemoryFetcher({C: (401, "no")})),
            "catalog", listing_key="42")


def test_work_and_session_check_capabilities(tmp_path):
    manifest = copy.deepcopy(MANIFEST)
    manifest["capabilities"] = ["search", "catalog", "work", "check_session"]
    recipes = copy.deepcopy(RECIPES)
    recipes["work"] = {
        "capability": "work", "inputs": ["listing_key"],
        "request": {"url": "{base_url}/work/{listing_key:path}"},
        "response": {"format": "html"},
        "extract": {"fields": {
            "title": {"xpath": "//h1/text()", "transforms": ["trim"]},
            "aliases": {"css": "ul.aliases li", "all": True},
            "creator": {"css": ".author::text"},
            "content_type": {"css": ".type::text"},
        }},
    }
    recipes["check_session"] = {
        "capability": "check_session", "request": {"url": "{base_url}/account"}, "response": {"format": "html"},
        "extract": {"fields": {"logged_in": {"css": "a.logout", "exists": True}}},
    }
    html = "<h1> The Moon </h1><ul class='aliases'><li>القمر</li><li>La Lune</li></ul><span class='type'>novel</span>"
    routes = {"https://books.example/work/42": (200, html),
              "https://books.example/account": (200, "<a class='logout'>out</a>")}
    rt = RecipeRuntime(package(tmp_path, manifest=manifest, recipes=recipes), MemoryFetcher(routes))
    work = run(rt, "work", listing_key="42")
    assert work.title == "The Moon" and work.aliases == ["القمر", "La Lune"]
    assert work.creator is None and work.content_type == "novel"
    assert run(rt, "check_session").logged_in is True


def test_unknown_classification_values_become_unknown(tmp_path):
    recipes = copy.deepcopy(RECIPES)
    recipes["search"]["extract"]["fields"]["content_type"] = {"css": ".t::text"}
    recipes["search"]["extract"]["fields"]["language"] = {"css": ".l::text"}
    recipes["search"]["pagination"] = {"mode": "none", "complete_when": "single_response"}
    html = "<ul><li class='result'><a href='/work/1'>X</a><span class='t'>webtoon-ish</span><span class='l'>Arabic!!</span></li></ul>"
    result = run(RecipeRuntime(package(tmp_path, recipes=recipes), MemoryFetcher({S + "1": (200, html)})),
                 "search", query="moon", page=1)
    assert result.items[0].content_type is None and result.items[0].language is None


def test_inputs_are_validated(tmp_path):
    rt = RecipeRuntime(package(tmp_path), MemoryFetcher({}))
    with pytest.raises(CapabilityError):
        run(rt, "catalog")  # missing listing_key
    with pytest.raises(CapabilityError):
        run(rt, "catalog", listing_key="42", query="x")  # undeclared input
    with pytest.raises(CapabilityError):
        run(rt, "reader", unit_key="1")  # undeclared capability


def test_packaged_tests_pass_and_fail(tmp_path):
    report = asyncio.run(run_packaged_tests(package(tmp_path)))
    assert report.passed, report.failures
    tests = {"cases": [{"capability": "search", "inputs": {"query": "moon", "page": 1},
                        "fixtures": [{"url": "https://books.example/search?q=moon&page=1", "file": "fixtures/search.html"}],
                        "expect": {"min_items": 5}}]}
    report = asyncio.run(run_packaged_tests(package(tmp_path, tests=tests)))
    assert not report.passed and "min_items" in report.failures[0]


def test_packaged_tests_map_catalog_title_to_raw_title(tmp_path):
    tests = {"cases": [{"capability": "catalog", "inputs": {"listing_key": "42"},
                        "fixtures": [{"url": C, "file": "fixtures/units.json"}],
                        "expect": {"min_items": 2, "fields_present": ["unit_key", "title"], "complete": True,
                                   "first": {"title": "Prologue", "number": None}}}]}
    units = json.dumps({"units": [{"id": "p", "title": "Prologue", "label": "Prologue"}, {"id": "c1", "title": "Ch 1"}]})
    report = asyncio.run(run_packaged_tests(package(tmp_path, tests=tests, extra_files={"tests/fixtures/units.json": units})))
    assert report.passed, report.failures


def test_health_json_boolean_and_not_found_category(tmp_path):
    manifest = copy.deepcopy(MANIFEST)
    manifest["capabilities"] = ["search", "catalog", "health"]
    recipes = copy.deepcopy(RECIPES)
    recipes["health"] = {"capability": "health", "request": {"url": "{base_url}/health"}, "response": {"format": "json"},
                         "extract": {"fields": {"ok": {"json": "$.ok"}}}}
    routes = {"https://books.example/health": (200, '{"ok": true}'), C: (404, "gone")}
    rt = RecipeRuntime(package(tmp_path, manifest=manifest, recipes=recipes), MemoryFetcher(routes))
    assert run(rt, "health").ok is True
    result = run(rt, "catalog", listing_key="42")
    assert result.evidence.issues[0].category == "not_found"
