"""Draft `.osp` generation (Master §12.2–12.3).

A draft is declarative data only: manifest, source configuration, recipes, and tests with the fixtures
discovery actually captured, so the package can be re-tested offline. Capabilities that discovery could
not confirm are left out and reported instead of being guessed, and generating a draft never installs it.
"""
from __future__ import annotations

import json
import re
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlsplit

import yaml

from oneshelf.generator.discovery import CONFIRMED, PROBABLE, SiteMap

GENERATED_PREFIX = "generated"
DRAFT_VERSION = "0.1.0"
API_VERSION = "1.0"
USABLE = (CONFIRMED, PROBABLE)
SEARCH_KEYS = ("q", "query", "s", "search", "keyword", "term")
# A generated adapter starts polite; a developer can raise it after reviewing the site's rules.
DRAFT_RATE_LIMIT = {"requests_per_minute": 30, "concurrency": 1}


@dataclass(frozen=True)
class _Guess:
    """A selector that came from discovery rather than from a field guess."""
    css: str
    json: str | None = None


@dataclass
class Draft:
    manifest: dict
    source: dict
    recipes: dict[str, dict]
    tests: dict
    fixtures: dict[str, bytes] = field(default_factory=dict)
    confidence: dict[str, str] = field(default_factory=dict)
    unsupported: dict[str, str] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)
    site: SiteMap | None = None

    def as_preview(self) -> dict:
        """What the developer sees before Generate (§12.3 preview and Recipe Inspector)."""
        return {"manifest": self.manifest, "source": self.source, "recipes": self.recipes,
                "confidence": self.confidence, "unsupported": self.unsupported, "notes": self.notes,
                "fetches": self.site.fetches if self.site else [], "tests": self.tests}


