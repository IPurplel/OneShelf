"""Download queue and worker pool.

One job = one series plus the chapters selected for it. Chapters are processed
by a bounded pool of workers, and within a chapter its pages are fetched
concurrently under a second bound. Defaults are modest (2 chapters x 6 images)
because the bottleneck that actually matters is the site's tolerance, not local
throughput.

State lives in SQLite, so an interrupted run resumes: a chapter whose CBZ
already exists and passes an integrity check is skipped rather than refetched.
"""

from __future__ import annotations

import asyncio
import contextlib
import inspect
import logging
from pathlib import Path
from typing import Any, Awaitable, Callable

from .adapters import resolve as resolve_adapter
from .fetcher import DownloadError, SessionRejected, pick_extension
from .models import (
    Chapter,
    ChapterProgress,
    ChapterStatus,
    Job,
    JobStatus,
    Series,
)
from .packager import (
    LIBRARY_EXTENSIONS,
    ChapterWorkspace,
    PageFile,
    PackagingError,
    book_path,
    build_comicinfo,
    chapter_path,
    looks_like_document,
    sweep_partials,
    text_path,
    validate_image,
    verify_cbz,
    verify_epub,
    verify_file,
    verify_pdf,
    write_cbz,
    write_epub,
    write_file,
    write_pdf,
)

log = logging.getLogger(__name__)

#: Statuses where a job still has work in flight, so it must not be removed
#: from under a running worker.
ACTIVE_STATUSES = (JobStatus.QUEUED, JobStatus.RUNNING, JobStatus.PAUSED)

#: How many times to re-ask an adapter for page URLs after a failed download.
#: Only for adapters whose URLs expire (``Adapter.pages_expire``); two rounds
#: covers one unlucky node without turning a genuinely missing page into a
#: minutes-long retry storm.
PAGE_REFRESH_ROUNDS = 2

EventCallback = Callable[[dict[str, Any]], Awaitable[None]]


