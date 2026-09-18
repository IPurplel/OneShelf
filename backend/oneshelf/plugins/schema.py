"""Declarative .osp schema (Master §9.1–9.3). Every model forbids unknown keys."""
from __future__ import annotations

import re
from typing import Literal

from lxml import etree
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from scrapling.core.translator import HTMLTranslator

from oneshelf.net.domains import DomainRuleError, normalize_rule
from oneshelf.plugins import jsonpath
from oneshelf.plugins.transforms import TransformError, _compile, validate_pipeline

API_MAJOR, API_MINOR = 1, 0
MAX_SELECTOR = 512
MAX_TEMPLATE = 512
MAX_PAGES_CAP = 1000

Capability = Literal["search", "work", "catalog", "reader", "downloads", "latest", "trending", "check_session", "health"]
ContentType = Literal["manga", "manhwa", "manhua", "comic", "book", "novel", "paper", "other"]
LIST_CAPABILITIES = {"search", "latest", "trending", "catalog", "reader", "downloads"}

FIELDS: dict[str, dict[str, bool]] = {  # capability -> {field: required}
    "search": {"listing_key": True, "title": True, "url": False, "cover_url": False, "content_type": False,
               "language": False, "creator": False, "description": False, "original_title": False},
    "work": {"title": True, "original_title": False, "aliases": False, "description": False, "creator": False,
             "cover_url": False, "content_type": False, "language": False, "status": False},
    "catalog": {"unit_key": True, "title": False, "number": False, "volume": False, "unit_type": False,
                "url": False, "release_date": False},
    "reader": {"url": True, "page_label": False},
    "downloads": {"url": True, "format": True, "variant": False, "size_bytes": False, "language": False},
    "check_session": {"logged_in": True},
    "health": {"ok": False},
}
FIELDS["latest"] = FIELDS["trending"] = FIELDS["search"]

_TRANSLATOR = HTMLTranslator()


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


def _rule(value: str) -> str:
    try:
        return normalize_rule(value)
    except DomainRuleError as exc:
        raise ValueError(str(exc)) from exc


class Network(Strict):
    domains: list[str] = Field(min_length=1, max_length=32)
    cdn_domains: list[str] = Field(default_factory=list, max_length=32)
    allow_http: bool = False

    @field_validator("domains", "cdn_domains")
    @classmethod
    def _rules(cls, value: list[str]) -> list[str]:
        return [_rule(v) for v in value]


class Browser(Strict):
    capabilities: list[Capability] = Field(default_factory=list)


class Auth(Strict):
    login_url: str
    session_domains: list[str] = Field(min_length=1)
    required_for: list[Capability] = Field(default_factory=list)
    optional_for: list[Capability] = Field(default_factory=list)

    @field_validator("session_domains")
    @classmethod
    def _rules(cls, value: list[str]) -> list[str]:
        return [_rule(v) for v in value]


class Defaults(Strict):
    language: str | None = Field(default=None, pattern=r"^[a-z]{2,3}(-[A-Za-z0-9]{2,8})*$")
    content_type: ContentType | None = None


class Manifest(Strict):
    schema_: Literal["oneshelf.osp/1"] = Field(alias="schema")
    id: str = Field(pattern=r"^[a-z0-9]+(?:[.-][a-z0-9]+)*$", min_length=3, max_length=64)
    name: str = Field(min_length=1, max_length=80)
    version: str = Field(pattern=r"^\d+\.\d+\.\d+$")
    api: str = Field(pattern=r"^\d+\.\d+$")
    description: str | None = Field(default=None, max_length=1000)
    publisher: str | None = Field(default=None, max_length=120)
    capabilities: list[Capability] = Field(min_length=1)
    network: Network
    browser: Browser = Field(default_factory=Browser)
    auth: Auth | None = None
    defaults: Defaults = Field(default_factory=Defaults)

    @field_validator("api")
    @classmethod
    def _api(cls, value: str) -> str:
        major, minor = (int(p) for p in value.split("."))
        if major != API_MAJOR or minor > API_MINOR:
            raise ValueError(f"unsupported plugin API {value}; this OneShelf supports {API_MAJOR}.{API_MINOR}")
        return value

    @field_validator("capabilities")
    @classmethod
    def _unique(cls, value: list[str]) -> list[str]:
        if len(set(value)) != len(value):
            raise ValueError("duplicate capabilities")
        return value


class UrlPattern(Strict):
    pattern: str
    capability: Literal["work", "catalog", "reader"]
    id_group: int | str = 1

    @field_validator("pattern")
    @classmethod
    def _re2(cls, value: str) -> str:
        try:
            _compile(value)
        except TransformError as exc:
            raise ValueError(str(exc)) from exc
        return value


class RateLimit(Strict):
    requests_per_minute: int = Field(default=60, ge=1, le=600)
    concurrency: int = Field(default=2, ge=1, le=4)


class Timeouts(Strict):
    connect_seconds: float = Field(default=10, gt=0, le=30)
    read_seconds: float = Field(default=30, gt=0, le=120)


class SourceConfig(Strict):
    base_url: str = Field(max_length=512)
    url_patterns: list[UrlPattern] = Field(default_factory=list, max_length=32)
    rate_limit: RateLimit = Field(default_factory=RateLimit)
    timeouts: Timeouts = Field(default_factory=Timeouts)


