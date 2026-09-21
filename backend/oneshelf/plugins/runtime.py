"""Declarative recipe runtime (Master §9, §14 descriptors; Meta Prompt G3/G4).

Recipes describe requests and extraction; this runtime renders requests, asks a Core-owned fetcher to
perform them, extracts typed results, and records completeness evidence. It never touches the database,
filesystem paths or raw session material.
"""
from __future__ import annotations

import json
import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from typing import Any, Protocol
from urllib.parse import urlsplit

from scrapling.parser import Selector

from oneshelf.net.http import FetchFailed, ResponseTooLarge, TooManyRedirects
from oneshelf.net.policy import BlockedDestination, DisallowedTarget
from oneshelf.plugins import jsonpath
from oneshelf.plugins.package import PluginPackage
from oneshelf.plugins.results import (
    Evidence, FileDescriptor, HealthCheck, Issue, ListResult, Listing, ResourceDescriptor, SessionCheck,
    UnitDescriptor, WorkDetails,
)
from oneshelf.plugins.schema import FIELDS, LIST_CAPABILITIES, FieldSpec, Recipe
from oneshelf.plugins.templates import TemplateError, placeholders, render
from oneshelf.plugins.transforms import TransformError, _normalize_url, apply_pipeline

MAX_ITEMS_PER_PAGE = 5000
MAX_TOTAL_ITEMS = 100_000
PAGINATION_INPUTS = {"page", "offset"}
CONTENT_TYPES = {"manga", "manhwa", "manhua", "comic", "book", "novel", "paper", "other"}
UNIT_TYPES = {"chapter", "special", "extra", "prologue", "epilogue", "one_shot", "other"}
_LANGUAGE = re.compile(r"^[a-z]{2,3}(-[A-Za-z0-9]{2,8})*$")
_TEXTUAL_CSS = re.compile(r"::(text|attr\([^)]*\))\s*$")
_TEXTUAL_XPATH = re.compile(r"(text\(\)|@[\w:.-]+|\*)\s*$|^\s*(string|normalize-space|concat|substring)")
_URL_FIELDS = {"url", "cover_url"}
KEY_FIELD = {"search": "listing_key", "latest": "listing_key", "trending": "listing_key", "catalog": "unit_key",
             "reader": "url", "downloads": "url"}
STRICT_LISTS = {"catalog", "reader", "downloads"}


class CapabilityError(RuntimeError):
    def __init__(self, category: str, message: str) -> None:
        super().__init__(message)
        self.category = category


class AuthRequired(CapabilityError):
    def __init__(self, message: str = "source session required or expired") -> None:
        super().__init__("auth_failure", message)


class RateLimited(CapabilityError):
    def __init__(self, retry_after: float | None) -> None:
        super().__init__("rate_limit", "source rate limit reached")
        self.retry_after = retry_after


@dataclass(frozen=True)
class RecipeRequest:
    capability: str
    method: str
    url: str
    headers: dict[str, str]
    form: dict[str, str] | None
    fetch: str
    auth: str


@dataclass
class FetchedResponse:
    url: str
    status: int
    headers: Mapping[str, str]
    body: bytes

    def header(self, name: str) -> str | None:
        for key, value in self.headers.items():
            if key.lower() == name.lower():
                return value
        return None


class Fetcher(Protocol):
    async def fetch(self, request: RecipeRequest) -> FetchedResponse: ...


class _PageFailure(Exception):
    def __init__(self, category: str, detail: str) -> None:
        super().__init__(detail)
        self.category = category


def _as_bool(value: Any) -> bool | None:
    if isinstance(value, str):
        value = {"true": True, "1": True, "yes": True, "false": False, "0": False, "no": False}.get(value.lower())
    return value if isinstance(value, bool) else None


def parse_retry_after(value: str | None) -> float | None:
    if not value:
        return None
    value = value.strip()
    if value.isdigit():
        return float(value)
    try:
        when = parsedate_to_datetime(value)
    except (TypeError, ValueError):
        return None
    return max(0.0, (when - datetime.now(UTC)).total_seconds())


TEMPLATE_NAME = re.compile(r"\{([a-zA-Z_][a-zA-Z0-9_]*)\}")


def template_names(template: str) -> set[str]:
    return set(TEMPLATE_NAME.findall(template))


def render_template(template: str, values: dict[str, Any], *, item: Any = None,
                    inputs: dict[str, Any] | None = None) -> str | None:
    """Substitutes known names; a missing value yields nothing rather than a half-built URL."""
    available: dict[str, Any] = {**(inputs or {}), **values}
    if item is not None:
        available["item"] = item
    rendered = template
    for name in template_names(template):
        value = available.get(name)
        if value is None or value == "":
            return None
        rendered = rendered.replace("{" + name + "}", str(value))
    return rendered


