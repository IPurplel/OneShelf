"""Request URL templates: literal text plus {input} / {input:encoder}. No expressions, no attribute access.

Encoders: url and path (the whole value as one percent-encoded component), segments (a relative path whose
"/" are kept, plugin API 1.2), absolute (a whole http(s) URL the source gave).
"""
from __future__ import annotations

import re
from urllib.parse import quote, urlsplit

# `language` is the Language Track's language, supplied by the core (Master §4, §41.3).
ALLOWED_INPUTS = frozenset({"query", "page", "offset", "cursor", "listing_key", "unit_key", "url", "language"})
def _absolute(value: object) -> str:
    """A URL the source itself gave us, inserted as it stands.

    Percent-encoding a whole URL turns it into a path segment, so a recipe that must request an address
    it was handed — a viewer page the catalog captured — asks for this explicitly. It is not a way in:
    only plain http(s) with a host is accepted, credentials and control characters are refused outright,
    and the egress policy still decides whether the host may be reached at all (§12.1, K2).
    """
    text = str(value)
    if len(text) > MAX_TEMPLATE or any(c in text for c in "\r\n\t ") or any(ord(c) < 0x20 for c in text):
        raise TemplateError("absolute URL contains whitespace or control characters")
    parsed = urlsplit(text)
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        raise TemplateError(f"not an absolute http(s) URL: {text[:64]!r}")
    if parsed.username or parsed.password or "@" in parsed.netloc:
        raise TemplateError("credentials are not allowed in a recipe URL")
    return text


def _segments(value: object) -> str:
    """A key that is itself a short path ("00500/00597", "work/chapter"): each segment is percent-encoded
    and the "/" between segments is kept. An empty, "." or ".." segment is refused, so a key can never
    climb out of the path the recipe puts it in, and a leading or trailing "/" is refused with it."""
    text = str(value)
    parts = text.split("/")
    if len(text) > MAX_TEMPLATE or any(p in ("", ".", "..") for p in parts):
        raise TemplateError(f"not a relative path of segments: {text[:64]!r}")
    return "/".join(quote(part, safe="") for part in parts)


ENCODERS = {
    "url": lambda v: quote(str(v), safe=""),
    "path": lambda v: quote(str(v), safe=""),
    "segments": _segments,
    "absolute": _absolute,
}
_PLACEHOLDER = re.compile(r"\{([^{}]*)\}")
_NAME = re.compile(r"^[a-z_][a-z0-9_]*$")
MAX_TEMPLATE = 1024


class TemplateError(ValueError):
    pass


def placeholders(template: str) -> list[tuple[str, str]]:
    if len(template) > MAX_TEMPLATE:
        raise TemplateError("template too long")
    stripped = template.replace("{{", "").replace("}}", "")
    found = []
    for match in _PLACEHOLDER.finditer(stripped):
        name, _, encoder = match.group(1).partition(":")
        encoder = encoder or "url"
        if not _NAME.match(name) or encoder not in ENCODERS:
            raise TemplateError(f"invalid placeholder {{{match.group(1)}}}")
        found.append((name, encoder))
    if "{" in _PLACEHOLDER.sub("", stripped) or "}" in _PLACEHOLDER.sub("", stripped):
        raise TemplateError("unbalanced braces in template")
    return found


def validate_url_template(template: str, declared_inputs: set[str]) -> None:
    items = placeholders(template)
    for name, _encoder in items:
        if name == "base_url":
            continue
        if name not in ALLOWED_INPUTS or name not in declared_inputs:
            raise TemplateError(f"undeclared template input: {name!r}")
    # A recipe may follow a URL the source itself produced (a unit's canonical page, §8). It must be the
    # whole template — nothing may be appended to it — and the egress policy still gates the fetch.
    if len(items) == 1 and items[0][0] == "url" and re.fullmatch(r"\{url(?::[a-z]+)?\}", template):
        return
    if template.startswith("{base_url}"):
        if any(name == "base_url" for name, _ in items[1:]):
            raise TemplateError("base_url may only appear at the start")
        return
    if any(name == "base_url" for name, _ in items):
        raise TemplateError("base_url may only appear at the start")
    if not re.match(r"^https?://[^{}/?#]+(?:[/?#]|$)", template):
        raise TemplateError("template must start with {base_url} or a literal http(s) origin")


def render(template: str, values: dict[str, object], *, base_url: str, form_value: bool = False) -> str:
    """Fill a template. In a URL a bare {name} is percent-encoded (the url encoder). In a form value it is
    inserted as it is, because the HTTP client form-encodes the whole body — encoding it here as well sent
    "Egri%2520csillagok" for "Egri csillagok". An explicit encoder ({name:url}) is honoured in both."""
    def replace(match: re.Match) -> str:
        name, _, encoder = match.group(1).partition(":")
        if name == "base_url":
            return base_url.rstrip("/")
        if name not in values or values[name] is None:
            raise TemplateError(f"missing template input: {name!r}")
        if form_value and not encoder:
            return str(values[name])
        return ENCODERS[encoder or "url"](values[name])

    sentinel_open, sentinel_close = "\x00OPEN\x00", "\x00CLOSE\x00"
    text = template.replace("{{", sentinel_open).replace("}}", sentinel_close)
    return _PLACEHOLDER.sub(replace, text).replace(sentinel_open, "{").replace(sentinel_close, "}")
