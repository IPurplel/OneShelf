"""Covers, served same-origin through the source's own network policy (INV-28; Master §11, §48).

The browser never loads a source's image host directly. It asks `/api/covers` with either a known image URL or a
listing key. For a listing, Core reads the work detail cover first and can try up to four grouped alternatives.
It fetches the image with `SourceService.fetch_resource`: only the plugin's approved domains and CDN domains, every redirect
and DNS answer re-checked, private networks refused, the source's session and resource headers, and the traffic
governor at a background priority. The body must decode as an image within a size limit, and it is returned
with the same sandbox and nosniff headers as reader pages. This is not a general proxy: a source id is
required, and nothing outside that source's allowlist can be reached.

To ask the source as little as possible (PERFORMANCE_STUDY.md §3.1):
- the image is kept on this device, reduced to display size (covers/cache.py), and served from there;
- a listing's looked-up cover address is kept too, so a known listing costs no `work` request;
- requests for the same cover at the same time share one fetch;
- a request whose page went away (a card scrolled past) stops, unless another request still wants it.
"""
from __future__ import annotations

import asyncio
import json
from urllib.parse import urlsplit

from fastapi import APIRouter, Query, Request, Response

from oneshelf.covers.cache import cover_key, prepare_cover_off_loop
from oneshelf.downloads.engine import detect_image_suffix
from oneshelf.net.governor import Priority
from oneshelf.net.http import ResponseTooLarge
from oneshelf.plugins.manager import PluginUnavailable
from oneshelf.plugins.runtime import AuthRequired, CapabilityError, RateLimited, TrafficDeferred

router = APIRouter(prefix="/api")

MAX_COVER_BYTES = 4 * 1024 * 1024
MEDIA_TYPES = {".png": "image/png", ".jpg": "image/jpeg", ".webp": "image/webp"}
_SECURITY_HEADERS = {
    "Content-Security-Policy": "sandbox; default-src 'none'",
    "X-Content-Type-Options": "nosniff",
    "Cross-Origin-Resource-Policy": "same-origin",
}
HEADERS_URL = {**_SECURITY_HEADERS, "Cache-Control": "private, max-age=604800, immutable"}
HEADERS_LISTING = {**_SECURITY_HEADERS, "Cache-Control": "private, max-age=86400, stale-while-revalidate=86400"}
CAPABILITY_ORDER = ("work", "search", "reader", "catalog")
DISCONNECT_POLL_SECONDS = 0.05

# Fetches in progress, shared by every request that wants the same cover at the same time.
_flights: dict[str, tuple[asyncio.Task, list[int]]] = {}


def _error(status: int, code: str, message: str, *, retry_after: float | None = None) -> Response:
    cache = "private, max-age=3600" if status in (413, 415) else "no-store"
    headers = {"Cache-Control": cache}
    if retry_after is not None:
        headers["Retry-After"] = str(max(1, int(retry_after + 0.999)))
    return Response(json.dumps({"error": {"code": code, "message": message}}), status_code=status,
                    media_type="application/json", headers=headers)


def _image(data: bytes, media_type: str, headers: dict[str, str]) -> Response:
    return Response(data, media_type=media_type, headers=headers)


async def _fetch_image(s, source: str, package, url: str, headers: dict[str, str]) -> Response:
    capability = next((c for c in CAPABILITY_ORDER if c in package.manifest.capabilities), None)
    if capability is None:
        return _error(404, "NO_COVER", "This source has no recipe that could carry a cover.")
    # Image hosts sometimes want what the source's own pages send (a Referer, say): whatever the source's
    # recipes declare for their resources, nothing more.
    resource_headers: dict[str, str] = {}
    for name in reversed(CAPABILITY_ORDER):
        if name in package.recipes:
            resource_headers.update(package.recipes[name].resource_headers)
    try:
        response = await s.source_service.fetch_resource(source, url, capability=capability,
                                                         priority=Priority.READ_AHEAD, max_bytes=MAX_COVER_BYTES,
                                                         headers=resource_headers or None)
    except ResponseTooLarge:
        return _error(413, "COVER_TOO_LARGE", "The cover is larger than OneShelf accepts.")
    except AuthRequired:
        return _error(404, "SESSION_REQUIRED", "This cover needs a connected account.")
    except TrafficDeferred as exc:
        return _error(503, "SOURCE_BUSY", "The source is busy; the cover waits.", retry_after=exc.retry_after)
    except RateLimited:
        return _error(429, "RATE_LIMITED", "The source is rate limited.")
    except (ValueError, RuntimeError, OSError) as exc:        # policy refusals, redirects away, network failures
        status = 403 if type(exc).__name__ in ("DisallowedTarget", "BlockedDestination", "DomainRuleError") else 502
        return _error(status, "COVER_UNAVAILABLE", "The cover could not be fetched within this source's policy.")
    if response.status != 200:
        return _error(404, "COVER_UNAVAILABLE", f"The source answered {response.status}.")
    if MEDIA_TYPES.get(detect_image_suffix(response.body)) is None:
        return _error(415, "NOT_AN_IMAGE", "The source did not return an image.")
    prepared = await prepare_cover_off_loop(response.body)      # full decode, then sized for display
    if prepared is None:
        return _error(415, "NOT_AN_IMAGE", "The source did not return an image.")
    data, media_type = prepared
    cache = getattr(s, "cover_cache", None)
    if cache is not None:
        await asyncio.to_thread(cache.put, cover_key(source, url), data, media_type)
    return _image(data, media_type, headers)