def _raw_for(node: Any, spec) -> list[Any]:
    """The raw values a selector or JSON path yields on this node."""
    if spec.kind == "template":
        return []
    if spec.kind == "json":
        if isinstance(node, Selector):
            return []
        return jsonpath.evaluate(spec.json_, node)
    if not hasattr(node, "css"):
        return []
    results = node.css(spec.css) if spec.kind == "css" else node.xpath(spec.xpath)
    textual = (_TEXTUAL_CSS.search(spec.css) if spec.kind == "css" else _TEXTUAL_XPATH.search(spec.xpath))
    if spec.exists:
        return [bool(results)]
    values = []
    for result in results:
        if textual or not hasattr(result, "get_all_text"):
            values.append(str(result.get()) if hasattr(result, "get") else str(result))
        else:
            values.append(result.get_all_text(separator=" ", strip=True))
    return values


def resolve_values(document: Any, extract) -> dict[str, Any]:
    """Document-level values a template may use; read once per page, never per item."""
    resolved: dict[str, Any] = {}
    for name, spec in extract.values.items():
        raw = _raw_for(document, spec)
        resolved[name] = raw[0] if raw else None
    return {k: v for k, v in resolved.items() if v is not None}


def parse_document(text: str, *, url: str) -> Selector:
    """Markup responses include XML feeds (Atom/OPDS); lxml refuses a declaration on a str input."""
    stripped = text.lstrip()
    if stripped.startswith("<?xml"):
        stripped = stripped.split("?>", 1)[-1].lstrip()
    return Selector(stripped or "<html/>", url=url)


