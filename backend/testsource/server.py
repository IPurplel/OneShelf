"""aiohttp application implementing the Test Source scenarios. All content is synthetic."""
from __future__ import annotations

import asyncio
import threading
import io
import json
from collections import defaultdict
from dataclasses import dataclass, field

from aiohttp import web
from PIL import Image

HOST = "testsource.example"
CDN_HOST = "cdn.testsource.example"
SESSION_COOKIE = "ts_session"

WORKS = {
    "irregular": {"title": "The Irregular Chronicle", "type": "manga", "language": "en"},
    "big": {"title": "A Very Long Saga", "type": "manhwa", "language": "en"},
    "paged": {"title": "Paged Archive", "type": "comic", "language": "en"},
    "arabic": {"title": "حكاية القمر", "type": "manga", "language": "ar"},
    "private": {"title": "Members Only", "type": "manga", "language": "en"},
    "broken": {"title": "Broken Media", "type": "manga", "language": "en"},
    "manual": {"title": "The Manual", "type": "book", "language": "en"},
    "malformed": {"title": "  Weird   Metadata ", "type": "not-a-type", "language": "Klingon!!"},
}

IRREGULAR_UNITS = [
    {"id": "irr-prologue", "title": "Prologue", "label": "Prologue", "type": "prologue"},
    {"id": "irr-1", "title": "Chapter 1", "label": "Chapter 1", "type": "chapter"},
    {"id": "irr-2", "title": "Chapter 2", "label": "Chapter 2", "type": "chapter"},
    {"id": "irr-special", "title": "Special: Beach Day", "label": "Special", "type": "special"},
    {"id": "irr-3-5", "title": "Chapter 3.5", "label": "Chapter 3.5", "type": "chapter"},
    {"id": "irr-3", "title": "Chapter 3", "label": "Chapter 3", "type": "chapter"},
    {"id": "irr-10a", "title": "Chapter 10 (part A)", "label": "Chapter 10", "type": "chapter"},
    {"id": "irr-10b", "title": "Chapter 10 (part B)", "label": "Chapter 10", "type": "chapter"},
    {"id": "irr-extra", "title": "Extra Story", "label": "Extra", "type": "extra"},
]


def pdf(pages: int = 1) -> bytes:
    """A real PDF whose page count equals the file version, so a spliced file is detectable."""
    from pypdf import PdfWriter

    writer = PdfWriter()
    for _ in range(max(1, pages)):
        writer.add_blank_page(width=200, height=300)
    buf = io.BytesIO()
    writer.write(buf)
    return buf.getvalue() + b"\n% padding " + b"x" * 40_000


def png(width=40, height=60, shade=90) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (width, height), (shade, shade, shade)).save(buf, format="PNG")
    return buf.getvalue()


@dataclass
class Scenario:
    """Mutable server-side state toggled by tests through the control API."""
    big_collapsed: bool = False
    paged_mode: str = "normal"  # normal | fail_page_3 | repeat_page_2 | short
    rate_limit_remaining: int = 0
    retry_after: int = 2
    valid_sessions: set[str] = field(default_factory=set)
    file_version: int = 1
    markup_version: int = 1     # 2 renames the generator-facing classes (adapter repair testing)
    cookie_log: dict[str, list[str | None]] = field(default_factory=lambda: defaultdict(list))
    request_log: list[str] = field(default_factory=list)


