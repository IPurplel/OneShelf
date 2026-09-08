"""Fetcher: quality upgrading, format sniffing, and rate limiting."""

from __future__ import annotations

import asyncio
import time

import httpx
import pytest

from app.fetcher import (
    DownloadError,
    Fetcher,
    RateLimiter,
    detect_extension,
    pick_extension,
    quality_candidates,
)

from .conftest import make_jpeg, make_png


# ------------------------------------------------------- quality upgrading


def test_original_url_is_always_the_last_resort():
    url = "https://cdn.example.net/a/001.jpg?w=350&quality=60"
    candidates = quality_candidates(url)

    assert candidates[-1] == url
    assert len(candidates) > 1


def test_resize_params_are_stripped_first():
    url = "https://cdn.example.net/a/001.jpg?w=350&quality=60"
    assert quality_candidates(url)[0] == "https://cdn.example.net/a/001.jpg"


def test_non_resize_params_are_preserved():
    """Signed-URL tokens must survive, or the upgrade 403s."""
    url = "https://cdn.example.net/a/001.jpg?w=350&token=abc123"
    best = quality_candidates(url)[0]

    assert "token=abc123" in best
    assert "w=350" not in best


def test_url_without_params_yields_itself_only():
    url = "https://cdn.example.net/a/001.jpg"
    assert quality_candidates(url) == [url]


def test_wordpress_thumbnail_is_upgraded_to_the_original():
    # WordPress writes name-WxH.jpg beside the full-size name.jpg. Serving the
    # thumbnail is the default on Madara themes, so without this the "best
    # quality" promise silently delivers a 193px-wide image.
    url = "https://cdn.example.net/wp-content/uploads/2020/10/berserk-193x278.jpg"
    candidates = quality_candidates(url)

    assert candidates[0] == "https://cdn.example.net/wp-content/uploads/2020/10/berserk.jpg"
    assert candidates[-1] == url


def test_dimensions_inside_a_filename_are_left_alone():
    # Only a suffix immediately before the extension is a WordPress size.
    url = "https://cdn.example.net/a/wide-1920x1080-poster.jpg"
    assert quality_candidates(url) == [url]


def test_thumbnail_and_resize_params_are_both_undone():
    url = "https://cdn.example.net/a/cover-150x220.jpg?w=100&quality=50"
    assert quality_candidates(url)[0] == "https://cdn.example.net/a/cover.jpg"


def test_weserv_wrapper_is_unwrapped():
    url = "https://wsrv.nl/?url=https%3A%2F%2Fcdn.example.net%2Fa%2F001.jpg&w=500"
    candidates = quality_candidates(url)

    assert candidates[0] == "https://cdn.example.net/a/001.jpg"
    assert candidates[-1] == url


def test_jetpack_photon_mirror_is_unwrapped():
    url = "https://i0.wp.com/cdn.example.net/a/001.jpg?resize=350%2C500&ssl=1"
    assert "https://cdn.example.net/a/001.jpg" in quality_candidates(url)


def test_statically_cdn_is_unwrapped():
    url = "https://cdn.statically.io/img/cdn.example.net/a/001.jpg?w=400"
    assert "https://cdn.example.net/a/001.jpg" in quality_candidates(url)


def test_next_image_proxy_is_unwrapped():
    url = "https://example.net/_next/image?url=https%3A%2F%2Fcdn.example.net%2Fa%2F1.jpg&w=640&q=75"
    assert quality_candidates(url)[0] == "https://cdn.example.net/a/1.jpg"


def test_upgrading_can_be_disabled():
    url = "https://cdn.example.net/a/001.jpg?w=350"
    assert quality_candidates(url, enabled=False) == [url]


def test_candidates_are_deduplicated():
    url = "https://wsrv.nl/?url=https%3A%2F%2Fcdn.example.net%2Fa%2F1.jpg"
    assert len(quality_candidates(url)) == len(set(quality_candidates(url)))


def test_surrounding_whitespace_is_tolerated():
    assert quality_candidates("  https://cdn.example.net/a/1.jpg  ") == [
        "https://cdn.example.net/a/1.jpg"
    ]


# ---------------------------------------------------------- format sniffing


