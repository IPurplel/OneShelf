"""FastAPI application: REST endpoints, WebSocket progress feed, static UI."""

from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager, suppress
from pathlib import Path
from typing import Any
from urllib.parse import quote, urlsplit

from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse, JSONResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import __version__
from .adapters import CONTENT_TYPES
from .adapters import describe as describe_adapters
from .adapters import resolve as resolve_adapter
from .adapters import select as select_adapter
from .adapters.base import (
    SCORE_AUTHOR,
    SCORE_EXACT,
    SCORE_IRRELEVANT,
    SCORE_PREFIX,
    SCORE_SUBSTRING,
    SCORE_WORD,
    SCORE_WORD_PREFIX,
    relevance,
)
from .adapters.textmatch import clean_query, query_variants
from .config import RUNTIME_EDITABLE, settings
from .db import Database
from .desync import DesyncProxy
from .fetcher import Fetcher
from .models import ChapterStatus
from .packager import (
    LIBRARY_EXTENSIONS,
    delete_archives,
    iter_zip,
    prune_empty_folder,
    series_folder,
    sweep_partials,
)
from .searchcache import SourceCache
from .queue import (
    JobQueue,
    chapter_from_dict,
    library_size,
    preview_series,
    series_from_dict,
)
from .session import SessionManager

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
)
log = logging.getLogger("manga-downloader")

WEB_DIR = Path(__file__).resolve().parent.parent / "web"

#: Ceiling on ``/api/search?limit=``. Per site, so ten sites can still return
#: ten times this — the point is that one request cannot ask a site for its
#: entire catalogue.
MAX_SEARCH_RESULTS = 50

state: dict[str, Any] = {}


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings.ensure_dirs()

    db = Database(settings.db_path)
    await db.connect()
    # Anything left 'running' was killed mid-flight; make it retryable.
    recovered = await db.reset_running_chapters()
    if recovered:
        log.info("Reset %d interrupted chapter(s) to pending", recovered)
    sweep_partials(settings.output_dir)

    # Must come up before anything opens a connection, so the browser and the
    # HTTP client both egress through the same route from the very first request.
    desync: DesyncProxy | None = None
    if settings.desync_enabled and not settings.proxy:
        desync = DesyncProxy(
            port=settings.desync_port,
            split_at=settings.desync_split,
            delay=settings.desync_delay,
        )
        settings._runtime_proxy = await desync.start()
    elif settings.desync_enabled and settings.proxy:
        log.info("desync_enabled ignored: an explicit proxy is configured")

    sessions = SessionManager(settings, db)
    fetcher = Fetcher(settings, sessions)
    await fetcher.start()
    queue = JobQueue(settings, db, sessions, fetcher)

    state.update(db=db, sessions=sessions, fetcher=fetcher, queue=queue,
                 desync=desync)
    log.info("Ready on http://%s:%s (output: %s)",
             settings.host, settings.port, settings.output_dir)

    try:
        yield
    finally:
        await queue.shutdown()
        await fetcher.close()
        await sessions.close()
        if desync is not None:
            await desync.stop()
        await db.close()


app = FastAPI(title="OneShelf", version=__version__, lifespan=lifespan)


# --------------------------------------------------------------- API models


class PreviewRequest(BaseModel):
    url: str = Field(..., min_length=8)


class DownloadRequest(BaseModel):
    series: dict[str, Any]
    chapters: list[dict[str, Any]] = Field(default_factory=list)


class DeleteFilesRequest(BaseModel):
    series_url: str
    chapters: list[str] | None = None
    """Chapter URLs to delete. ``None`` or empty means the whole series."""


class SettingsRequest(BaseModel):
    values: dict[str, Any]


class ManualSessionRequest(BaseModel):
    url: str
    cookies: str
    user_agent: str = ""


# ------------------------------------------------------------------ helpers


def _queue() -> JobQueue:
    queue = state.get("queue")
    if queue is None:
        raise HTTPException(503, "Service still starting")
    return queue


# ------------------------------------------------------------------- routes


@app.get("/api/health")
async def health() -> dict[str, Any]:
    sessions: SessionManager = state["sessions"]
    proxy = settings.proxy_config
    return {
        "status": "ok",
        "version": __version__,
        "output_dir": str(settings.output_dir),
        "output_writable": _writable(settings.output_dir),
        "proxy": proxy.describe() if proxy else None,
        "desync": state["desync"].status() if state.get("desync") else None,
        "session": sessions.status(),
        "adapters": describe_adapters(),
    }


