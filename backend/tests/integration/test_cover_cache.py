"""Covers kept on this device and sized for display (covers/cache.py, api/covers.py)."""
import io
from types import SimpleNamespace
from urllib.parse import quote

import pytest
from PIL import Image

from oneshelf.covers.cache import COVER_WIDTH, CoverCache, prepare_cover

from .test_library_api import TS, api  # noqa: F401  (the live Test Source fixture)

COVER = "http://cdn.testsource.example/covers/irregular.png"


def counting(monkeypatch, service, name):
    calls = []
    original = getattr(service, name)

    async def wrapper(*args, **kwargs):
        calls.append(args)
        return await original(*args, **kwargs)

    monkeypatch.setattr(service, name, wrapper)
    return calls


def test_a_cover_is_fetched_from_the_source_once(api, monkeypatch):
    client, _ = api
    fetches = counting(monkeypatch, client.app.state.services.source_service, "fetch_resource")
    url = f"/api/covers?source={TS}&url={quote(COVER, safe='')}"
    first, second = client.get(url), client.get(url)
    assert first.status_code == second.status_code == 200
    assert first.content == second.content and second.headers["x-content-type-options"] == "nosniff"
    assert len(fetches) == 1


def test_a_listing_cover_is_looked_up_once(api, monkeypatch):
    client, _ = api
    s = client.app.state.services
    runs = []

    async def run(source, capability, inputs, *, priority):
        runs.append(inputs)
        return SimpleNamespace(cover_url=COVER)

    monkeypatch.setattr(s.source_service, "run", run)
    for _ in range(3):
        assert client.get("/api/covers", params={"source": TS, "listing_key": "irregular"}).status_code == 200
    assert len(runs) == 1


def test_a_listing_without_a_cover_is_not_asked_again_on_every_scroll(api, monkeypatch):
    client, _ = api
    s = client.app.state.services
    runs = []

    async def run(source, capability, inputs, *, priority):
        runs.append(inputs)
        return SimpleNamespace(cover_url=None)

    monkeypatch.setattr(s.source_service, "run", run)
    for _ in range(3):
        assert client.get("/api/covers", params={"source": TS, "listing_key": "plain"}).status_code == 404
    assert len(runs) == 1


def png(width, height, mode="RGB"):
    out = io.BytesIO()
    Image.new(mode, (width, height), "teal" if mode == "RGB" else (0, 128, 128, 128)).save(out, "PNG")
    return out.getvalue()


def test_a_wide_cover_is_reduced_to_display_size():
    data, media_type = prepare_cover(png(2400, 3600))
    assert media_type == "image/webp"
    with Image.open(io.BytesIO(data)) as image:
        assert image.size == (COVER_WIDTH, 900)


def test_a_cover_already_small_enough_is_kept_as_it_is():
    original = png(300, 450)
    assert prepare_cover(original) == (original, "image/png")


def test_transparency_survives_reduction():
    data, _ = prepare_cover(png(1200, 1200, "RGBA"))
    with Image.open(io.BytesIO(data)) as image:
        assert image.mode == "RGBA"


@pytest.mark.parametrize("data", [b"", b"<html>nope</html>", b"\x89PNG\r\n\x1a\n" + b"\0" * 64])
def test_what_is_not_an_image_is_refused(data):
    assert prepare_cover(data) is None


def test_a_decompression_bomb_is_refused(monkeypatch):
    monkeypatch.setattr(Image, "MAX_IMAGE_PIXELS", 1000)
    assert prepare_cover(png(200, 200)) is None


def test_the_cache_is_bounded_and_keeps_what_was_used_last(tmp_path):
    clock = [1000.0]
    cache = CoverCache(tmp_path / "blobs", tmp_path / "cache.db", cap_bytes=250, clock=lambda: clock[0])
    try:
        for name in ("a", "b", "c"):
            cache.put(name * 64, b"x" * 100, "image/png")
            clock[0] += 1
            cache.get("a" * 64)                      # "a" is in use, so "b" goes first
        assert cache.get("b" * 64) is None and cache.get("a" * 64) is not None
        assert cache.total_bytes() <= 250
    finally:
        cache.close()


def test_entries_expire(tmp_path):
    clock = [0.0]
    cache = CoverCache(tmp_path / "blobs", tmp_path / "cache.db", ttl_seconds=10, clock=lambda: clock[0])
    try:
        cache.put("k" * 64, b"img", "image/png")
        cache.remember_lookup("s", "l", "en", "")
        clock[0] = 11
        assert cache.get("k" * 64) is None
        assert cache.lookup("s", "l", "en") == ""          # a missing cover is remembered for a day
        clock[0] = 24 * 3600 + 1
        assert cache.lookup("s", "l", "en") is None
    finally:
        cache.close()


class FakeRequest:
    def __init__(self, gone=False):
        self.gone = gone

    async def is_disconnected(self):
        return self.gone


def test_simultaneous_requests_for_one_cover_share_one_fetch():
    import asyncio

    from fastapi import Response

    from oneshelf.api import covers

    async def scenario():
        started = []

        async def fetch():
            started.append(1)
            await asyncio.sleep(0.1)
            return Response(b"img", media_type="image/png")

        results = await asyncio.gather(*(covers._shared(FakeRequest(), "k1", fetch) for _ in range(5)))
        return started, results
    started, results = asyncio.run(scenario())
    assert len(started) == 1 and all(r.body == b"img" and r.status_code == 200 for r in results)


def test_a_cover_nobody_waits_for_any_more_is_not_fetched_to_the_end():
    import asyncio

    from oneshelf.api import covers

    async def scenario():
        finished = []

        async def fetch():
            await asyncio.sleep(0.2)
            finished.append(1)

        response = await covers._shared(FakeRequest(gone=True), "k2", fetch)
        await asyncio.sleep(0.3)
        return response.status_code, finished, "k2" in covers._flights
    status, finished, still_flying = asyncio.run(scenario())
    assert status == 204 and finished == [] and not still_flying
