"""End-to-end pipeline test.

Runs the real JobQueue, Fetcher, packager and database against a local HTTP
server serving generated images. Only the browser/Cloudflare layer is faked,
since that is the one part that cannot work offline. This is what proves the
pieces actually fit together — the unit tests only pin them individually.
"""

from __future__ import annotations

import asyncio
import contextlib
import threading
import zipfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from xml.etree import ElementTree as ET

import pytest

from app.db import Database
from app.fetcher import Fetcher
from app.models import Chapter, ChapterStatus, JobStatus, Series
from app.queue import JobQueue

from .conftest import make_noise_png

PAGES_PER_CHAPTER = 4


class _Handler(BaseHTTPRequestHandler):
    """Serves /ch<N>/<page>.png, plus a deliberately broken page for failure tests."""

    requests: list[str] = []
    """Every path served, so a test can prove what was *not* re-downloaded."""

    def do_GET(self) -> None:  # noqa: N802 - stdlib naming
        _Handler.requests.append(self.path)
        if self.path.endswith(".pdf"):
            # A real-looking PDF, and — on the "wall" path — the HTML notice a
            # file host serves instead when it does not feel like cooperating.
            body = (b"<!DOCTYPE html><html><body>Please log in"
                    + b"<p>filler</p>" * 200 + b"</body></html>"
                    if "wall" in self.path else b"%PDF-1.7\n" + b"0" * 4096)
            self.send_response(200)
            self.send_header("Content-Type", "application/pdf")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        if self.path.endswith(".svg"):
            # A reader page: an SVG wrapping a base64 image, which is the shape
            # noor-book.com serves. Width varies with the page number so a test
            # can prove the pages were bound in the right order.
            import base64 as _b64
            import re as _re

            match = _re.search(r"/(\d+)/[^/]*\.svg$", self.path)
            number = int(match.group(1)) if match else 1
            encoded = _b64.b64encode(make_noise_png(100 + number, 150)).decode()
            body = (
                '<svg width="686" height="967" xmlns="http://www.w3.org/2000/svg">'
                '<image id="b" xlink:href="data:image/png;base64,'
                + encoded + '"/></svg>'
            ).encode()
            self.send_response(200)
            self.send_header("Content-Type", "image/svg+xml")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        if self.path.endswith("/broken.png"):
            # Truncated payload: passes the magic-byte sniff, fails validation.
            body = make_noise_png()[:400]
        elif self.path.endswith("/notfound.png"):
            self.send_error(404)
            return
        else:
            body = make_noise_png(120, 180)

        self.send_response(200)
        self.send_header("Content-Type", "image/png")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args) -> None:  # silence stderr noise
        pass


@pytest.fixture
def http_server():
    _Handler.requests.clear()
    server = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{server.server_port}"
    server.shutdown()
    server.server_close()


class StubSessions:
    """Minimal SessionManager stand-in — no cookies, no challenge."""

    user_agent = "pytest-agent"

    def __init__(self) -> None:
        self.refreshes = 0

    async def get_session(self, url, *, force=False):
        from app.session import HostSession

        return HostSession(host="127.0.0.1", cookies={}, user_agent="pytest-agent")

    async def peek_session(self, url):
        return await self.get_session(url)

    async def refresh(self, url):
        self.refreshes += 1
        return await self.get_session(url)


class StubAdapter:
    """Returns a fixed page list per chapter."""

    id = "stub"

    def __init__(self, base_url: str, broken_chapters: set[str] | None = None) -> None:
        self.base_url = base_url
        self.broken = broken_chapters or set()

    async def fetch_pages(self, chapter: Chapter):
        from app.models import Page

        if chapter.url in self.broken:
            return [Page(index=1, url=f"{self.base_url}/broken.png", referer=chapter.url)]
        return [
            Page(index=i, url=f"{self.base_url}/ch{chapter.index}/{i:03d}.png",
                 referer=chapter.url)
            for i in range(1, PAGES_PER_CHAPTER + 1)
        ]