class RecipeRuntime:
    def __init__(self, package: PluginPackage, fetcher: Fetcher) -> None:
        self.package = package
        self.fetcher = fetcher

    # -- public ---------------------------------------------------------------------------------

    async def run(self, capability: str, inputs: dict[str, Any]):
        recipe = self.package.recipes.get(capability)
        if recipe is None:
            raise CapabilityError("unsupported", f"capability {capability!r} is not provided by this plugin")
        values = self._validate_inputs(recipe, inputs)
        if capability in LIST_CAPABILITIES:
            return await self._run_list(recipe, values)
        try:
            response, document = await self._fetch_page(recipe, self._render(recipe, values), page=None)
        except _PageFailure as failure:
            # A single-document capability has no list to record the failure in: it is a capability error,
            # the one kind callers handle — never the runtime's private page failure (found 2026-09-21).
            raise CapabilityError(failure.category, str(failure)) from failure
        fields = self._extract_fields(recipe, document, response.url, recipe.extract.fields,
                                      values=resolve_values(document, recipe.extract), inputs=values)
        missing = [name for name, required in FIELDS[capability].items() if required and fields.get(name) in (None, "")]
        if missing:
            raise CapabilityError("selector_missing", f"required fields missing: {missing}")
        return self._build_single(capability, fields)

    # -- inputs and requests --------------------------------------------------------------------

    def _validate_inputs(self, recipe: Recipe, inputs: dict[str, Any]) -> dict[str, Any]:
        extra = set(inputs) - set(recipe.inputs)
        if extra:
            raise CapabilityError("invalid_input", f"undeclared inputs: {sorted(extra)}")
        needed = {name for name, _ in placeholders(recipe.request.url)} - {"base_url"} - PAGINATION_INPUTS
        missing = sorted(n for n in needed if inputs.get(n) in (None, ""))
        if missing:
            raise CapabilityError("invalid_input", f"missing inputs: {missing}")
        return dict(inputs)

    def _render(self, recipe: Recipe, values: dict[str, Any]) -> RecipeRequest:
        base = self.package.source.base_url
        try:
            url = render(recipe.request.url, values, base_url=base)
            form = {k: render(v, values, base_url=base) for k, v in recipe.request.form.items()} if recipe.request.form else None
        except TemplateError as exc:
            raise CapabilityError("invalid_input", str(exc)) from exc
        return RecipeRequest(recipe.capability, recipe.request.method, url, dict(recipe.request.headers), form,
                             recipe.request.fetch, recipe.request.auth)

    def _is_login_page(self, final_url: str) -> bool:
        auth = self.package.manifest.auth
        if auth is None:
            return False
        login, final = urlsplit(auth.login_url), urlsplit(final_url)
        return (final.hostname or "").lower() == (login.hostname or "").lower() and final.path.rstrip("/") == login.path.rstrip("/")

    async def _fetch_page(self, recipe: Recipe, request: RecipeRequest, *, page: int | None):
        try:
            response = await self.fetcher.fetch(request)
        except (DisallowedTarget, BlockedDestination) as exc:
            raise _PageFailure("blocked", str(exc)) from exc
        except TimeoutError as exc:
            raise _PageFailure("timeout", str(exc)) from exc
        except (FetchFailed, TooManyRedirects, ResponseTooLarge) as exc:
            raise _PageFailure("transport", str(exc)) from exc
        if response.status == 429:
            raise RateLimited(parse_retry_after(response.header("Retry-After")))
        if recipe.request.auth != "none" and (response.status in (401, 403) or self._is_login_page(response.url)):
            raise AuthRequired()
        if response.status not in recipe.response.expect_status:
            category = ("server_error" if response.status >= 500 else "not_found" if response.status in (404, 410)
                        else "unexpected_response")
            raise _PageFailure(category, f"HTTP {response.status}")
        try:
            if recipe.response.format == "json":
                document: Any = json.loads(response.body)
                if recipe.response.markup_at is not None:
                    # The envelope carried markup: unwrap it and read it as the document it is.
                    found = jsonpath.evaluate(recipe.response.markup_at, document)
                    text = next((v for v in found if isinstance(v, str)), None)
                    if text is None:
                        raise _PageFailure("parser_failure",
                                           f"no markup at {recipe.response.markup_at!r} in the response")
                    document = parse_document(text, url=response.url)
            else:
                document = parse_document(response.body.decode("utf-8", errors="replace"), url=response.url)
        except (ValueError, UnicodeDecodeError) as exc:
            raise _PageFailure("parser_failure", f"could not parse {recipe.response.format}: {exc}") from exc
        return response, document

    # -- extraction -----------------------------------------------------------------------------

    def _raw_values(self, node: Any, spec: FieldSpec) -> list[Any]:
        return _raw_for(node, spec)

    @staticmethod
    def _scalar(value: Any) -> str | None:
        if value is None or isinstance(value, (dict, list)):
            return None
        if isinstance(value, bool):
            return "true" if value else "false"
        return str(value)

    def _field(self, node: Any, spec: FieldSpec, base_url: str, issues: list[Issue],
               values: dict[str, Any] | None = None, item: Any = None,
               inputs: dict[str, Any] | None = None) -> Any:
        if spec.template is not None:
            rendered = render_template(spec.template, values or {},
                                       item=self._scalar(item) if item is not None else None, inputs=inputs)
            return apply_pipeline(rendered, spec.transforms, base_url=base_url) if rendered else None
        raw = self._raw_values(node, spec)
        if spec.exists:
            return bool(raw and raw[0]) if spec.kind != "json" else bool(raw)
        values = [self._scalar(v) for v in raw]
        value: Any = [v for v in values if v is not None] if spec.all else (values[0] if values else None)
        try:
            value = apply_pipeline(value, spec.transforms, base_url=base_url)
        except TransformError as exc:
            issues.append(Issue("parser_failure", f"transform failed: {exc}"))
            return None
        if isinstance(value, str):
            value = value.strip() or None
        elif isinstance(value, list):
            value = [v.strip() for v in value if isinstance(v, str) and v.strip()]
        return value

    def _extract_fields(self, recipe: Recipe, node: Any, base_url: str, specs: dict[str, FieldSpec],
                        issues: list[Issue] | None = None, values: dict[str, Any] | None = None,
                        inputs: dict[str, Any] | None = None) -> dict[str, Any]:
        issues = issues if issues is not None else []
        out = {name: self._field(node, spec, base_url, issues, values, item=node, inputs=inputs)
               for name, spec in specs.items()}
        for name in _URL_FIELDS & out.keys():
            if isinstance(out[name], str):
                out[name] = _normalize_url(out[name], base_url)
        return out

    # -- typed builders ---------------------------------------------------------------------------

    @staticmethod
    def _content_type(value: Any) -> str | None:
        return value.lower() if isinstance(value, str) and value.lower() in CONTENT_TYPES else None

    @staticmethod
    def _language(value: Any) -> str | None:
        return value if isinstance(value, str) and _LANGUAGE.match(value) else None

    def _build_entry(self, capability: str, f: dict[str, Any], index: int):
        if capability in ("search", "latest", "trending"):
            return Listing(listing_key=f["listing_key"], title=f["title"], url=f.get("url"), cover_url=f.get("cover_url"),
                           content_type=self._content_type(f.get("content_type")), language=self._language(f.get("language")),
                           creator=f.get("creator"), description=f.get("description"), original_title=f.get("original_title"))
        if capability == "catalog":
            unit_type = (f.get("unit_type") or "").lower().replace("-", "_").replace(" ", "_")
            return UnitDescriptor(unit_key=f["unit_key"], order_index=index, raw_title=f.get("title"), number=f.get("number"),
                                  volume=f.get("volume"), unit_type=unit_type if unit_type in UNIT_TYPES else "unknown",
                                  url=f.get("url"), release_date=f.get("release_date"))
        if capability == "reader":
            return ResourceDescriptor(url=f["url"], index=index, page_label=f.get("page_label"))
        size = f.get("size_bytes")
        return FileDescriptor(url=f["url"], format=str(f["format"]).lower(), variant=f.get("variant"),
                              size_bytes=int(size) if isinstance(size, str) and size.isdigit() else None,
                              language=self._language(f.get("language")))

    def _build_single(self, capability: str, f: dict[str, Any]):
        if capability == "work":
            aliases = f.get("aliases") or []
            return WorkDetails(title=f["title"], original_title=f.get("original_title"),
                               aliases=aliases if isinstance(aliases, list) else [aliases],
                               description=f.get("description"), creator=f.get("creator"), cover_url=f.get("cover_url"),
                               content_type=self._content_type(f.get("content_type")),
                               language=self._language(f.get("language")), status=f.get("status"))
        if capability == "check_session":
            return SessionCheck(logged_in=_as_bool(f.get("logged_in")))
        return HealthCheck(ok=_as_bool(f.get("ok")))

    # -- list capabilities with pagination ------------------------------------------------------------

    async def _run_list(self, recipe: Recipe, values: dict[str, Any]) -> ListResult:
        capability, pagination = recipe.capability, recipe.pagination
        key_field = KEY_FIELD[capability]
        evidence = Evidence()
        entries_fields: list[dict[str, Any]] = []
        seen_keys: set[str] = set()
        seen_urls: set[str] = set()
        previous_signature: tuple | None = None
        complete = False
        next_request: RecipeRequest | None = None
        max_pages = 1 if pagination.mode == "none" else pagination.max_pages

        for page_index in range(max_pages):
            page_values = dict(values)
            if pagination.mode == "page_number":
                page_values["page"] = pagination.start + page_index
            elif pagination.mode == "offset":
                page_values["offset"] = pagination.start + page_index * (pagination.step or 1)
            elif pagination.mode == "next_link" and page_values.get("page") is None and "page" in recipe.inputs:
                page_values["page"] = pagination.start
            request = next_request if next_request is not None else self._render(recipe, page_values)
            if request.url in seen_urls:
                evidence.stop_reason = "pagination_loop"
                break
            seen_urls.add(request.url)
            try:
                response, document = await self._fetch_page(recipe, request, page=page_index + 1)
            except _PageFailure as failure:
                # Some sites answer 404 for a page past the last one. Where a recipe says so, and a page
                # has already been read, that is the end of the list rather than a failure of it — and
                # reporting it as a failure marks a complete set of results incomplete (§5, §14).
                if (pagination.stop_when == "not_found" and failure.category == "not_found"
                        and evidence.pages > 0):
                    complete, evidence.stop_reason = True, "no_more_pages"
                    break
                evidence.issues.append(Issue(failure.category, str(failure), page_index + 1))
                evidence.stop_reason = "page_failed"
                break
            evidence.pages += 1

            item_nodes = self._raw_items(recipe, document)[:MAX_ITEMS_PER_PAGE]
            page_values = resolve_values(document, recipe.extract)
            page_fields = []
            for node in item_nodes:
                fields = self._extract_fields(recipe, node, response.url, recipe.extract.fields, evidence.issues,
                                              page_values, inputs=values)
                missing = [n for n, req in FIELDS[capability].items() if req and fields.get(n) in (None, "")]
                if missing:
                    evidence.skipped += 1
                    if capability in STRICT_LISTS:
                        evidence.issues.append(Issue("catalog_validation_failure", f"item missing {missing}", page_index + 1))
                    continue
                page_fields.append(fields)

            signature = tuple(str(f.get(key_field)) for f in page_fields)
            if page_fields and signature == previous_signature:
                evidence.stop_reason = "repeated_page"
                break
            previous_signature = signature
            for fields in page_fields:
                key = str(fields.get(key_field))
                if key in seen_keys:
                    evidence.duplicates += 1
                    continue
                seen_keys.add(key)
                entries_fields.append(fields)
            if len(entries_fields) > MAX_TOTAL_ITEMS:
                evidence.issues.append(Issue("catalog_validation_failure", "too many items"))
                evidence.stop_reason = "item_cap_reached"
                break

            if pagination.mode == "none":
                complete, evidence.stop_reason = True, "single_response"
                break
            if pagination.stop_when == "empty_items" and not item_nodes:
                complete, evidence.stop_reason = True, "empty_page"
                break
            if pagination.stop_when == "total_count":
                if evidence.total_expected is None:
                    total = self._field(document, pagination.total, response.url, evidence.issues)
                    if not (isinstance(total, str) and total.isdigit()):
                        evidence.issues.append(Issue("parser_failure", "total count not found", page_index + 1))
                        evidence.stop_reason = "total_unknown"
                        break
                    evidence.total_expected = int(total)
                if len(seen_keys) >= evidence.total_expected:
                    complete, evidence.stop_reason = True, "total_reached"
                    break
                if not item_nodes:
                    evidence.stop_reason = "total_not_reached"
                    break
            if pagination.mode == "next_link":
                next_url = self._field(document, pagination.next, response.url, evidence.issues)
                next_url = _normalize_url(next_url, response.url) if isinstance(next_url, str) else None
                if not next_url:
                    complete, evidence.stop_reason = True, "last_page"
                    break
                next_request = RecipeRequest(capability, "GET", next_url, dict(recipe.request.headers), None,
                                             recipe.request.fetch, recipe.request.auth)
        else:
            evidence.stop_reason = "page_cap_reached"

        if complete and capability in STRICT_LISTS and any(i.category == "catalog_validation_failure" for i in evidence.issues):
            complete = False
        if recipe.extract.order == "reverse":
            entries_fields.reverse()
        entries = [self._build_entry(capability, f, i) for i, f in enumerate(entries_fields)]
        return ListResult(capability, entries, complete, evidence)

    def _raw_items(self, recipe: Recipe, document: Any) -> list[Any]:
        spec = recipe.extract.items
        if spec.kind == "json":
            return [] if isinstance(document, Selector) else [n for n in jsonpath.evaluate(spec.json_, document)]
        return list(document.css(spec.css) if spec.kind == "css" else document.xpath(spec.xpath))


