"""Shared test fixtures.

Everything here runs offline: a fake session manager replays saved HTML instead
of touching the network, so the parsing rules are pinned without depending on a
live site that can change at any moment.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture(autouse=True)
def _isolate_search_cache():
    """Empty the per-source search cache around every test.

    The cache is a process-global, which is right in production and poison in a
    test suite: one test's cached answer for a (site, query, limit) is served
    to the next, so a test that stubs a *failing* adapter silently gets the
    previous test's success and asserts against it. Found exactly that way —
    eight tests failed together the moment caching was wired in, and every one
    passed alone.
    """
    from app.main import search_cache

    search_cache.invalidate()
    yield
    search_cache.invalidate()


def fixture(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


class FakeSessionManager:
    """Stands in for :class:`app.session.SessionManager`.

    Maps URLs (and POST endpoints) to canned HTML and records what was asked
    for, so tests can assert on the request sequence as well as the parse.
    """

    def __init__(
        self,
        pages: dict[str, str],
        posts: dict[str, str] | None = None,
        json_routes: dict[str, object] | None = None,
    ) -> None:
        self.pages = pages
        self.posts = posts or {}
        self.json_routes = json_routes or {}
        self.requested: list[str] = []
        self.waited: list[str | None] = []
        self.scrolled: list[str | None] = []
        self.wait_timeouts: list[float | None] = []
        self.clicked: list[tuple[str, tuple[str, ...]]] = []
        self.posted: list[tuple[str, dict]] = []
        self.direct: list[str] = []
        """URLs fetched over plain HTTP rather than through the browser."""

    async def fetch_html(
        self,
        url: str,
        *,
        referer: str | None = None,
        wait_for: str | None = None,
        wait_ms: int = 0,
        scroll_for: str | None = None,
        wait_timeout: float | None = None,
    ) -> str:
        # wait_for/wait_ms/scroll_for are recorded rather than honoured: there
        # is no browser here, and the adapters that use them must still be
        # testable.
        self.requested.append(url)
        self.waited.append(wait_for)
        self.scrolled.append(scroll_for)
        self.wait_timeouts.append(wait_timeout)
        if url not in self.pages:
            raise RuntimeError(f"no fixture registered for GET {url}")
        return self.pages[url]

    async def fetch_html_after_click(
        self,
        url: str,
        *,
        click_texts: tuple[str, ...],
        wait_for: str | None = None,
        consent_texts: tuple[str, ...] = (),
        referer: str | None = None,
    ) -> str:
        self.clicked.append((url, click_texts))
        return await self.fetch_html(
            url, referer=referer, wait_for=wait_for
        )

    async def fetch_text_direct(self, url: str, *, referer: str | None = None) -> str:
        """The plain-HTTP path, for adapters that need no browser."""
        self.direct.append(url)
        if url not in self.pages:
            raise RuntimeError(f"no fixture registered for direct GET {url}")
        return self.pages[url]

    async def fetch_json_direct(self, url: str, params=None):
        self.requested.append(url)
        for key, payload in self.json_routes.items():
            if key in url:
                return payload
        raise RuntimeError(f"no fixture registered for JSON {url}")

    async def post_form(self, url: str, data: dict, *, referer: str | None = None) -> str:
        self.posted.append((url, data))
        if url not in self.posts:
            raise RuntimeError(f"no fixture registered for POST {url}")
        return self.posts[url]


@pytest.fixture
def series_url() -> str:
    return "https://example.net/manga/example-series/"


@pytest.fixture
def madara_sessions(series_url):
    return FakeSessionManager(
        pages={
            series_url: fixture("madara_series.html"),
            "https://example.net/manga/example-series/chapter-1/": fixture("madara_reader.html"),
        },
        posts={
            series_url + "ajax/chapters/": fixture("madara_chapters.html"),
        },
    )


@pytest.fixture
def settings(tmp_path):
    """Real Settings object pointed at a temporary directory."""
    from app.config import Settings

    return Settings(
        output_dir=tmp_path / "manga",
        config_dir=tmp_path / "config",
    )


def make_png(width: int = 8, height: int = 8, color=(200, 30, 30)) -> bytes:
    """Generate a small valid PNG for packager tests."""
    import io

    from PIL import Image

    buffer = io.BytesIO()
    Image.new("RGB", (width, height), color).save(buffer, format="PNG")
    return buffer.getvalue()


def make_jpeg(width: int = 8, height: int = 8) -> bytes:
    import io

    from PIL import Image

    buffer = io.BytesIO()
    Image.new("RGB", (width, height), (10, 90, 200)).save(buffer, format="JPEG")
    return buffer.getvalue()


def make_noise_png(width: int = 120, height: int = 180) -> bytes:
    """A PNG that does not compress to almost nothing.

    A flat-colour image of any size collapses to a couple of hundred bytes,
    which is not representative of a real manga page and makes size-related
    behaviour hard to test honestly.
    """
    import io
    import os

    from PIL import Image

    image = Image.frombytes("RGB", (width, height), os.urandom(width * height * 3))
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()