class JobQueue:
    """Owns all in-flight and completed jobs for the process lifetime."""

    def __init__(self, settings, db, session_manager, fetcher) -> None:
        self._settings = settings
        self._db = db
        self._sessions = session_manager
        self._fetcher = fetcher

        self._jobs: dict[int, Job] = {}
        self._tasks: dict[int, asyncio.Task] = {}
        self._pause_flags: dict[int, asyncio.Event] = {}
        self._next_id = 1
        self._listeners: list[EventCallback] = []
        self._lock = asyncio.Lock()

    # ---------------------------------------------------------------- events

    def subscribe(self, callback: EventCallback) -> None:
        self._listeners.append(callback)

    def unsubscribe(self, callback: EventCallback) -> None:
        with contextlib.suppress(ValueError):
            self._listeners.remove(callback)

    async def _emit(self, event: dict[str, Any]) -> None:
        for listener in list(self._listeners):
            try:
                await listener(event)
            except Exception:  # a dead websocket must not stall downloads
                log.debug("Event listener failed", exc_info=True)

    # ------------------------------------------------------------- job admin

    async def create_job(self, series: Series, chapters: list[Chapter]) -> Job:
        async with self._lock:
            job_id = self._next_id
            self._next_id += 1

        job = Job(id=job_id, series=series, chapters=chapters)
        job.progress = {
            c.url: ChapterProgress(chapter_url=c.url, title=c.title)
            for c in chapters
        }
        self._jobs[job_id] = job

        pause = asyncio.Event()
        pause.set()  # set == running; cleared == paused
        self._pause_flags[job_id] = pause

        await self._db.upsert_series(series)
        await self._db.upsert_chapters(series.url, chapters)

        self._tasks[job_id] = asyncio.create_task(self._run_job(job))
        await self._emit({"type": "job_created", "job": job.summary()})
        return job

    def get(self, job_id: int) -> Job | None:
        return self._jobs.get(job_id)

    def list_jobs(self) -> list[dict[str, Any]]:
        return [job.summary() for job in self._jobs.values()]

    def job_detail(self, job_id: int) -> dict[str, Any] | None:
        job = self._jobs.get(job_id)
        if job is None:
            return None
        return {
            **job.summary(),
            "chapters": [p.to_dict() for p in job.progress.values()],
        }

    async def pause(self, job_id: int) -> bool:
        flag = self._pause_flags.get(job_id)
        job = self._jobs.get(job_id)
        if not flag or not job or job.status not in (JobStatus.RUNNING, JobStatus.QUEUED):
            return False
        flag.clear()
        job.status = JobStatus.PAUSED
        await self._emit({"type": "job_updated", "job": job.summary()})
        return True

    async def resume(self, job_id: int) -> bool:
        flag = self._pause_flags.get(job_id)
        job = self._jobs.get(job_id)
        if not flag or not job or job.status != JobStatus.PAUSED:
            return False
        flag.set()
        job.status = JobStatus.RUNNING
        await self._emit({"type": "job_updated", "job": job.summary()})
        return True

    async def cancel(self, job_id: int) -> bool:
        """Stop a job that still has work in flight.

        The status guard is not redundant with the UI hiding the button. A job
        finishes on its own schedule, so the Cancel offered by the last render
        can be clicked a moment after the last chapter lands — and without this,
        that click rewrote a completed job as ``cancelled`` and answered 200, so
        a download that fully succeeded was reported to the user as stopped.
        """
        task = self._tasks.get(job_id)
        job = self._jobs.get(job_id)
        if not task or not job or job.status not in ACTIVE_STATUSES:
            return False
        # Un-pause first, otherwise workers block on the gate and never observe
        # the cancellation.
        flag = self._pause_flags.get(job_id)
        if flag:
            flag.set()
        task.cancel()
        job.status = JobStatus.CANCELLED
        await self._emit({"type": "job_updated", "job": job.summary()})
        return True

    async def retry_failed(self, job_id: int) -> int:
        job = self._jobs.get(job_id)
        if job is None or job.status in (JobStatus.RUNNING, JobStatus.QUEUED):
            return 0

        failed = [
            c for c in job.chapters
            if job.progress[c.url].status == ChapterStatus.FAILED
        ]
        if not failed:
            return 0

        for chapter in failed:
            job.progress[chapter.url] = ChapterProgress(
                chapter_url=chapter.url, title=chapter.title
            )
        job.status = JobStatus.QUEUED
        job.error = None
        flag = self._pause_flags.setdefault(job_id, asyncio.Event())
        flag.set()
        self._tasks[job_id] = asyncio.create_task(self._run_job(job, only=failed))
        await self._emit({"type": "job_updated", "job": job.summary()})
        return len(failed)

    async def remove(self, job_id: int) -> bool:
        """Drop a finished job from the queue.

        Clears the job's task and pause-flag entries too. Nothing removed
        those before, so they grew for the life of the process alongside
        ``_jobs`` — a slow leak masked by the app usually being restarted.

        Refuses while the job is still active. Stopping is a separate,
        deliberate act that the UI offers first, so removing can never
        silently abandon a download mid-chapter.

        Downloaded archives and chapter rows are untouched: a job is
        bookkeeping, not the files it produced.
        """
        job = self._jobs.get(job_id)
        if job is None or job.status in ACTIVE_STATUSES:
            return False
        self._forget(job_id)
        await self._emit({"type": "jobs_changed"})
        return True

    async def stop_all(self) -> int:
        """Cancel every job that still has work in flight."""
        pending = []
        stopped = 0
        for job_id, job in list(self._jobs.items()):
            if job.status not in ACTIVE_STATUSES:
                continue
            task = self._tasks.get(job_id)
            if await self.cancel(job_id):
                stopped += 1
                if task is not None:
                    pending.append(task)

        if pending:
            # Wait for the cancellations to actually land. cancel() only
            # requests it; a caller that cleared immediately afterwards would
            # drop our handle on a worker still writing to disk.
            await asyncio.gather(*pending, return_exceptions=True)
        return stopped

    async def clear(self, *, finished_only: bool = True) -> dict[str, int]:
        """Remove jobs from the queue, optionally stopping active ones first.

        Returns what actually happened rather than what was asked for.
        """
        stopped = await self.stop_all() if not finished_only else 0

        removed = 0
        for job_id, job in list(self._jobs.items()):
            if job.status in ACTIVE_STATUSES:
                continue
            self._forget(job_id)
            removed += 1

        if removed and not self.has_active:
            # A cancelled chapter leaves a .part directory and a .tmp archive
            # behind. Only safe with nothing running: those belong to whichever
            # job owns them, and sweeping mid-download would delete live work.
            swept = sweep_partials(self._settings.output_dir)
            if swept:
                log.info("Swept %d partial file(s) after clearing the queue", swept)

        await self._emit({"type": "jobs_changed"})
        return {"stopped": stopped, "removed": removed}

    @property
    def has_active(self) -> bool:
        return any(job.status in ACTIVE_STATUSES for job in self._jobs.values())

    def _forget(self, job_id: int) -> None:
        self._jobs.pop(job_id, None)
        self._tasks.pop(job_id, None)
        self._pause_flags.pop(job_id, None)

    async def shutdown(self) -> None:
        for task in self._tasks.values():
            task.cancel()
        if self._tasks:
            await asyncio.gather(*self._tasks.values(), return_exceptions=True)

    # ------------------------------------------------------------ execution

    async def _run_job(self, job: Job, only: list[Chapter] | None = None) -> None:
        chapters = only if only is not None else job.chapters
        job.status = JobStatus.RUNNING
        await self._emit({"type": "job_updated", "job": job.summary()})

        try:
            adapter = await resolve_adapter(job.series.url, self._sessions)
            semaphore = asyncio.Semaphore(max(self._settings.chapter_concurrency, 1))

            async def worker(chapter: Chapter) -> None:
                async with semaphore:
                    await self._pause_flags[job.id].wait()
                    await self._process_chapter(job, adapter, chapter)

            await asyncio.gather(*(worker(c) for c in chapters))

            statuses = {p.status for p in job.progress.values()}
            if ChapterStatus.FAILED in statuses:
                job.status = JobStatus.FAILED
                failed = sum(
                    1 for p in job.progress.values() if p.status == ChapterStatus.FAILED
                )
                job.error = f"{failed} chapter(s) failed"
            else:
                job.status = JobStatus.DONE

        except asyncio.CancelledError:
            job.status = JobStatus.CANCELLED
            for progress in job.progress.values():
                if progress.status in (ChapterStatus.PENDING, ChapterStatus.RUNNING):
                    progress.status = ChapterStatus.CANCELLED
            raise
        except Exception as exc:
            log.exception("Job %d failed", job.id)
            job.status = JobStatus.FAILED
            job.error = str(exc)
        finally:
            await self._emit({"type": "job_updated", "job": job.summary()})

    @staticmethod
    async def _packaging_for(adapter, chapter: Chapter) -> str:
        """What to build from this chapter: ``cbz``, ``file``, ``pdf`` or ``text``.

        Asked per chapter rather than read off the class, because ``books``
        serves both shapes: most of its sites link a finished PDF, while Noor
        exposes a book only through its page-by-page reader.

        **May answer asynchronously.** A platform's theme says how to find a
        chapter and cannot say what is inside it — several web-novel sites run
        a manga platform's markup — so for those adapters the honest answer
        requires opening the chapter. Awaited when the hook returns an
        awaitable, called plainly when it does not, so every existing adapter
        keeps its synchronous one-liner.
        """
        chosen = getattr(adapter, "packaging_for", None)
        if callable(chosen):
            result = chosen(chapter)
            if inspect.isawaitable(result):
                return await result
            return result
        return getattr(adapter, "packaging", "cbz")

    async def _process_chapter(self, job: Job, adapter, chapter: Chapter) -> None:
        # A book is not a chapter of anything: the site serves one file that is
        # already the finished artifact, so there are no pages to order and no
        # archive to build. Everything around it — resume, progress, the
        # database, failure handling — is the same, which is why it forks here
        # and nowhere else.
        packaging = await self._packaging_for(adapter, chapter)
        if packaging == "file":
            await self._process_file(job, adapter, chapter)
            return
        if packaging == "text":
            await self._process_text(job, adapter, chapter)
            return

        progress = job.progress[chapter.url]
        # A PDF is bound from pages exactly like a CBZ, so everything below is
        # shared; only the last step and the extension differ.
        as_pdf = packaging == "pdf"
        destination = (book_path(self._settings.output_dir, job.series, chapter)
                       if as_pdf
                       else chapter_path(self._settings.output_dir, job.series, chapter))

        # Resume: a valid artifact already on disk needs no work.
        if verify_pdf(destination) if as_pdf else verify_cbz(destination):
            progress.status = ChapterStatus.DONE
            progress.output_path = str(destination)
            with contextlib.suppress(Exception):
                import zipfile
                with zipfile.ZipFile(destination) as archive:
                    pages = [
                        n for n in archive.namelist() if not n.endswith("ComicInfo.xml")
                    ]
                progress.pages_total = progress.pages_done = len(pages)
            await self._db.set_chapter_status(
                chapter.url, ChapterStatus.DONE.value, output_path=str(destination)
            )
            await self._emit_chapter(job, progress)
            log.info("Skipping %s (already downloaded)", destination.name)
            return

        progress.status = ChapterStatus.RUNNING
        progress.error = None
        await self._db.set_chapter_status(chapter.url, ChapterStatus.RUNNING.value)
        await self._emit_chapter(job, progress)

        try:
            pages = await adapter.fetch_pages(chapter)
            progress.pages_total = len(pages)
            progress.pages_done = 0
            await self._emit_chapter(job, progress)

            files = await self._download_pages(job, adapter, chapter, pages, progress)

            if as_pdf:
                # No ComicInfo: it describes a comic, and this is a book bound
                # from the pages its own reader serves.
                with ChapterWorkspace(destination.parent, f"{chapter.index:04d}"):
                    write_pdf(destination, files)
            else:
                # An adapter that knows its material overrides the global
                # setting: a single flag cannot be right for both manga
                # (right-to-left) and Western comics (left-to-right).
                direction = self._settings.right_to_left
                if getattr(adapter, "right_to_left", None) is not None:
                    direction = adapter.right_to_left

                comicinfo = build_comicinfo(
                    job.series,
                    chapter,
                    len(files),
                    language=self._settings.language,
                    right_to_left=direction,
                )
                with ChapterWorkspace(destination.parent, f"{chapter.index:04d}"):
                    write_cbz(destination, files, comicinfo)

            progress.status = ChapterStatus.DONE
            progress.output_path = str(destination)
            await self._db.set_chapter_status(
                chapter.url,
                ChapterStatus.DONE.value,
                pages_total=len(files),
                output_path=str(destination),
            )
            log.info("Wrote %s (%d pages)", destination.name, len(files))

        except asyncio.CancelledError:
            progress.status = ChapterStatus.CANCELLED
            await self._db.set_chapter_status(chapter.url, ChapterStatus.CANCELLED.value)
            raise
        except (DownloadError, PackagingError, SessionRejected, Exception) as exc:
            progress.status = ChapterStatus.FAILED
            progress.error = str(exc)
            await self._db.set_chapter_status(
                chapter.url, ChapterStatus.FAILED.value, error=str(exc)
            )
            log.warning("Chapter failed (%s): %s", chapter.title, exc)

        await self._emit_chapter(job, progress)

    async def _process_text(self, job: Job, adapter, chapter: Chapter) -> None:
        """Fetch one prose chapter and bind it into an EPUB.

        Deliberately shaped like :meth:`_process_file` rather than like the
        page pipeline: there is nothing to download in parallel and nothing to
        order, because the adapter hands back the whole chapter already in
        reading order. What it keeps from the page pipeline is everything the
        user sees — resume, progress, cancellation and the same failure
        reporting — so a novel behaves like every other job in the queue.
        """
        progress = job.progress[chapter.url]
        destination = text_path(self._settings.output_dir, job.series, chapter)

        if verify_epub(destination):
            progress.status = ChapterStatus.DONE
            progress.output_path = str(destination)
            progress.pages_total = progress.pages_done = 1
            await self._db.set_chapter_status(
                chapter.url, ChapterStatus.DONE.value, output_path=str(destination)
            )
            await self._emit_chapter(job, progress)
            log.info("Skipping %s (already downloaded)", destination.name)
            return

        progress.status = ChapterStatus.RUNNING
        progress.error = None
        progress.pages_total = 1
        progress.pages_done = 0
        await self._db.set_chapter_status(chapter.url, ChapterStatus.RUNNING.value)
        await self._emit_chapter(job, progress)

        try:
            await self._pause_flags[job.id].wait()
            text = await adapter.fetch_text(chapter)
            # write_epub refuses an empty chapter, which is the failure that
            # matters here: a reader that answered with a login wall or a
            # removed-chapter notice parses cleanly and would otherwise be
            # stored as a valid, empty book.
            with ChapterWorkspace(destination.parent, f"{chapter.index:04d}"):
                write_epub(
                    destination,
                    text,
                    series_title=job.series.title,
                    author=job.series.author,
                    language=self._settings.language,
                    identifier=chapter.url,
                )

            progress.pages_done = 1
            progress.status = ChapterStatus.DONE
            progress.output_path = str(destination)
            await self._db.set_chapter_status(
                chapter.url, ChapterStatus.DONE.value,
                pages_total=1, output_path=str(destination),
            )
            log.info("Wrote %s (%d characters)", destination.name, text.characters)

        except asyncio.CancelledError:
            progress.status = ChapterStatus.CANCELLED
            await self._db.set_chapter_status(chapter.url, ChapterStatus.CANCELLED.value)
            raise
        except Exception as exc:
            progress.status = ChapterStatus.FAILED
            progress.error = str(exc)
            await self._db.set_chapter_status(
                chapter.url, ChapterStatus.FAILED.value, error=str(exc)
            )
            log.warning("Chapter failed (%s): %s", chapter.title, exc)

        await self._emit_chapter(job, progress)

    async def _process_file(self, job: Job, adapter, chapter: Chapter) -> None:
        """Download one book file and write it through unchanged."""
        progress = job.progress[chapter.url]
        destination = book_path(self._settings.output_dir, job.series, chapter)

        if verify_file(destination):
            progress.status = ChapterStatus.DONE
            progress.output_path = str(destination)
            progress.pages_total = progress.pages_done = 1
            await self._db.set_chapter_status(
                chapter.url, ChapterStatus.DONE.value, output_path=str(destination)
            )
            await self._emit_chapter(job, progress)
            log.info("Skipping %s (already downloaded)", destination.name)
            return

        progress.status = ChapterStatus.RUNNING
        progress.error = None
        progress.pages_total = 1
        progress.pages_done = 0
        await self._db.set_chapter_status(chapter.url, ChapterStatus.RUNNING.value)
        await self._emit_chapter(job, progress)

        try:
            if destination.suffix.lower() not in LIBRARY_EXTENSIONS:
                raise PackagingError(
                    f"{destination.name} is not a file type this library "
                    f"stores ({', '.join(sorted(LIBRARY_EXTENSIONS))})"
                )

            sources = await adapter.fetch_pages(chapter)
            if not sources:
                raise DownloadError(f"No download link found for {chapter.title}")

            await self._pause_flags[job.id].wait()
            result = await self._fetcher.fetch_file(
                sources[0].url, referer=sources[0].referer
            )
            # A file host that answers a download with a login wall or a
            # rate-limit notice returns 200 and HTML. Storing that under a .pdf
            # would leave a library full of unreadable "books".
            if not looks_like_document(result.content, destination.suffix):
                raise DownloadError(
                    f"{sources[0].url} did not return a "
                    f"{destination.suffix.lstrip('.').upper()} "
                    f"({result.content_type or 'unknown type'}, "
                    f"{len(result.content)} bytes)"
                )

            write_file(destination, result.content)
            progress.pages_done = 1
            progress.status = ChapterStatus.DONE
            progress.output_path = str(destination)
            await self._db.set_chapter_status(
                chapter.url, ChapterStatus.DONE.value,
                pages_total=1, output_path=str(destination),
            )
            log.info("Wrote %s (%.1f MB)", destination.name,
                     len(result.content) / (1 << 20))

        except asyncio.CancelledError:
            progress.status = ChapterStatus.CANCELLED
            await self._db.set_chapter_status(chapter.url, ChapterStatus.CANCELLED.value)
            raise
        except Exception as exc:
            progress.status = ChapterStatus.FAILED
            progress.error = str(exc)
            await self._db.set_chapter_status(
                chapter.url, ChapterStatus.FAILED.value, error=str(exc)
            )
            log.warning("Download failed (%s): %s", chapter.title, exc)

        await self._emit_chapter(job, progress)

    async def _download_pages(
        self, job: Job, adapter, chapter: Chapter, pages, progress: ChapterProgress
    ) -> list[PageFile]:
        results: dict[int, PageFile] = {}
        failures = await self._fetch_pages(job, adapter, pages, results, progress)

        # Some adapters mint page URLs per request rather than serving them
        # from stable paths, so a failure says "that URL is dead", not "that
        # page is gone". Re-listing costs one request and typically points at
        # a different, working host.
        rounds = PAGE_REFRESH_ROUNDS if getattr(adapter, "pages_expire", False) else 0
        for attempt in range(1, rounds + 1):
            if not failures:
                break
            log.info("%d page(s) failed for %s; re-listing (round %d/%d)",
                     len(failures), chapter.title, attempt, rounds)
            fresh = await self._relist_pages(adapter, chapter)
            retry = [p for p in fresh if p.index in failures]
            if not retry:
                break
            failures = await self._fetch_pages(job, adapter, retry, results, progress)

        if failures:
            # One bad page invalidates the chapter: a CBZ with a hole in it is
            # worse than an obvious failure the user can retry.
            outcome = failures[min(failures)]
            raise DownloadError(f"Page download failed: {outcome}") from outcome

        return [results[i] for i in sorted(results)]

    async def _fetch_pages(
        self, job: Job, adapter, pages, results: dict[int, PageFile],
        progress: ChapterProgress,
    ) -> dict[int, BaseException]:
        """Download ``pages`` into ``results``; return what did not arrive.

        Every page is attempted even once one has failed, so a re-list retries
        the whole set of casualties rather than discovering them one at a time.
        """
        semaphore = asyncio.Semaphore(max(self._settings.image_concurrency, 1))
        lock = asyncio.Lock()

        async def fetch_one(page) -> None:
            async with semaphore:
                await self._pause_flags[job.id].wait()
                result = await self._fetcher.fetch_image(page.url, referer=page.referer)
                # Before validation, not after: a page does not always arrive as
                # an image. Noor's reader wraps each one in an SVG, and the
                # adapter is the only thing that knows to unwrap it.
                # getattr, like every other adapter attribute read here: an
                # adapter is a duck, not necessarily a subclass.
                unwrap = getattr(adapter, "transform_page", None)
                content = unwrap(result.content) if callable(unwrap) else result.content
                validate_image(content)  # reject truncated/corrupt payloads
                file = PageFile(
                    index=page.index,
                    data=content,
                    extension=pick_extension(content, result.url),
                )
                async with lock:
                    results[page.index] = file
                    progress.pages_done = len(results)
                await self._emit_chapter(job, progress)

        outcomes = await asyncio.gather(
            *(fetch_one(p) for p in pages), return_exceptions=True
        )

        failures: dict[int, BaseException] = {}
        for page, outcome in zip(pages, outcomes):
            if isinstance(outcome, asyncio.CancelledError):
                raise outcome
            if isinstance(outcome, BaseException):
                failures[page.index] = outcome
        return failures

    async def _relist_pages(self, adapter, chapter: Chapter) -> list:
        """Ask the adapter for fresh page URLs. Never fatal.

        This runs to rescue a chapter that has already failed, so an adapter
        that cannot answer just leaves the original failure to be reported.
        """
        try:
            return await adapter.refresh_pages(chapter)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            log.warning("Could not re-list pages for %s: %s", chapter.title, exc)
            return []

    async def _emit_chapter(self, job: Job, progress: ChapterProgress) -> None:
        await self._emit({
            "type": "chapter_progress",
            "job_id": job.id,
            "chapter": progress.to_dict(),
        })