@app.post("/api/connectivity")
async def connectivity(request: PreviewRequest) -> dict[str, Any]:
    """Check whether a URL is reachable, and say *how* it failed.

    Worth its own endpoint because the three common failures are
    indistinguishable from the UI otherwise: a connection reset before any HTTP
    response (network-level filtering), a bot-check interstitial, and an ordinary
    HTTP error. Each needs a different fix.
    """
    import httpx as _httpx

    proxy = settings.proxy_config
    options: dict[str, Any] = {"timeout": 20.0, "follow_redirects": True}
    if proxy is not None:
        options["proxy"] = proxy.for_httpx()

    result: dict[str, Any] = {
        "url": request.url,
        "proxy": proxy.describe() if proxy else None,
    }

    try:
        async with _httpx.AsyncClient(**options) as client:
            response = await client.get(
                request.url, headers={"User-Agent": state["sessions"].user_agent}
            )
    except _httpx.ProxyError as exc:
        result.update(reachable=False, kind="proxy_error", detail=str(exc),
                      hint="The proxy itself refused or could not be reached.")
        return result
    except _httpx.ConnectError as exc:
        reset = _is_connection_reset(exc)
        result.update(
            reachable=False,
            kind="connection_reset" if reset else "connect_error",
            detail=_describe_exception(exc),
            hint=(
                (
                    "Connection killed before any HTTP response arrived - "
                    "network-level filtering of the hostname, not the site "
                    "blocking you. "
                ) + (
                    "Try enabling 'desync_enabled' in Settings: it fragments "
                    "the TLS handshake so the filter cannot read the hostname, "
                    "and needs no external service."
                    if not settings.desync_enabled else
                    "The built-in bypass is already enabled and did not help, "
                    "so the filtering is more capable than simple packet "
                    "inspection. Route through a proxy or VPN instead."
                )
                if reset else
                "Could not establish a connection. Check DNS and routing."
            ),
        )
        return result
    except Exception as exc:
        result.update(reachable=False, kind=type(exc).__name__, detail=str(exc))
        return result

    from .session import is_challenge

    body = response.text
    challenged = is_challenge(body, status=response.status_code)
    result.update(
        reachable=True,
        kind="challenge" if challenged else "ok",
        status=response.status_code,
        bytes=len(response.content),
        hint=(
            "Reached the site, but it served a bot check. The browser will need "
            "to solve it — that is expected here."
            if challenged else "Reached the site normally."
        ),
    )
    return result


def _writable(path: Path) -> bool:
    try:
        path.mkdir(parents=True, exist_ok=True)
        probe = path / ".write-test"
        probe.write_bytes(b"")
        probe.unlink()
        return True
    except OSError:
        return False


@app.post("/api/preview")
async def preview(request: PreviewRequest) -> dict[str, Any]:
    """Resolve a series URL to its metadata and full chapter list.

    This is the slow call — it may have to solve a Cloudflare challenge — so the
    UI shows a spinner and everything afterwards reuses the harvested session.
    """
    try:
        return await preview_series(request.url, state["sessions"], state["db"])
    except Exception as exc:
        log.warning("Preview failed for %s: %s", request.url, exc)
        raise HTTPException(502, str(exc)) from exc


@app.post("/api/download")
async def download(request: DownloadRequest) -> dict[str, Any]:
    if not request.chapters:
        raise HTTPException(400, "No chapters selected")

    series = series_from_dict(request.series)
    chapters = [chapter_from_dict(c) for c in request.chapters]
    chapters.sort(key=lambda c: c.sort_key)

    job = await _queue().create_job(series, chapters)
    return {"job_id": job.id, "queued": len(chapters)}


@app.get("/api/jobs")
async def list_jobs() -> dict[str, Any]:
    return {"jobs": _queue().list_jobs()}


@app.get("/api/jobs/{job_id}")
async def job_detail(job_id: int) -> dict[str, Any]:
    detail = _queue().job_detail(job_id)
    if detail is None:
        raise HTTPException(404, "No such job")
    return detail


# Declared before /api/jobs/{job_id}/{action}: job_id is typed int, so the
# parameterised route would otherwise match "stop" and reject it as invalid.
@app.post("/api/jobs/stop")
async def stop_all_jobs() -> dict[str, Any]:
    """Stop every download in flight. Finished files are kept."""
    stopped = await _queue().stop_all()
    log.info("Stopped %d active job(s) on request", stopped)
    return {"stopped": stopped}


@app.post("/api/jobs/clear")
async def clear_jobs(all: bool = False) -> dict[str, Any]:
    """Clear the queue list. Downloaded archives are never touched.

    Defaults to finished jobs only, so clearing cannot abandon a download by
    accident; ``all=true`` stops anything running first.
    """
    result = await _queue().clear(finished_only=not all)
    log.info("Queue cleared: %s", result)
    return result


