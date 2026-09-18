"""Structural analysis for the Adapter Generator (Master §12.3).

Given a fetched page, find the repeated blocks a human would call "the results" or "the chapters", and
propose selectors for the fields a recipe needs. Everything here is heuristic and reported with its
evidence: the generator never claims a capability it has not actually exercised.
"""
from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass, field
from urllib.parse import urljoin, urlsplit

from lxml import html as lxml_html

# Class tokens that look generated (hashes, utility soup) make brittle selectors.
UNSTABLE = re.compile(r"(^|[-_])(\d{2,}|[0-9a-f]{6,}|css|jsx?|sc)([-_]|$)", re.IGNORECASE)
TITLE_HINTS = ("title", "name", "heading", "headline")
COVER_HINTS = ("cover", "thumb", "poster", "image")
TYPE_HINTS = ("type", "kind", "format", "category")
LANGUAGE_HINTS = ("lang", "language", "locale")
DATE_HINTS = ("date", "time", "published", "updated", "release")
NUMBER_HINTS = ("num", "number", "chapter", "episode", "ep", "vol")
CHAPTER_PATH = re.compile(r"/(chapter|chapters|ch|episode|ep|read|unit|part|volume)[/-]", re.IGNORECASE)
IMAGE_SUFFIX = re.compile(r"\.(png|jpe?g|webp|gif|avif)(\?|$)", re.IGNORECASE)


@dataclass(frozen=True)
class FieldGuess:
    css: str | None = None
    json: str | None = None
    sample: str | None = None
    hint: str | None = None


@dataclass
class Repeated:
    selector: str
    elements: list = field(default_factory=list)

    @property
    def count(self) -> int:
        return len(self.elements)


def parse(text: str):
    return lxml_html.fromstring(text)


def classes(element) -> list[str]:
    return [c for c in (element.get("class") or "").split() if c and not UNSTABLE.search(c)]


def _signature(element) -> tuple:
    return element.tag, tuple(sorted(classes(element))[:2])


def _selector_for(element, *, with_class: bool = True) -> str:
    tokens = classes(element)
    return f"{element.tag}.{tokens[0]}" if with_class and tokens else element.tag


def repeated_blocks(tree, *, min_items: int = 2) -> list[Repeated]:
    """Sibling groups that share a tag and class and each contain a link — a list of things."""
    groups: dict[tuple, list] = defaultdict(list)
    for parent in tree.iter():
        for child in parent:
            if isinstance(child.tag, str):
                groups[(id(parent), _signature(child))].append(child)
    found = []
    for (_parent_id, signature), elements in groups.items():
        if len(elements) < min_items or not signature[1]:
            continue
        if not all(el.xpath(".//a[@href]") for el in elements):
            continue
        found.append(Repeated(_selector_for(elements[0]), elements))
    found.sort(key=lambda r: (r.count, len(r.selector)), reverse=True)
    return found


def _relative(item, element, *, attribute: str | None = None) -> str:
    """A short selector for `element` as seen from its repeated `item`."""
    selector = _selector_for(element)
    if selector == element.tag:                      # no stable class: qualify by the nearest classed parent
        parent = element.getparent()
        if parent is not None and parent is not item and classes(parent):
            selector = f"{_selector_for(parent)} {element.tag}"
    return f"{selector}::attr({attribute})" if attribute else f"{selector}::text"


def _hinted(element, hints: tuple[str, ...]) -> bool:
    haystack = " ".join(classes(element) + [element.get("id") or "", element.get("itemprop") or ""]).lower()
    return any(hint in haystack for hint in hints)


def _main_link(item):
    links = [a for a in item.xpath(".//a[@href]") if (a.text_content() or "").strip()]
    if not links:
        return None
    hinted = [a for a in links if _hinted(a, TITLE_HINTS)]
    pool = hinted or links
    return max(pool, key=lambda a: len((a.text_content() or "").strip()))


