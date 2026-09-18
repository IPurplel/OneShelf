"""Repair Existing Adapter (Master §12.3).

Repair is diagnosis first: run the installed recipes against the live site and see which capabilities
actually broke. Only then is the site re-discovered, and the result is a *new version* of the package
whose changed selectors are shown as a diff and validated before anything is activated. Activation and
rollback stay with the plugin manager, so a failed repair leaves the working adapter in place.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from oneshelf.generator.discovery import USABLE_START, discover
from oneshelf.generator.draft import Draft, build_draft, write_package
from oneshelf.net.governor import Priority, TrafficGovernor
from oneshelf.net.http import HttpClient
from oneshelf.net.policy import EgressPolicy
from oneshelf.plugins.package import PluginPackage, load_package
from oneshelf.plugins.runtime import CapabilityError, RecipeRuntime
from oneshelf.sources.fetcher import DevHostsResolver, SourceFetcher

PROBE_INPUTS = {"search": {"query": "a"}, "work": {}, "catalog": {}, "reader": {}}


class RepairError(RuntimeError):
    pass


@dataclass
class Diagnosis:
    plugin_id: str
    checked: list[str] = field(default_factory=list)
    broken: list[str] = field(default_factory=list)
    details: dict[str, str] = field(default_factory=dict)
    samples: dict[str, object] = field(default_factory=dict)

    @property
    def healthy(self) -> bool:
        return not self.broken


@dataclass(frozen=True)
class SelectorChange:
    capability: str
    field_name: str
    before: str
    after: str


@dataclass
class RepairOutcome:
    plugin_id: str
    version: str
    path: Path
    changes: list[SelectorChange]
    validated: bool
    draft: Draft
    notes: list[str] = field(default_factory=list)


def _policy(package: PluginPackage, *, allow_http: bool, dev: bool) -> EgressPolicy:
    network = package.manifest.network
    return EgressPolicy(domains=tuple(network.domains), cdn_domains=tuple(network.cdn_domains),
                        allow_http=allow_http or network.allow_http, dev_loopback_exception=dev)


async def _probe(package: PluginPackage, *, dev_hosts: dict | None, allow_http: bool) -> Diagnosis:
    diagnosis = Diagnosis(plugin_id=package.id)
    policy = _policy(package, allow_http=allow_http, dev=bool(dev_hosts))
    resolver = DevHostsResolver(dev_hosts) if dev_hosts else None
    async with HttpClient(policy, resolver_backend=resolver) as client:
        fetcher = SourceFetcher(package, client, TrafficGovernor(), None, Priority.INTERACTIVE)
        runtime = RecipeRuntime(package, fetcher)
        listing_key = unit_key = None
        for capability in ("search", "work", "catalog", "reader"):
            if capability not in package.recipes:
                continue
            inputs = dict(PROBE_INPUTS[capability])
            if capability in ("work", "catalog"):
                if listing_key is None:
                    continue
                inputs["listing_key"] = listing_key
            if capability == "reader":
                if unit_key is None:
                    continue
                inputs["unit_key"] = unit_key
            diagnosis.checked.append(capability)
            try:
                result = await runtime.run(capability, inputs)
            except CapabilityError as exc:
                diagnosis.broken.append(capability)
                diagnosis.details[capability] = f"{exc.category}: {exc}"
                continue
            items = getattr(result, "items", None)
            if items is not None and not items:
                diagnosis.broken.append(capability)
                diagnosis.details[capability] = "the recipe ran but returned no items"
                continue
            diagnosis.samples[capability] = result
            if capability == "search" and items:
                listing_key = items[0].listing_key
            if capability == "catalog" and items:
                unit_key = items[0].unit_key
    return diagnosis


async def diagnose(package: PluginPackage, *, dev_hosts: dict | None = None, allow_http: bool = False) -> Diagnosis:
    """Which capabilities of an installed adapter still work against the live site."""
    return await _probe(package, dev_hosts=dev_hosts, allow_http=allow_http)


def _draft_selectors(recipes: dict) -> dict[tuple[str, str], str]:
    found: dict[tuple[str, str], str] = {}
    for capability, recipe in recipes.items():
        extract = recipe.get("extract") if isinstance(recipe, dict) else None
        if not extract:
            continue
        items = extract.get("items") or {}
        if items.get("css") or items.get("json"):
            found[(capability, "items")] = items.get("css") or items.get("json")
        for name, spec in (extract.get("fields") or {}).items():
            value = spec.get("css") or spec.get("json")
            if value:
                found[(capability, name)] = value
    return found


def _installed_selectors(package: PluginPackage) -> dict[tuple[str, str], str]:
    found: dict[tuple[str, str], str] = {}
    for capability, recipe in package.recipes.items():
        items = recipe.extract.items
        if items is not None and (items.css or items.json_):
            found[(capability, "items")] = items.css or items.json_
        for name, spec in recipe.extract.fields.items():
            value = spec.css or spec.json_
            if value:
                found[(capability, name)] = value
    return found


def _bump(version: str) -> str:
    major, minor, patch = (version.split(".") + ["0", "0"])[:3]
    return f"{major}.{minor}.{int(patch) + 1}"


def _start_url(package: PluginPackage) -> str:
    search = package.recipes.get("search")
    base = package.source.base_url.rstrip("/")
    if search is not None:
        url = search.request.url.replace("{base_url}", base)
        for name, value in USABLE_START.items():
            url = url.replace("{" + name + "}", value)
        return url
    return base


async def repair(package: PluginPackage, *, destination: str | Path, dev_hosts: dict | None = None,
                 allow_http: bool = False, start_url: str | None = None) -> RepairOutcome:
    """Re-discover the site and produce a validated replacement version, or refuse to replace anything."""
    start = start_url or _start_url(package)
    site = await discover(start, dev_hosts=dev_hosts, allow_http=allow_http or package.manifest.network.allow_http)
    draft = build_draft(site, name=package.manifest.name, publisher=package.manifest.publisher)
    missing = [c for c in package.recipes if c not in draft.recipes]
    if missing:
        raise RepairError("discovery could not map these capabilities any more: " + ", ".join(sorted(missing))
                          + ". Nothing was replaced; inspect the site, or mark it "
                            "'Unsupported by Declarative Adapter'.")
    draft.manifest["id"] = package.manifest.id
    draft.manifest["version"] = _bump(package.manifest.version)
    if package.manifest.network.cdn_domains and not draft.manifest["network"]["cdn_domains"]:
        draft.manifest["network"]["cdn_domains"] = list(package.manifest.network.cdn_domains)

    before, after = _installed_selectors(package), _draft_selectors(draft.recipes)
    changes = [SelectorChange(capability, name, before[(capability, name)], value)
               for (capability, name), value in sorted(after.items())
               if (capability, name) in before and before[(capability, name)] != value]

    path = Path(write_package(draft, destination))
    repaired = load_package(path)                              # strict validation of the replacement
    diagnosis = await _probe(repaired, dev_hosts=dev_hosts, allow_http=allow_http)
    if diagnosis.broken:
        path.unlink(missing_ok=True)
        raise RepairError("the repaired adapter still fails for: " + ", ".join(diagnosis.broken)
                          + ". The installed version was left untouched.")
    return RepairOutcome(plugin_id=package.id, version=draft.manifest["version"], path=path, changes=changes,
                         validated=True, draft=draft, notes=list(draft.notes))
