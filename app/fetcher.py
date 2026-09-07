"""HTTP layer for bulk image downloads.

Runs over ``httpx`` using the cookies and User-Agent harvested by
:mod:`app.session`. The browser is only consulted when the edge challenges us
again mid-run, at which point the queue pauses, the session is re-solved, and
the failed request is retried rather than the whole job failing.

Also responsible for the "best quality" requirement: many Madara sites serve
pages through an image proxy or CDN that downscales and re-encodes on the fly.
:func:`quality_candidates` reconstructs the origin URL so we fetch the full-size
original, always keeping the site-supplied URL as a fallback.
"""

from __future__ import annotations

import asyncio
import logging
import random
import re
import time
from dataclasses import dataclass
from typing import Iterable
from urllib.parse import parse_qs, unquote, urlencode, urlparse, urlunparse

import httpx

from .session import is_challenge

log = logging.getLogger(__name__)

# Query parameters that ask a CDN for a smaller or re-encoded image.
RESIZE_PARAMS = {
    "w", "h", "width", "height", "resize", "fit", "crop",
    "q", "quality", "output", "format", "fm", "dpr", "size", "scale",
}

# Hosts that wrap another URL in a ?url= parameter.
WRAPPER_HOSTS = {
    "images.weserv.nl", "wsrv.nl", "res.cloudinary.com",
    "imageproxy.example", "i.imgproxy.net",
}

# Jetpack/Photon mirrors: https://i0.wp.com/<origin-host>/<path>?resize=...
PHOTON_HOSTS = {"i0.wp.com", "i1.wp.com", "i2.wp.com", "i3.wp.com"}

IMAGE_CONTENT_TYPES = ("image/", "application/octet-stream")

#: Extra passes when a request succeeds but does not return an image. A 200
#: carrying HTML is a throttle notice, not a missing page, and the status-based
#: retry never sees it — so one unlucky moment used to kill a whole chapter.
IMAGE_RETRY_ROUNDS = 2

RETRY_STATUS = {408, 425, 429, 500, 502, 503, 504}

#: Codes an edge uses for a bot check. They are *also* what an ordinary CDN
#: answers when it is briefly unhappy, so the status alone never decides —
#: see :meth:`Fetcher._is_bot_check`.
CHALLENGE_STATUS = {403, 503}


class DownloadError(RuntimeError):
    """Raised when an image could not be retrieved after all retries."""


class NotAnImage(DownloadError):
    """The request succeeded, but what came back was not an image.

    Its own type because it is the one failure worth simply waiting out: these
    sites answer 200 with a small HTML notice when they are throttling, which
    no status-based retry can recognise.
    """


class SessionRejected(RuntimeError):
    """The host rejected our credentials; the session needs re-solving."""


def _strip_resize_params(url: str) -> str | None:
    parsed = urlparse(url)
    if not parsed.query:
        return None
    params = parse_qs(parsed.query, keep_blank_values=True)
    kept = {k: v for k, v in params.items() if k.lower() not in RESIZE_PARAMS}
    if len(kept) == len(params):
        return None
    query = urlencode(kept, doseq=True)
    return urlunparse(parsed._replace(query=query))


#: WordPress writes resized copies as ``name-<W>x<H>.<ext>`` beside the
#: original at ``name.<ext>``. Anchored to just before the extension so a
#: filename that merely contains something like "1920x1080" is left alone.
_WP_SIZE_RE = re.compile(r"-\d{2,4}x\d{2,4}(?=\.[A-Za-z0-9]{2,5}$)")


def _strip_size_suffix(url: str) -> str | None:
    """Point a WordPress thumbnail URL at the full-size original."""
    parsed = urlparse(url)
    path, count = _WP_SIZE_RE.subn("", parsed.path)
    if not count:
        return None
    return urlunparse(parsed._replace(path=path))