@app.post("/api/jobs/{job_id}/{action}")
async def job_action(job_id: int, action: str) -> dict[str, Any]:
    queue = _queue()
    handlers = {
        "pause": queue.pause,
        "resume": queue.resume,
        "cancel": queue.cancel,
        "retry": queue.retry_failed,
        "remove": queue.remove,
    }
    handler = handlers.get(action)
    if handler is None:
        raise HTTPException(400, f"Unknown action '{action}'")

    result = await handler(job_id)
    if not result:
        raise HTTPException(409, f"Cannot {action} job {job_id} in its current state")
    return {"ok": True, "result": result}


@app.get("/api/library")
async def library() -> dict[str, Any]:
    rows = await state["db"].list_series()
    for row in rows:
        row["size_bytes"] = library_size(settings.output_dir, row["title"])
    return {"series": rows}


@app.get("/api/library/archive")
async def archive_series(title: str) -> StreamingResponse:
    """Stream one series' chapters as a single .zip.

    The way to get files off a container that has no NAS mount, without
    reaching for scp. Streamed, so a 30 GB series costs a chunk of memory
    rather than a second copy on disk.
    """
    root = settings.output_dir.resolve()
    try:
        folder = series_folder(settings.output_dir, title).resolve()
        # The title arrives from the client, so confirm it really lands inside
        # the output directory rather than trusting the name it sanitises to.
        folder.relative_to(root)
    except (ValueError, OSError) as exc:
        raise HTTPException(400, f"Invalid series title: {title!r}") from exc

    if not folder.is_dir():
        raise HTTPException(404, f"Nothing downloaded for {title!r} yet")

    files = sorted(path for path in folder.iterdir()
                   if path.is_file() and path.suffix.lower() in LIBRARY_EXTENSIONS)
    if not files:
        raise HTTPException(404, f"Nothing downloaded for {title!r} yet")

    members = [(path, f"{folder.name}/{path.name}") for path in files]
    total = sum(path.stat().st_size for path in files)
    log.info("Streaming %d chapters (%.1f MB) of %s as a zip",
             len(files), total / (1 << 20), title)

    # Titles are frequently non-Latin, so send an ASCII fallback alongside the
    # RFC 5987 form rather than letting the header mangle the name.
    ascii_name = folder.name.encode("ascii", "ignore").decode() or "series"
    disposition = (
        f'attachment; filename="{ascii_name}.zip"; '
        f"filename*=UTF-8''{quote(folder.name + '.zip')}"
    )
    return StreamingResponse(
        iter_zip(members),
        media_type="application/zip",
        headers={"Content-Disposition": disposition},
    )


class ClientGone(Exception):
    """The caller hung up before the work finished."""


async def _gather_while_connected(request: Request, coroutines: list, poll: float = 0.4):
    """``asyncio.gather``, abandoned the moment the client disconnects.

    ASGI does not cancel a handler when the caller goes away, so an abandoned
    request runs to its full timeout — and everything here shares one rate
    limiter, so that time is taken directly from whatever the user is actually
    waiting for. Measured on this app: a request killed at 4s went on to fetch
    16 more book pages over the following 20 seconds.

    The browser aborts a superseded search, which is what makes the disconnect
    happen at all; this is the half that acts on it.
    """
    work = asyncio.ensure_future(asyncio.gather(*coroutines))

    async def watch() -> None:
        while not await request.is_disconnected():
            await asyncio.sleep(poll)

    watcher = asyncio.ensure_future(watch())
    try:
        done, _ = await asyncio.wait(
            {work, watcher}, return_when=asyncio.FIRST_COMPLETED
        )
    finally:
        watcher.cancel()
        with suppress(asyncio.CancelledError, Exception):
            await watcher

    if work in done:
        return work.result()

    work.cancel()
    with suppress(asyncio.CancelledError, Exception):
        await work
    raise ClientGone


#: The pseudo-type that searches every kind at once. Not a member of
#: ``CONTENT_TYPES``: it is a request shape, not something an adapter can serve.
ANY_TYPE = "all"

#: Per-source candidate cache. Keyed on exactly what is sent to a site — the
#: site, the query text, and the result limit — so matching and ranking stay
#: free to change without invalidating anything.
search_cache = SourceCache()


@app.get("/api/sources")
async def sources() -> dict[str, Any]:
    """The catalogue the search box is built from.

    The UI used to hardcode three category chips and nothing else, so it could
    not say how many sites back a category, name them, or let one be switched
    off — and a category with no searchable sites behind it looked identical to
    one with eight. Deciding the adapter from the URL alone keeps this free:
    nothing is fetched, so the page can ask on every load.
    """
    grouped: dict[str, list[dict[str, str]]] = {kind: [] for kind in CONTENT_TYPES}
    for site in settings.search_sites:
        adapter = select_adapter(site)
        # Asked of the site, not the adapter class: one platform can serve more
        # than one kind, and a web novel on a manga theme belongs under Books.
        kind = adapter.content_type_for(site)
        if kind not in grouped:
            continue
        grouped[kind].append({
            "site": site,
            "host": urlsplit(site).netloc or site,
            "adapter": adapter.id,
            "adapter_name": adapter.name,
        })
    return {
        "kinds": [
            {"type": kind, "label": KIND_LABELS[kind], "sites": grouped[kind],
             "count": len(grouped[kind])}
            for kind in sorted(grouped, key=lambda k: KIND_ORDER.index(k))
        ],
        "total": sum(len(v) for v in grouped.values()),
    }


