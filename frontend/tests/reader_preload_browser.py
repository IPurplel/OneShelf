"""Reader preloads never outrun the first visible page or duplicate a completed page fetch."""
import sys
from pathlib import Path
from urllib.parse import urlparse

from playwright.sync_api import sync_playwright

sys.path.insert(0, str(Path(__file__).parent))
from layout_browser import COVER, fixture  # noqa: E402


def main() -> None:
    page_requests: list[str] = []
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        page = browser.new_page(viewport={"width": 390, "height": 844}, reduced_motion="reduce")
        page.add_init_script("localStorage.setItem('oneshelf.reader.global', JSON.stringify({mode:'single'}))")

        def route(request):
            path = urlparse(request.request.url).path
            if path == "/api/reader/units/u0/pages":
                return request.fulfill(json={"reading_unit_id": "u0", "pages": [
                    {"index": index, "label": str(index), "url": None} for index in range(1, 4)]})
            if path.startswith("/api/reader/units/u0/pages/"):
                page_requests.append(request.request.url)
                return request.fulfill(content_type="image/svg+xml", body=COVER,
                                       headers={"Cache-Control": "no-store"})
            return fixture(request, 3)

        page.route("http://127.0.0.1:5173/api/**", route)
        page.goto("http://127.0.0.1:5173/read/u0?work=w0&track=t0")
        first = page.locator("img.reader__page").first
        first.wait_for()
        page.wait_for_function("document.querySelector('img.reader__page')?.naturalWidth > 0")
        page.wait_for_function("performance.getEntriesByType('resource').some(e => e.name.includes('/pages/2?prefetch=1'))")
        assert urlparse(page_requests[0]).path.endswith("/pages/1"), page_requests
        page.keyboard.press("ArrowRight")
        page.wait_for_function("""() => {
            const image = document.querySelector('img.reader__page');
            return image?.src.startsWith('blob:') && image.naturalWidth > 0;
        }""")
        assert len([url for url in page_requests if urlparse(url).path.endswith("/pages/2")]) == 1, page_requests
        print(f"visible page first; page 2 fetched once; {len(page_requests)} total page requests")
        browser.close()


if __name__ == "__main__":
    main()
