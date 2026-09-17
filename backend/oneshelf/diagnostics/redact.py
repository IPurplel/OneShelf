"""Redaction for local diagnostics (Master §43, §48). Applied at write time, never after storage."""
from __future__ import annotations

import logging
import re
from collections.abc import Mapping
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

REDACTED = "[redacted]"
SENSITIVE_HEADERS = {"cookie", "set-cookie", "authorization", "proxy-authorization", "x-api-key", "x-auth-token",
                     "x-csrf-token", "x-xsrf-token"}
_SENSITIVE_PARAM = re.compile(
    r"(token|sig|signature|secret|password|passwd|session|sessionid|auth|key|credential|code|jwt)", re.IGNORECASE)
_ALLOWED_PARAMS = {"page", "q", "query", "offset", "limit", "expires", "lang", "sort"}
_TEXT_PATTERNS = [
    (re.compile(r"(?i)\b(bearer|basic)\s+[A-Za-z0-9._~+/=-]+"), r"\1 " + REDACTED),
    (re.compile(r"(?i)\b(cookie|set-cookie)\s*[:=]\s*(\"[^\"]*\"|'[^']*'|[^\s,]+)"), r"\1=" + REDACTED),
    (re.compile(r"(?i)\b(password|passwd|pwd|token|secret|session(?:id)?|api[_-]?key)\s*[:=]\s*[^\s&,;\"']+"),
     r"\1=" + REDACTED),
    (re.compile(r"(?i)\bsid=[^\s;,&\"']+"), "sid=" + REDACTED),
]


def redact_headers(headers: Mapping[str, str]) -> dict[str, str]:
    return {k: (REDACTED if k.lower() in SENSITIVE_HEADERS else v) for k, v in headers.items()}


def redact_url(url: str) -> str:
    try:
        parts = urlsplit(url)
    except ValueError:
        return REDACTED
    query = [(k, REDACTED if k.lower() not in _ALLOWED_PARAMS and _SENSITIVE_PARAM.search(k) else v)
             for k, v in parse_qsl(parts.query, keep_blank_values=True)]
    netloc = parts.hostname or ""
    if parts.port:
        netloc += f":{parts.port}"
    return urlunsplit((parts.scheme, netloc, parts.path, urlencode(query, safe="[]"), ""))


def redact_text(text: str) -> str:
    text = re.sub(r"https?://[^\s\"'<>]+", lambda m: redact_url(m.group(0)), text)
    for pattern, replacement in _TEXT_PATTERNS:
        text = pattern.sub(replacement, text)
    return text


def _redact_value(value):
    if isinstance(value, Mapping):
        return redact_headers({str(k): str(v) for k, v in value.items()})
    if isinstance(value, str):
        return redact_text(value)
    return value


class RedactingFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.msg = redact_text(str(record.msg))
        if isinstance(record.args, tuple):
            record.args = tuple(_redact_value(a) for a in record.args)
        elif isinstance(record.args, Mapping):
            record.args = {k: _redact_value(v) for k, v in record.args.items()}
        return True