#: Display names and a stable order, so the UI need not carry its own copy and
#: drift from what the server actually serves.
KIND_LABELS = {"manga": "Manga", "comics": "Comics", "book": "Books"}
KIND_ORDER = ["manga", "comics", "book"]


@app.get("/api/search")
async def search(
    request: Request,
    q: str,
    type: str | None = None,
    limit: int = 8,
    sites: str | None = None,
    refresh: bool = False,
) -> dict[str, Any]:
    """Search the sites that serve one kind of content.

    ``type`` is required and not defaulted. Searching everything at once mixed
    novels into a manga query and manga into a book query, and no ranking fixes
    that — the kinds are genuinely different things. Making the caller say which
    also means a query only wakes the sites that could answer it, which is the
    difference between two sites and ten.

    Each site is queried through its own search page and given its own
    deadline, so one slow or broken site never holds up the rest — a partial
    result list is far more useful than a spinner waiting on the worst site.
    """
    if type is None or type.strip() == "":
        raise HTTPException(400, "A content type is required: "
                                 f"{', '.join(sorted(CONTENT_TYPES))}")
    kind = type.strip().lower()
    if kind != ANY_TYPE and kind not in CONTENT_TYPES:
        raise HTTPException(400, f"Unknown content type {type!r}. Choose one of "
                                 f"{', '.join(sorted(CONTENT_TYPES))}.")

    # Clamped, not trusted: this number is handed to every adapter's search,
    # and several page through results to reach it. A caller asking for 100000
    # would send each site — each behind a browser that may have to clear a bot
    # check — off to walk its whole catalogue on one query string.
    limit = max(1, min(limit, MAX_SEARCH_RESULTS))

    # What gets *sent*. `clean_query` strips the invisible marks a copied
    # title drags along -- LRM/RLM, the bidi embedding controls, ZWJ/ZWNJ and
    # a stray BOM. They survive `.strip()`, they are invisible to the person
    # who pasted them, and left in place they reach the punctuation rule in
    # `fold()` and become a *space*, splitting one word into two tokens that
    # every gate downstream then looks for separately.
    #
    # Only invisible characters are removed. Letters, case and punctuation go
    # to the site exactly as typed, because the index on the other end may
    # well be exact -- and because this string is echoed back to the user as
    # the query they searched for.
    query = clean_query(q)
    # Which sites can serve this kind at all, decided from the URL alone so
    # nothing is fetched to find out. ``all`` keeps every site that serves any
    # kind — the results are grouped by kind afterwards rather than mixed,
    # which is what made searching everything at once unusable before.
    chosen = [s for s in settings.search_sites
              if select_adapter(s).content_type_for(s) in CONTENT_TYPES
              and (kind == ANY_TYPE
                   or select_adapter(s).content_type_for(s) == kind)]

    # An explicit site list narrows it further. Matched on the host so the UI
    # can send back what it displayed without having to echo the exact URL.
    if sites is not None:
        wanted = {w.strip().lower() for w in sites.split(",") if w.strip()}
        if wanted:
            chosen = [s for s in chosen
                      if s.lower() in wanted
                      or (urlsplit(s).netloc or s).lower() in wanted]

    if len(query) < 2:
        return _search_response(query, kind, [], [])

    sessions = state["sessions"]

    async def one(site: str) -> tuple[str, list, str]:
        """Search one site. Returns ``(site, hits, status)``.

        The status is the point. Every failure used to arrive as an empty list,
        so a site that timed out, a site that errored and a site that simply
        had no match were indistinguishable — and the UI could only say
        "nothing found", which blames the query for the site's problem.
        """
        try:
            adapter = await resolve_adapter(site, sessions)
            # The URL-only guess above is a filter, not the verdict: the page
            # itself decides the adapter, so confirm before searching. The kind
            # is the *site's*, so a novel site on a manga theme is not skipped
            # from a book search for serving the wrong thing.
            site_kind = adapter.content_type_for(site)
            if site_kind not in CONTENT_TYPES or (
                kind != ANY_TYPE and site_kind != kind
            ):
                log.info("Skipping %s: it serves %s, not %s",
                         site, site_kind, kind)
                return site, [], "skipped"
            async def ask() -> tuple[list, str]:
                deadline = settings.search_timeout
                found = await asyncio.wait_for(
                    adapter.search(site, query, limit=limit), timeout=deadline)

                # Folding rescues a hit the site returned. It cannot rescue a
                # hit the site never returned -- and an unnormalised Arabic
                # index answers "رواية" and "روايه" as different words. So a
                # site that found *nothing* is asked again in the spellings a
                # reader might have typed instead.
                #
                # Only on nothing, and only until something answers. Every
                # query in this fan-out shares one rate limiter and one
                # timeout, and HANDOFF records what happens to a search budget
                # when work is spent on queries nobody is waiting for.
                if not found:
                    for variant in query_variants(query)[1:]:
                        try:
                            found = await asyncio.wait_for(
                                adapter.search(site, variant, limit=limit),
                                timeout=deadline)
                        except asyncio.TimeoutError:
                            log.info("Variant %r timed out on %s", variant, site)
                            break
                        if found:
                            log.info("%s found %d hit(s) for %r, spelled %r",
                                     site, len(found), query, variant)
                            break

                rows = [{**r.to_dict(), "content_type": site_kind}
                        for r in found]
                return rows, "ok" if rows else "empty"

            # The key is what was actually sent to this site. `kind` is absent
            # deliberately: it decides whether we ask, never what the site
            # answers, so including it would split the cache for nothing.
            hits, status, _cached = await search_cache.get_or_fetch(
                (site, query, limit), ask, refresh=refresh,
            )
            return site, list(hits), status
        except asyncio.TimeoutError:
            log.info("Search timed out on %s after %.0fs",
                     site, settings.search_timeout)
            return site, [], "timeout"
        except Exception as exc:
            log.info("Search failed on %s: %s", site, exc)
            return site, [], "error"

    try:
        pairs = await _gather_while_connected(request, [one(s) for s in chosen])
    except ClientGone:
        # Typing a six-letter query fires a search per pause, and each one wakes
        # every site for this kind. Nothing reads this response, but stopping
        # the work is the point: it hands the rate limiter back to the query the
        # user is still waiting on.
        log.info("Search %r abandoned by the client", query)
        return _search_response(query, kind, [], [])

    # A site's search decides what it returns; it does not decide what is worth
    # showing first, and these engines match descriptions and loose word stems.
    # Score every hit against the query, drop what is judged irrelevant, and
    # rank the rest — otherwise the exact title sits wherever the round-robin
    # happens to put it. Measured on "berserk": the real series came 1st, 7th
    # and 20th, below two hits that shared no word with the query at all.
    kept: dict[str, list[dict[str, Any]]] = {site: [] for site, _, _ in pairs}
    dropped = 0
    for site, found, _ in pairs:
        for item in found:
            score = relevance(query, item.get("title") or "",
                              item.get("alt_title"), item.get("author"))
            if score <= SCORE_IRRELEVANT:
                dropped += 1
                continue
            kept[site].append({**item, "score": score,
                               "match": _match_reason(score)})

    if dropped:
        log.info("Search %r: dropped %d irrelevant hit(s)", query, dropped)

    # Best band first; within a band, still interleaved by site, so the top of
    # the list is "everyone's exact match" rather than one site's whole page.
    ordered: list[dict[str, Any]] = []
    for band in sorted({i["score"] for items in kept.values() for i in items},
                       reverse=True):
        rows = [[i for i in items if i["score"] == band] for items in kept.values()]
        for index in range(max((len(r) for r in rows), default=0)):
            for row in rows:
                if index < len(row):
                    ordered.append(row[index])

    # A site that answered is credited with what *survived* filtering, so the
    # UI cannot claim a site that contributed nothing usable. A site whose only
    # hits were dropped as noise is reported as "empty", not "ok" — it did
    # answer, but not with anything worth showing.
    site_rows = [
        {"site": site, "host": urlsplit(site).netloc or site,
         "count": len(kept[site]),
         "status": "empty" if (status == "ok" and not kept[site]) else status}
        for site, _, status in pairs
    ]

    # Grouping runs *after* ranking and never changes it: the surviving record
    # keeps the best rank its group earned. Relevance decided what belongs in
    # the list; identity only decides how many cards it takes to show it.
    ordered, merged = _merge_duplicates(ordered)
    if merged:
        log.info("Search %r: merged %d duplicate record(s) across sites",
                 query, merged)
    return _search_response(query, kind, ordered, site_rows, merged=merged)