def test_detect_extension_from_magic_bytes():
    assert detect_extension(make_png()) == ".png"
    assert detect_extension(make_jpeg()) == ".jpg"
    assert detect_extension(b"RIFF\x00\x00\x00\x00WEBPVP8 ") == ".webp"
    assert detect_extension(b"GIF89a....") == ".gif"


def test_detect_extension_rejects_non_image():
    assert detect_extension(b"<html><body>nope</body></html>") is None
    assert detect_extension(b"") is None


def test_pick_extension_trusts_bytes_over_url():
    """Sites routinely serve WebP from a .jpg path; the bytes decide."""
    webp = b"RIFF\x00\x00\x00\x00WEBPVP8 " + b"\x00" * 32
    assert pick_extension(webp, "https://cdn.example.net/a/001.jpg") == ".webp"


def test_pick_extension_falls_back_to_url_then_default():
    assert pick_extension(b"unknown-bytes", "https://cdn.example.net/a/001.png") == ".png"
    assert pick_extension(b"unknown-bytes", "https://cdn.example.net/a/001") == ".jpg"


# -------------------------------------------------------------- rate limit


@pytest.mark.asyncio
async def test_rate_limiter_spaces_requests():
    limiter = RateLimiter(rate=20.0)  # 50 ms apart, plus jitter
    start = time.monotonic()
    for _ in range(4):
        await limiter.acquire()
    elapsed = time.monotonic() - start

    # Three gaps of >= 50 ms after the first immediate acquisition.
    assert elapsed >= 0.15


@pytest.mark.asyncio
async def test_rate_limiter_serialises_concurrent_callers():
    limiter = RateLimiter(rate=25.0)
    order: list[int] = []

    async def worker(index: int) -> None:
        await limiter.acquire()
        order.append(index)

    await asyncio.gather(*(worker(i) for i in range(5)))
    assert len(order) == 5


@pytest.mark.asyncio
async def test_rate_limiter_clamps_absurd_rates():
    limiter = RateLimiter(rate=0.0)  # must not divide by zero
    await asyncio.wait_for(limiter.acquire(), timeout=1.0)


# ------------------------------------------------- browser fetch fallback


class RecordingSessions:
    """Session manager stub exposing the browser's own fetch path."""

    def __init__(self, payload=b"", content_type="image/jpeg", fail=False):
        self.payload = payload
        self.content_type = content_type
        self.fail = fail
        self.calls: list[tuple[str, str | None]] = []
        self.refreshed = 0

    async def fetch_bytes(self, url, *, referer=None):
        self.calls.append((url, referer))
        if self.fail:
            raise RuntimeError("browser said no")
        return self.payload, self.content_type

    async def refresh(self, url):
        self.refreshed += 1


class NoBrowserSessions:
    """An older/plain session manager with no fetch_bytes at all."""

    async def refresh(self, url):
        return None


@pytest.mark.asyncio
async def test_browser_fallback_returns_the_image(tmp_path):
    from app.config import Settings

    payload = make_jpeg()
    sessions = RecordingSessions(payload=payload)
    fetcher = Fetcher(Settings(config_dir=tmp_path), sessions)

    result = await fetcher._fetch_via_browser("https://e.net/p/1.jpg", referer="https://e.net/c/")

    assert result is not None
    assert result.content == payload
    assert sessions.calls == [("https://e.net/p/1.jpg", "https://e.net/c/")]


@pytest.mark.asyncio
async def test_browser_fallback_rejects_a_non_image(tmp_path):
    from app.config import Settings

    # A challenge page answered with 200 is still not a page of the manga.
    sessions = RecordingSessions(payload=b"<html>just a moment</html>",
                                 content_type="text/html")
    fetcher = Fetcher(Settings(config_dir=tmp_path), sessions)

    assert await fetcher._fetch_via_browser("https://e.net/p/1.jpg", referer=None) is None


@pytest.mark.asyncio
async def test_browser_fallback_is_never_fatal(tmp_path):
    from app.config import Settings

    # It is a rescue attempt for an already-failed request; if it fails too,
    # the caller must be free to carry on with its normal recovery.
    sessions = RecordingSessions(fail=True)
    fetcher = Fetcher(Settings(config_dir=tmp_path), sessions)

    assert await fetcher._fetch_via_browser("https://e.net/p/1.jpg", referer=None) is None


