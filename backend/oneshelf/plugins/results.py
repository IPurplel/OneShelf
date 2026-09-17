"""Typed capability results returned by declarative recipes (Master §9.1). None means Unknown."""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Issue:
    category: str  # timeout, server_error, parser_failure, selector_missing, auth_failure, rate_limit,
    #               unexpected_response, catalog_validation_failure, blocked, transport
    detail: str
    page: int | None = None


@dataclass
class Evidence:
    """Why a list result is (or is not) complete (Master §5.1, Meta Prompt G3)."""
    pages: int = 0
    stop_reason: str | None = None
    duplicates: int = 0
    skipped: int = 0
    total_expected: int | None = None
    issues: list[Issue] = field(default_factory=list)


@dataclass(frozen=True)
class Listing:
    listing_key: str
    title: str
    url: str | None = None
    cover_url: str | None = None
    content_type: str | None = None
    language: str | None = None
    creator: str | None = None
    description: str | None = None
    original_title: str | None = None


@dataclass(frozen=True)
class UnitDescriptor:
    unit_key: str
    order_index: int
    raw_title: str | None = None
    number: str | None = None
    volume: str | None = None
    unit_type: str = "unknown"
    url: str | None = None
    release_date: str | None = None


@dataclass(frozen=True)
class ResourceDescriptor:
    url: str
    index: int
    page_label: str | None = None


@dataclass(frozen=True)
class FileDescriptor:
    url: str
    format: str
    variant: str | None = None
    size_bytes: int | None = None
    language: str | None = None


@dataclass
class ListResult:
    capability: str
    entries: list
    complete: bool
    evidence: Evidence

    @property
    def items(self) -> list[Listing]:
        return self.entries

    @property
    def units(self) -> list[UnitDescriptor]:
        return self.entries

    @property
    def resources(self) -> list[ResourceDescriptor]:
        return self.entries

    @property
    def files(self) -> list[FileDescriptor]:
        return self.entries


@dataclass(frozen=True)
class WorkDetails:
    title: str
    original_title: str | None = None
    aliases: list[str] = field(default_factory=list)
    description: str | None = None
    creator: str | None = None
    cover_url: str | None = None
    content_type: str | None = None
    language: str | None = None
    status: str | None = None


@dataclass(frozen=True)
class SessionCheck:
    logged_in: bool | None


@dataclass(frozen=True)
class HealthCheck:
    ok: bool | None
