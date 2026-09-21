"""Covers, served same-origin through the source's own network policy (INV-28; Master §11, §48).

The browser never loads a source's image host directly. It asks `/api/covers?source=…&url=…`, and Core fetches
that URL with `SourceService.fetch_resource`: only the plugin's approved domains and CDN domains, every redirect
and DNS answer re-checked, private networks refused, the source's session and resource headers, and the traffic
governor at a background priority. The body must decode as an image within a size limit, and it is returned
with the same sandbox and nosniff headers as reader pages. This is not a general proxy: a source id is
required, and nothing outside that source's allowlist can be reached.
"""
from __future__ import annotations

import json
from urllib.parse import urlsplit

from fastapi import APIRouter, Request, Response

from oneshelf.downloads.engine import detect_image_suffix
from oneshelf.integrity.validators import _validate_image
from oneshelf.net.governor import Priority
from oneshelf.net.http import ResponseTooLarge
from oneshelf.plugins.manager import PluginUnavailable
from oneshelf.plugins.runtime import AuthRequired, RateLimited

router = APIRouter(prefix="/api")

MAX_COVER_BYTES = 4 * 1024 * 1024
MEDIA_TYPES = {".png": "image/png", ".jpg": "image/jpeg", ".webp": "image/webp"}
HEADERS = {
    "Content-Security-Policy": "sandbox; default-src 'none'",
    "X-Content-Type-Options": "nosniff",
    "Cross-Origin-Resource-Policy": "same-origin",
    "Cache-Control": "private, max-age=86400",
}
CAPABILITY_ORDER = ("work", "search", "reader", "catalog")


def _error(status: int, code: str, message: str) -> Response:
    return Response(json.dumps({"error": {"code": code, "message": message}}), status_code=status,
                    media_type="application/json", headers={"Cache-Control": "no-store"})


@router.get("/covers")
async def cover(request: Request, source: str = "", url: str = ""):
    if request.headers.get("sec-fetch-site") == "cross-site":
        return _error(403, "CROSS_SITE", "Covers are only served to this library's own pages.")
    parts = urlsplit(url)
    if parts.scheme not in ("http", "https") or not parts.hostname or len(url) > 2048:
        return _error(422, "INVALID_URL", "A cover must be an http(s) address.")
    s = request.app.state.services
    try:
        package = s.plugins.load_active(source)
    except PluginUnavailable:
        return _error(404, "SOURCE_UNAVAILABLE", "No active source by that id.")
    capability = next((c for c in CAPABILITY_ORDER if c in package.recipes), None)
    if capability is None:
        return _error(404, "NO_COVER", "This source has no recipe that could carry a cover.")
    # Image hosts sometimes want what the source's own pages send (a Referer, say): whatever the source's
    # recipes declare for their resources, nothing more.
    headers: dict[str, str] = {}
    for name in reversed(CAPABILITY_ORDER):
        if name in package.recipes:
            headers.update(package.recipes[name].resource_headers)
    try:
        response = await s.source_service.fetch_resource(source, url, capability=capability,
                                                         priority=Priority.READ_AHEAD, max_bytes=MAX_COVER_BYTES,
                                                         headers=headers or None)
    except ResponseTooLarge:
        return _error(413, "COVER_TOO_LARGE", "The cover is larger than OneShelf accepts.")
    except AuthRequired:
        return _error(404, "SESSION_REQUIRED", "This cover needs a connected account.")
    except RateLimited:
        return _error(429, "RATE_LIMITED", "The source is rate limited.")
    except (ValueError, RuntimeError, OSError) as exc:        # policy refusals, redirects away, network failures
        status = 403 if type(exc).__name__ in ("DisallowedTarget", "BlockedDestination", "DomainRuleError") else 502
        return _error(status, "COVER_UNAVAILABLE", "The cover could not be fetched within this source's policy.")
    if response.status != 200:
        return _error(404, "COVER_UNAVAILABLE", f"The source answered {response.status}.")
    media_type = MEDIA_TYPES.get(detect_image_suffix(response.body))
    if media_type is None or _validate_image(response.body):
        return _error(415, "NOT_AN_IMAGE", "The source did not return an image.")
    return Response(response.body, media_type=media_type, headers=HEADERS)
