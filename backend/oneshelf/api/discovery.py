"""Discovery API: search (streamed), direct URL entry, Home sections, catalog trust and mappings."""
from __future__ import annotations

import json
from dataclasses import asdict
from typing import Literal

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from oneshelf.api.sources import error, services
from oneshelf.catalog.trust import TrustRejected
from oneshelf.plugins.manager import PluginUnavailable
from oneshelf.plugins.runtime import AuthRequired, CapabilityError, RateLimited
from oneshelf.search.grouping import LiveListing, persist_listing
from oneshelf.search.mapping import MappingError, MappingService
from oneshelf.search.url_resolve import UnsupportedUrl

router = APIRouter(prefix="/api")


def _result(result) -> dict:
    return {"work_id": result.work_id, "title": result.title, "content_type": result.content_type,
            "soft": result.soft, "availability": result.availability,
            "provenance": [asdict(p) for p in result.provenance]}


def _update(update) -> dict:
    return {"stage": update.stage, "results": [_result(r) for r in update.results],
            "source_status": update.source_status, "sources_total": update.sources_total,
            "sources_done": update.sources_done, "sources_failed": update.sources_failed}


def _sse(payload: dict) -> str:
    return f"event: {payload['stage']}\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"


@router.get("/search")
async def search(request: Request, q: str, refresh: bool = False):
    """Local-first results stream in immediately; live sources enrich them progressively (§6.1)."""
    service = services(request).search

    async def stream():
        async for update in service.search(q, refresh=refresh):
            yield _sse(_update(update))

    return StreamingResponse(stream(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"})


class RetryBody(BaseModel):
    query: str = Field(min_length=1, max_length=500)
    source_id: str = Field(min_length=1, max_length=64)


@router.post("/search/retry")
async def retry_source(request: Request, body: RetryBody):
    service = services(request).search
    last = None
    async for update in service.retry_source(body.query, body.source_id):
        last = update
    return _update(last)


class UrlBody(BaseModel):
    url: str = Field(min_length=1, max_length=2048)


@router.post("/resolve-url")
async def resolve_url(request: Request, body: UrlBody):
    s = services(request)
    try:
        preview = await s.url_resolver.preview(body.url)
    except UnsupportedUrl as exc:
        return error(422, "UNSUPPORTED_URL", str(exc))
    except AuthRequired:
        return error(409, "SESSION_REQUIRED", "This source needs a connected account for that page.")
    except RateLimited as exc:
        return error(429, "RATE_LIMITED", f"The source is rate limited (retry after {exc.retry_after}s).")
    except CapabilityError as exc:
        return error(502, "SOURCE_FAILED", f"{exc.category}: {exc}")
    return {"source_id": preview.resolved.plugin_id, "capability": preview.resolved.capability,
            "identifier": preview.resolved.identifier, "result": _result(preview.result),
            "details": asdict(preview.details) if preview.details else None}


@router.get("/home")
async def home(request: Request):
    s = services(request)
    sections = await s.home.sections()
    hero = await s.home.hero()
    return {"hero": asdict(hero) if hero else None,
            "continue_reading": [asdict(i) for i in sections.continue_reading],
            "trending": [_result(r) for r in sections.trending],
            "latest": [_result(r) for r in sections.latest],
            "recently_added": [asdict(i) for i in sections.recently_added]}


class BindBody(BaseModel):
    source_id: str = Field(min_length=1, max_length=64)
    listing_key: str = Field(min_length=1, max_length=512)
    title: str = Field(min_length=1, max_length=500)
    url: str | None = Field(default=None, max_length=2048)
    language: str | None = Field(default=None, max_length=35)
    content_type: str | None = Field(default=None, max_length=32)
    work_id: str | None = Field(default=None, max_length=64)
    decided_by: Literal["user", "evidence"] = "user"


@router.post("/listings/bind")
async def bind_listing(request: Request, body: BindBody):
    """Durable actions (Shelf, Follow, Download) bind a concrete listing and track (INV-03)."""
    s = services(request)
    listing = LiveListing(source_id=body.source_id, listing_key=body.listing_key, title=body.title, url=body.url,
                          content_type=body.content_type, language=body.language)
    work_id = body.work_id
    if work_id is None:
        existing = s.conn.execute("SELECT work_id FROM source_listings WHERE source_id = ? AND source_listing_key = ?",
                                  (body.source_id, body.listing_key)).fetchone()
        work_id = existing["work_id"] if existing is not None else None
    if work_id is None:  # a listing nobody has bound yet becomes its own Work
        from oneshelf.domain.clock import utcnow_iso
        from oneshelf.domain.ids import new_id
        from oneshelf.db.connection import transaction
        from oneshelf.search.index import index_work

        work_id = new_id()
        now = utcnow_iso()
        with transaction(s.conn):
            s.conn.execute("INSERT INTO works (id, display_title, content_type, content_type_source, created_at,"
                           " updated_at) VALUES (?,?,?,?,?,?)",
                           (work_id, body.title, body.content_type or "unknown",
                            "source" if body.content_type else "unknown", now, now))
        index_work(s.conn, work_id)
    binding = persist_listing(s.conn, listing, work_id=work_id, decided_by=body.decided_by)
    return {"listing_id": binding.listing_id, "work_id": binding.work_id, "track_id": binding.track_id}


@router.get("/tracks/{track_id}/catalog")
async def catalog_state(request: Request, track_id: str):
    s = services(request)
    trusted = s.catalog.trusted_catalog(track_id)
    candidate = s.catalog.suspicious_candidate(track_id)
    previous = s.catalog.previous_catalog(track_id)
    return {"track_id": track_id,
            "trusted": {"snapshot_id": trusted.snapshot_id, "unit_count": trusted.unit_count,
                        "fetched_at": trusted.fetched_at} if trusted else None,
            "previous": {"snapshot_id": previous.snapshot_id, "unit_count": previous.unit_count} if previous else None,
            "suspicious": {"snapshot_id": candidate.snapshot_id, "unit_count": candidate.unit_count} if candidate else None}


@router.post("/tracks/{track_id}/catalog/refresh")
async def refresh_catalog(request: Request, track_id: str):
    s = services(request)
    row = s.conn.execute(
        "SELECT t.source_id, l.source_listing_key FROM source_tracks t LEFT JOIN source_listings l ON l.id = t.listing_id"
        " WHERE t.id = ?", (track_id,)).fetchone()
    if row is None:
        return error(404, "TRACK_NOT_FOUND", "Unknown source track.")
    if row["source_listing_key"] is None:
        return error(409, "NO_LISTING", "This track has no source listing to refresh.")
    try:
        package = s.plugins.load_active(row["source_id"])
        result = await s.source_service.run(row["source_id"], "catalog", {"listing_key": row["source_listing_key"]})
    except PluginUnavailable as exc:
        return error(409, "SOURCE_UNAVAILABLE", str(exc))
    except AuthRequired:
        return error(409, "SESSION_REQUIRED", "This source needs a connected account.")
    except RateLimited as exc:
        return error(429, "RATE_LIMITED", f"The source is rate limited (retry after {exc.retry_after}s).")
    except CapabilityError as exc:
        return error(502, "SOURCE_FAILED", f"{exc.category}: {exc}")
    outcome = s.catalog.refresh(track_id, result, plugin_version=package.version)
    return {"track_id": track_id, "state": outcome.state, "unit_count": outcome.unit_count,
            "previous_count": outcome.previous_count, "lost": outcome.lost, "reason": outcome.reason,
            "snapshot_id": outcome.snapshot_id, "evidence": outcome.evidence}


class TrustBody(BaseModel):
    snapshot_id: str = Field(min_length=1, max_length=64)


@router.post("/tracks/{track_id}/catalog/trust")
async def trust_catalog(request: Request, track_id: str, body: TrustBody):
    s = services(request)
    try:
        outcome = s.catalog.trust_catalog(track_id, body.snapshot_id)
    except TrustRejected as exc:
        return error(409, "CANNOT_TRUST_CATALOG", str(exc))
    return {"track_id": track_id, "state": outcome.state, "unit_count": outcome.unit_count}


class MergeBody(BaseModel):
    work_id: str = Field(min_length=1, max_length=64)
    other_work_id: str = Field(min_length=1, max_length=64)


class ListingBody(BaseModel):
    listing_id: str = Field(min_length=1, max_length=64)
    work_id: str | None = Field(default=None, max_length=64)
    title: str | None = Field(default=None, max_length=500)


def _mappings(request: Request) -> MappingService:
    return MappingService(services(request).conn)


@router.post("/mappings/merge")
async def merge(request: Request, body: MergeBody):
    try:
        _mappings(request).merge(body.work_id, body.other_work_id)
    except MappingError as exc:
        return error(409, "MERGE_REFUSED", str(exc))
    return {"work_id": body.work_id, "merged": body.other_work_id}


@router.post("/mappings/split")
async def split(request: Request, body: ListingBody):
    try:
        work_id = _mappings(request).split(body.listing_id, title=body.title)
    except MappingError as exc:
        return error(404, "LISTING_NOT_FOUND", str(exc))
    return {"listing_id": body.listing_id, "work_id": work_id}


@router.post("/mappings/unlink")
async def unlink(request: Request, body: ListingBody):
    try:
        _mappings(request).unlink(body.listing_id)
    except MappingError as exc:
        return error(404, "LISTING_NOT_FOUND", str(exc))
    return {"listing_id": body.listing_id, "work_id": None}


@router.post("/mappings/never-match")
async def never_match(request: Request, body: ListingBody):
    if not body.work_id:
        return error(422, "WORK_REQUIRED", "A work id is required.")
    _mappings(request).never_match(body.listing_id, body.work_id)
    return {"listing_id": body.listing_id, "never_match": body.work_id}
