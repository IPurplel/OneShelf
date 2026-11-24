"""Discover API: the browsable sources, one page of a source's list, and the two surprises (the shelf one by mood)."""
from __future__ import annotations

from dataclasses import asdict

from fastapi import APIRouter, Query, Request

from oneshelf.api.discovery import _cover_previewer, _download_checker, _result
from oneshelf.api.shelf import _entry
from oneshelf.api.sources import error, services, source_failed
from oneshelf.discovery.discover import FEEDS, MAX_PAGE, FeedUnavailable, UnknownSource
from oneshelf.plugins.runtime import RateLimited

router = APIRouter(prefix="/api/discover")


def _items(request: Request, items) -> list[dict]:
    s = services(request)
    can_preview = _cover_previewer(s.plugins)
    can_download = _download_checker(s.source_service)
    on_shelf = s.discover.shelf_ids()
    return [{**_result(item, can_preview, can_download), "on_shelf": item.work_id in on_shelf} for item in items]


@router.get("/sources")
async def discover_sources(request: Request):
    return {"sources": [asdict(source) for source in services(request).discover.browsable()]}


@router.get("/list")
async def discover_list(request: Request, source: str = Query(min_length=1, max_length=64),
                        kind: str = "latest", page: int = 1):
    if kind not in FEEDS or not 1 <= page <= MAX_PAGE:
        return error(422, "INVALID_FEED", "Choose Latest or Popular, and a page from 1 to 50.")
    try:
        found = await services(request).discover.feed(source, kind, page)
    except UnknownSource:
        return error(404, "SOURCE_UNAVAILABLE", "No active source by that id offers browsing.")
    except ValueError:
        return error(422, "INVALID_FEED", "This source does not offer that list.")
    except RateLimited:
        return error(429, "RATE_LIMITED", "The source asked OneShelf to slow down. Try again in a moment.")
    except FeedUnavailable as exc:
        return source_failed(exc)
    return {"source_id": found.source_id, "kind": found.kind, "page": found.page, "has_more": found.has_more,
            "cached": found.cached, "items": _items(request, found.items)}


@router.get("/random")
async def discover_random(request: Request, from_: str = Query("sources", alias="from"),
                          source: str | None = None, content_type: str | None = None,
                          mood: str = Query("fresh", max_length=16),
                          exclude: str = Query("", max_length=2000)):
    s = services(request)
    if from_ == "library":
        try:
            picked = s.discover.suggest_from_shelf(mood, content_type, {w for w in exclude.split(",") if w})
        except ValueError:
            return error(422, "INVALID_FEED", "Choose a mood: continue, short, light or fresh.")
        entry = s.shelf.get(picked["work_id"]) if picked else None
        if entry is None:
            return {"item": None, "reason": None, "more": False}
        return {"item": _entry(entry), "reason": picked["reason"], "more": picked["more"]}
    if from_ != "sources":
        return error(422, "INVALID_FEED", "Choose a surprise from your sources or from your shelf.")
    try:
        picked = await s.discover.surprise_from_sources(source)
    except UnknownSource:
        return error(404, "SOURCE_UNAVAILABLE", "No active source by that id offers browsing.")
    if picked is None:
        return {"item": None, "reason": None}
    item, origin, kind = picked
    return {"item": _items(request, [item])[0],
            "reason": {"source_id": origin.source_id, "source_name": origin.name, "kind": kind}}