class ExpiringAdapter:
    """Page URLs that only work until the node behind them drops out.

    Shaped like MangaDex@Home, which mints a URL naming one node per request:
    the first listing for a chapter points a page at a host that answers 404,
    and asking again returns a set that works.
    """

    id = "expiring"
    pages_expire = True

    def __init__(self, base_url: str) -> None:
        self.base_url = base_url
        self.listings: dict[str, int] = {}

    async def fetch_pages(self, chapter: Chapter):
        from app.models import Page

        count = self.listings.get(chapter.url, 0) + 1
        self.listings[chapter.url] = count
        stale = count == 1
        return [
            Page(
                index=i,
                url=(f"{self.base_url}/notfound.png" if stale and i == 2
                     else f"{self.base_url}/ch{chapter.index}/{i:03d}.png"),
                referer=chapter.url,
            )
            for i in range(1, PAGES_PER_CHAPTER + 1)
        ]

    async def refresh_pages(self, chapter: Chapter):
        return await self.fetch_pages(chapter)


class BookAdapter:
    """A book site: whole files, already the finished artifact."""

    id = "books"
    packaging = "file"

    def __init__(self, base_url: str) -> None:
        self.base_url = base_url

    async def fetch_pages(self, chapter: Chapter):
        from app.models import Page

        return [Page(index=1, url=f"{self.base_url}/files/{chapter.title}",
                     referer="https://books.example/agnes-grey/")]


class ReaderAdapter:
    """A site that serves a book only as reader pages, like noor-book.com.

    Declares ``pdf`` per chapter and unwraps each page, which is exactly the
    contract ``books`` implements for Noor.
    """

    id = "books"
    packaging = "file"
    PAGES = 6

    def __init__(self, base_url: str) -> None:
        self.base_url = base_url

    def packaging_for(self, chapter: Chapter) -> str:
        return "pdf" if chapter.url.endswith("#read") else self.packaging

    def transform_page(self, content: bytes) -> bytes:
        from app.adapters.books import _noor_unwrap

        return _noor_unwrap(content)

    async def fetch_pages(self, chapter: Chapter):
        from app.models import Page

        return [
            Page(index=n, url=f"{self.base_url}/book/read_book_image/0/hash/{n}/tok.svg",
                 referer="https://www.noor-book.com/en/ebook-x-pdf-1")
            for n in range(1, self.PAGES + 1)
        ]


@contextlib.asynccontextmanager
async def _wired(adapter, settings, monkeypatch):
    """A real queue, database and fetcher driven by ``adapter``."""
    settings.ensure_dirs()
    settings.requests_per_second = 200.0  # keep the test fast

    db = Database(settings.db_path)
    await db.connect()

    sessions = StubSessions()
    fetcher = Fetcher(settings, sessions)
    await fetcher.start()

    queue = JobQueue(settings, db, sessions, fetcher)

    async def fake_resolve(url, session_manager):
        return adapter

    monkeypatch.setattr("app.queue.resolve_adapter", fake_resolve)
    try:
        yield queue, db, settings, adapter
    finally:
        await queue.shutdown()
        await fetcher.close()
        await db.close()


@pytest.fixture
async def pipeline(settings, http_server, monkeypatch):
    """Wire up a real queue with a stubbed adapter and session layer."""
    async with _wired(StubAdapter(http_server), settings, monkeypatch) as wired:
        yield wired


@pytest.fixture
async def expiring_pipeline(settings, http_server, monkeypatch):
    """The same, driven by an adapter whose page URLs go stale."""
    async with _wired(ExpiringAdapter(http_server), settings, monkeypatch) as wired:
        yield wired


@pytest.fixture
async def book_pipeline(settings, http_server, monkeypatch):
    """The same, driven by a book adapter that yields whole files."""
    async with _wired(BookAdapter(http_server), settings, monkeypatch) as wired:
        yield wired


def _series() -> Series:
    return Series(
        url="https://example.net/manga/example-series/",
        title="Example Series",
        source="stub",
        author="Placeholder Author",
    )


def _chapters(count: int) -> list[Chapter]:
    return [
        Chapter(
            url=f"https://example.net/manga/example-series/chapter-{i}/",
            title=f"Chapter {i}",
            number=str(i),
            index=i,
        )
        for i in range(1, count + 1)
    ]