@pytest.mark.asyncio
async def test_browser_fallback_skipped_when_unsupported(tmp_path):
    from app.config import Settings

    fetcher = Fetcher(Settings(config_dir=tmp_path), NoBrowserSessions())
    assert await fetcher._fetch_via_browser("https://e.net/p/1.jpg", referer=None) is None


# ------------------------------------------------ challenge classification


class CdnSessions:
    """Session manager for a host no challenge was ever solved for.

    Records the recovery paths a fetch takes, so a test can prove which one it
    chose rather than only what it returned.
    """

    user_agent = "pytest-agent"

    def __init__(self, session=None):
        self.session = session
        self.refreshed = 0
        self.browser_fetches = 0

    async def peek_session(self, url):
        return self.session

    async def get_session(self, url, *, force=False):
        raise AssertionError("downloading an image must not solve a challenge")

    async def refresh(self, url):
        self.refreshed += 1
        return self.session

    async def fetch_bytes(self, url, *, referer=None):
        self.browser_fetches += 1
        raise RuntimeError("no browser in tests")


class ScriptedClient:
    """Answers each GET from a queued list, repeating the last response."""

    def __init__(self, *responses):
        self.responses = list(responses)
        self.requests: list[dict] = []

    async def get(self, url, headers=None):
        self.requests.append({"url": url, "headers": dict(headers or {})})
        if len(self.responses) > 1:
            return self.responses.pop(0)
        return self.responses[0]


#: A managed challenge as Cloudflare actually serves it: the marker is in the
#: body, not in the status code, which an ordinary CDN uses for its own reasons.
CHALLENGE_BODY = (
    "<html><head><title>Just a moment...</title></head><body>"
    "<script src='/cdn-cgi/challenge-platform/h/b/orchestrate/jsd/v1'></script>"
    "</body></html>"
)


def _response(status: int, body=b"", content_type: str = "text/html") -> httpx.Response:
    return httpx.Response(
        status,
        content=body if isinstance(body, bytes) else body.encode(),
        headers={"content-type": content_type},
        request=httpx.Request("GET", "https://node.example.net/data/x/1.png"),
    )


def _scripted_fetcher(tmp_path, sessions, *responses) -> Fetcher:
    from app.config import Settings

    fetcher = Fetcher(
        Settings(config_dir=tmp_path, requests_per_second=100.0), sessions
    )
    fetcher._client = ScriptedClient(*responses)

    async def no_backoff(attempt, response=None):
        return None  # the real one sleeps for seconds between attempts

    fetcher._backoff = no_backoff
    return fetcher


@pytest.mark.asyncio
async def test_a_plain_403_is_retried_rather_than_treated_as_a_bot_check(tmp_path):
    """MangaDex@Home nodes answer 403/503 while they pull from upstream.

    Reading that as a Cloudflare challenge sent the browser off to solve one
    against an image CDN — ten times per chapter, and then failure anyway.
    """
    payload = make_jpeg()
    sessions = CdnSessions()
    fetcher = _scripted_fetcher(
        tmp_path, sessions,
        _response(403, b"upstream fetch failed", "text/plain"),
        _response(200, payload, "image/jpeg"),
    )

    result = await fetcher.fetch_image("https://node.example.net/data/x/1.png")

    assert result.content == payload
    assert sessions.refreshed == 0
    assert sessions.browser_fetches == 0
    assert len(fetcher._client.requests) == 2  # retried, not escalated


@pytest.mark.asyncio
async def test_a_cloudflare_interstitial_still_refreshes_the_session(tmp_path):
    sessions = CdnSessions()
    fetcher = _scripted_fetcher(tmp_path, sessions, _response(403, CHALLENGE_BODY))

    with pytest.raises(Exception):
        await fetcher.fetch_image("https://node.example.net/data/x/1.png")

    assert sessions.browser_fetches >= 1  # the cheap borrow is tried first
    assert sessions.refreshed >= 1


