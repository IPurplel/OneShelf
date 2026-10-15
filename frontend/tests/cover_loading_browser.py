"""Search cover request budget in a real browser, with a crowded result list."""
import json
import sys
from pathlib import Path
from urllib.parse import urlparse

from playwright.sync_api import sync_playwright

sys.path.insert(0, str(Path(__file__).parent))
from layout_browser import COVER, fixture, results  # noqa: E402


def main() -> None:
    rows = results(24)
    for index, row in enumerate(rows):
        row["cover_url"] = f"/api/covers/{index}"
    requested: list[int] = []

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        page = browser.new_page(viewport={"width": 390, "height": 844}, reduced_motion="reduce")

        def route(request):
            path = urlparse(request.request.url).path
            if path == "/api/search":
                update = {"stage": "complete", "results": rows, "source_status": {},
                          "sources_total": 0, "sources_done": 0, "sources_failed": 0}
                return request.fulfill(content_type="text/event-stream",
                                       body=f"event: complete\ndata: {json.dumps(update)}\n\n")
            if path.startswith("/api/covers/"):
                requested.append(int(path.rsplit("/", 1)[1]))
                return request.fulfill(content_type="image/svg+xml", body=COVER)
            return fixture(request, 4)

        page.route("http://127.0.0.1:5173/api/**", route)
        page.goto("http://127.0.0.1:5173/search?q=book", wait_until="domcontentloaded")
        page.locator(".search__results .workcard").first.wait_for()
        page.wait_for_timeout(500)
        initial = requested.copy()
        assert {0, 1}.issubset(initial), f"visible covers were not requested: {initial}"
        assert len(initial) <= 4, f"too many covers requested before scrolling: {initial}"

        page.locator(".search__results .workcard").nth(12).scroll_into_view_if_needed()
        for _ in range(30):
            if 12 in requested:
                break
            page.wait_for_timeout(50)
        assert 12 in requested, f"scrolled-to cover was not requested: {requested}"
        print(f"initial covers: {len(initial)}; after scroll: {len(requested)}")
        browser.close()


if __name__ == "__main__":
    main()