async def _await_job(queue: JobQueue, job_id: int, timeout: float = 30.0) -> None:
    async with asyncio.timeout(timeout):
        while True:
            job = queue.get(job_id)
            if job and job.status in (
                JobStatus.DONE, JobStatus.FAILED, JobStatus.CANCELLED
            ):
                return
            await asyncio.sleep(0.05)


# ------------------------------------------------------------------- tests


async def test_full_download_produces_valid_cbz_files(pipeline):
    queue, db, settings, _ = pipeline
    series = _series()

    job = await queue.create_job(series, _chapters(3))
    await _await_job(queue, job.id)

    assert job.status == JobStatus.DONE

    folder = settings.output_dir / "Example Series"
    archives = sorted(folder.glob("*.cbz"))
    assert [a.name for a in archives] == [
        "Example Series - c001.cbz",
        "Example Series - c002.cbz",
        "Example Series - c003.cbz",
    ]

    with zipfile.ZipFile(archives[0]) as archive:
        names = [n for n in archive.namelist() if n != "ComicInfo.xml"]
        assert names == ["001.png", "002.png", "003.png", "004.png"]

        info = ET.fromstring(archive.read("ComicInfo.xml"))
        assert info.findtext("Series") == "Example Series"
        assert info.findtext("Number") == "001"
        assert info.findtext("PageCount") == str(PAGES_PER_CHAPTER)
        # StubAdapter declares no direction of its own, so this is the global
        # settings fallback, which defaults to left-to-right.
        assert info.findtext("Manga") == "Yes"


async def test_no_partial_artefacts_remain(pipeline):
    queue, _, settings, _ = pipeline

    job = await queue.create_job(_series(), _chapters(2))
    await _await_job(queue, job.id)

    assert not list(settings.output_dir.rglob(".part-*"))
    assert not list(settings.output_dir.rglob("*.tmp"))


async def test_rerun_skips_completed_chapters(pipeline):
    """Resumability: the second pass must not refetch what is already on disk."""
    queue, db, settings, _ = pipeline
    series = _series()
    chapters = _chapters(2)

    first = await queue.create_job(series, chapters)
    await _await_job(queue, first.id)
    archive = settings.output_dir / "Example Series" / "Example Series - c001.cbz"
    original_mtime = archive.stat().st_mtime_ns

    second = await queue.create_job(series, chapters)
    await _await_job(queue, second.id)

    assert second.status == JobStatus.DONE
    assert all(p.status == ChapterStatus.DONE for p in second.progress.values())
    # Untouched file proves the skip path ran rather than a silent re-download.
    assert archive.stat().st_mtime_ns == original_mtime


async def test_corrupt_page_fails_its_chapter_only(pipeline):
    """A bad page must fail loudly, not seal a CBZ with a hole in it."""
    queue, db, settings, adapter = pipeline
    chapters = _chapters(3)
    adapter.broken = {chapters[1].url}

    job = await queue.create_job(_series(), chapters)
    await _await_job(queue, job.id)

    assert job.status == JobStatus.FAILED
    assert job.progress[chapters[1].url].status == ChapterStatus.FAILED
    assert job.progress[chapters[0].url].status == ChapterStatus.DONE
    assert job.progress[chapters[2].url].status == ChapterStatus.DONE

    # The failed chapter must not have produced an archive at all.
    folder = settings.output_dir / "Example Series"
    assert not (folder / "Example Series - c002.cbz").exists()
    assert (folder / "Example Series - c001.cbz").is_file()


async def test_expired_page_urls_are_relisted_and_the_chapter_survives(
    expiring_pipeline,
):
    """A dead node must cost one re-listing, not the whole chapter.

    MangaDex@Home picks a node per request, so a page that 404s is a stale URL
    rather than a missing page — asking the adapter again fixes it.
    """
    queue, _, settings, adapter = expiring_pipeline
    chapters = _chapters(2)

    job = await queue.create_job(_series(), chapters)
    await _await_job(queue, job.id)

    assert job.status == JobStatus.DONE
    assert adapter.listings == {c.url: 2 for c in chapters}

    archive = settings.output_dir / "Example Series" / "Example Series - c001.cbz"
    with zipfile.ZipFile(archive) as opened:
        names = [n for n in opened.namelist() if n != "ComicInfo.xml"]
        assert len(names) == PAGES_PER_CHAPTER

    # Only the casualty is refetched: pages already in hand are not downloaded
    # a second time just because a sibling failed.
    assert _Handler.requests.count("/ch1/001.png") == 1
    assert _Handler.requests.count("/ch1/002.png") == 1