#: What a relevance band means, in words the interface can show. Scores are
#: bands rather than a continuum (see ``adapters.base``), so each one has an
#: honest one-word explanation — which is what lets a result say *why* it is
#: here instead of leaving the user to guess.
#: Ordered by threshold, highest first — the lookup returns the first band the
#: score clears, so a list in any other order mislabels. Author (90) sits below
#: exact (100) and above title-prefix (80), exactly as the scoring intends.
_MATCH_REASONS = sorted(
    [
        (SCORE_EXACT, "exact title"),
        (SCORE_AUTHOR, "by this author"),
        (SCORE_PREFIX, "title starts with"),
        (SCORE_WORD, "title contains"),
        (SCORE_WORD_PREFIX, "partial word"),
        (SCORE_SUBSTRING, "loose match"),
    ],
    key=lambda pair: -pair[0],
)


def _match_reason(score: int) -> str:
    for threshold, label in _MATCH_REASONS:
        if score >= threshold:
            return label
    # Everything left is SCORE_UNJUDGEABLE: the query and the hit share no
    # script, so the site matched on a name it is not showing us.
    return "matched another title"


def _identity_key(item: dict[str, Any]) -> tuple[str, str, str]:
    """The strict identity of a work: kind, folded title, folded author.

    Used to decide whether two records are *the same work* — a different
    question from whether either is relevant, and one that needs stronger
    evidence. Folding alone is not enough: `على` and `علي` are different words
    that share a normalised form, so the author and the content type have to
    agree too.
    """
    from .adapters.textmatch import fold

    return (
        str(item.get("content_type") or ""),
        fold(str(item.get("title") or "")),
        fold(str(item.get("author") or "")),
    )


