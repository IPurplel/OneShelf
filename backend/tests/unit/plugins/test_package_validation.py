"""Master §9.3, §10 steps 3–6, §11, INV-13/14: declarative packages are validated before anything runs."""
import copy

import pytest

from oneshelf.plugins.package import PackageError, load_package
from tests.fixtures.osp import DELETE, MANIFEST, RECIPES, SOURCE, add_symlink_entry, build_osp, variant


def load(tmp_path, **kw):
    return load_package(build_osp(tmp_path / "p.osp", **kw))


def rejects(tmp_path, match=None, **kw):
    with pytest.raises(PackageError, match=match):
        load(tmp_path, **kw)


def test_valid_package_loads_with_derived_permissions(tmp_path):
    pkg = load(tmp_path)
    assert pkg.manifest.id == "example.books" and pkg.manifest.version == "1.0.0"
    assert set(pkg.recipes) == {"search", "catalog"}
    assert pkg.permissions == {"network:domain:books.example", "network:cdn:*.cdn.books.example"}
    assert len(pkg.sha256) == 64


def test_permissions_include_browser_session_and_http(tmp_path):
    manifest = variant(MANIFEST, network__allow_http=True)
    manifest["browser"] = {"capabilities": ["catalog"]}
    manifest["auth"] = {"login_url": "https://books.example/login", "session_domains": ["books.example"],
                        "required_for": ["catalog"], "optional_for": ["search"]}
    recipes = copy.deepcopy(RECIPES)
    recipes["catalog"]["request"]["fetch"] = "browser"
    recipes["catalog"]["request"]["auth"] = "required"
    recipes["search"]["request"]["auth"] = "optional"
    pkg = load(tmp_path, manifest=manifest, recipes=recipes)
    assert {"network:http", "browser:catalog", "session:required:catalog", "session:optional:search"} <= pkg.permissions


# -- archive-level static checks ------------------------------------------------------------------

@pytest.mark.parametrize("name", ["plugin.py", "recipes/hook.js", "run.sh", "lib/native.so", "bin/tool", "recipes/x.pyc"])
def test_executable_or_unknown_files_are_rejected(tmp_path, name):
    rejects(tmp_path, match="file type", extra_files={name: b"print('hi')"})


def test_symlink_entries_are_rejected(tmp_path):
    path = build_osp(tmp_path / "p.osp")
    add_symlink_entry(path, "tests/fixtures/link.html", "/etc/passwd")
    with pytest.raises(PackageError, match="symlink"):
        load_package(path)


def test_zip_slip_names_are_rejected(tmp_path):
    rejects(tmp_path, extra_files={"../evil.yaml": b"a: 1"})


def test_non_zip_is_rejected(tmp_path):
    p = tmp_path / "p.osp"
    p.write_bytes(b"#!/bin/sh\nrm -rf /\n")
    with pytest.raises(PackageError):
        load_package(p)


def test_missing_manifest_is_rejected(tmp_path):
    rejects(tmp_path, match="manifest", drop=["manifest.yaml"])


# -- YAML safety ------------------------------------------------------------------------------------

def test_yaml_python_tags_are_rejected(tmp_path):
    rejects(tmp_path, raw_files={"manifest.yaml": "!!python/object/apply:os.system ['id']\n"})


def test_yaml_alias_bombs_are_rejected(tmp_path):
    bomb = "a: &a [x, x]\nb: &b [*a, *a]\nc: &c [*b, *b]\nd: [*c, *c]\n"
    rejects(tmp_path, match="alias", raw_files={"source.yaml": bomb})


# -- manifest schema --------------------------------------------------------------------------------

@pytest.mark.parametrize("changes", [
    {"script": "import os"},
    {"id": "Bad ID!"}, {"id": "../x"}, {"version": "1.0"}, {"version": "latest"},
    {"api": "2.0"}, {"schema": "something/else"}, {"name": ""},
    {"capabilities": ["search", "exec"]}, {"trust": "official"},
    {"defaults": {"language": "en", "content_type": "hentai-ish"}},
])
def test_manifest_schema_rejections(tmp_path, changes):
    manifest = copy.deepcopy(MANIFEST)
    manifest.update(changes)
    rejects(tmp_path, manifest=manifest)