def item_fields(items: list, *, base_url: str, unit_key: bool = False) -> dict[str, FieldGuess]:
    """Field guesses shared by every item in a repeated block."""
    guesses: dict[str, FieldGuess] = {}
    sample = items[0]
    link = _main_link(sample)
    if link is not None:
        guesses["title"] = FieldGuess(css=_relative(sample, link), sample=(link.text_content() or "").strip())
        guesses["url"] = FieldGuess(css=_relative(sample, link, attribute="href"),
                                    sample=urljoin(base_url, link.get("href")))
        key = "unit_key" if unit_key else "listing_key"
        guesses[key] = FieldGuess(css=guesses["url"].css, sample=guesses["url"].sample, hint="from the item URL")
    images = sample.xpath(".//img[@src]")
    for image in images:
        if _hinted(image, COVER_HINTS) or len(images) == 1:
            guesses["cover_url"] = FieldGuess(css=_relative(sample, image, attribute="src"),
                                              sample=urljoin(base_url, image.get("src")))
            break
    for element in sample.iter():
        if element is sample or not isinstance(element.tag, str):
            continue
        text = (element.text_content() or "").strip()
        if element.tag == "time" and element.get("datetime"):
            guesses.setdefault("published_at", FieldGuess(css=_relative(sample, element, attribute="datetime"),
                                                          sample=element.get("datetime")))
            continue
        if not text or element.xpath(".//a[@href]"):
            continue
        for name, hints in (("content_type", TYPE_HINTS), ("language", LANGUAGE_HINTS),
                            ("published_at", DATE_HINTS), ("number", NUMBER_HINTS)):
            if name not in guesses and _hinted(element, hints):
                guesses[name] = FieldGuess(css=_relative(sample, element), sample=text)
                break
    return guesses


def page_fields(tree, *, base_url: str) -> dict[str, FieldGuess]:
    """Fields for a single work page: title, cover and whatever metadata is labelled."""
    guesses: dict[str, FieldGuess] = {}
    for heading in tree.xpath("//h1|//h2"):
        text = (heading.text_content() or "").strip()
        if text:
            guesses["title"] = FieldGuess(css=_relative(tree, heading), sample=text)
            break
    if "title" not in guesses:
        meta = tree.xpath("//meta[@property='og:title']/@content")
        if meta:
            guesses["title"] = FieldGuess(css="meta[property='og:title']::attr(content)", sample=meta[0])
    cover = tree.xpath("//meta[@property='og:image']/@content")
    if cover:
        guesses["cover_url"] = FieldGuess(css="meta[property='og:image']::attr(content)",
                                          sample=urljoin(base_url, cover[0]))
    for element in tree.iter():
        if not isinstance(element.tag, str) or element.tag in ("script", "style"):
            continue
        text = (element.text_content() or "").strip()
        if not text or len(text) > 120 or len(element) > 0:
            continue
        for name, hints in (("content_type", TYPE_HINTS), ("language", LANGUAGE_HINTS),
                            ("published_at", DATE_HINTS)):
            if name not in guesses and _hinted(element, hints):
                guesses[name] = FieldGuess(css=_relative(tree, element), sample=text)
                break
    return guesses


def chapter_blocks(tree, *, base_url: str) -> Repeated | None:
    """Repeated blocks whose links look like reading units rather than navigation."""
    best = None
    host = urlsplit(base_url).netloc
    for block in repeated_blocks(tree):
        links = [a.get("href") for el in block.elements for a in el.xpath(".//a[@href]")]
        if not links:
            continue
        internal = [urljoin(base_url, href) for href in links]
        if any(urlsplit(url).netloc not in ("", host) for url in internal):
            continue
        looks_like_units = sum(bool(CHAPTER_PATH.search(url)) for url in internal)
        if looks_like_units >= max(2, len(internal) // 2) and (best is None or block.count > best.count):
            best = block
    return best


def image_group(tree, *, base_url: str) -> tuple[str | None, list[str]]:
    """The page images of a reader view: several images sharing a directory, not icons."""
    groups: dict[str, list] = defaultdict(list)
    for image in tree.xpath("//img[@src]"):
        url = urljoin(base_url, image.get("src"))
        if not IMAGE_SUFFIX.search(url):
            continue
        prefix = url.rsplit("/", 1)[0]
        groups[prefix].append((image, url))
    if not groups:
        return None, []
    _prefix, members = max(groups.items(), key=lambda kv: len(kv[1]))
    if len(members) < 2:
        return None, []
    element = members[0][0]
    return f"{_selector_for(element)}::attr(src)", [url for _element, url in members]


def looks_javascript_driven(tree, *, expected_content: bool = True) -> bool:
    """A near-empty body next to scripts that build it is a JavaScript page, not a broken selector."""
    body = tree.xpath("//body")
    if not body:
        return False
    # Script bodies are code, not content: measure only the text a reader would see.
    visible = body[0].xpath(".//text()[not(ancestor::script) and not(ancestor::style)]")
    text = " ".join(t.strip() for t in visible if t.strip())
    scripts = tree.xpath("//script")
    links = tree.xpath("//body//a[@href]")
    return expected_content and len(text) < 40 and not links and bool(scripts)


def asset_hosts(urls: list[str]) -> list[str]:
    hosts = []
    for url in urls:
        host = urlsplit(url).netloc.split("@")[-1].split(":")[0].lower()
        if host and host not in hosts:
            hosts.append(host)
    return hosts
