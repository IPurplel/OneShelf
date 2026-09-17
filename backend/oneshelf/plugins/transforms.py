"""Bounded safe transform library for declarative recipes (Master §9.4).

Pipelines are data, validated at install time. Regular expressions use RE2 (linear time, no
backreferences or lookaround). Every value and step count is size-limited. None means Unknown and
passes through unchanged.
"""
from __future__ import annotations

import base64
import binascii
import html
import re
from collections.abc import Callable
from datetime import datetime
from typing import Any
from urllib.parse import unquote, urljoin, urlsplit, urlunsplit

import re2

from oneshelf.text.arabic import normalize_strong

MAX_STEPS = 16
MAX_VALUE_BYTES = 1024 * 1024
MAX_LIST_ITEMS = 10_000
MAX_PATTERN_LENGTH = 512
RE2_MAX_MEM = 8 * 1024 * 1024

Value = str | list | None
_DEFAULT_DATE_FORMATS = ("%Y-%m-%d", "%b %d, %Y", "%B %d, %Y", "%d %b %Y", "%d %B %Y")
_DIGITS = str.maketrans({**{chr(0x0660 + i): str(i) for i in range(10)},
                         **{chr(0x06F0 + i): str(i) for i in range(10)}, "٫": "."})
_NUMBER = re.compile(r"\d+(?:\.\d+)?")


class TransformError(ValueError):
    pass


# -- argument schemas: name -> {arg: (type, required)} ------------------------------------------
_SCHEMAS: dict[str, dict[str, tuple[tuple[type, ...], bool]]] = {
    "trim": {}, "extract_number": {}, "normalize_arabic": {}, "html_decode": {}, "url_decode": {},
    "base64_decode": {}, "normalize_url": {},
    "parse_date": {"formats": ((list,), False)},
    "replace": {"old": ((str,), True), "new": ((str,), True)},
    "regex_extract": {"pattern": ((str,), True), "group": ((int, str), False)},
    "regex_replace": {"pattern": ((str,), True), "replacement": ((str,), True)},
    "split": {"sep": ((str,), True), "index": ((int,), False)},
    "join": {"sep": ((str,), True)},
}


def _compile(pattern: str):
    if len(pattern) > MAX_PATTERN_LENGTH:
        raise TransformError("regex pattern too long")
    options = re2.Options()
    options.max_mem = RE2_MAX_MEM
    try:
        return re2.compile(pattern, options)
    except re2.error as exc:
        raise TransformError(f"unsupported regex: {exc}") from exc


def _parse_step(step: Any) -> tuple[str, dict]:
    if isinstance(step, str):
        name, args = step, {}
    elif isinstance(step, dict) and len(step) == 1:
        name, args = next(iter(step.items()))
        args = {} if args is None else args
    else:
        raise TransformError(f"invalid transform step: {step!r}")
    if name not in _SCHEMAS:
        raise TransformError(f"unknown transform: {name!r}")
    if not isinstance(args, dict):
        raise TransformError(f"arguments for {name} must be a mapping")
    schema = _SCHEMAS[name]
    for key, value in args.items():
        if key not in schema:
            raise TransformError(f"unexpected argument {key!r} for {name}")
        if not isinstance(value, schema[key][0]) or isinstance(value, bool):
            raise TransformError(f"invalid type for {name}.{key}")
    for key, (_types, required) in schema.items():
        if required and key not in args:
            raise TransformError(f"missing argument {key!r} for {name}")
    if name == "split" and not args["sep"]:
        raise TransformError("split separator must not be empty")
    if name == "parse_date" and not all(isinstance(f, str) for f in args.get("formats", [])):
        raise TransformError("parse_date formats must be strings")
    return name, args


def validate_pipeline(spec: Any) -> None:
    if not isinstance(spec, list):
        raise TransformError("transform pipeline must be a list")
    if len(spec) > MAX_STEPS:
        raise TransformError("too many transform steps")
    for step in spec:
        name, args = _parse_step(step)
        if "pattern" in args:
            _compile(args["pattern"])


def _size(value: Value) -> int:
    if value is None:
        return 0
    if isinstance(value, list):
        if len(value) > MAX_LIST_ITEMS:
            raise TransformError("too many list items")
        return sum(_size(v) for v in value)
    return len(value.encode("utf-8"))


def _check(value: Value) -> Value:
    if _size(value) > MAX_VALUE_BYTES:
        raise TransformError("value exceeds size limit")
    return value


def _extract_number(text: str) -> str | None:
    match = _NUMBER.search(text.translate(_DIGITS))
    return match.group(0) if match else None


def _parse_date(text: str, formats: list[str] | None) -> str | None:
    text = text.strip()
    if not text:
        return None
    if not formats:
        try:
            return datetime.fromisoformat(text.replace("Z", "+00:00")).date().isoformat()
        except ValueError:
            pass
    for fmt in formats or _DEFAULT_DATE_FORMATS:
        try:
            return datetime.strptime(text, fmt).date().isoformat()
        except ValueError:
            continue
    return None


def _normalize_url(text: str, base_url: str | None) -> str | None:
    candidate = urljoin(base_url or "", text.strip())
    try:
        parts = urlsplit(candidate)
    except ValueError:
        return None
    if parts.scheme not in ("http", "https") or not parts.hostname or parts.username or parts.password:
        return None
    return urlunsplit((parts.scheme, parts.netloc.lower(), parts.path or "/", parts.query, ""))


def _base64(text: str) -> str:
    try:
        return base64.b64decode(text.strip(), validate=True).decode("utf-8")
    except (binascii.Error, UnicodeDecodeError, ValueError) as exc:
        raise TransformError("invalid base64 text") from exc


def _scalar(name: str, args: dict, base_url: str | None) -> Callable[[str], str | None]:
    if name == "trim":
        return str.strip
    if name == "extract_number":
        return _extract_number
    if name == "normalize_arabic":
        return normalize_strong
    if name == "html_decode":
        return html.unescape
    if name == "url_decode":
        return unquote
    if name == "base64_decode":
        return _base64
    if name == "normalize_url":
        return lambda t: _normalize_url(t, base_url)
    if name == "parse_date":
        return lambda t: _parse_date(t, args.get("formats"))
    if name == "replace":
        return lambda t: _check(t.replace(args["old"], args["new"]))
    if name == "regex_extract":
        regex, group = _compile(args["pattern"]), args.get("group", 0)

        def extract(t: str) -> str | None:
            match = regex.search(t)
            return match.group(group) if match else None

        return extract
    if name == "regex_replace":
        regex = _compile(args["pattern"])
        return lambda t: _check(regex.sub(args["replacement"], t))
    raise TransformError(f"no scalar implementation for {name}")


def apply_pipeline(value: Value, spec: list, *, base_url: str | None = None) -> Value:
    _check(value)
    for step in spec:
        name, args = _parse_step(step)
        if value is None:
            return None
        if name == "split":
            if isinstance(value, list):
                raise TransformError("split expects text")
            parts = value.split(args["sep"])
            if "index" in args:
                value = parts[args["index"]] if -len(parts) <= args["index"] < len(parts) else None
            else:
                value = parts
        elif name == "join":
            value = args["sep"].join(v for v in (value if isinstance(value, list) else [value]) if v is not None)
        else:
            fn = _scalar(name, args, base_url)
            value = [None if v is None else fn(v) for v in value] if isinstance(value, list) else fn(value)
        _check(value)
    return value
