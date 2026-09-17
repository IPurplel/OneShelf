"""Extraction Contracts and method policy (Master §14).

A contract fixes source, language, Reading Unit and required output. Fallback may change only the
extraction method, never the contract itself, and only for failures that are actually method-specific:
authentication, CAPTCHA, rate limits and whole-source outages wait instead.
"""
from __future__ import annotations

import json
import sqlite3
from dataclasses import asdict, dataclass, field, replace
from typing import Literal

from oneshelf.db.connection import transaction
from oneshelf.domain.clock import utcnow_iso
from oneshelf.settings.defaults import DEFAULTS

METHODS = ("direct", "html_api", "reader_media", "browser")
MODES = ("preferred_ask", "strict", "automatic")
SCOPES = ("global", "source", "work", "content_type")

# Failures that a different extraction method could plausibly fix.
METHOD_SPECIFIC = {"parser_failure", "selector_missing", "media_invalid", "not_found", "unexpected_response",
                   "resource_missing"}
WAITING = {"auth_failure": "wait_for_session", "rate_limit": "wait_for_rate_limit"}


@dataclass(frozen=True)
class ExtractionContract:
    source_id: str
    language: str
    reading_unit_id: str
    output_format: str
    method: str
    mode: str = DEFAULTS.downloads.fallback_mode
    fallback_order: tuple[str, ...] = ()
    attempted_methods: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.method not in METHODS:
            raise ValueError(f"unknown extraction method {self.method!r}")
        if self.mode not in MODES:
            raise ValueError(f"unknown fallback mode {self.mode!r}")
        if not self.attempted_methods:
            object.__setattr__(self, "attempted_methods", (self.method,))

    def with_method(self, method: str) -> ExtractionContract:
        """Only the method changes; source, language, unit and required output are preserved."""
        return replace(self, method=method, attempted_methods=(*self.attempted_methods, method))

    def to_json(self) -> str:
        return json.dumps(asdict(self))

    @classmethod
    def from_json(cls, data: str) -> ExtractionContract:
        raw = json.loads(data)
        raw["fallback_order"] = tuple(raw.get("fallback_order") or ())
        raw["attempted_methods"] = tuple(raw.get("attempted_methods") or ())
        return cls(**raw)


@dataclass(frozen=True)
class ResolvedMethod:
    method: str
    mode: str
    origin: str  # one_time | source | global | plugin
    fallback_order: tuple[str, ...] = ()


@dataclass(frozen=True)
class FallbackDecision:
    action: Literal["retry", "fallback", "ask", "fail", "wait_for_session", "wait_for_rate_limit"]
    method: str | None = None
    reason: str | None = None


class Settings:
    """Scoped settings storage; §42 defaults stay in the defaults registry and are overridden here."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn

    def set(self, scope: str, scope_id: str | None, key: str, value) -> None:
        if scope not in SCOPES:
            raise ValueError(f"unknown settings scope {scope!r}")
        if key == "extraction.method" and value not in METHODS:
            raise ValueError(f"unknown extraction method {value!r}")
        if key == "extraction.mode" and value not in MODES:
            raise ValueError(f"unknown fallback mode {value!r}")
        if key == "extraction.fallback_order" and (not isinstance(value, list)
                                                   or any(v not in METHODS for v in value)):
            raise ValueError("fallback order must be a list of known methods")
        with transaction(self.conn):
            self.conn.execute(
                "INSERT INTO settings (scope, scope_id, key, value_json, updated_at) VALUES (?,?,?,?,?)"
                " ON CONFLICT(scope, scope_id, key) DO UPDATE SET value_json=excluded.value_json,"
                " updated_at=excluded.updated_at",
                (scope, scope_id or "", key, json.dumps(value), utcnow_iso()))

    def get(self, scope: str, scope_id: str | None, key: str, default=None):
        row = self.conn.execute("SELECT value_json FROM settings WHERE scope = ? AND scope_id = ? AND key = ?",
                                (scope, scope_id or "", key)).fetchone()
        return default if row is None else json.loads(row[0])

    def delete(self, scope: str, scope_id: str | None, key: str) -> None:
        with transaction(self.conn):
            self.conn.execute("DELETE FROM settings WHERE scope = ? AND scope_id = ? AND key = ?",
                              (scope, scope_id or "", key))


def resolve_method(settings: Settings, source_id: str, *, plugin_recommendation: str | None = None,
                   one_time: str | None = None) -> ResolvedMethod:
    """Precedence: one-time override > source override > global default > plugin recommendation (§14)."""
    source_method = settings.get("source", source_id, "extraction.method")
    global_method = settings.get("global", None, "extraction.method")
    if one_time is not None:
        method, origin = one_time, "one_time"
    elif source_method is not None:
        method, origin = source_method, "source"
    elif global_method is not None:
        method, origin = global_method, "global"
    else:
        method, origin = plugin_recommendation or "html_api", "plugin"
    if method not in METHODS:
        raise ValueError(f"unknown extraction method {method!r}")
    mode = (settings.get("source", source_id, "extraction.mode")
            or settings.get("global", None, "extraction.mode") or DEFAULTS.downloads.fallback_mode)
    order = (settings.get("source", source_id, "extraction.fallback_order")
             or settings.get("global", None, "extraction.fallback_order") or [])
    return ResolvedMethod(method, mode, origin, tuple(order))


def may_fall_back(category: str | None) -> bool:
    return category in METHOD_SPECIFIC


def next_method(contract: ExtractionContract, *, attempts: int, retry_budget: int, category: str | None) -> FallbackDecision:
    """Smart Retry stays within the current method; only then is a method change considered."""
    if category in WAITING:
        return FallbackDecision(WAITING[category])
    if attempts < retry_budget:
        return FallbackDecision("retry", contract.method)
    if not may_fall_back(category):
        return FallbackDecision("fail", None, category)
    if contract.mode == "strict":
        return FallbackDecision("fail", None, category)
    if contract.mode == "automatic":
        for candidate in contract.fallback_order:
            if candidate not in contract.attempted_methods:
                return FallbackDecision("fallback", candidate, category)
        return FallbackDecision("fail", None, category)
    return FallbackDecision("ask", None, category)