async def test_a_stable_adapter_is_never_asked_to_relist(pipeline):
    """Re-listing a site that serves fixed paths returns the same dead URL."""
    queue, _, _, adapter = pipeline
    chapters = _chapters(1)
    adapter.broken = {chapters[0].url}
    adapter.refresh_pages = None  # calling it would raise TypeError

    job = await queue.create_job(_series(), chapters)
    await _await_job(queue, job.id)

    assert job.status == JobStatus.FAILED


async def test_a_book_is_written_through_not_packaged(book_pipeline):
    """No archive, no ComicInfo: the downloaded file is the artifact."""
    queue, _, settings, _ = book_pipeline
    series = Series(url="https://books.example/agnes-grey/", title="Agnes Grey",
                    source="books")
    chapters = [
        Chapter(url=f"{series.url}#1", title="agnes-grey.pdf", index=1),
        Chapter(url=f"{series.url}#2", title="agnes-grey2.pdf", index=2),
    ]

    job = await queue.create_job(series, chapters)
    await _await_job(queue, job.id)

    assert job.status == JobStatus.DONE
    folder = settings.output_dir / "Agnes Grey"
    assert sorted(p.name for p in folder.iterdir()) == [
        "agnes-grey.pdf", "agnes-grey2.pdf"]
    assert (folder / "agnes-grey.pdf").read_bytes().startswith(b"%PDF-")
    assert not list(folder.glob("*.cbz"))


async def test_a_login_wall_served_as_a_pdf_is_a_failure(book_pipeline):
    """200 OK and HTML: storing that would leave an unreadable "book"."""
    queue, _, settings, _ = book_pipeline
    series = Series(url="https://books.example/agnes-grey/", title="Agnes Grey",
                    source="books")
    chapter = Chapter(url=f"{series.url}#1", title="wall.pdf", index=1)

    job = await queue.create_job(series, [chapter])
    await _await_job(queue, job.id)

    assert job.status == JobStatus.FAILED
    assert "did not return a PDF" in (job.progress[chapter.url].error or "")
    assert not (settings.output_dir / "Agnes Grey" / "wall.pdf").exists()


async def test_a_downloaded_book_is_not_fetched_twice(book_pipeline):
    queue, _, settings, _ = book_pipeline
    series = Series(url="https://books.example/agnes-grey/", title="Agnes Grey",
                    source="books")
    chapters = [Chapter(url=f"{series.url}#1", title="agnes-grey.pdf", index=1)]

    first = await queue.create_job(series, chapters)
    await _await_job(queue, first.id)
    served = _Handler.requests.count("/files/agnes-grey.pdf")

    second = await queue.create_job(series, chapters)
    await _await_job(queue, second.id)

    assert second.status == JobStatus.DONE
    assert _Handler.requests.count("/files/agnes-grey.pdf") == served


async def test_retry_failed_recovers_after_fix(pipeline):
    queue, _, settings, adapter = pipeline
    chapters = _chapters(2)
    adapter.broken = {chapters[0].url}

    job = await queue.create_job(_series(), chapters)
    await _await_job(queue, job.id)
    assert job.status == JobStatus.FAILED

    adapter.broken = set()  # simulate the site recovering
    retried = await queue.retry_failed(job.id)
    assert retried == 1
    await _await_job(queue, job.id)

    assert job.status == JobStatus.DONE
    assert (settings.output_dir / "Example Series" / "Example Series - c001.cbz").is_file()