@pytest.mark.parametrize("rule", [
    "127.0.0.1", "[::1]", "localhost", "router.local", "nas.lan", "svc.internal", "home.arpa", "x.home.arpa",
    "com", "*.com", "*", "evil.*", "books.example:8080", "http://books.example", "a..b", "*.*.books.example",
    "169.254.169.254", "2130706433",
])
def test_unsafe_domain_rules_are_rejected(tmp_path, rule):
    rejects(tmp_path, manifest=variant(MANIFEST, network__domains=[rule]))


def test_idn_domains_are_normalized(tmp_path):
    manifest = variant(MANIFEST, network__domains=["مكتبة.example"])
    source = variant(SOURCE, base_url="https://xn--ngbcb3hj.example", url_patterns=[])
    tests = {"cases": [{"capability": "search", "inputs": {"query": "x", "page": 1},
                        "fixtures": [{"url": "https://xn--ngbcb3hj.example/search?q=x&page=1", "file": "fixtures/search.html"}],
                        "expect": {"min_items": 1}}]}
    pkg = load(tmp_path, manifest=manifest, source=source, tests=tests)
    assert "network:domain:xn--ngbcb3hj.example" in pkg.permissions


# -- cross-file consistency -------------------------------------------------------------------------

def test_base_url_must_be_allowlisted_and_https(tmp_path):
    rejects(tmp_path, match="base_url", source=variant(SOURCE, base_url="https://other.example"))
    rejects(tmp_path, match="http", source=variant(SOURCE, base_url="http://books.example"))


def test_declared_capabilities_and_recipes_must_match(tmp_path):
    recipes = copy.deepcopy(RECIPES)
    del recipes["catalog"]
    rejects(tmp_path, match="recipe", recipes=recipes)
    recipes = copy.deepcopy(RECIPES)
    recipes["latest"] = copy.deepcopy(recipes["search"]) | {"capability": "latest"}
    rejects(tmp_path, match="not declared", recipes=recipes)


def test_browser_fetch_requires_declaration(tmp_path):
    recipes = copy.deepcopy(RECIPES)
    recipes["search"]["request"]["fetch"] = "browser"
    rejects(tmp_path, match="browser", recipes=recipes)


def test_auth_scope_must_be_declared_and_consistent(tmp_path):
    recipes = copy.deepcopy(RECIPES)
    recipes["catalog"]["request"]["auth"] = "required"
    rejects(tmp_path, match="auth", recipes=recipes)
    manifest = copy.deepcopy(MANIFEST)
    manifest["auth"] = {"login_url": "https://evil.example/login", "session_domains": ["books.example"], "required_for": ["catalog"]}
    rejects(tmp_path, match="login_url", manifest=manifest)
    manifest["auth"] = {"login_url": "https://books.example/login", "session_domains": ["*.cdn.books.example"], "required_for": ["catalog"]}
    rejects(tmp_path, match="session_domains", manifest=manifest)


@pytest.mark.parametrize("header", ["Cookie", "authorization", "Host", "X-Forwarded-For", "Proxy-Authorization", "Content-Length"])
def test_core_owned_headers_are_rejected(tmp_path, header):
    recipes = copy.deepcopy(RECIPES)
    recipes["search"]["request"]["headers"] = {header: "x"}
    rejects(tmp_path, match="header", recipes=recipes)


@pytest.mark.parametrize("url", [
    "{base_url}/s?q={undeclared}", "{base_url}/s?q={query:shell}", "{base_url}/s?q={query.__class__}",
    "https://evil.example/s?q={query:url}", "{query:raw}/x", "file:///etc/passwd",
])
def test_request_templates_are_restricted(tmp_path, url):
    recipes = copy.deepcopy(RECIPES)
    recipes["search"]["request"]["url"] = url
    rejects(tmp_path, recipes=recipes)


@pytest.mark.parametrize("field", [
    {"css": "a[[["}, {"xpath": "//a[@"}, {"json": "$..[?(@.x)]"}, {"css": "a", "xpath": "//a"},
    {"css": "a", "transforms": ["eval"]}, {"css": "a", "transforms": [{"regex_extract": {"pattern": "(a)\\1"}}]},
    {"css": "a" * 600},
])
def test_invalid_field_selectors_or_transforms_are_rejected(tmp_path, field):
    recipes = copy.deepcopy(RECIPES)
    recipes["search"]["extract"]["fields"]["title"] = field
    rejects(tmp_path, recipes=recipes)