@pytest.mark.asyncio
async def test_a_bare_403_from_a_host_we_hold_cookies_for_is_a_bot_check(tmp_path):
    """An edge that issued us clearance can reject it with no explanation.

    Holding a cookie for the host is the evidence that it challenges at all,
    so there a bare 403 means the clearance has expired.
    """
    from app.session import HostSession

    sessions = CdnSessions(
        HostSession(host="node.example.net", cookies={"cf_clearance": "abc"})
    )
    fetcher = _scripted_fetcher(tmp_path, sessions, _response(403, b"", "text/plain"))

    with pytest.raises(Exception):
        await fetcher.fetch_image("https://node.example.net/data/x/1.png")

    assert sessions.refreshed >= 1


@pytest.mark.asyncio
async def test_downloading_an_image_never_provokes_a_challenge_solve(tmp_path):
    """Headers use whatever session exists; they must never demand one.

    ``get_session`` solves a challenge when there is nothing cached, so calling
    it here pointed a browser at every image host a series happened to use.
    """
    payload = make_jpeg()
    sessions = CdnSessions()
    fetcher = _scripted_fetcher(
        tmp_path, sessions, _response(200, payload, "image/jpeg")
    )

    await fetcher.fetch_image("https://node.example.net/data/x/1.png")

    headers = fetcher._client.requests[0]["headers"]
    assert headers["User-Agent"] == "pytest-agent"
    assert "Cookie" not in headers


@pytest.mark.asyncio
async def test_a_404_is_not_retried(tmp_path):
    """Permanent for that URL. An adapter with expiring URLs re-lists instead."""
    sessions = CdnSessions()
    fetcher = _scripted_fetcher(tmp_path, sessions, _response(404, b"", "text/plain"))

    with pytest.raises(DownloadError):
        await fetcher.fetch_image("https://node.example.net/data/x/1.png")

    assert len(fetcher._client.requests) == 1


def test_blogger_thumbnail_is_upgraded_to_the_original():
    # Blogger serves /s1600/ variants; s0 asks for the original upload.
    url = "https://blogger.googleusercontent.com/img/a/AB/s1600/page-01.jpg"
    candidates = quality_candidates(url)

    assert "https://blogger.googleusercontent.com/img/a/AB/s0/page-01.jpg" in candidates
    assert candidates[-1] == url  # original stays the fallback


def test_blogger_width_height_variant_is_upgraded():
    url = "https://blogger.googleusercontent.com/img/a/AB/w640-h480/p.jpg"
    assert "https://blogger.googleusercontent.com/img/a/AB/s0/p.jpg" in quality_candidates(url)


def test_non_blogger_hosts_are_left_alone_by_the_blogger_rule():
    url = "https://cdn.example.net/a/s1600/page.jpg"
    assert quality_candidates(url) == [url]


# --------------------------------------------------- a 200 that is not an image
# These sites answer 200 with a small HTML notice when they are throttling, and
# no status-based retry can recognise that. Measured on noor-book.com: 90 pages
# downloaded, page 91 answered 114 bytes of text/html, and the same URL fetched
# fine seconds later -- one unlucky moment killed the whole chapter.

THROTTLE = b"<html><body>please slow down</body></html>"


@pytest.mark.asyncio
async def test_a_throttle_notice_is_waited_out_rather_than_fatal(tmp_path):
    payload = make_jpeg()   # not make_png(): that one is 77 bytes, under min_bytes
    sessions = CdnSessions()
    fetcher = _scripted_fetcher(
        tmp_path, sessions,
        _response(200, THROTTLE, "text/html"),
        _response(200, payload, "image/jpeg"),
    )
    fetcher._settings.prefer_original_quality = False   # one candidate, one try

    async def instant(seconds):
        return None

    import app.fetcher as fetcher_module
    original_sleep = fetcher_module.asyncio.sleep
    fetcher_module.asyncio.sleep = instant
    try:
        result = await fetcher.fetch_image("https://node.example.net/data/x/1.png")
    finally:
        fetcher_module.asyncio.sleep = original_sleep

    assert result.content == payload