# -- packaged tests (install step 7) --------------------------------------------------------------

@dataclass
class TestReport:
    passed: bool
    cases: int
    failures: list[str] = field(default_factory=list)


class FixtureFetcher:
    def __init__(self, package: PluginPackage, fixtures) -> None:
        self.routes = {f.url: f for f in fixtures}
        self.package = package

    async def fetch(self, request: RecipeRequest) -> FetchedResponse:
        fixture = self.routes.get(request.url)
        if fixture is None:
            raise FetchFailed(f"no packaged fixture for {request.url}")
        headers = {"Content-Type": fixture.content_type} if fixture.content_type else {}
        return FetchedResponse(request.url, fixture.status, headers, self.package.files[f"tests/{fixture.file}"])


def _expected_attr(entry: Any, name: str) -> Any:
    if name == "title" and isinstance(entry, UnitDescriptor):
        return entry.raw_title
    return getattr(entry, name, None)


async def run_packaged_tests(package: PluginPackage) -> TestReport:
    report = TestReport(passed=True, cases=len(package.tests.cases))
    for index, case in enumerate(package.tests.cases):
        label = f"case {index} ({case.capability})"
        try:
            result = await RecipeRuntime(package, FixtureFetcher(package, case.fixtures)).run(case.capability, dict(case.inputs))
        except CapabilityError as exc:
            report.failures.append(f"{label}: {exc.category}: {exc}")
            continue
        expect = case.expect
        entries = result.entries if isinstance(result, ListResult) else [result]
        if isinstance(result, ListResult) and len(entries) < expect.min_items:
            report.failures.append(f"{label}: expected min_items {expect.min_items}, got {len(entries)}")
            continue
        first = entries[0] if entries else None
        for name in expect.fields_present:
            if first is None or _expected_attr(first, name) in (None, "", []):
                report.failures.append(f"{label}: field {name!r} missing")
        if expect.complete is not None and isinstance(result, ListResult) and result.complete != expect.complete:
            report.failures.append(f"{label}: expected complete={expect.complete}, got {result.complete}")
        for name, value in expect.first.items():
            actual = _expected_attr(first, name) if first is not None else None
            if (None if actual is None else str(actual)) != value:
                report.failures.append(f"{label}: first.{name} expected {value!r}, got {actual!r}")
    report.passed = not report.failures
    return report