def units_for(work: str, scenario: Scenario) -> list[dict]:
    if work == "irregular":
        return IRREGULAR_UNITS
    if work == "big":
        count = 7 if scenario.big_collapsed else 300
        return [{"id": f"big-{i}", "title": f"Chapter {i}", "label": f"Chapter {i}", "type": "chapter"} for i in range(1, count + 1)]
    if work == "paged":
        return [{"id": f"pg-{i}", "title": f"Episode {i}", "label": f"Episode {i}", "type": "chapter"} for i in range(1, 121)]
    if work == "arabic":
        return [{"id": f"ar-{i}", "title": f"الفصل {'٠١٢٣٤٥٦٧٨٩'[i]}", "label": f"الفصل {'٠١٢٣٤٥٦٧٨٩'[i]}", "type": "chapter"}
                for i in range(1, 4)]
    if work == "private":
        return [{"id": "priv-1", "title": "Chapter 1", "label": "Chapter 1", "type": "chapter"}]
    if work == "broken":
        return [{"id": "bad-html", "title": "HTML instead of media", "label": "Chapter 1", "type": "chapter"},
                {"id": "bad-corrupt", "title": "Corrupt media", "label": "Chapter 2", "type": "chapter"},
                {"id": "bad-limited", "title": "Rate limited media", "label": "Chapter 3", "type": "chapter"}]
    if work == "manual":
        return [{"id": "manual-1", "title": "The Manual (PDF)", "label": "Manual", "type": "other"}]
    if work == "malformed":
        return [{"id": "mal-1", "title": None, "label": "???", "type": "Chapter-ish"}, {"title": "no id at all"}]
    raise web.HTTPNotFound()


SCENARIO_KEY: web.AppKey[Scenario] = web.AppKey("scenario", Scenario)


