"""Domain types shared between adapters, the queue, and the API layer."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

# Illegal on Windows/SMB shares, which is where output very often lands.
_UNSAFE = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
_WINDOWS_RESERVED = {
    "CON", "PRN", "AUX", "NUL",
    *(f"COM{i}" for i in range(1, 10)),
    *(f"LPT{i}" for i in range(1, 10)),
}


def sanitize_filename(name: str, fallback: str = "untitled") -> str:
    """Make ``name`` safe for use as a single path component."""
    cleaned = _UNSAFE.sub("_", name).strip().strip(".")
    cleaned = re.sub(r"\s+", " ", cleaned)
    if cleaned.upper() in _WINDOWS_RESERVED:
        cleaned = f"_{cleaned}"
    return cleaned[:150] or fallback


class ChapterStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    DONE = "done"
    FAILED = "failed"
    CANCELLED = "cancelled"


class JobStatus(str, Enum):
    QUEUED = "queued"
    RUNNING = "running"
    PAUSED = "paused"
    DONE = "done"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass(slots=True)
class Series:
    url: str
    title: str
    source: str
    """Adapter id that produced this record, e.g. ``madara``."""
    cover_url: str | None = None
    author: str | None = None
    description: str | None = None
    site_id: str | None = None
    """Site-internal post id, when the adapter could determine one."""

    @property
    def folder_name(self) -> str:
        return sanitize_filename(self.title)

    def to_dict(self) -> dict[str, Any]:
        return {
            "url": self.url,
            "title": self.title,
            "source": self.source,
            "cover_url": self.cover_url,
            "author": self.author,
            "description": self.description,
        }


@dataclass(slots=True)
class Chapter:
    url: str
    title: str
    number: str | None = None
    """Chapter number as text (``"12"``, ``"12.5"``) — kept as a string because
    sites are wildly inconsistent and some use non-numeric labels."""
    index: int = 0
    """Position in the series, ascending. Authoritative ordering when ``number``
    is missing or unparseable."""
    date: str | None = None

    @property
    def sort_key(self) -> tuple[float, int]:
        return (parse_chapter_number(self.number) or float(self.index), self.index)

    def filename(self, series_title: str) -> str:
        label = format_chapter_number(self.number, self.index)
        return f"{sanitize_filename(series_title)} - c{label}.cbz"

    def to_dict(self) -> dict[str, Any]:
        return {
            "url": self.url,
            "title": self.title,
            "number": self.number,
            "index": self.index,
            "date": self.date,
        }


@dataclass(slots=True)
class SearchResult:
    """One hit from a site's own search, ready for the picker."""

    title: str
    url: str
    source: str
    """Adapter id that produced it."""
    site: str
    """Hostname, so a result list spanning several sites stays legible."""
    cover_url: str | None = None
    alt_title: str | None = None
    """The alternative title the query actually matched, when it is not the one
    being shown.

    A site that indexes every translation of a name will answer an Arabic query
    with a series whose displayed title is romanised. Without saying which name
    matched, a correct hit is indistinguishable from noise."""
    author: str | None = None
    """Who wrote it, when the search response says.

    Carried separately rather than folded into the title, because it is both
    scored (searching an author's name should find their books) and shown. The
    Gutenberg adapter used to append it to ``title`` to fake the first of
    those, which made every displayed title wrong to buy it."""

    def to_dict(self) -> dict[str, Any]:
        return {
            "title": self.title,
            "url": self.url,
            "source": self.source,
            "site": self.site,
            "cover_url": self.cover_url,
            "alt_title": self.alt_title,
            "author": self.author,
        }


@dataclass(slots=True)
class TextBlock:
    """One paragraph or heading of a prose chapter.

    Prose sources are not pages of pixels, so nothing downstream can treat them
    as images. Keeping the block *kind* alongside its text is what preserves a
    chapter's shape: a scene-break heading has to stay a heading, and the run of
    paragraphs between two headings has to stay in the order the site served it.
    """

    kind: str
    """``"p"`` for a paragraph, ``"h1"``-``"h6"`` for a heading."""
    text: str

    def __post_init__(self) -> None:
        if self.kind not in TEXT_BLOCK_KINDS:
            raise ValueError(f"unknown text block kind: {self.kind!r}")


#: The block kinds an adapter may emit. A closed set, because the packager
#: turns each one straight into an XHTML element name.
TEXT_BLOCK_KINDS = frozenset({"p", "h1", "h2", "h3", "h4", "h5", "h6"})


@dataclass(slots=True)
class TextChapter:
    """A prose chapter as the reader served it.

    ``blocks`` is already in reading order — the adapter is the only thing that
    knows the site's DOM, so ordering is settled there rather than guessed at
    packaging time.
    """

    title: str
    blocks: list[TextBlock]
    language: str | None = None
    """BCP-47 tag when the source states one, e.g. ``"ar"``. ``None`` defers to
    the global ``language`` setting."""

    @property
    def characters(self) -> int:
        return sum(len(block.text) for block in self.blocks)


@dataclass(slots=True)
class Page:
    index: int
    url: str
    referer: str | None = None
    """Some CDNs hotlink-protect images; the chapter URL is sent as Referer."""


@dataclass(slots=True)
class ChapterProgress:
    chapter_url: str
    title: str
    status: ChapterStatus = ChapterStatus.PENDING
    pages_done: int = 0
    pages_total: int = 0
    error: str | None = None
    output_path: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "chapter_url": self.chapter_url,
            "title": self.title,
            "status": self.status.value,
            "pages_done": self.pages_done,
            "pages_total": self.pages_total,
            "error": self.error,
            "output_path": self.output_path,
        }


@dataclass(slots=True)
class Job:
    id: int
    series: Series
    chapters: list[Chapter]
    status: JobStatus = JobStatus.QUEUED
    progress: dict[str, ChapterProgress] = field(default_factory=dict)
    error: str | None = None

    def summary(self) -> dict[str, Any]:
        counts: dict[str, int] = {}
        for item in self.progress.values():
            counts[item.status.value] = counts.get(item.status.value, 0) + 1
        return {
            "id": self.id,
            "status": self.status.value,
            "series": self.series.to_dict(),
            "total": len(self.chapters),
            "counts": counts,
            "error": self.error,
        }


_NUMBER_RE = re.compile(r"(\d+(?:\.\d+)?)")


def parse_chapter_number(raw: str | None) -> float | None:
    """Extract a numeric chapter value from a label such as ``"الفصل 12.5"``."""
    if not raw:
        return None
    match = _NUMBER_RE.search(raw)
    if not match:
        return None
    try:
        return float(match.group(1))
    except ValueError:
        return None


def format_chapter_number(raw: str | None, index: int) -> str:
    """Zero-padded chapter label so filenames sort lexically.

    Decimal chapters keep their fraction (``008.5``); everything else is padded
    to three digits, which covers long-running series without re-sorting later.
    """
    value = parse_chapter_number(raw)
    if value is None:
        return f"{index:03d}"
    if value.is_integer():
        return f"{int(value):03d}"
    whole, _, frac = f"{value:.10g}".partition(".")
    return f"{int(whole):03d}.{frac}"
