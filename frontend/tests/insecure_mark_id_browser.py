"""Exercise the LAN HTTP crypto API surface on localhost Chromium with randomUUID removed."""
import argparse
import json
import re
from pathlib import Path

from playwright.sync_api import expect, sync_playwright
from targeted_ui_bugfix_browser import new_page

UUID_V4 = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$")


def run(base: str, output: Path) -> None:
    trace = {}
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        for language in ("en", "ar"):
            page, state = new_page(browser, base, language, 390, "bookmark")
            page.add_init_script("Object.defineProperty(Crypto.prototype, 'randomUUID', "
                                 "{ value: undefined, configurable: true });")
            highlights = []

            def highlight_route(route):
                body = route.request.post_data_json
                highlights.append(body)
                if len(highlights) == 1:
                    return route.fulfill(status=503, json={"error": {"message": "Response lost"}})
                return route.fulfill(json={"id": f"h{len(highlights)}", "locator": body["locator"],
                    "text": body["text"], "colour": "yellow", "created_at": "2026-10-07T00:00:00Z"})

            page.route(base + "/api/reader/units/u0/highlights", highlight_route)
            page.goto(base + "/read/u0?work=w0&track=t-en")
            environment = page.evaluate("({ secure: isSecureContext, "
                "randomUUID: typeof crypto.randomUUID, getRandomValues: typeof crypto.getRandomValues })")
            assert environment == {"secure": True, "randomUUID": "undefined",
                                   "getRandomValues": "function"}, environment
            expect(page.get_by_role("status")).to_contain_text("1")

            page.locator(".reader__bar--top button").nth(2).click()
            expect(page.get_by_role("alert")).to_be_visible()
            page.locator(".book__markProblem button").click()
            expect(page.get_by_role("alert")).to_have_count(0)
            bookmark_calls = [call["body"] for call in state["calls"] if call.get("path", "").endswith("/bookmarks")]
            assert len(bookmark_calls) == 2
            assert UUID_V4.fullmatch(bookmark_calls[0]["operation_id"])
            assert bookmark_calls[1]["operation_id"] == bookmark_calls[0]["operation_id"]

            def save_highlight():
                page.locator(".reader__bar--top button").nth(3).click()
                passage = page.locator(".book__passage")
                expect(passage).to_be_visible()
                passage.evaluate("""element => {
                    const range = document.createRange();
                    range.setStart(element.firstChild, 0);
                    range.setEnd(element.firstChild, 4);
                    const selected = window.getSelection();
                    selected.removeAllRanges();
                    selected.addRange(range);
                    document.dispatchEvent(new Event('selectionchange'));
                }""")
                page.locator(".drawer__actions button").click()

            save_highlight()
            expect(page.get_by_role("alert")).to_be_visible()
            page.screenshot(path=str(output / f"{language}-390-fallback-mark-error.png"), full_page=True)
            page.locator(".book__markProblem button").click()
            expect(page.get_by_role("alert")).to_have_count(0)
            save_highlight()
            expect(page.get_by_role("alert")).to_have_count(0)
            assert len(highlights) == 3
            assert UUID_V4.fullmatch(highlights[0]["operation_id"])
            assert highlights[1]["operation_id"] == highlights[0]["operation_id"]
            assert UUID_V4.fullmatch(highlights[2]["operation_id"])
            assert highlights[2]["operation_id"] != highlights[0]["operation_id"]
            assert not state["errors"], state["errors"]
            trace[language] = {"environment": environment, "bookmarks": bookmark_calls,
                               "highlights": highlights}
            page.close()
            print("PASS insecure-context-equivalent marks", language, flush=True)
        browser.close()
    (output / "request-trace.json").write_text(json.dumps(trace, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default="http://127.0.0.1:5173")
    parser.add_argument("--screenshots", default="/tmp/oneshelf-lan-mark-ids")
    options = parser.parse_args()
    output = Path(options.screenshots)
    output.mkdir(parents=True, exist_ok=True)
    run(options.url, output)