#: Blogger serves size variants in the path (``/s1600/``, ``/w640-h480/``) or
#: after an ``=`` (``=s320``). ``s0`` asks for the original upload.
_BLOGGER_SIZE_RE = re.compile(r"/(?:s\d{2,5}|w\d{2,5}-h\d{2,5})(?:-[a-z]{1,3})?/")
_BLOGGER_EQ_SIZE_RE = re.compile(r"=(?:s\d{2,5}|w\d{2,5}(?:-h\d{2,5})?)(?:-[a-z]{1,3})?$")


def _strip_blogger_size(url: str) -> str | None:
    """Point a Blogger image at its original upload."""
    if "googleusercontent.com" not in url and "blogspot.com" not in url:
        return None
    upgraded, count = _BLOGGER_SIZE_RE.subn("/s0/", url)
    if not count:
        upgraded, count = _BLOGGER_EQ_SIZE_RE.subn("=s0", url)
    return upgraded if count else None


def _upgrades(base: str) -> list[str]:
    """Quality upgrades for one URL, most aggressive first."""
    stripped = _strip_resize_params(base)
    found = [
        _strip_size_suffix(stripped or base),  # both fixes applied
        stripped,
        _strip_size_suffix(base),
        _strip_blogger_size(base),
    ]
    return [candidate for candidate in found if candidate]


def _unwrap_proxy(url: str) -> str | None:
    """Recover the origin URL from a known image-proxy wrapper."""
    parsed = urlparse(url)
    host = parsed.netloc.lower()

    if host in WRAPPER_HOSTS or parsed.path.endswith("/_next/image"):
        target = parse_qs(parsed.query).get("url", [None])[0]
        if target:
            target = unquote(target)
            if target.startswith("//"):
                target = f"{parsed.scheme}:{target}"
            if target.startswith("http"):
                return target

    if host in PHOTON_HOSTS:
        # Path is /<origin-host>/<origin-path>
        remainder = parsed.path.lstrip("/")
        if "/" in remainder:
            origin_host, _, origin_path = remainder.partition("/")
            if "." in origin_host:
                return urlunparse(("https", origin_host, f"/{origin_path}", "", "", ""))

    if host.startswith("cdn.statically.io"):
        # /img/<origin-host>/<origin-path>
        parts = parsed.path.lstrip("/").split("/", 2)
        if len(parts) == 3 and parts[0] in ("img", "image"):
            return urlunparse(("https", parts[1], f"/{parts[2]}", "", "", ""))

    return None


def quality_candidates(url: str, *, enabled: bool = True) -> list[str]:
    """Return URLs to try, highest expected quality first.

    The original site URL is always last so a failed upscale degrades to
    "exactly what the reader shows" instead of a missing page.
    """
    url = url.strip()
    if not enabled:
        return [url]

    candidates: list[str] = []

    def add(candidate: str | None) -> None:
        if candidate and candidate not in candidates and candidate != url:
            candidates.append(candidate)

    unwrapped = _unwrap_proxy(url)
    if unwrapped:
        for candidate in _upgrades(unwrapped):
            add(candidate)
        add(unwrapped)

    for candidate in _upgrades(url):
        add(candidate)
    candidates.append(url)
    return candidates


class RateLimiter:
    """Token bucket, one per host, with jitter.

    Hammering a small aggregator is how the IP ends up banned, which costs far
    more time than the extra throughput ever saves.
    """

    def __init__(self, rate: float) -> None:
        self._rate = max(rate, 0.1)
        self._lock = asyncio.Lock()
        self._next_slot = 0.0

    async def acquire(self) -> None:
        async with self._lock:
            now = time.monotonic()
            wait = self._next_slot - now
            if wait > 0:
                await asyncio.sleep(wait)
                now = time.monotonic()
            self._next_slot = now + (1.0 / self._rate) + random.uniform(0, 0.15)


@dataclass(slots=True)
class FetchResult:
    url: str
    content: bytes
    content_type: str

    def __len__(self) -> int:  # convenience for progress accounting
        return len(self.content)