async def _image_response(request: Request, s, source: str, package, url: str, *,
                          headers: dict[str, str] = HEADERS_URL) -> Response:
    cache = getattr(s, "cover_cache", None)
    key = cover_key(source, url)
    if cache is not None:
        kept = await asyncio.to_thread(cache.get, key)
        if kept is not None:
            return _image(kept[0], kept[1], headers)
    return await _shared(request, f"image\0{key}", lambda: _fetch_image(s, source, package, url, headers))


async def _shared(request: Request, key: str, start) -> Response:
    """One fetch for everyone asking for `key` now; stopped when nobody is waiting for it any more."""
    flight = _flights.get(key)
    if flight is None or flight[0].done():
        task = asyncio.ensure_future(start())
        flight = (task, [0])
        _flights[key] = flight
        task.add_done_callback(lambda done, k=key, f=flight: _flights.pop(k, None) if _flights.get(k) is f else None)
    task, interest = flight
    interest[0] += 1
    try:
        while not task.done():
            if await request.is_disconnected():
                return Response(status_code=204, headers={"Cache-Control": "no-store"})
            await asyncio.wait({task}, timeout=DISCONNECT_POLL_SECONDS)
        response = task.result()
        # Every waiter gets its own response object with the same body and headers.
        return Response(response.body, status_code=response.status_code, media_type=response.media_type,
                        headers={k: v for k, v in response.headers.items() if k.lower() != "content-length"})
    finally:
        interest[0] -= 1
        if interest[0] == 0 and not task.done():
            task.cancel()


@router.get("/covers")
async def cover(request: Request, source: str = "", url: str = "", listing_key: str = "", language: str = "",
                alt_source: list[str] = Query(default=[]), alt_listing_key: list[str] = Query(default=[]),
                alt_language: list[str] = Query(default=[])):
    if request.headers.get("sec-fetch-site") == "cross-site":
        return _error(403, "CROSS_SITE", "Covers are only served to this library's own pages.")
    if (bool(url) == bool(listing_key) or len(listing_key) > 512 or len(language) > 35
            or len(alt_source) != len(alt_listing_key) or len(alt_source) != len(alt_language)
            or len(alt_source) > 4 or (url and alt_source)
            or any(not src or len(src) > 64 or not key or len(key) > 512 or len(lang) > 35
                   for src, key, lang in zip(alt_source, alt_listing_key, alt_language))):
        return _error(422, "INVALID_URL", "Provide one cover URL or up to five valid listing keys.")
    if url:
        parts = urlsplit(url)
        if parts.scheme not in ("http", "https") or not parts.hostname or len(url) > 2048:
            return _error(422, "INVALID_URL", "A cover must be an http(s) address.")
        s = request.app.state.services
        try:
            package = s.plugins.load_active(source)
        except PluginUnavailable:
            return _error(404, "SOURCE_UNAVAILABLE", "No active source by that id.")
        return await _image_response(request, s, source, package, url)

    s = request.app.state.services
    cache = getattr(s, "cover_cache", None)
    candidates = [(source, listing_key, language), *zip(alt_source, alt_listing_key, alt_language)]
    last_error = _error(404, "NO_COVER", "No grouped listing has a cover.")
    for candidate_source, key, candidate_language in candidates:
        try:
            package = s.plugins.load_active(candidate_source)
        except PluginUnavailable:
            continue
        recipe = package.recipes.get("work")
        if recipe is None or "listing_key" not in recipe.inputs or "cover_url" not in recipe.extract.fields:
            continue
        inputs = {"listing_key": key}
        if "language" in recipe.inputs:
            inputs["language"] = candidate_language or package.manifest.defaults.language or "und"
        found_url = (await asyncio.to_thread(cache.lookup, candidate_source, key, inputs.get("language", ""))
                     if cache is not None else None)
        if found_url is None:
            try:
                details = await s.source_service.run(candidate_source, "work", inputs,
                                                     priority=Priority.READ_AHEAD)
            except AuthRequired:
                last_error = _error(404, "SESSION_REQUIRED", "This cover needs a connected account.")
                continue
            except TrafficDeferred as exc:
                last_error = _error(503, "SOURCE_BUSY", "The source is busy; the cover waits.",
                                    retry_after=exc.retry_after)
                continue
            except RateLimited:
                last_error = _error(429, "RATE_LIMITED", "The source is rate limited.")
                continue
            except (CapabilityError, ValueError, RuntimeError, OSError):
                last_error = _error(502, "COVER_UNAVAILABLE", "The cover could not be fetched within this source's policy.")
                continue
            found_url = getattr(details, "cover_url", None) or ""
            parts = urlsplit(found_url)
            if parts.scheme not in ("http", "https") or not parts.hostname or len(found_url) > 2048:
                found_url = ""
            if cache is not None:
                await asyncio.to_thread(cache.remember_lookup, candidate_source, key, inputs.get("language", ""),
                                        found_url)
            if found_url:
                _remember_listing_cover(s, candidate_source, key, found_url)
        if not found_url:
            last_error = _error(404, "NO_COVER", "This listing has no cover.")
            continue
        response = await _image_response(request, s, candidate_source, package, found_url, headers=HEADERS_LISTING)
        if response.status_code == 200:
            return response
        if response.status_code == 204:       # the page went away
            return response
        last_error = response
    return last_error


def _remember_listing_cover(s, source_id: str, listing_key: str, url: str) -> None:
    """A listing the library already holds keeps the cover it was found to have, as opening it would
    (api/discovery.py: _open_details). Presentation only (INV-28); an existing cover is never replaced."""
    from oneshelf.db.connection import transaction

    try:
        with transaction(s.conn):
            s.conn.execute("UPDATE source_listings SET cover_url = COALESCE(cover_url, ?)"
                           " WHERE source_id = ? AND source_listing_key = ?", (url, source_id, listing_key))
    except Exception:          # a busy database must not cost the person their cover
        pass