async def test_database_records_chapter_outcomes(pipeline):
    queue, db, _, adapter = pipeline
    series = _series()
    chapters = _chapters(2)
    adapter.broken = {chapters[1].url}

    job = await queue.create_job(series, chapters)
    await _await_job(queue, job.id)

    states = await db.get_chapter_states(series.url)
    assert states[chapters[0].url]["status"] == "done"
    assert states[chapters[0].url]["output_path"].endswith("c001.cbz")
    assert states[chapters[1].url]["status"] == "failed"
    assert states[chapters[1].url]["error"]


async def test_progress_events_are_emitted(pipeline):
    queue, _, _, _ = pipeline
    events: list[dict] = []

    async def collect(event: dict) -> None:
        events.append(event)

    queue.subscribe(collect)
    job = await queue.create_job(_series(), _chapters(1))
    await _await_job(queue, job.id)

    kinds = {e["type"] for e in events}
    assert "job_created" in kinds
    assert "chapter_progress" in kinds

    page_counts = [
        e["chapter"]["pages_done"] for e in events if e["type"] == "chapter_progress"
    ]
    assert max(page_counts) == PAGES_PER_CHAPTER


async def test_cancel_stops_a_running_job(pipeline):
    queue, _, _, _ = pipeline

    job = await queue.create_job(_series(), _chapters(8))
    await asyncio.sleep(0.05)
    assert await queue.cancel(job.id)

    assert job.status == JobStatus.CANCELLED


async def test_a_finished_job_cannot_be_cancelled(pipeline):
    """A job finishes on its own schedule, so Cancel outlives the work.

    The button is only rendered while the job is active, but the render is a
    snapshot: click it a moment after the last chapter lands and, unguarded,
    the call rewrote a completed download as 'cancelled' and answered 200 —
    reporting a job that fully succeeded as one the user stopped.
    """
    queue, _, _, _ = pipeline

    job = await queue.create_job(_series(), _chapters(1))
    await _wait_for_job(queue, job)
    assert job.status == JobStatus.DONE

    assert await queue.cancel(job.id) is False
    assert job.status == JobStatus.DONE


async def test_reset_running_chapters_after_unclean_shutdown(pipeline):
    """Startup recovery: interrupted chapters become retryable, not stuck."""
    queue, db, _, _ = pipeline
    series = _series()
    chapters = _chapters(1)
    await db.upsert_series(series)
    await db.upsert_chapters(series.url, chapters)
    await db.set_chapter_status(chapters[0].url, "running")

    recovered = await db.reset_running_chapters()

    assert recovered == 1
    states = await db.get_chapter_states(series.url)
    assert states[chapters[0].url]["status"] == "pending"


# ------------------------------------------------------- queue housekeeping


async def test_finished_jobs_can_be_removed(pipeline):
    queue, _, _, _ = pipeline

    job = await queue.create_job(_series(), _chapters(1))
    await _wait_for_job(queue, job)

    assert await queue.remove(job.id) is True
    assert queue.get(job.id) is None
    assert queue.list_jobs() == []


async def test_removing_a_job_frees_its_bookkeeping(pipeline):
    """_tasks and _pause_flags grew forever alongside _jobs."""
    queue, _, _, _ = pipeline

    job = await queue.create_job(_series(), _chapters(1))
    await _wait_for_job(queue, job)
    await queue.remove(job.id)

    assert job.id not in queue._tasks
    assert job.id not in queue._pause_flags


async def test_an_active_job_cannot_be_removed(pipeline):
    """Removing a running job would abandon a download mid-chapter."""
    queue, _, _, _ = pipeline

    job = await queue.create_job(_series(), _chapters(8))
    await asyncio.sleep(0.05)

    assert await queue.remove(job.id) is False
    assert queue.get(job.id) is job


async def test_stop_all_cancels_everything_in_flight(pipeline):
    queue, _, _, _ = pipeline

    first = await queue.create_job(_series(), _chapters(8))
    second = await queue.create_job(_series(), _chapters(8))
    await asyncio.sleep(0.05)

    assert await queue.stop_all() == 2
    assert first.status == JobStatus.CANCELLED
    assert second.status == JobStatus.CANCELLED
    # The tasks must actually be finished, not merely asked to stop, or a
    # following clear would drop the handle on a worker still writing.
    assert all(task.done() for task in queue._tasks.values())