def _plugin_id(host: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", host.lower()).strip("-")
    return f"{GENERATED_PREFIX}.{slug}"[:64]


def _relative(url_template: str | None, base_url: str) -> str | None:
    if not url_template:
        return None
    return url_template.replace(base_url, "{base_url}", 1)


def _field(guess, *, transforms: list | None = None, required: bool = False) -> dict:
    spec: dict = {}
    if getattr(guess, "css", None):
        spec["css"] = guess.css
    if getattr(guess, "json", None):
        spec["json"] = guess.json
    if transforms:
        spec["transforms"] = transforms
    if required:
        spec["required"] = True
    return spec


def _key_extraction(pattern: str | None, group: str) -> list:
    """Turn an item URL into the stable key the rest of OneShelf uses.

    The href on the page is usually relative, so it is resolved against the page first and only then
    matched, otherwise the pattern silently never fires and the item is dropped.
    """
    if not pattern:
        return ["trim"]
    simple = pattern.replace(f"(?P<{group}>", "(").lstrip("^").rstrip("$")
    return ["normalize_url", {"regex_extract": {"pattern": simple, "group": 1}}]


def _search_recipe(site: SiteMap) -> dict | None:
    search = site.search
    if not (search.url_template and search.item_selector and "listing_key" in search.fields):
        return None
    url = _relative(search.url_template, site.base_url)
    inputs = ["query"]
    if search.page_param:
        url = f"{url}&{search.page_param}={{page}}"
        inputs.append("page")
    fields = {"listing_key": _field(search.fields["listing_key"],
                                    transforms=_key_extraction(site.work.id_pattern, "work_id"), required=True),
              "title": _field(search.fields["title"], transforms=["trim"], required=True)}
    for name, transforms in (("url", ["normalize_url"]), ("cover_url", ["normalize_url"]),
                             ("content_type", ["trim"]), ("language", ["trim"])):
        if name in search.fields:
            fields[name] = _field(search.fields[name], transforms=transforms)
    recipe = {"capability": "search", "inputs": inputs, "request": {"url": url},
              "response": {"format": "html"},
              "extract": {"items": {"css": search.item_selector}, "fields": fields}}
    if search.page_param:
        recipe["pagination"] = {"mode": "page_number", "start": 1, "max_pages": 10, "stop_when": "empty_items"}
    return recipe


def _work_recipe(site: SiteMap) -> dict | None:
    if not (site.work.url_template and site.work.fields.get("title")):
        return None
    url = _relative(site.work.url_template, site.base_url).replace("{work_id}", "{listing_key:path}")
    fields = {"title": _field(site.work.fields["title"], transforms=["trim"], required=True)}
    for name in ("cover_url", "content_type", "language"):
        if name in site.work.fields:
            fields[name] = _field(site.work.fields[name],
                                  transforms=["normalize_url"] if name == "cover_url" else ["trim"])
    return {"capability": "work", "inputs": ["listing_key"], "request": {"url": url},
            "response": {"format": "html"}, "extract": {"fields": fields}}


def _catalog_recipe(site: SiteMap) -> dict | None:
    catalog = site.catalog
    if not (catalog.item_selector and site.work.url_template and "unit_key" in catalog.fields):
        return None
    url = _relative(site.work.url_template, site.base_url).replace("{work_id}", "{listing_key:path}")
    fields = {"unit_key": _field(catalog.fields["unit_key"],
                                 transforms=_key_extraction(catalog.unit_pattern, "unit_key"), required=True)}
    if "title" in catalog.fields:
        fields["title"] = _field(catalog.fields["title"], transforms=["trim"])
        fields["number"] = _field(catalog.fields["title"], transforms=["extract_number"])
    if "published_at" in catalog.fields:
        fields["release_date"] = _field(catalog.fields["published_at"], transforms=["trim"])
    return {"capability": "catalog", "inputs": ["listing_key"], "request": {"url": url},
            "response": {"format": "html"},
            "extract": {"items": {"css": catalog.item_selector}, "order": "source_listed", "fields": fields},
            "pagination": {"mode": "none", "complete_when": "single_response"}}


def _reader_recipe(site: SiteMap) -> dict | None:
    reader = site.reader
    if not (reader.url_template and reader.image_selector):
        return None
    url = _relative(reader.url_template, site.base_url).replace("{unit_key}", "{unit_key:path}")
    return {"capability": "reader", "inputs": ["unit_key"], "request": {"url": url},
            "response": {"format": "html"},
            "extract": {"items": {"css": reader.image_selector.split("::")[0]},
                        "fields": {"url": _field(_Guess(reader.image_selector), transforms=["normalize_url"],
                                                 required=True)}},
            "pagination": {"mode": "none", "complete_when": "single_response"}}


def _last_segment(url: str) -> str:
    segments = [s for s in urlsplit(url).path.split("/") if s] if url else []
    return segments[-1] if segments else ""


def _sample_inputs(capability: str, site: SiteMap) -> dict:
    if capability == "search":
        sample = (site.samples.get("search") or [""])[0]
        query = ""
        for part in urlsplit(sample).query.split("&"):
            key, _, value = part.partition("=")
            if key.lower() in SEARCH_KEYS:
                query = value
        inputs: dict = {"query": query}
        if site.search.page_param:
            inputs["page"] = 1
        return inputs
    if capability == "work":
        listing = site.search.fields.get("listing_key")
        return {"listing_key": _last_segment(listing.sample if listing else "")}
    unit = site.catalog.fields.get("unit_key")
    return {"unit_key": _last_segment(unit.sample if unit else "")}


def _tests(site: SiteMap, recipes: dict[str, dict]) -> tuple[dict, dict[str, str]]:
    """Offline cases built from the pages discovery actually fetched (§12.3 automated tests)."""
    cases: list[dict] = []
    fixture_sources: dict[str, str] = {}
    for capability in ("search", "work", "reader"):
        samples = site.samples.get(capability) or []
        if capability not in recipes or not samples:
            continue
        url = samples[0]
        name = f"tests/fixtures/{capability}.html"
        fields = sorted(recipes[capability]["extract"].get("fields", {}))
        expect = {"fields_present": fields}
        if "items" in recipes[capability]["extract"]:
            expect["min_items"] = 1
        cases.append({"capability": capability, "inputs": _sample_inputs(capability, site),
                      "fixtures": [{"url": url, "file": f"fixtures/{capability}.html"}], "expect": expect})
        fixture_sources[name] = url
    return {"cases": cases}, fixture_sources


def build_draft(site: SiteMap, *, name: str, publisher: str | None = None) -> Draft:
    host = site.domains[0]
    builders = {"search": _search_recipe, "work": _work_recipe, "catalog": _catalog_recipe, "reader": _reader_recipe}
    recipes: dict[str, dict] = {}
    unsupported: dict[str, str] = {}
    for capability, builder in builders.items():
        state = site.capabilities.get(capability)
        recipe = builder(site) if state in USABLE else None
        if recipe is not None:
            recipes[capability] = recipe
        else:
            unsupported[capability] = state or "unknown"
    manifest = {
        "schema": "oneshelf.osp/1",
        "id": _plugin_id(host),
        "name": name,
        "version": DRAFT_VERSION,
        "api": API_VERSION,
        "description": f"Draft adapter generated from {site.start_url}. Review before installing.",
        "capabilities": sorted(recipes),
        "network": {"domains": [host], "cdn_domains": list(site.cdn_domains),
                    "allow_http": site.base_url.startswith("http://")},
    }
    if publisher:
        manifest["publisher"] = publisher
    source = {"base_url": site.base_url, "rate_limit": dict(DRAFT_RATE_LIMIT)}
    if site.work.id_pattern:
        source["url_patterns"] = [{"pattern": site.work.id_pattern.replace("(?P<work_id>", "("),
                                   "capability": "work", "id_group": 1}]
    tests, fixture_sources = _tests(site, recipes)
    fixtures = {name: _captured(site, url) for name, url in fixture_sources.items()}
    return Draft(manifest=manifest, source=source, recipes=recipes, tests=tests, fixtures=fixtures,
                 confidence={c: site.capabilities.get(c, "unknown") for c in builders},
                 unsupported=unsupported, notes=list(site.notes), site=site)


def _captured(site: SiteMap, url: str) -> bytes:
    return site.bodies.get(url, b"") if getattr(site, "bodies", None) else b""


def write_package(draft: Draft, destination: str | Path) -> Path:
    """Writes the draft as an `.osp`. This is Generate; installing it is a separate, explicit action."""
    destination = Path(destination)
    entries: dict[str, bytes] = {
        "manifest.yaml": yaml.safe_dump(draft.manifest, sort_keys=False, allow_unicode=True).encode(),
        "source.yaml": yaml.safe_dump(draft.source, sort_keys=False, allow_unicode=True).encode(),
        "tests/tests.yaml": yaml.safe_dump(draft.tests, sort_keys=False, allow_unicode=True).encode(),
    }
    for capability, recipe in draft.recipes.items():
        entries[f"recipes/{capability}.yaml"] = yaml.safe_dump(recipe, sort_keys=False, allow_unicode=True).encode()
    for name, body in draft.fixtures.items():
        entries[name] = body or b"<!-- page not captured during discovery -->"
    destination.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(destination, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name in sorted(entries):
            info = zipfile.ZipInfo(name, date_time=(2026, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            archive.writestr(info, entries[name])
    return destination


def draft_summary(draft: Draft) -> str:
    return json.dumps(draft.as_preview(), indent=1, ensure_ascii=False, default=str)