class FieldSpec(Strict):
    css: str | None = Field(default=None, max_length=MAX_SELECTOR)
    xpath: str | None = Field(default=None, max_length=MAX_SELECTOR)
    json_: str | None = Field(default=None, alias="json", max_length=jsonpath.MAX_LENGTH)
    # A template composes a value from document-level `values`, the current `item`, and recipe inputs.
    # Real APIs return a base URL, a hash and bare filenames separately (Master §41.1, MangaDex).
    template: str | None = Field(default=None, max_length=MAX_TEMPLATE)
    all: bool = False
    exists: bool = False
    required: bool = False
    transforms: list = Field(default_factory=list)

    @model_validator(mode="after")
    def _check(self) -> FieldSpec:
        chosen = [s for s in (self.css, self.xpath, self.json_, self.template) if s is not None]
        if len(chosen) != 1:
            raise ValueError("exactly one of css, xpath, json or template is required")
        if self.template is not None and (self.all or self.exists):
            raise ValueError("a template field cannot use all or exists")
        try:
            if self.css is not None:
                _TRANSLATOR.css_to_xpath(self.css)
            if self.xpath is not None:
                etree.XPath(self.xpath)
            if self.json_ is not None:
                jsonpath.parse(self.json_)
            validate_pipeline(self.transforms)
        except (TransformError, jsonpath.JsonPathError) as exc:
            raise ValueError(str(exc)) from exc
        except Exception as exc:  # cssselect / lxml syntax errors
            raise ValueError(f"invalid selector: {exc}") from exc
        return self

    @property
    def kind(self) -> str:
        if self.css is not None:
            return "css"
        if self.xpath is not None:
            return "xpath"
        return "json" if self.json_ is not None else "template"


class Request(Strict):
    method: Literal["GET", "POST"] = "GET"
    url: str
    headers: dict[str, str] = Field(default_factory=dict, max_length=20)
    form: dict[str, str] | None = None
    fetch: Literal["http", "browser"] = "http"
    auth: Literal["none", "optional", "required"] = "none"

    @field_validator("headers")
    @classmethod
    def _headers(cls, value: dict[str, str]) -> dict[str, str]:
        forbidden = {"cookie", "authorization", "host", "content-length", "transfer-encoding", "connection",
                     "te", "upgrade", "set-cookie"}
        for name, header_value in value.items():
            lower = name.lower()
            if (not re.match(r"^[A-Za-z0-9-]{1,64}$", name) or lower in forbidden
                    or lower.startswith(("proxy-", "x-forwarded-", "sec-")) or lower == "forwarded"):
                raise ValueError(f"header not allowed in recipes: {name!r}")
            if len(header_value) > 512 or "\r" in header_value or "\n" in header_value:
                raise ValueError(f"invalid header value for {name!r}")
        return value


class Response(Strict):
    format: Literal["html", "json"]
    expect_status: list[int] = Field(default_factory=lambda: [200])


class Extract(Strict):
    # Values read once per page and reusable by templates (a base URL, a hash, a token in the body).
    values: dict[str, FieldSpec] = Field(default_factory=dict, max_length=8)
    items: FieldSpec | None = None
    order: Literal["source_listed", "reverse"] = "source_listed"
    fields: dict[str, FieldSpec] = Field(min_length=1)


class Pagination(Strict):
    mode: Literal["none", "page_number", "offset", "next_link"] = "none"
    start: int = Field(default=1, ge=0)
    step: int | None = Field(default=None, ge=1, le=10_000)
    max_pages: int = Field(default=1, ge=1, le=MAX_PAGES_CAP)
    stop_when: Literal["empty_items", "total_count", "no_next"] | None = None
    total: FieldSpec | None = None
    next: FieldSpec | None = None
    complete_when: Literal["single_response"] | None = None

    @model_validator(mode="after")
    def _consistent(self) -> Pagination:
        if self.mode == "next_link" and self.next is None:
            raise ValueError("next_link pagination needs a next selector")
        if self.stop_when == "total_count" and self.total is None:
            raise ValueError("total_count completion needs a total selector")
        if self.mode == "offset" and self.step is None:
            raise ValueError("offset pagination needs a step")
        return self


class Recipe(Strict):
    capability: Capability
    inputs: list[str] = Field(default_factory=list)
    request: Request
    response: Response
    extract: Extract
    pagination: Pagination = Field(default_factory=Pagination)


class FixtureResponse(Strict):
    url: str
    file: str
    status: int = 200
    content_type: str | None = None


class Expectation(Strict):
    min_items: int = Field(default=0, ge=0)
    fields_present: list[str] = Field(default_factory=list)
    complete: bool | None = None
    first: dict[str, str | None] = Field(default_factory=dict)


class TestCase(Strict):
    capability: Capability
    inputs: dict[str, str | int] = Field(default_factory=dict)
    fixtures: list[FixtureResponse] = Field(min_length=1)
    expect: Expectation = Field(default_factory=Expectation)


class TestSuite(Strict):
    cases: list[TestCase] = Field(min_length=1, max_length=100)