async def test_clear_leaves_active_jobs_alone_by_default(pipeline):
    queue, _, _, _ = pipeline

    finished = await queue.create_job(_series(), _chapters(1))
    await _wait_for_job(queue, finished)
    running = await queue.create_job(_series(), _chapters(8))
    await asyncio.sleep(0.05)

    result = await queue.clear()

    assert result == {"stopped": 0, "removed": 1}
    assert queue.get(running.id) is running
    assert queue.get(finished.id) is None


async def test_clear_all_stops_then_empties(pipeline):
    queue, _, _, _ = pipeline

    await queue.create_job(_series(), _chapters(8))
    await queue.create_job(_series(), _chapters(8))
    await asyncio.sleep(0.05)

    result = await queue.clear(finished_only=False)

    assert result["stopped"] == 2
    assert result["removed"] == 2
    assert queue.list_jobs() == []


async def test_clearing_never_touches_downloaded_files(pipeline):
    """A job is bookkeeping, not the archives it produced.

    "Delete" means removing files over in the Library; here it must not.
    """
    queue, db, settings, _ = pipeline

    job = await queue.create_job(_series(), _chapters(2))
    await _wait_for_job(queue, job)
    before = sorted(p.name for p in settings.output_dir.rglob("*.cbz"))
    assert before

    await queue.clear()

    assert sorted(p.name for p in settings.output_dir.rglob("*.cbz")) == before
    states = await db.get_chapter_states(_series().url)
    assert all(row["status"] == "done" for row in states.values())


async def _wait_for_job(queue, job, timeout=15.0):
    deadline = asyncio.get_running_loop().time() + timeout
    while asyncio.get_running_loop().time() < deadline:
        if job.status not in (JobStatus.QUEUED, JobStatus.RUNNING, JobStatus.PAUSED):
            return
        await asyncio.sleep(0.05)
    raise AssertionError(f"job stayed {job.status}")


# ------------------------------------------------------------ library joining
# Previewing writes the same series and chapter rows a download does, so row
# existence cannot be what puts a series in the Library — clicking a search
# result would file something you have never downloaded. Proved here against
# the real database rather than only at the SQL level.


async def test_previewing_does_not_add_a_series_to_the_library(pipeline):
    """`preview_series` writes exactly this, and it must stay invisible."""
    _queue, db, _settings, _ = pipeline
    series = _series()

    await db.upsert_series(series)
    await db.upsert_chapters(series.url, _chapters(3))

    assert await db.list_series() == []


async def test_a_real_download_puts_the_series_in_the_library(pipeline):
    queue, db, _settings, _ = pipeline
    series = _series()

    await db.upsert_series(series)
    await db.upsert_chapters(series.url, _chapters(3))
    assert await db.list_series() == [], "not before anything is downloaded"

    job = await queue.create_job(series, _chapters(2))
    await _await_job(queue, job.id)
    assert job.status == JobStatus.DONE

    rows = await db.list_series()
    assert [row["title"] for row in rows] == ["Example Series"]
    assert rows[0]["downloaded_count"] == 2
    # The full chapter list the preview recorded, not just what was queued.
    assert rows[0]["chapter_count"] == 3


async def test_a_job_that_downloads_nothing_stays_out_of_the_library(pipeline):
    """A chapter that only ever fails is not a download."""
    queue, db, _settings, adapter = pipeline
    series = _series()
    chapters = _chapters(2)
    adapter.broken = {c.url for c in chapters}   # every page is corrupt

    job = await queue.create_job(series, chapters)
    await _await_job(queue, job.id)

    assert job.status == JobStatus.FAILED
    assert all(job.progress[c.url].status == ChapterStatus.FAILED for c in chapters)
    assert await db.list_series() == []


# ------------------------------------------- a book bound from reader pages
# Noor's download control is account-gated and on a live book produced no link
# at all, while its reader served the same book's 124 pages. So the whole book
# arrives as page images and has to be bound into one document.


@pytest.fixture
async def reader_pipeline(settings, http_server, monkeypatch):
    async with _wired(ReaderAdapter(http_server), settings, monkeypatch) as wired:
        yield wired


def _read_series() -> Series:
    return Series(url="https://www.noor-book.com/en/ebook-x-pdf-1",
                  title="The Stranger", source="books")