def _merge_duplicates(results: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], int]:
    """Collapse records that are the same work, conservatively.

    Two records merge only when :func:`_identity_key` agrees exactly — same
    kind, same folded title, **same folded author** — so an unnamed record
    never absorbs a named one and two different names never combine.

    That strictness is deliberate, and it was arrived at by getting it wrong
    first: a looser rule that let a named author join a group of unnamed
    records merged a work by "Someone Else" into an unrelated one and then
    displayed that author on the merged card. The costs are not symmetric —
    showing a work twice is untidy, merging two works hides one of them — so
    where the evidence is ambiguous the records stay apart. A novel and its
    manga adaptation differ in ``content_type`` and never merge.

    Nothing is discarded. The surviving record carries every source in
    ``sources``, so a site with more chapters stays one click away; only the
    visual duplication goes.
    """
    groups: dict[tuple[str, str, str], list[dict[str, Any]]] = {}
    order: list[tuple[str, str, str]] = []
    for item in results:
        key = _identity_key(item)
        if not key[1]:
            # No title to group on: keep it, ungrouped, under a unique key.
            key = (*key, f"__ungrouped-{len(order)}")  # type: ignore[assignment]
        if key not in groups:
            groups[key] = []
            order.append(key)
        groups[key].append(item)

    merged_out: list[dict[str, Any]] = []
    merged_count = 0
    for key in order:
        group = groups[key]
        primary = group[0]
        if len(group) == 1:
            merged_out.append(primary)
            continue
        merged_count += len(group) - 1
        merged_out.append({
            **primary,
            # The best evidence available across the group, not merely the
            # first record's — sites differ in what metadata they carry.
            "cover_url": next((g.get("cover_url") for g in group if g.get("cover_url")),
                              primary.get("cover_url")),
            "alt_title": next((g.get("alt_title") for g in group if g.get("alt_title")),
                              primary.get("alt_title")),
            "sources": [
                {"site": g.get("site"), "url": g.get("url"), "source": g.get("source")}
                for g in group
            ],
        })
    return merged_out, merged_count


def _search_response(
    query: str,
    kind: str,
    results: list[dict[str, Any]],
    site_rows: list[dict[str, Any]],
    merged: int = 0,
) -> dict[str, Any]:
    """One shape for every exit from :func:`search`.

    Built in one place because there are four of them — short query, abandoned
    request, no sites, and a real answer — and the three cheap ones previously
    returned a different, smaller dict than the real one. Anything the UI
    learned to read on a successful search was therefore absent exactly when it
    was needed to explain why the search was empty.
    """
    for item in results:
        item.setdefault("sources", [
            {"site": item.get("site"), "url": item.get("url"),
             "source": item.get("source")}
        ])
    counts: dict[str, int] = {}
    for item in results:
        content_type = item.get("content_type")
        if content_type:
            counts[content_type] = counts.get(content_type, 0) + 1
    return {
        "query": query,
        "type": kind,
        "results": results,
        "sites": site_rows,
        # Per-kind totals, so an "All" search can be grouped and labelled
        # without the browser counting the list itself.
        "kinds": [
            {"type": k, "label": KIND_LABELS[k], "count": counts.get(k, 0)}
            for k in KIND_ORDER if counts.get(k)
        ],
        "answered": sum(1 for s in site_rows if s["status"] == "ok"),
        "searched": len(site_rows),
        # How many records were folded away, so the UI can say "also on 2 other
        # sites" rather than silently showing fewer results than were found.
        "merged": merged,
    }