class Fetcher:
    """Cookie-aware HTTP client with retries, backoff, and quality upgrading."""

    def __init__(self, settings, session_manager) -> None:
        self._settings = settings
        self._sessions = session_manager
        self._client: httpx.AsyncClient | None = None
        self._client_h1: httpx.AsyncClient | None = None
        """HTTP/1.1-only twin of :attr:`_client`; see :meth:`_retry_over_http1`."""
        self._h1_hosts: set[str] = set()
        """Hosts already found to need HTTP/1.1, so the h2 attempt is skipped."""
        self._client_options: dict = {}
        self._limiters: dict[str, RateLimiter] = {}

    async def start(self) -> None:
        if self._client is None:
            options: dict = {
                "http2": True,
                "follow_redirects": True,
                "timeout": httpx.Timeout(self._settings.request_timeout),
                "limits": httpx.Limits(
                    max_connections=max(self._settings.image_concurrency * 2, 10),
                    max_keepalive_connections=max(self._settings.image_concurrency, 5),
                ),
            }

            proxy = self._settings.proxy_config
            if proxy is not None:
                # Must match the browser's route: a clearance cookie is bound to
                # the IP that earned it, so a split path fails every request.
                options["proxy"] = proxy.for_httpx()
                log.info("HTTP egress via proxy %s", proxy.describe())

            self._client_options = options
            self._client = httpx.AsyncClient(**options)

    async def close(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None
        if self._client_h1 is not None:
            await self._client_h1.aclose()
            self._client_h1 = None

    def _http1_client(self) -> httpx.AsyncClient:
        """The HTTP/1.1-only client, created on first need.

        Same options as the main client — proxy, timeout, limits — with
        negotiation pinned below HTTP/2.
        """
        if self._client_h1 is None:
            options = dict(self._client_options)
            options["http2"] = False
            self._client_h1 = httpx.AsyncClient(**options)
        return self._client_h1

    async def _retry_over_http1(
        self, url: str, headers: dict[str, str]
    ) -> httpx.Response | None:
        """Re-request ``url`` without HTTP/2. ``None`` if that did not help.

        Some CDNs fingerprint the HTTP/2 connection preface and settings frame
        and refuse a client whose h2 does not look like a browser's — while
        answering the *identical* request over HTTP/1.1 normally. Measured
        2026-09-07 against ``downloads.hindawi.org``: every header combination
        tried returned 403 over h2 and 200 with the full 2.45 MB EPUB over
        HTTP/1.1.

        This is checked before the browser fallback because it is far cheaper
        and, for a binary download, the only one that can work at all: a
        browser cannot ``goto`` an EPUB — it aborts the navigation.
        """
        try:
            response = await self._http1_client().get(url, headers=headers)
        except (httpx.TransportError, httpx.HTTPError) as exc:
            log.debug("HTTP/1.1 retry of %s failed: %s", url, exc)
            return None
        if response.status_code >= 400:
            return None
        return response

    @property
    def client(self) -> httpx.AsyncClient:
        if self._client is None:
            raise RuntimeError("Fetcher.start() must be awaited before use")
        return self._client

    def _limiter(self, host: str) -> RateLimiter:
        limiter = self._limiters.get(host)
        if limiter is None:
            limiter = RateLimiter(self._settings.requests_per_second)
            self._limiters[host] = limiter
        return limiter

    async def fetch_file(
        self,
        url: str,
        *,
        referer: str | None = None,
        min_bytes: int = 1024,
    ) -> FetchResult:
        """Download a document — an EPUB, a PDF — rather than a page image.

        Same transport as :meth:`fetch_image` and deliberately none of its
        content rules: quality upgrading is meaningless for a book (and would
        happily strip a query parameter the file host requires), and the
        magic-byte check for images would reject every one of them. What is
        kept is the floor on size, because the usual way this fails is a short
        HTML notice served with a 200.
        """
        result = await self._get_with_retries(url, referer=referer, dest="document")
        if len(result.content) < min_bytes:
            raise DownloadError(
                f"{url} returned {len(result.content)} bytes of "
                f"{result.content_type or 'unknown type'}, which is too small "
                "to be the file itself"
            )
        return result

    async def _headers(
        self, url: str, referer: str | None, *, dest: str = "image"
    ) -> dict[str, str]:
        # Deliberately a *passive* lookup. Asking for a session here used to
        # mean "solve a challenge for this host if there isn't one", which
        # pointed the browser at every image CDN we touched — MangaDex@Home
        # hands out a different node per chapter, so a 20-page chapter opened
        # 20 browser tabs on image URLs before downloading a single byte. A
        # challenge is something a *response* tells us about; until one does,
        # send what we have.
        session = await self._sessions.peek_session(url)
        headers = {
            # Must match the UA that solved the challenge, or clearance is void.
            "User-Agent": session.user_agent if session else self._sessions.user_agent,
            "Accept": ("image/avif,image/webp,image/apng,image/*,*/*;q=0.8"
                       if dest == "image" else "*/*"),
            "Accept-Language": "en-US,en;q=0.9,ar;q=0.8",
            # A download is a navigation-ish request, not an <img> load; some
            # file hosts serve an interstitial to anything claiming otherwise.
            "Sec-Fetch-Dest": "image" if dest == "image" else "document",
            "Sec-Fetch-Mode": "no-cors" if dest == "image" else "navigate",
            "Sec-Fetch-Site": "cross-site",
        }
        if session and session.cookies:
            headers["Cookie"] = session.cookie_header()
        if referer:
            headers["Referer"] = referer
            parsed = urlparse(referer)
            headers["Origin"] = f"{parsed.scheme}://{parsed.netloc}"
        return headers

    async def fetch_image(
        self,
        url: str,
        *,
        referer: str | None = None,
        min_bytes: int = 100,
    ) -> FetchResult:
        """Download one page image, trying quality upgrades in order."""
        candidates = quality_candidates(
            url, enabled=self._settings.prefer_original_quality
        )
        last_error: Exception | None = None

        for round_number in range(IMAGE_RETRY_ROUNDS + 1):
            if round_number:
                # A 200 carrying HTML is usually a throttle notice, and the
                # status-based retry in _get_with_retries never sees it — so a
                # single moment of unhappiness killed the chapter. Measured on
                # Noor: 90 pages downloaded, page 91 answered 114 bytes of
                # text/html, and the same URL fetched fine seconds later.
                await asyncio.sleep(min(2.0 ** round_number, 8.0)
                                    + random.uniform(0, 0.5))
                log.info("Retrying %s (round %d/%d): %s",
                         url, round_number, IMAGE_RETRY_ROUNDS, last_error)

            result = await self._try_candidates(candidates, referer, min_bytes)
            if isinstance(result, FetchResult):
                return result
            last_error = result
            # Only a "that was not an image" verdict is worth waiting out. A
            # hard failure has already been retried by _get_with_retries.
            if not isinstance(last_error, NotAnImage):
                break

        raise DownloadError(f"Failed to download {url}: {last_error}") from last_error

    async def _try_candidates(
        self, candidates: list[str], referer: str | None, min_bytes: int
    ) -> "FetchResult | Exception":
        """One pass over the quality candidates. Returns the error, never raises."""
        last_error: Exception | None = None

        for index, candidate in enumerate(candidates):
            is_last = index == len(candidates) - 1
            try:
                result = await self._get_with_retries(candidate, referer=referer)
            except Exception as exc:
                last_error = exc
                if is_last:
                    break
                log.debug("Quality candidate failed (%s): %s", candidate, exc)
                continue

            # A proxy sometimes answers 200 with an HTML error page or a 1x1
            # tracking pixel; treat that as a miss and fall through to the next.
            # The floor only needs to catch degenerate responses (a 1x1 PNG is
            # ~70 bytes) - malformed payloads are caught by the magic-byte sniff
            # here and by full Pillow decoding before the chapter is sealed.
            if len(result.content) < min_bytes or not _looks_like_image(result):
                last_error = NotAnImage(
                    f"{candidate} returned {len(result.content)} bytes of "
                    f"{result.content_type or 'unknown type'}"
                )
                if is_last:
                    break
                continue

            return result

        return last_error or NotAnImage("no candidates were tried")

    async def _get_with_retries(
        self, url: str, *, referer: str | None, dest: str = "image"
    ) -> FetchResult:
        host = urlparse(url).netloc
        attempts = self._settings.max_retries
        last_error: Exception | None = None

        for attempt in range(1, attempts + 1):
            await self._limiter(host).acquire()
            try:
                headers = await self._headers(url, referer, dest=dest)
                client = (
                    self._http1_client() if host in self._h1_hosts else self.client
                )
                response = await client.get(url, headers=headers)
            except (httpx.TransportError, httpx.HTTPError) as exc:
                last_error = exc
                await self._backoff(attempt)
                continue

            if response.status_code in CHALLENGE_STATUS and host not in self._h1_hosts:
                # Cheapest explanation first, and before deciding whether this
                # is a bot check at all: the host may simply dislike our
                # HTTP/2. One re-request over HTTP/1.1 settles it. For a
                # document download it is also the *only* fallback that can
                # work — the browser cannot navigate to an EPUB, it aborts —
                # and it costs one request against a host that has already
                # refused us.
                downgraded = await self._retry_over_http1(url, headers)
                if downgraded is not None:
                    self._h1_hosts.add(host)
                    log.info("%s rejected HTTP/2; using HTTP/1.1 for this host", host)
                    return FetchResult(
                        url=str(downgraded.url),
                        content=downgraded.content,
                        content_type=downgraded.headers.get("content-type", ""),
                    )

            if response.status_code in CHALLENGE_STATUS and await self._is_bot_check(
                url, response
            ):
                # Some edges bind clearance to the client's TLS fingerprint as
                # well as its IP and UA. There the cookie is correct and still
                # rejected, so re-solving loops forever. Borrowing the browser's
                # own connection answers it directly - and costs nothing to try
                # before falling back to the slower re-solve.
                borrowed = await self._fetch_via_browser(url, referer=referer)
                if borrowed is not None:
                    return borrowed

                # Otherwise clearance really has expired. Re-solve once, then
                # retry; the queue's pause/resume handles repeated failures.
                log.warning("HTTP %s on %s - refreshing session",
                            response.status_code, host)
                last_error = SessionRejected(f"HTTP {response.status_code} for {url}")
                try:
                    await self._sessions.refresh(url)
                except Exception as exc:
                    raise SessionRejected(str(exc)) from exc
                await self._backoff(attempt)
                continue

            if response.status_code in CHALLENGE_STATUS:
                # A 403 or 503 that is nobody's bot check: an image host having
                # a bad moment. Retried like any other transient failure.
                last_error = DownloadError(f"HTTP {response.status_code} for {url}")
                log.debug("HTTP %s on %s - transient, retrying",
                          response.status_code, host)
                await self._backoff(attempt, response=response)
                continue

            if response.status_code in RETRY_STATUS:
                last_error = DownloadError(f"HTTP {response.status_code} for {url}")
                await self._backoff(attempt, response=response)
                continue

            if response.status_code >= 400:
                # 404 and friends are permanent; retrying only wastes the budget.
                raise DownloadError(f"HTTP {response.status_code} for {url}")

            return FetchResult(
                url=str(response.url),
                content=response.content,
                content_type=response.headers.get("content-type", ""),
            )

        raise DownloadError(f"Gave up on {url} after {attempts} attempts: {last_error}")

    async def _is_bot_check(self, url: str, response: httpx.Response) -> bool:
        """Whether a 403/503 is an edge challenging us, or just a bad response.

        This distinction is the whole difference between re-solving a challenge
        and sending a browser after an innocent CDN. MangaDex@Home nodes answer
        403/503/404 while they pull a chapter from upstream, and reading that as
        a bot check launched a Cloudflare solve *against an image node* — ten
        times per chapter, and then failure.

        Either signal is enough: the body is recognisably a Cloudflare
        interstitial, or we already hold credentials for this host, which only
        happens once it has challenged us before — and a host that challenges
        can reject a stale cookie with nothing but a bare 403.
        """
        session = await self._sessions.peek_session(url)
        if session is not None and session.cookies:
            return True
        try:
            body = response.text[:20_000]
        except Exception:  # pragma: no cover - an undecodable binary body
            return False
        return is_challenge(body, status=response.status_code)

    async def _fetch_via_browser(
        self, url: str, *, referer: str | None
    ) -> FetchResult | None:
        """Retry one URL through the browser. ``None`` if that is not possible.

        Never fatal: this is a fallback for a request that has already failed,
        so any error here just means the caller carries on with its normal
        recovery path.
        """
        fetch_bytes = getattr(self._sessions, "fetch_bytes", None)
        if fetch_bytes is None:
            return None
        try:
            content, content_type = await fetch_bytes(url, referer=referer)
        except Exception as exc:
            log.debug("Browser fallback failed for %s: %s", url, exc)
            return None

        result = FetchResult(url=url, content=content, content_type=content_type)
        if not content or not _looks_like_image(result):
            return None
        log.info("Fetched %s through the browser after an HTTP rejection", url)
        return result

    async def _backoff(self, attempt: int, response: httpx.Response | None = None) -> None:
        if response is not None:
            retry_after = response.headers.get("retry-after")
            if retry_after:
                try:
                    await asyncio.sleep(min(float(retry_after), 60.0))
                    return
                except ValueError:
                    pass
        delay = min(2.0 ** attempt, 30.0) + random.uniform(0, 1.0)
        await asyncio.sleep(delay)


def _looks_like_image(result: FetchResult) -> bool:
    ctype = (result.content_type or "").lower()
    if ctype and not any(ctype.startswith(t) for t in IMAGE_CONTENT_TYPES):
        return False
    return bool(detect_extension(result.content))


# Magic-number sniffing. The URL extension is unreliable on these sites (WebP
# is routinely served from a .jpg path), and the stored extension must match the
# real bytes or readers mis-handle the archive.
_SIGNATURES: tuple[tuple[bytes, str], ...] = (
    (b"\xff\xd8\xff", ".jpg"),
    (b"\x89PNG\r\n\x1a\n", ".png"),
    (b"GIF87a", ".gif"),
    (b"GIF89a", ".gif"),
    (b"BM", ".bmp"),
)


def detect_extension(data: bytes) -> str | None:
    """Return the file extension implied by ``data``'s magic bytes."""
    for signature, extension in _SIGNATURES:
        if data.startswith(signature):
            return extension
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return ".webp"
    if data[4:12] in (b"ftypavif", b"ftypavis"):
        return ".avif"
    if data[4:8] == b"ftyp" and data[8:12] in (b"heic", b"heix", b"mif1"):
        return ".heic"
    # SVG last, and by content rather than by signature: it is text, so there is
    # nothing to match at offset zero. Recognised at all because Noor's reader
    # serves each book page as an SVG wrapping a raster image — without this the
    # fetcher rejects the page before the adapter is ever given a chance to
    # unwrap it. What lands in the archive is still the image inside.
    head = data[:512].lstrip()[:256].lower()
    if head.startswith(b"<svg") or (head.startswith(b"<?xml") and b"<svg" in head):
        return ".svg"
    return None


def pick_extension(data: bytes, url: str, fallback: str = ".jpg") -> str:
    sniffed = detect_extension(data)
    if sniffed:
        return sniffed
    suffix = urlparse(url).path.rsplit(".", 1)
    if len(suffix) == 2 and 2 <= len(suffix[1]) <= 5:
        return f".{suffix[1].lower()}"
    return fallback


async def gather_limited(coros: Iterable, limit: int) -> list:
    """Run awaitables with bounded concurrency, preserving input order."""
    semaphore = asyncio.Semaphore(limit)

    async def run(coro):
        async with semaphore:
            return await coro

    return await asyncio.gather(*(run(c) for c in coros), return_exceptions=True)
