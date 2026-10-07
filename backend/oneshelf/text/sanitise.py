"""Sanitising source HTML for text reading units (Master §27; architecture review C, 2026-09-30).

Remote markup is reduced to an allowlist on the server before it is returned or stored, so nothing
unsanitised is ever persisted or reaches the app origin. The allowlist mirrors the Book Reader's EPUB
sanitiser (frontend/src/features/reader/epub.ts): text structure only, no scripts, no embeds, no forms,
no styles, no event handlers, and links only to http, https and mailto. Version 1 is text-only: an
image is replaced by its alt text, because a text unit has no stored assets yet.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from urllib.parse import urljoin, urlsplit

import nh3
from lxml import etree, html as lxml_html

MAX_TEXT_UNIT_BYTES = 1024 * 1024
SECTION_TARGET_CHARS = 16_000

TAGS = {
    "a", "abbr", "article", "aside", "b", "bdi", "bdo", "blockquote", "br", "caption", "center", "cite", "code",
    "col", "colgroup", "dd", "del", "details", "dfn", "div", "dl", "dt", "em", "figcaption", "figure", "footer",
    "h1", "h2", "h3", "h4", "h5", "h6", "header", "hgroup", "hr", "i", "ins", "kbd", "li", "mark", "ol", "p",
    "pre", "q", "rp", "rt", "rtc", "ruby", "s", "samp", "section", "small", "span", "strike", "strong", "sub",
    "summary", "sup", "table", "tbody", "td", "tfoot", "th", "thead", "time", "tr", "tt", "u", "ul", "var", "wbr",
}
# Elements whose content is dropped with them, not kept as text.
CLEAN_CONTENT_TAGS = {"script", "style", "noscript", "iframe", "frame", "frameset", "object", "embed", "svg", "math",
                      "template", "form", "select", "textarea", "button", "title", "head"}
GENERIC_ATTRIBUTES = {"dir", "lang", "title"}
ATTRIBUTES = {
    "*": GENERIC_ATTRIBUTES,
    "a": {"href"},
    "td": {"colspan", "rowspan"},
    "th": {"colspan", "rowspan", "scope"},
    "ol": {"start", "reversed"},
    "li": {"value"},
    "time": {"datetime"},
    "bdo": {"dir"},
}
URL_SCHEMES = {"http", "https", "mailto"}
_BLOCKS = {"p", "div", "section", "article", "blockquote", "pre", "ul", "ol", "dl", "table", "figure", "hr",
           "h1", "h2", "h3", "h4", "h5", "h6", "header", "footer", "aside", "details"}
_HEADINGS = {"h1", "h2", "h3", "h4", "h5", "h6"}
_WHITESPACE = re.compile(r"\s+")


class TextUnitTooLarge(ValueError):
    pass


def _images_to_alt(markup: str) -> str:
    """Version 1 keeps no images: each <img> becomes its alt text so no words are lost."""
    if "<img" not in markup.lower():
        return markup
    root = lxml_html.fragment_fromstring(markup, create_parent="div")
    for image in root.iter("img"):
        alt = (image.get("alt") or "").strip()
        parent = image.getparent()
        tail = (f" {alt} " if alt else "") + (image.tail or "")
        previous = image.getprevious()
        if previous is not None:
            previous.tail = (previous.tail or "") + tail
        else:
            parent.text = (parent.text or "") + tail
        parent.remove(image)
    return "".join(
        [root.text or ""] + [etree.tostring(child, encoding="unicode", method="html") for child in root]
    )


def _link_filter(base_url: str | None):
    """Links survive only as absolute http, https or mailto URLs; a relative link is resolved against
    the page it came from when that is known, and dropped otherwise (it would point into the app)."""
    def keep(tag: str, attribute: str, value: str) -> str | None:
        if tag != "a" or attribute != "href":
            return value
        target = urljoin(base_url, value.strip()) if base_url else value.strip()
        return target if urlsplit(target).scheme.lower() in URL_SCHEMES else None
    return keep


def sanitise(markup: str, *, base_url: str | None = None) -> str:
    """The allowlisted form of source markup. Idempotent: sanitise(sanitise(x)) == sanitise(x)."""
    if len(markup.encode("utf-8")) > MAX_TEXT_UNIT_BYTES:
        raise TextUnitTooLarge(f"text unit is larger than {MAX_TEXT_UNIT_BYTES} bytes")
    cleaned = nh3.clean(
        _images_to_alt(markup),
        tags=TAGS,
        clean_content_tags=CLEAN_CONTENT_TAGS,
        attributes=ATTRIBUTES,
        url_schemes=URL_SCHEMES,
        attribute_filter=_link_filter(base_url),
        link_rel="noopener noreferrer",
        strip_comments=True,
    )
    return cleaned.strip()


def plain_text(markup: str) -> str:
    """Whitespace-collapsed text of sanitised markup, as the reader counts and searches it."""
    if not markup.strip():
        return ""
    root = lxml_html.fragment_fromstring(markup, create_parent="div")
    return _WHITESPACE.sub(" ", root.text_content()).strip()


@dataclass(frozen=True)
class Section:
    html: str
    title: str | None
    characters: int


def _heading(element) -> str | None:
    for candidate in element.iter("h1", "h2", "h3", "h4", "h5", "h6"):
        text = _WHITESPACE.sub(" ", candidate.text_content()).strip()
        if text:
            return text
    return None


def split_sections(markup: str, *, target_chars: int = SECTION_TARGET_CHARS) -> list[Section]:
    """Split sanitised markup at top-level block boundaries into sections of about target_chars.

    The reader frame is sandboxed with an opaque origin, so it cannot report a scroll position;
    sections are what give progress, bookmarks and search their granularity.
    """
    if not markup.strip():
        return []
    root = lxml_html.fragment_fromstring(markup, create_parent="div")
    pieces: list[tuple[str, str | None, int, bool]] = []  # (markup, heading, characters, is a heading)
    if root.text and root.text.strip():
        pieces.append((root.text, None, len(_WHITESPACE.sub(" ", root.text).strip()), False))
    for child in root:
        serialized = etree.tostring(child, encoding="unicode", method="html", with_tail=True)
        text = _WHITESPACE.sub(" ", child.text_content() + (child.tail or "")).strip()
        is_heading = child.tag in _HEADINGS
        heading = text if is_heading else _heading(child) if child.tag in _BLOCKS else None
        pieces.append((serialized, heading or None, len(text), is_heading))
    sections: list[Section] = []
    buffer: list[tuple[str, str | None, int, bool]] = []
    for piece in pieces:
        size = sum(p[2] for p in buffer)
        if buffer and size + piece[2] > target_chars:
            # A heading belongs with what follows it, never at the end of the section before.
            carried = []
            while buffer and buffer[-1][3]:
                carried.insert(0, buffer.pop())
            if buffer:
                sections.append(_section(buffer))
            buffer = carried
        buffer.append(piece)
    if buffer:
        sections.append(_section(buffer))
    return [s for s in sections if s.html]


def _section(buffer: list[tuple[str, str | None, int, bool]]) -> Section:
    html = sanitise("".join(piece[0] for piece in buffer))
    title = next((piece[1] for piece in buffer if piece[1]), None)
    return Section(html=html, title=title, characters=len(plain_text(html)))


MAX_UNIT_BYTES = 8 * MAX_TEXT_UNIT_BYTES


def unit_sections(items: list[tuple[str | None, str | None]]) -> list[Section]:
    """The sections of one text reading unit from its reader items, as (html, title) pairs.

    A reader result is one unit however many items it has (a chapter that arrives verse by verse is
    still one chapter): every item is sanitised under the per-item cap, the parts are joined in order,
    and the whole is split into sections once. The first title names the first section when it has
    no heading of its own.
    """
    joined = "".join(sanitise(html) for html, _ in items if html)
    if len(joined.encode("utf-8")) > MAX_UNIT_BYTES:
        raise TextUnitTooLarge(f"text unit is larger than {MAX_UNIT_BYTES} bytes")
    sections = split_sections(joined)
    title = next((t for _, t in items if t), None)
    if sections and title and sections[0].title is None:
        sections[0] = Section(sections[0].html, title, sections[0].characters)
    return sections