@app.get("/api/cover")
async def cover(url: str) -> Response:
    """Fetch a cover image on the browser's behalf.

    The UI cannot load these directly. Cover art routinely sits on a host the
    network filters (manga-starz serves it from a different domain entirely) or
    behind the same clearance the pages need — and an ``<img>`` in the page
    goes straight out from the browser, bypassing the bypass proxy, the session
    cookies and the referer this app has already established.

    So the request is made here instead, through the same fetcher that
    downloads pages, and the bytes are handed back.
    """
    if not url.lower().startswith(("http://", "https://")):
        raise HTTPException(400, "Only http(s) URLs can be fetched")

    try:
        result = await state["fetcher"].fetch_image(url, referer=url)
    except Exception as exc:
        log.debug("Cover fetch failed for %s: %s", url, exc)
        raise HTTPException(502, f"Could not fetch that cover: {exc}") from exc

    return Response(
        content=result.content,
        media_type=result.content_type or "image/jpeg",
        # Cover art never changes; let the browser keep it for a day.
        headers={"Cache-Control": "public, max-age=86400"},
    )


@app.get("/api/library/chapters")
async def library_chapters(series_url: str) -> dict[str, Any]:
    """Downloaded state for one series, for the delete picker.

    Straight from the database with on-disk sizes attached — opening the panel
    must not touch the network or wake the browser.
    """
    states = await state["db"].get_chapter_states(series_url)
    chapters = []
    for url, row in states.items():
        size = 0
        recorded = row.get("output_path")
        if recorded:
            with suppress(OSError):
                size = Path(recorded).stat().st_size
        chapters.append({
            "url": url,
            "title": row.get("title"),
            "number": row.get("number"),
            "status": row.get("status"),
            "size_bytes": size,
            "on_disk": size > 0,
        })
    return {"chapters": chapters}


@app.post("/api/library/delete")
async def delete_files(request: DeleteFilesRequest) -> dict[str, Any]:
    """Delete downloaded archives, keeping the series in the library.

    The series and its chapter list stay, so anything removed can be fetched
    again in one click. The queue resumes from the file rather than the
    database, so a deleted chapter is simply downloaded afresh.
    """
    db = state["db"]
    states = await db.get_chapter_states(request.series_url)
    if not states:
        raise HTTPException(404, f"Unknown series: {request.series_url}")

    wanted = set(request.chapters or states.keys())

    # Never delete a file a worker is in the middle of writing: that turns a
    # space-saving action into a corrupted download.
    running = {
        url for url in wanted
        if states.get(url, {}).get("status") == ChapterStatus.RUNNING.value
    }

    targets: list[Path] = []
    deletable: list[str] = []
    for url in wanted - running:
        row = states.get(url)
        if not row or not row.get("output_path"):
            continue
        targets.append(Path(row["output_path"]))
        deletable.append(url)

    removed, freed = delete_archives(targets, settings.output_dir)
    await db.clear_chapter_downloads(deletable)

    # downloaded_only=False: this is a row lookup, not the Library listing. The
    # default filters by first_download_at, which is a question about what the
    # Library shows — nothing to do with which folder to prune. Every series
    # that can reach this point happens to satisfy it today, so this is not a
    # live bug; it is a policy this endpoint should not be reading at all.
    rows = await db.list_series(downloaded_only=False)
    title = next((r["title"] for r in rows if r["url"] == request.series_url), None)
    if title:
        prune_empty_folder(series_folder(settings.output_dir, title),
                           settings.output_dir)

    log.info("Deleted %d archive(s), freed %.1f MB from %s",
             removed, freed / (1 << 20), title or request.series_url)
    return {
        "removed": removed,
        "freed_bytes": freed,
        "skipped": sorted(running),
    }


@app.delete("/api/library")
async def forget_series(url: str) -> dict[str, Any]:
    """Remove a series from the index. Files on disk are left untouched."""
    await state["db"].delete_series(url)
    return {"ok": True}


@app.get("/api/settings")
async def get_settings() -> dict[str, Any]:
    return {
        "values": {
            key: _jsonable(getattr(settings, key)) for key in sorted(RUNTIME_EDITABLE)
        },
        "editable": sorted(RUNTIME_EDITABLE),
    }


@app.put("/api/settings")
async def update_settings(request: SettingsRequest) -> dict[str, Any]:
    try:
        applied = settings.apply_runtime_update(request.values)
    except Exception as exc:
        raise HTTPException(400, f"Invalid settings: {exc}") from exc
    settings.ensure_dirs()

    if "browser_cdp" in applied:
        # Attaching to (or detaching from) an external browser changes which
        # browser we drive, so the current one has to go. Dropped rather than
        # rebuilt here: the next request opens the right one lazily, and a
        # failed attach then surfaces on that request instead of this one.
        sessions = state.get("sessions")
        if sessions is not None:
            await sessions.close()
            log.info("Browser released after a browser_cdp change")

    return {"applied": {k: _jsonable(v) for k, v in applied.items()}}