def _read_chapter() -> Chapter:
    return Chapter(url="https://www.noor-book.com/en/ebook-x-pdf-1#read",
                   title="The Stranger.pdf", index=1)


async def test_a_reader_book_lands_as_one_pdf(reader_pipeline):
    queue, _, settings, _ = reader_pipeline
    series, chapter = _read_series(), _read_chapter()

    job = await queue.create_job(series, [chapter])
    await _await_job(queue, job.id)

    assert job.status == JobStatus.DONE
    out = settings.output_dir / "The Stranger" / "The Stranger.pdf"
    assert out.is_file(), list((settings.output_dir / "The Stranger").iterdir())
    body = out.read_bytes()
    assert body.startswith(b"%PDF-")
    assert body.rstrip().endswith(b"%%EOF")
    # Not a CBZ, and not one file per page.
    assert not list((settings.output_dir / "The Stranger").glob("*.cbz"))


async def test_every_reader_page_is_in_the_book(reader_pipeline):
    import re

    queue, _, settings, _ = reader_pipeline
    job = await queue.create_job(_read_series(), [_read_chapter()])
    await _await_job(queue, job.id)

    body = (settings.output_dir / "The Stranger" / "The Stranger.pdf").read_bytes()
    assert len(re.findall(rb"/Type\s*/Page(?![s/\w])", body)) == ReaderAdapter.PAGES
    # Widths encode the page number, so this also pins the order.
    widths = [int(w) for w in re.findall(rb"/Width\s+(\d+)", body)]
    assert widths == [101, 102, 103, 104, 105, 106]


async def test_the_pages_are_unwrapped_not_stored_as_svg(reader_pipeline):
    """Without the adapter's transform every page fails image validation."""
    queue, _, settings, _ = reader_pipeline
    job = await queue.create_job(_read_series(), [_read_chapter()])
    await _await_job(queue, job.id)

    progress = job.progress[_read_chapter().url]
    assert progress.status == ChapterStatus.DONE
    assert progress.pages_done == ReaderAdapter.PAGES
    assert b"<svg" not in (
        settings.output_dir / "The Stranger" / "The Stranger.pdf").read_bytes()[:2048]


async def test_a_finished_book_is_not_downloaded_again(reader_pipeline):
    queue, _, settings, _ = reader_pipeline
    series, chapter = _read_series(), _read_chapter()

    first = await queue.create_job(series, [chapter])
    await _await_job(queue, first.id)
    served = len([p for p in _Handler.requests if p.endswith(".svg")])
    assert served >= ReaderAdapter.PAGES

    second = await queue.create_job(series, [chapter])
    await _await_job(queue, second.id)

    assert second.status == JobStatus.DONE
    assert len([p for p in _Handler.requests if p.endswith(".svg")]) == served


async def test_a_reader_book_joins_the_library(reader_pipeline):
    queue, db, _, _ = reader_pipeline
    series = _read_series()

    job = await queue.create_job(series, [_read_chapter()])
    await _await_job(queue, job.id)

    rows = await db.list_series()
    assert [row["url"] for row in rows] == [series.url]
    assert rows[0]["downloaded_count"] == 1


async def test_packaging_may_be_decided_asynchronously():
    """A platform's theme cannot say whether a chapter is pictures or prose.

    Several web-novel sites run a manga platform's markup, so for those
    adapters the honest answer requires opening the chapter. The queue awaits
    a hook that answers asynchronously and calls a plain one plainly, so every
    existing adapter keeps its synchronous one-liner.
    """
    chapter = Chapter(url="https://example.net/c/1/", title="1", number="1", index=1)

    class Sync:
        packaging = "cbz"

        def packaging_for(self, chapter):
            return "pdf"

    class Async:
        packaging = "cbz"

        async def packaging_for(self, chapter):
            return "text"

    class Neither:
        packaging = "file"

    assert await JobQueue._packaging_for(Sync(), chapter) == "pdf"
    assert await JobQueue._packaging_for(Async(), chapter) == "text"
    assert await JobQueue._packaging_for(Neither(), chapter) == "file"
