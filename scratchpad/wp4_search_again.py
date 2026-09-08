"""WP-4: prove the search box survives opening a result, in a real browser.

    python scratchpad/wp4_search_again.py [--port 8099]

The sequence the work package requires, with **no reload** anywhere in it:

    search -> click result -> back to results -> click a DIFFERENT result
           -> new search -> click a result

web/ has no test runner: three static files, no build step. So this drives the
real UI against a real server on isolated storage, and asserts on what the page
actually does. Every step prints what it saw, and the transcript is the
evidence.

The searches are served from a stub adapter rather than the live sites: the
assertions here are all about *the browser*, and a real multi-site search would
make the run depend on eight third parties agreeing to answer twice.
"""
from __future__ import annotations

import argparse
import asyncio
import contextlib
import os
from pathlib import Path
import socket
import sys
import tempfile

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

STUB_RESULTS = [
    {"title": "Berserk", "url": "https://example.invalid/manga/berserk",
     "source": "stub", "site": "example.invalid", "content_type": "manga"},
    {"title": "Berserk: The Guidebook",
     "url": "https://example.invalid/manga/berserk-guidebook",
     "source": "stub", "site": "example.invalid", "content_type": "manga"},
    {"title": "رواية الغريب", "url": "https://example.invalid/manga/algharib",
     "source": "stub", "site": "example.invalid", "content_type": "manga"},
]


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=0)
    parser.add_argument("--headed", action="store_true")
    args = parser.parse_args()

    workdir = Path(tempfile.mkdtemp(prefix="wp4-", dir=ROOT / ".state"))
    os.environ.update({
        "MD_CONFIG_DIR": str(workdir / "config"),
        "MD_OUTPUT_DIR": str(workdir / "downloads"),
        "MD_DESYNC_PORT": "0",
        "PYTHONIOENCODING": "utf-8",
    })

    import uvicorn

    port = args.port or free_port()

    # Search and preview are stubbed: this run is about the browser, and a
    # preview that had to reach a real site would make the assertions depend on
    # a third party answering the same way three times.
    async def fake_search(request, q="", type=None, sites=None, limit=12,
                          refresh=False):
        query = (q or "").strip()
        results = [dict(r, score=100, match="exact") for r in STUB_RESULTS] \
            if len(query) >= 2 else []
        return {"query": query, "type": type or "manga", "results": results,
                "sites": [{"site": "https://example.invalid",
                           "host": "example.invalid", "status": "ok",
                           "count": len(results)}],
                "counts": {"manga": len(results)}, "merged": 0}

    async def fake_preview(payload):
        url = payload.url if hasattr(payload, "url") else payload["url"]
        slug = url.rstrip("/").rsplit("/", 1)[-1]
        return {
            "series": {"url": url, "title": f"Preview of {slug}",
                       "source": "stub", "cover_url": None,
                       "description": "", "site_id": None},
            "chapters": [{"url": f"{url}/{n}", "title": f"Chapter {n}",
                          "number": str(n), "index": n, "date": None,
                          "status": "pending"} for n in range(1, 6)],
            "in_library": False,
        }

    from fastapi import FastAPI, WebSocket
    stub = FastAPI()

    @stub.get("/api/search")
    async def _search(q: str = "", type: str | None = None,
                      sites: str | None = None, limit: int = 12,
                      refresh: bool = False):
        return await fake_search(None, q, type, sites, limit, refresh)

    @stub.post("/api/preview")
    async def _preview(payload: dict):
        return await fake_preview(payload)

    @stub.get("/api/sources")
    async def _sources():
        return {"kinds": [{"type": "manga", "label": "Manga",
                           "sites": [{"site": "https://example.invalid",
                                      "host": "example.invalid",
                                      "adapter": "stub",
                                      "adapter_name": "Stub"}],
                           "count": 1},
                          {"type": "comics", "label": "Comics",
                           "sites": [], "count": 0},
                          {"type": "book", "label": "Books",
                           "sites": [], "count": 0}]}

    @stub.get("/api/series")
    async def _series():
        return []

    @stub.get("/api/jobs")
    async def _jobs():
        return []

    @stub.get("/api/settings")
    async def _settings():
        return {"editable": {}, "values": {}}

    @stub.websocket("/ws")
    async def _ws(websocket: WebSocket):
        # The UI opens a socket for job progress on load. Without it the page
        # logs a handshake failure every few seconds, which buries the console
        # errors this run is actually watching for.
        await websocket.accept()
        try:
            while True:
                await websocket.receive_text()
        except Exception:
            return

    from fastapi.staticfiles import StaticFiles
    stub.mount("/", StaticFiles(directory=str(ROOT / "web"), html=True),
               name="web")

    config = uvicorn.Config(stub, host="127.0.0.1", port=port, log_level="warning")
    server = uvicorn.Server(config)
    task = asyncio.create_task(server.serve())
    while not server.started:
        await asyncio.sleep(0.05)

    ok = True
    try:
        ok = await drive(f"http://127.0.0.1:{port}/", headed=args.headed)
    finally:
        server.should_exit = True
        with contextlib.suppress(Exception):
            await task

    print("\nRESULT:", "PASS" if ok else "FAIL")
    return 0 if ok else 1