async def preview_series(url: str, session_manager, db) -> dict[str, Any]:
    """Resolve a URL to a series plus chapter list for the Add view.

    Merges in per-chapter status from the database so the UI can show what is
    already downloaded before the user selects anything.
    """
    adapter = await resolve_adapter(url, session_manager)
    series = await adapter.fetch_series(url)
    chapters = await adapter.fetch_chapters(series)

    await db.upsert_series(series)
    await db.upsert_chapters(series.url, chapters)
    states = await db.get_chapter_states(series.url)

    return {
        "series": series.to_dict(),
        "adapter": adapter.id,
        "chapters": [
            {
                **chapter.to_dict(),
                "status": states.get(chapter.url, {}).get("status", "pending"),
                "output_path": states.get(chapter.url, {}).get("output_path"),
            }
            for chapter in chapters
        ],
    }


def series_from_dict(data: dict[str, Any]) -> Series:
    return Series(
        url=data["url"],
        title=data["title"],
        source=data.get("source", "generic"),
        cover_url=data.get("cover_url"),
        author=data.get("author"),
        description=data.get("description"),
    )


def chapter_from_dict(data: dict[str, Any]) -> Chapter:
    return Chapter(
        url=data["url"],
        title=data.get("title", ""),
        number=data.get("number"),
        index=int(data.get("index", 0)),
        date=data.get("date"),
    )


def library_size(output_dir: Path, series_title: str) -> int:
    """Total bytes on disk for one series, for the Library view."""
    from .models import sanitize_filename

    folder = output_dir / sanitize_filename(series_title)
    if not folder.is_dir():
        return 0
    return sum(f.stat().st_size for f in folder.iterdir()
               if f.is_file() and f.suffix.lower() in LIBRARY_EXTENSIONS)