def create_app(scenario: Scenario | None = None) -> web.Application:
    scenario = scenario or Scenario()
    app = web.Application()
    app[SCENARIO_KEY] = scenario

    @web.middleware
    async def track(request: web.Request, handler):
        scenario.request_log.append(f"{request.host.split(':')[0]}{request.path_qs}")
        scenario.cookie_log[request.host.split(":")[0]].append(request.headers.get("Cookie"))
        return await handler(request)

    app.middlewares.append(track)

    def logged_in(request: web.Request) -> bool:
        return request.cookies.get(SESSION_COOKIE) in scenario.valid_sessions

    async def search(request: web.Request) -> web.Response:
        q = request.query.get("q", "").strip().lower()
        page = int(request.query.get("page", "1"))
        hits = [(k, w) for k, w in WORKS.items() if q and (q in w["title"].lower() or q in k)]
        chunk = hits[(page - 1) * 3: page * 3]
        items = "".join(
            f"<li class='result'><a class='title' href='/work/{k}'>{w['title']}</a>"
            f"<span class='type'>{w['type']}</span><span class='lang'>{w['language']}</span>"
            f"<img class='cover' src='//{CDN_HOST}/covers/{k}.png'></li>" for k, w in chunk)
        return web.Response(text=f"<html><body><ul class='results'>{items}</ul></body></html>", content_type="text/html")

    async def work(request: web.Request) -> web.Response:
        key = request.match_info["work"]
        w = WORKS.get(key)
        if w is None:
            raise web.HTTPNotFound()
        return web.Response(content_type="text/html", text=(
            f"<html><body><h1 class='title'>{w['title']}</h1><div class='type'>{w['type']}</div>"
            f"<div class='lang'>{w['language']}</div><ul class='aliases'><li>Alias of {key}</li></ul></body></html>"))

    async def catalog(request: web.Request) -> web.Response:
        key = request.match_info["work"]
        if key == "private" and not logged_in(request):
            raise web.HTTPFound("/login?next=/api/works/private/units")
        page = int(request.query.get("page", "1"))
        units = units_for(key, scenario)
        size = 50
        if key == "paged":
            if scenario.paged_mode == "fail_page_3" and page == 3:
                raise web.HTTPInternalServerError(text="database on fire")
            if scenario.paged_mode == "repeat_page_2" and page == 2:
                page = 1
            if scenario.paged_mode == "short" and page >= 2:
                return web.json_response({"total": len(units), "units": []})
        chunk = units[(page - 1) * size: page * size]
        return web.json_response({"total": len(units), "units": chunk})

    async def pages(request: web.Request) -> web.Response:
        unit = request.match_info["unit"]
        if unit.startswith("priv") and not logged_in(request):
            raise web.HTTPFound(f"/login?next=/api/units/{unit}/pages")
        if unit == "bad-html":
            return web.json_response({"pages": [{"url": f"http://{CDN_HOST}/img/{unit}/1.png", "label": "1"},
                                                {"url": f"http://{CDN_HOST}/media/html-as-image.png", "label": "2"}]})
        if unit == "bad-corrupt":
            return web.json_response({"pages": [{"url": f"http://{CDN_HOST}/media/corrupt.png", "label": "1"}]})
        return web.json_response({"pages": [
            {"url": f"http://{CDN_HOST}/img/{unit}/{i}.png", "label": str(i)} for i in range(1, 4)]})

    async def pages_split(request: web.Request) -> web.Response:
        """Pages given as a base URL, a hash and bare filenames (the shape MangaDex's at-home API uses)."""
        unit = request.match_info["unit"]
        return web.json_response({"base": f"http://{CDN_HOST}", "hash": unit,
                                  "files": [f"{i}.png" for i in range(1, 4)]})

    async def files(request: web.Request) -> web.Response:
        return web.json_response({"files": [{"url": f"http://{HOST}/files/versioned.pdf", "format": "pdf"}]})

    async def image(request: web.Request) -> web.Response:
        if request.match_info.get("unit") == "bad-limited" and scenario.rate_limit_remaining > 0:
            scenario.rate_limit_remaining -= 1
            return web.Response(status=429, text="slow down", headers={"Retry-After": str(scenario.retry_after)})
        return web.Response(body=png(), content_type="image/png")

    async def html_as_image(request: web.Request) -> web.Response:
        return web.Response(text="<!DOCTYPE html><html>Access denied</html>", content_type="image/png")

    async def corrupt_image(request: web.Request) -> web.Response:
        return web.Response(body=b"\x89PNG\r\n\x1a\n" + b"\x00" * 64, content_type="image/png")

    async def versioned_file(request: web.Request) -> web.StreamResponse:
        body = pdf(scenario.file_version)
        etag = f'"v{scenario.file_version}"'
        headers = {"ETag": etag, "Accept-Ranges": "bytes"}
        range_header = request.headers.get("Range")
        if range_header and request.headers.get("If-Range", etag) == etag and range_header.startswith("bytes="):
            start = int(range_header[6:].split("-")[0])
            headers["Content-Range"] = f"bytes {start}-{len(body) - 1}/{len(body)}"
            return web.Response(status=206, body=body[start:], headers=headers)
        return web.Response(body=body, headers=headers, content_type="application/pdf")

    async def interrupted(request: web.Request) -> web.StreamResponse:
        response = web.StreamResponse(headers={"Content-Length": "100000", "Content-Type": "application/pdf"})
        await response.prepare(request)
        await response.write(b"%PDF-1.4 partial")
        await asyncio.sleep(0.01)
        request.transport.close()
        return response

    async def limited(request: web.Request) -> web.Response:
        if scenario.rate_limit_remaining > 0:
            scenario.rate_limit_remaining -= 1
            return web.Response(status=429, text="slow down", headers={"Retry-After": str(scenario.retry_after)})
        return web.Response(text="<html><ul class='results'></ul></html>", content_type="text/html")

    async def flaky(request: web.Request) -> web.Response:
        raise web.HTTPInternalServerError(text="boom")

    async def redirect_out(request: web.Request) -> web.Response:
        raise web.HTTPFound("http://unapproved.example/collect")

    async def login_form(request: web.Request) -> web.Response:
        return web.Response(content_type="text/html", text=(
            "<html><body><form method='post' action='/login'><input name='username'><input name='password' type='password'>"
            "<button type='submit'>Sign in</button></form></body></html>"))

    async def login_submit(request: web.Request) -> web.Response:
        form = await request.post()
        if form.get("username") != "reader" or form.get("password") != "correct horse":
            return web.Response(status=401, text="bad credentials")
        token = f"s{len(scenario.valid_sessions) + 1}-" + "x" * 16
        scenario.valid_sessions.add(token)
        response = web.HTTPFound("/account")
        response.set_cookie(SESSION_COOKIE, token, path="/", httponly=True)
        raise response

    async def account(request: web.Request) -> web.Response:
        if logged_in(request):
            body = ("<a class='logout' href='/logout'>Log out</a><script>localStorage.setItem('ts_pref','compact');"
                    "sessionStorage.setItem('ts_tab','library');</script>")
        else:
            body = "<a href='/login'>Sign in</a>"
        return web.Response(text=f"<html><body>{body}</body></html>", content_type="text/html")

    async def js_search(request: web.Request) -> web.Response:
        q = json.dumps(request.query.get("q", ""))
        works = json.dumps({k: w["title"] for k, w in WORKS.items()})
        script = (f"const q={q}.toLowerCase(); const works={works}; const ul=document.querySelector('ul.results');"
                  "for (const [k,t] of Object.entries(works)) { if (q && (t.toLowerCase().includes(q) || k.includes(q))) {"
                  "const li=document.createElement('li'); li.className='result'; const a=document.createElement('a');"
                  "a.className='title'; a.href='/work/'+k; a.textContent=t; li.appendChild(a); ul.appendChild(li);} }")
        return web.Response(content_type="text/html",
                            text=f"<html><body><ul class='results'></ul><script>{script}</script></body></html>")

    async def gen_search(request: web.Request) -> web.Response:
        """Conventional static search results linking to the static work pages (generator discovery)."""
        q = request.query.get("q", "").strip().lower()
        hits = [(k, w) for k, w in WORKS.items() if q and (q in w["title"].lower() or q in k)]
        items = "".join(
            f"<li class='result'><a class='title' href='/gen/work/{k}'>{w['title']}</a>"
            f"<span class='type'>{w['type']}</span><span class='lang'>{w['language']}</span>"
            f"<img class='cover' src='//{CDN_HOST}/covers/{k}.png'></li>" for k, w in hits)
        return web.Response(content_type="text/html",
                            text=f"<html><body><ul class='results'>{items}</ul></body></html>")

    async def gen_work(request: web.Request) -> web.Response:
        """A conventional static work page: title, cover and linked chapters (generator discovery)."""
        key = request.match_info["work"]
        w = WORKS.get(key)
        if w is None:
            raise web.HTTPNotFound()
        units = units_for(key, scenario)[:6]
        item_class = "chapter" if scenario.markup_version == 1 else "ch-row"
        chapters = "".join(
            f"<li class='{item_class}'><a href='/gen/chapter/{u['id']}'>{u['title']}</a>"
            f"<time datetime='{u.get('published_at', '2026-01-01')}'>{u.get('published_at', '2026-01-01')}</time></li>"
            for u in units)
        return web.Response(content_type="text/html", text=(
            f"<html><head><meta property='og:image' content='//{CDN_HOST}/covers/{key}.png'></head><body>"
            f"<h1 class='title'>{w['title']}</h1><div class='meta'><span class='type'>{w['type']}</span>"
            f"<span class='lang'>{w['language']}</span></div>"
            f"<ul class='chapters'>{chapters}</ul></body></html>"))

    async def gen_chapter(request: web.Request) -> web.Response:
        unit = request.match_info["unit"]
        image_class = "page" if scenario.markup_version == 1 else "pg-img"
        images = "".join(f"<img class='{image_class}' src='//{CDN_HOST}/img/{unit}/{i}.png' alt='Page {i}'>"
                         for i in range(1, 4))
        return web.Response(content_type="text/html",
                            text=f"<html><body><div class='reader'>{images}</div>"
                                 f"<script src='//tracker.example/ads.js'></script></body></html>")

    async def probe(request: web.Request) -> web.Response:
        targets = [t for t in request.query.getall("t", []) if t]
        tags = "".join(f"<img src='{t}'><iframe src='{t}'></iframe>" for t in targets)
        fetches = "".join(f"fetch({json.dumps(t)}).catch(()=>{{}});" for t in targets)
        return web.Response(content_type="text/html",
                            text=f"<html><body>{tags}<p id='done'>probe</p><script>{fetches}</script></body></html>")

    async def redirect_to(request: web.Request) -> web.Response:
        raise web.HTTPFound(request.query["url"])

    async def health(request: web.Request) -> web.Response:
        return web.json_response({"ok": True})

    async def control(request: web.Request) -> web.Response:
        data = await request.json()
        for key, value in data.items():
            if key == "expire_sessions":
                scenario.valid_sessions.clear()
            elif hasattr(scenario, key):
                setattr(scenario, key, value)
        return web.json_response({"ok": True})

    app.add_routes([
        web.get("/search", search), web.get("/work/{work}", work), web.get("/api/works/{work}/units", catalog),
        web.get("/api/units/{unit}/pages", pages), web.get("/api/units/{unit}/pages-split", pages_split), web.get("/api/units/{unit}/files", files), web.get("/img/{unit}/{page}.png", image),
        web.get("/covers/{work}.png", image), web.get("/media/html-as-image.png", html_as_image),
        web.get("/media/corrupt.png", corrupt_image), web.get("/files/versioned.pdf", versioned_file),
        web.get("/files/interrupted.pdf", interrupted), web.get("/limited", limited), web.get("/flaky", flaky),
        web.get("/redirect-out", redirect_out), web.get("/login", login_form), web.post("/login", login_submit),
        web.get("/account", account), web.get("/health", health), web.post("/__control", control),
        web.get("/js-search", js_search), web.get("/probe", probe), web.get("/redirect-to", redirect_to),
        web.get("/gen/search", gen_search), web.get("/gen/work/{work}", gen_work),
        web.get("/gen/chapter/{unit}", gen_chapter),
    ])
    return app


