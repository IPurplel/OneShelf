"""Request URL templates: literal text plus {input} / {input:encoder}. No expressions, no attribute access."""
from __future__ import annotations

import re
from urllib.parse import quote

# `language` is the Language Track's language, supplied by the core (Master §4, §41.3).
ALLOWED_INPUTS = frozenset({"query", "page", "offset", "cursor", "listing_key", "unit_key", "url", "language"})
ENCODERS = {
    "url": lambda v: quote(str(v), safe=""),
    "path": lambda v: quote(str(v), safe=""),
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


def render(template: str, values: dict[str, object], *, base_url: str) -> str:
    def replace(match: re.Match) -> str:
        name, _, encoder = match.group(1).partition(":")
        if name == "base_url":
            return base_url.rstrip("/")
        if name not in values or values[name] is None:
            raise TemplateError(f"missing template input: {name!r}")
        return ENCODERS[encoder or "url"](values[name])

    sentinel_open, sentinel_close = "\x00OPEN\x00", "\x00CLOSE\x00"
    text = template.replace("{{", sentinel_open).replace("}}", sentinel_close)
    return _PLACEHOLDER.sub(replace, text).replace(sentinel_open, "{").replace(sentinel_close, "}")