@app.post("/api/session/manual")
async def manual_session(request: ManualSessionRequest) -> dict[str, Any]:
    """Install a cf_clearance cookie copied from the user's own browser.

    The escape hatch for when headless solving cannot succeed — Cloudflare
    sometimes hard-blocks datacenter IP ranges regardless of automation quality.
    """
    sessions: SessionManager = state["sessions"]
    try:
        installed = sessions.set_manual_session(
            request.url, request.cookies, request.user_agent or sessions.user_agent
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return {
        "ok": True,
        "host": installed.host,
        "has_clearance": installed.has_clearance,
        "cookie_count": len(installed.cookies),
    }


@app.post("/api/session/refresh")
async def refresh_session(request: PreviewRequest) -> dict[str, Any]:
    sessions: SessionManager = state["sessions"]
    try:
        session = await sessions.refresh(request.url)
    except Exception as exc:
        raise HTTPException(502, str(exc)) from exc
    return {"ok": True, "has_clearance": session.has_clearance}


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket) -> None:
    await websocket.accept()
    queue = state.get("queue")
    if queue is None:
        await websocket.close(code=1013)
        return

    outbox: asyncio.Queue[dict] = asyncio.Queue(maxsize=1000)

    async def on_event(event: dict) -> None:
        # Never block the download workers on a slow or dead client.
        if not outbox.full():
            outbox.put_nowait(event)

    queue.subscribe(on_event)
    try:
        await websocket.send_json({"type": "snapshot", "jobs": queue.list_jobs()})
        while True:
            event = await outbox.get()
            await websocket.send_json(event)
    except (WebSocketDisconnect, RuntimeError):
        pass
    finally:
        queue.unsubscribe(on_event)


def _jsonable(value: Any) -> Any:
    return str(value) if isinstance(value, Path) else value


def _walk_causes(exc: BaseException, limit: int = 8):
    """Yield an exception and the causes chained beneath it."""
    seen: set[int] = set()
    current: BaseException | None = exc
    while current is not None and len(seen) < limit and id(current) not in seen:
        seen.add(id(current))
        yield current
        current = current.__cause__ or current.__context__


def _is_connection_reset(exc: BaseException) -> bool:
    """Detect a TCP reset anywhere in the exception chain.

    Matching on the message is useless here: httpx wraps the real cause and its
    own ``str()`` is empty, so the reset is only visible as a nested
    ``ConnectionResetError`` several levels down.
    """
    return any(isinstance(e, ConnectionResetError) for e in _walk_causes(exc))


def _describe_exception(exc: BaseException) -> str:
    """Readable summary, since the outermost exception is often blank."""
    parts = [
        f"{type(e).__name__}: {e}" if str(e) else type(e).__name__
        for e in _walk_causes(exc)
    ]
    return " <- ".join(parts)


@app.exception_handler(Exception)
async def unhandled(request, exc: Exception) -> JSONResponse:  # pragma: no cover
    log.exception("Unhandled error on %s", request.url.path)
    return JSONResponse({"detail": str(exc)}, status_code=500)


def asset_token() -> str:
    """A short token that changes whenever the UI files change.

    StaticFiles serves app.js and style.css with an ETag but no Cache-Control,
    so browsers fall back to heuristic freshness and can keep using a cached
    copy without ever revalidating. A shipped UI change then simply never
    arrives, which looks exactly like a broken feature rather than a stale
    cache. Versioning the URL sidesteps the question: new content, new URL.
    """
    stamp = 0.0
    for name in ("app.js", "style.css"):
        try:
            stamp = max(stamp, (WEB_DIR / name).stat().st_mtime)
        except OSError:  # pragma: no cover - unreadable asset
            continue
    if not stamp:
        return __version__
    return f"{__version__}-{int(stamp)}"


def index_html() -> str:
    """The UI shell with cache-busted asset URLs."""
    html = (WEB_DIR / "index.html").read_text(encoding="utf-8")
    token = asset_token()
    return (
        html.replace('href="/style.css"', f'href="/style.css?v={token}"')
            .replace('src="/app.js"', f'src="/app.js?v={token}"')
    )


# Static UI last so /api/* and /ws take precedence over the catch-all mount.
if WEB_DIR.is_dir():
    @app.get("/")
    async def index() -> HTMLResponse:
        # no-cache on the shell only: it is tiny and must be revalidated, or
        # the browser keeps handing out the old asset URLs and the versioning
        # above buys nothing. The assets themselves stay freely cacheable.
        return HTMLResponse(
            index_html(), headers={"Cache-Control": "no-cache"}
        )

    app.mount("/", StaticFiles(directory=WEB_DIR, html=True), name="web")


def run() -> None:
    import uvicorn

    uvicorn.run(
        "app.main:app",
        host=settings.host,
        port=settings.port,
        log_level="info",
    )


if __name__ == "__main__":
    run()
