"""Build .osp test packages from Python data (always synthetic)."""
from __future__ import annotations

import copy
import io
import stat
import zipfile
from pathlib import Path

import yaml

MANIFEST = {
    "schema": "oneshelf.osp/1",
    "id": "example.books",
    "name": "Example Books",
    "version": "1.0.0",
    "api": "1.0",
    "capabilities": ["search", "catalog"],
    "network": {"domains": ["books.example"], "cdn_domains": ["*.cdn.books.example"]},
    "defaults": {"language": "en", "content_type": "book"},
}

SOURCE = {"base_url": "https://books.example", "url_patterns": [
    {"pattern": r"^https://books\.example/work/(\d+)$", "capability": "catalog", "id_group": 1}]}

RECIPES = {
    "search": {
        "capability": "search",
        "inputs": ["query", "page"],
        "request": {"method": "GET", "url": "{base_url}/search?q={query:url}&page={page}", "fetch": "http"},
        "response": {"format": "html"},
        "extract": {
            "items": {"css": "li.result"},
            "fields": {
                "listing_key": {"css": "a::attr(href)", "transforms": [{"regex_extract": {"pattern": r"/work/(\d+)", "group": 1}}], "required": True},
                "title": {"css": "a::text", "transforms": ["trim"], "required": True},
                "url": {"css": "a::attr(href)", "transforms": ["normalize_url"]},
            },
        },
        "pagination": {"mode": "page_number", "start": 1, "max_pages": 5, "stop_when": "empty_items"},
    },
    "catalog": {
        "capability": "catalog",
        "inputs": ["listing_key"],
        "request": {"method": "GET", "url": "{base_url}/api/work/{listing_key:path}/units", "fetch": "http",
                    "headers": {"Accept": "application/json"}},
        "response": {"format": "json"},
        "extract": {
            "items": {"json": "$.units[*]"},
            "order": "source_listed",
            "fields": {
                "unit_key": {"json": "$.id", "required": True},
                "title": {"json": "$.title"},
                "number": {"json": "$.label", "transforms": ["extract_number"]},
            },
        },
        "pagination": {"mode": "none", "complete_when": "single_response"},
    },
}

TESTS = {"cases": [{"capability": "search", "inputs": {"query": "moon", "page": 1},
                    "fixtures": [{"url": "https://books.example/search?q=moon&page=1", "file": "fixtures/search.html"}],
                    "expect": {"min_items": 1, "fields_present": ["listing_key", "title"]}}]}

SEARCH_HTML = b"<ul><li class='result'><a href='/work/42'> The Moon </a></li></ul>"


def build_osp(path: Path, *, manifest=None, source=None, recipes=None, tests=None, extra_files=None,
              drop=(), raw_files=None) -> Path:
    files: dict[str, bytes] = {
        "manifest.yaml": yaml.safe_dump(manifest if manifest is not None else copy.deepcopy(MANIFEST), allow_unicode=True).encode(),
        "source.yaml": yaml.safe_dump(source if source is not None else copy.deepcopy(SOURCE)).encode(),
        "tests/tests.yaml": yaml.safe_dump(tests if tests is not None else copy.deepcopy(TESTS)).encode(),
        "tests/fixtures/search.html": SEARCH_HTML,
    }
    for name, recipe in (recipes if recipes is not None else copy.deepcopy(RECIPES)).items():
        files[f"recipes/{name}.yaml"] = yaml.safe_dump(recipe, allow_unicode=True).encode()
    for name, data in (extra_files or {}).items():
        files[name] = data if isinstance(data, bytes) else data.encode()
    for name, data in (raw_files or {}).items():  # exact bytes, e.g. hostile YAML
        files[name] = data.encode() if isinstance(data, str) else data
    for name in drop:
        files.pop(name, None)
    with zipfile.ZipFile(path, "w") as z:
        for name, data in files.items():
            z.writestr(name, data)
    return path


def add_symlink_entry(path: Path, name: str, target: str) -> None:
    info = zipfile.ZipInfo(name)
    info.external_attr = (stat.S_IFLNK | 0o777) << 16
    with zipfile.ZipFile(path, "a") as z:
        z.writestr(info, target)


def variant(base: dict, **changes) -> dict:
    out = copy.deepcopy(base)
    for dotted, value in changes.items():
        node = out
        keys = dotted.split("__")
        for key in keys[:-1]:
            node = node[key]
        if value is _DELETE:
            node.pop(keys[-1], None)
        else:
            node[keys[-1]] = value
    return out


class _Delete:
    pass


_DELETE = _Delete()
DELETE = _DELETE