@pytest.mark.asyncio
async def test_it_gives_up_eventually_instead_of_looping(tmp_path):
    from app.fetcher import IMAGE_RETRY_ROUNDS

    sessions = CdnSessions()
    fetcher = _scripted_fetcher(
        tmp_path, sessions,
        *[_response(200, THROTTLE, "text/html") for _ in range(12)],
    )
    fetcher._settings.prefer_original_quality = False

    async def instant(seconds):
        return None

    import app.fetcher as fetcher_module
    original_sleep = fetcher_module.asyncio.sleep
    fetcher_module.asyncio.sleep = instant
    try:
        with pytest.raises(DownloadError, match="text/html"):
            await fetcher.fetch_image("https://node.example.net/data/x/1.png")
    finally:
        fetcher_module.asyncio.sleep = original_sleep

    assert len(fetcher._client.requests) == IMAGE_RETRY_ROUNDS + 1


# ------------------------------------------------------- HTTP/2-hostile hosts


@pytest.mark.asyncio
async def test_a_403_is_retried_over_http1_before_the_browser(tmp_path):
    """Some CDNs refuse our HTTP/2 and answer the same request over 1.1.

    Measured 2026-09-07 against downloads.hindawi.org: every header
    combination returned 403 over h2 and 200 with the full EPUB over HTTP/1.1.
    The browser fallback cannot rescue this one — it cannot navigate to an
    EPUB, it aborts — so the downgrade has to be tried first.
    """
    payload = b"%PDF-1.4" + b"0" * 4000
    sessions = CdnSessions()
    fetcher = _scripted_fetcher(tmp_path, sessions, _response(403, b"denied"))

    h1 = ScriptedClient(_response(200, payload, "application/octet-stream"))
    fetcher._client_h1 = h1

    result = await fetcher.fetch_file("https://downloads.example.org/b/1.epub")

    assert result.content == payload
    assert len(h1.requests) == 1
    assert sessions.browser_fetches == 0, "the browser must not be reached"
    assert sessions.refreshed == 0, "no session re-solve should be attempted"


@pytest.mark.asyncio
async def test_a_host_that_needed_http1_is_not_asked_over_http2_again(tmp_path):
    """One downgrade per host, not one per file."""
    payload = b"%PDF-1.4" + b"0" * 4000
    fetcher = _scripted_fetcher(tmp_path, CdnSessions(), _response(403, b"denied"))
    h1 = ScriptedClient(_response(200, payload, "application/octet-stream"))
    fetcher._client_h1 = h1

    await fetcher.fetch_file("https://downloads.example.org/b/1.epub")
    before = len(fetcher._client.requests)
    await fetcher.fetch_file("https://downloads.example.org/b/2.epub")

    assert len(fetcher._client.requests) == before, "h2 was tried again"
    assert len(h1.requests) == 2


@pytest.mark.asyncio
async def test_the_downgrade_is_skipped_when_http1_fails_too(tmp_path):
    """A genuine block must still reach the existing recovery paths."""
    sessions = CdnSessions()
    fetcher = _scripted_fetcher(tmp_path, sessions, _response(403, CHALLENGE_BODY))
    fetcher._client_h1 = ScriptedClient(_response(403, b"denied"))

    with pytest.raises(Exception):
        await fetcher.fetch_image("https://node.example.net/data/x/1.png")

    assert sessions.browser_fetches >= 1


async def test_unicode_referer_is_encoded_before_becoming_an_http_header(settings):
    fetcher = Fetcher(settings, CdnSessions())
    headers = await fetcher._headers('https://cdn.example.net/1.jpg', 'https://example.net/كتاب')
    request = httpx.Request('GET', 'https://cdn.example.net/1.jpg', headers=headers)
    assert request.headers['referer'] == 'https://example.net/%D9%83%D8%AA%D8%A7%D8%A8'


async def test_host_rate_override_paces_aliases_without_delaying_other_hosts(settings, monkeypatch):
    monkeypatch.setattr('app.fetcher.random.uniform', lambda *args: 0)
    settings.requests_per_second = 1000
    settings.host_requests_per_second = {'noor-book.com': 10}
    fetcher = Fetcher(settings, CdnSessions())
    start = time.monotonic()

    async def issue(host):
        await fetcher._limiter(host).acquire()
        return time.monotonic() - start

    first, second, other = await asyncio.gather(issue('www.noor-book.com'),
                                               issue('noor-book.com'), issue('example.net'))
    assert second >= 0.09
    assert first < 0.09 and other < 0.09