async def drive(url: str, *, headed: bool) -> bool:
    from patchright.async_api import async_playwright

    steps: list[tuple[str, bool, str]] = []

    def record(name: str, passed: bool, detail: str = "") -> None:
        steps.append((name, passed, detail))
        print(f"  [{'ok ' if passed else 'FAIL'}] {name}"
              + (f"  -- {detail}" if detail else ""), flush=True)

    async with async_playwright() as pw:
        # no_viewport=True and nothing else: passing viewport, locale,
        # user_agent or ignore_https_errors applies detectable CDP overrides.
        browser = await pw.chromium.launch(headless=not headed)
        page = await browser.new_page(no_viewport=True)
        page.on("console", lambda m: print(f"    console[{m.type}] {m.text}")
                if m.type == "error" else None)

        await page.goto(url, wait_until="domcontentloaded")
        await page.wait_for_selector("#search-kinds .kind")

        loads = {"count": 1}
        page.on("load", lambda _: loads.__setitem__("count", loads["count"] + 1))

        await page.click('#search-kinds .kind[data-kind="manga"]')

        # ---------------------------------------------------------- 1. search
        await page.fill("#search-input", "berserk")
        await page.wait_for_selector(".search-hit:not(.skeleton)")
        hits = await page.locator(".search-hit:not(.skeleton)").count()
        record("search returns results", hits >= 3, f"{hits} hits")

        # ---------------------------------------------- 2. click a result
        first = await page.locator(".search-hit .hit-title").first.inner_text()
        await page.locator(".search-hit").first.click()
        await page.wait_for_selector("#preview:not([hidden])")
        title = await page.locator("#series-title").inner_text()
        record("clicking a result opens its preview", "berserk" in title.lower(),
               f"{title!r} from {first!r}")
        record("the result list is closed",
               await page.locator("#search-results").is_hidden())
        record("a way back is offered",
               await page.locator("#back-to-results").is_visible())

        # ------------------------------------------- 3. back to results
        await page.click("#back-to-results")
        await page.wait_for_selector(".search-hit:not(.skeleton)")
        back = await page.locator(".search-hit:not(.skeleton)").count()
        record("back to results restores the list", back == hits,
               f"{back} hits, no reload")
        record("the preview is closed",
               await page.locator("#preview").is_hidden())

        # ------------------------------- 4. click a DIFFERENT result
        second = await page.locator(".search-hit .hit-title").nth(1).inner_text()
        await page.locator(".search-hit").nth(1).click()
        await page.wait_for_selector("#preview:not([hidden])")
        title2 = await page.locator("#series-title").inner_text()
        record("a different result opens a different preview",
               title2 != title, f"{title2!r} from {second!r}")

        # ------------------------------------------------ 5. a NEW search
        await page.click("#back-to-results")
        await page.wait_for_selector(".search-hit:not(.skeleton)")
        await page.fill("#search-input", "")
        await page.fill("#search-input", "الغريب")
        await page.wait_for_selector(".search-hit:not(.skeleton)")
        record("a new search runs after all of that",
               await page.locator(".search-hit:not(.skeleton)").count() >= 1)

        # ------------------------------------ 6. click a result again
        await page.locator(".search-hit").first.click()
        await page.wait_for_selector("#preview:not([hidden])")
        record("and its result opens too",
               await page.locator("#preview").is_visible())

        # ------------------------------------------------ the other routes
        await page.keyboard.press("Escape")
        record("Escape leaves the preview",
               await page.locator("#preview").is_hidden())

        await page.keyboard.press("/")
        focused = await page.evaluate("document.activeElement?.id")
        record("'/' focuses the search box, not the chapter filter",
               focused == "search-input", f"focus went to {focused!r}")

        # The reported symptom, directly: the box still holds the query and
        # retyping it fires no `input` event at all.
        await page.locator(".search-hit").first.click()
        await page.wait_for_selector("#preview:not([hidden])")
        value = await page.input_value("#search-input")
        record("the query is still in the box after opening a result",
               value == "الغريب", repr(value))
        await page.focus("#search-input")
        await page.keyboard.press("Enter")
        await page.wait_for_selector(".search-hit:not(.skeleton)")
        record("Enter brings the same list back",
               await page.locator(".search-hit:not(.skeleton)").count() >= 1)

        record("no page reload happened at any point", loads["count"] == 1,
               f"{loads['count']} load event(s)")

        await browser.close()

    print(f"\n{sum(1 for _, p, _ in steps if p)}/{len(steps)} checks passed")
    return all(passed for _, passed, _ in steps)


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