def test_capability_required_fields_must_be_extracted(tmp_path):
    recipes = copy.deepcopy(RECIPES)
    del recipes["catalog"]["extract"]["fields"]["unit_key"]
    rejects(tmp_path, match="unit_key", recipes=recipes)


def test_pagination_limits(tmp_path):
    recipes = copy.deepcopy(RECIPES)
    recipes["search"]["pagination"]["max_pages"] = 100_000
    rejects(tmp_path, recipes=recipes)


def test_url_patterns_use_bounded_regex(tmp_path):
    rejects(tmp_path, source=variant(SOURCE, url_patterns=[{"pattern": "(a)\\1", "capability": "catalog", "id_group": 1}]))


def test_tests_file_is_required(tmp_path):
    rejects(tmp_path, match="tests", drop=["tests/tests.yaml"])


def test_fixture_urls_must_be_allowlisted(tmp_path):
    tests = {"cases": [{"capability": "search", "inputs": {"query": "x", "page": 1},
                        "fixtures": [{"url": "http://169.254.169.254/latest", "file": "fixtures/search.html"}],
                        "expect": {"min_items": 1}}]}
    rejects(tmp_path, tests=tests)


def test_a_recipe_may_declare_the_headers_its_resources_need(tmp_path):
    """Some CDNs refuse an image without a Referer. Declaring that is a recipe's job, not Core's.

    The alternative is a source-specific branch inside the downloader, which §52 and §9 both refuse.
    """
    import copy

    recipes = copy.deepcopy(RECIPES)
    recipes["catalog"]["resource_headers"] = {"Referer": "https://example.test/"}
    package = load_package(build_osp(tmp_path / "with-headers.osp", recipes=recipes))
    assert package.recipes["catalog"].resource_headers == {"Referer": "https://example.test/"}


@pytest.mark.parametrize("header", ["Cookie", "Authorization", "X-Forwarded-For", "Host"])
def test_resource_headers_may_not_smuggle_credentials_or_spoof_the_hop(tmp_path, header):
    import copy

    recipes = copy.deepcopy(RECIPES)
    recipes["catalog"]["resource_headers"] = {header: "anything"}
    with pytest.raises(Exception, match="not allowed"):
        load_package(build_osp(tmp_path / "bad-headers.osp", recipes=recipes))


def test_a_recipe_may_follow_the_url_its_own_catalog_captured(tmp_path):
    """§8: the source gave us the address; asking for it back is not a widening of anything."""
    import copy

    recipes = copy.deepcopy(RECIPES)
    recipes["reader"] = {
        "capability": "reader", "inputs": ["url"],
        "request": {"method": "GET", "url": "{url:absolute}", "fetch": "http"},
        "response": {"format": "html"},
        "extract": {"items": {"css": "img"}, "fields": {"url": {"css": "::attr(src)", "required": True}}},
        "pagination": {"mode": "none", "complete_when": "single_response"},
    }
    package = load_package(build_osp(tmp_path / "follows.osp", recipes=recipes,
                                     manifest=variant(MANIFEST, capabilities=["search", "catalog", "reader"])))
    assert package.recipes["reader"].request.url == "{url:absolute}"


def test_following_a_url_without_saying_it_is_absolute_is_refused_rather_than_silently_encoded(tmp_path):
    """A bare {url} is percent-encoded into a path segment, so the request could never have worked."""
    import copy

    recipes = copy.deepcopy(RECIPES)
    recipes["reader"] = {
        "capability": "reader", "inputs": ["url"],
        "request": {"method": "GET", "url": "{url}", "fetch": "http"},
        "response": {"format": "html"},
        "extract": {"items": {"css": "img"}, "fields": {"url": {"css": "::attr(src)", "required": True}}},
        "pagination": {"mode": "none", "complete_when": "single_response"},
    }
    with pytest.raises(PackageError, match="absolute"):
        load_package(build_osp(tmp_path / "bare.osp", recipes=recipes,
                               manifest=variant(MANIFEST, capabilities=["search", "catalog", "reader"])))
