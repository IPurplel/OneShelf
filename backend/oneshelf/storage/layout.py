"""Human-readable managed layout: Family / Work / Language / Source / Files (Master §24.2).

Short stable OneShelf IDs are embedded so same-title Works and units never collide and files can be
recovered after manual moves. Metadata changes never rename existing files.
"""
from __future__ import annotations

import re

from oneshelf.storage.paths import safe_component

_SEQUENTIAL = {"manga", "manhwa", "manhua", "comic"}
_BOOKS = {"book", "novel", "paper"}
_EXTENSION = re.compile(r"^[a-z0-9]{1,8}$")


def family_for(content_type: str) -> str:
    if content_type in _SEQUENTIAL:
        return "Sequential Art"
    if content_type in _BOOKS:
        return "Books"
    return "Other"


def asset_relative_path(
    content_type: str,
    work_title: str,
    work_id: str,
    language: str,
    source_id: str,
    unit_label: str,
    unit_id: str,
    extension: str,
) -> str:
    if not _EXTENSION.match(extension):
        raise ValueError(f"invalid extension: {extension!r}")
    return "/".join(
        (
            family_for(content_type),
            f"{safe_component(work_title)} [{safe_component(work_id)}]",
            safe_component(language, max_bytes=35),
            safe_component(source_id, max_bytes=64),
            f"{safe_component(unit_label)} [{safe_component(unit_id)}].{extension}",
        )
    )