class TestSourceServer:
    """Runs the Test Source on 127.0.0.1 with an ephemeral port."""

    __test__ = False  # not a pytest test class

    def __init__(self, scenario: Scenario | None = None) -> None:
        self.scenario = scenario or Scenario()
        self.port: int | None = None
        self._runner: web.AppRunner | None = None

    async def __aenter__(self) -> TestSourceServer:
        self._runner = web.AppRunner(create_app(self.scenario), access_log=None)
        await self._runner.setup()
        site = web.TCPSite(self._runner, "127.0.0.1", 0)
        await site.start()
        self.port = site._server.sockets[0].getsockname()[1]
        return self

    async def __aexit__(self, *exc) -> None:
        if self._runner is not None:
            await self._runner.cleanup()

    def hosts(self) -> dict[str, tuple[str, int]]:
        return {HOST: ("127.0.0.1", self.port), CDN_HOST: ("127.0.0.1", self.port)}


class BackgroundTestSource:
    """Runs the Test Source on its own thread and loop, for tests that drive the app through a client."""

    __test__ = False

    def __init__(self, scenario: Scenario | None = None) -> None:
        self.scenario = scenario or Scenario()
        self.port: int | None = None
        self._thread: threading.Thread | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._ready = threading.Event()
        self._stop: asyncio.Event | None = None

    def __enter__(self) -> BackgroundTestSource:
        self._thread = threading.Thread(target=self._run, daemon=True, name="oneshelf-test-source")
        self._thread.start()
        if not self._ready.wait(timeout=20):
            raise RuntimeError("the Test Source did not start")
        return self

    def __exit__(self, *exc) -> None:
        if self._loop is not None and self._stop is not None:
            self._loop.call_soon_threadsafe(self._stop.set)
        if self._thread is not None:
            self._thread.join(timeout=20)

    def _run(self) -> None:
        asyncio.run(self._serve())

    async def _serve(self) -> None:
        self._loop = asyncio.get_running_loop()
        self._stop = asyncio.Event()
        runner = web.AppRunner(create_app(self.scenario), access_log=None)
        await runner.setup()
        site = web.TCPSite(runner, "127.0.0.1", 0)
        await site.start()
        self.port = site._server.sockets[0].getsockname()[1]
        self._ready.set()
        try:
            await self._stop.wait()
        finally:
            await runner.cleanup()

    def hosts(self) -> dict[str, tuple[str, int]]:
        return {HOST: ("127.0.0.1", self.port), CDN_HOST: ("127.0.0.1", self.port)}

    def address(self) -> str:
        return f"127.0.0.1:{self.port}"
