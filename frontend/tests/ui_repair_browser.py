"""Chrome fixture regressions for UI-001..005; use a local Vite preview, never production data."""
import argparse
import json
from pathlib import Path

from playwright.sync_api import expect, sync_playwright

from layout_browser import COVER, fixture


SIZES = [(1440, 900), (768, 1024), (390, 844), (320, 768)]


def run(page, url, out, width, language):
    console = []
    failed = []
    page.on("console", lambda message: console.append(message.text) if message.type == "error" else None)
    page.on("pageerror", lambda error: console.append(str(error)))
    page.on("response", lambda response: failed.append(f"{response.status} {response.url}")
            if response.status >= 400 and "/api/covers/broken" not in response.url else None)
    page.route(url + "/api/**", lambda route: fixture(route, 7))
    page.route(url + "/api/covers/broken", lambda route: route.fulfill(status=200, content_type="image/svg+xml", body=COVER))
    page.route(url + "/api/reader/units/u0/alternatives", lambda route: route.fulfill(json=dict(
        unit_id="u0", track_id="t0", source_id="local", language="en", alternatives=[])))
    detail_requests = []

    def download_detail(route):
        detail_requests.append(route.request.url)
        route.fulfill(json=dict(batch_id="b0", state="active", completed=1, failed=1, pending=0,
                                canceled=1, skipped=1, counts={}, jobs=[
            dict(id="j1", reading_unit_id="u0", unit_title="Chapter One", work_id="w0", track_id="t0",
                 work_title="Reader smoke test", state="COMPLETED", available=True, bytes_done=120, bytes_total=120),
            dict(id="j2", reading_unit_id="u2", unit_title="Chapter Two", state="FAILED",
                 error_category="transport", last_error="Source timed out", bytes_done=0),
            dict(id="j3", reading_unit_id="u3", unit_title="Chapter Three", state="CANCELED", bytes_done=0),
        ]))

    page.route(url + "/api/downloads/b0", download_detail)
    page.route(url + "/api/downloads", lambda route: route.fulfill(json=dict(batches=[dict(
        batch_id="b0", state="completed_with_issues", completed=1, failed=1, pending=0,
        canceled=1, skipped=1, counts=dict(COMPLETED=1, FAILED=1, CANCELED=1))])))
    if language == "ar":
        page.add_init_script("localStorage.setItem('oneshelf.language', 'ar')")

    # Direct route focus order and selected category reveal, including RTL and the 320px reflow case.
    page.goto(url + "/settings/developer")
    page.locator("#settings-tab-developer").wait_for()
    page.keyboard.press("Tab")
    expect(page.locator(".skip-link")).to_be_focused()
    page.keyboard.press("Tab")
    assert not page.evaluate("document.activeElement.closest('.settings__layout') !== null"), "Settings took focus before navigation"
    visible = page.evaluate("""() => { const nav=document.querySelector('.settings__nav');
      const tab=nav.querySelector('[aria-selected=true]'); const a=nav.getBoundingClientRect(), b=tab.getBoundingClientRect();
      return b.left>=a.left-1 && b.right<=a.right+1 }""")
    assert visible, "selected Settings category is clipped"
    page.screenshot(path=str(out / f"{language}-{width}-settings.png"))
    selected = page.locator("#settings-tab-developer")
    selected.focus()
    page.keyboard.press("Home")
    expect(page.locator("#settings-tab-general")).to_have_attribute("aria-selected", "true")
    orientation = page.get_by_role("tablist").get_attribute("aria-orientation")
    page.keyboard.press("ArrowDown" if orientation == "vertical" else "ArrowRight")
    expect(page.locator("#settings-tab-reader")).to_have_attribute("aria-selected", "true")

    # Search view switch retains its query and source-choice contract.
    page.goto(url + "/search?q=book&language=AR")
    expect(page.locator(".search__results .workcard")).to_have_count(7)
    page.get_by_role("button", name="عرض قائمة" if language == "ar" else "List view").click()
    expect(page.locator(".search__results")).to_have_attribute("data-layout", "list")
    assert "language=AR" in page.url and "q=book" in page.url
    page.locator(".search__results .workcard").first.click()
    drawer = page.get_by_role("dialog")
    expect(drawer.locator(".choice__option")).to_have_count(2)
    page.keyboard.press("Escape")
    page.screenshot(path=str(out / f"{language}-{width}-search-list.png"))

    # The closed list does not request every batch's details.
    page.goto(url + "/downloads")
    expect(page.locator(".batches__row")).to_have_count(1)
    assert not detail_requests
    toggle = page.locator(".batches__row button[aria-expanded]")
    toggle.focus()
    page.keyboard.press("Enter")
    expect(toggle).to_have_attribute("aria-expanded", "true")
    expect(page.get_by_text("Chapter One")).to_be_visible()
    expect(page.locator('.batches__job a[href="/read/u0?work=w0&track=t0"]')).to_have_count(1)
    expect(page.get_by_text("Chapter Two")).to_be_visible()
    assert len(detail_requests) == 1
    page.screenshot(path=str(out / f"{language}-{width}-downloads.png"))
    page.locator('.batches__job a[href="/read/u0?work=w0&track=t0"]').click()
    expect(page.get_by_role("button", name="Reader settings" if language == "en" else "إعدادات القارئ")).to_be_visible()

    # The current source-list API lacks this aggregate field; fixture exercises the agreed presentation contract.
    page.route(url + "/api/sources", lambda route: route.fulfill(json=dict(sources=[
        dict(id="alpha", name="Reading Room Library", state="active", version="1.0.0", trust_label="official",
             channel="bundled", capabilities=["search", "work"], auth_available=False, session_state="none",
             last_successful_check_at="2026-10-18T12:30:00Z"),
        dict(id="beta", name="Archive Source", state="disabled", version="1.0.0", trust_label="official",
             channel="bundled", capabilities=["search"], auth_available=False, session_state="none",
             last_successful_check_at=None),
    ])))
    page.goto(url + "/sources")
    expect(page.locator(".cards__row")).to_have_count(2)
    expect(page.locator(".cards__row time")).to_have_count(1)
    if language == "en" and width in (1440, 390):
        axe_path = Path(__file__).resolve().parents[1] / "node_modules/axe-core/axe.min.js"
        page.add_script_tag(path=str(axe_path))
        contrast = page.evaluate("async () => (await axe.run(document, { runOnly: ['color-contrast'] })).violations")
        assert not contrast, f"Sources contrast: {[item['id'] for item in contrast]}"
    page.screenshot(path=str(out / f"{language}-{width}-sources.png"))

    # Empty inbox actions must be absent; populated behavior is covered in component tests.
    page.goto(url + "/")
    page.get_by_role("button", name="Notifications" if language == "en" else "الإشعارات").click()
    expect(page.get_by_role("dialog")).to_be_visible()
    assert page.get_by_role("button", name="Mark all as seen" if language == "en" else "علِّم الكل كمقروء").count() == 0
    page.screenshot(path=str(out / f"{language}-{width}-notifications.png"))

    overflow = page.evaluate("document.documentElement.scrollWidth - innerWidth")
    assert overflow <= 1, f"document overflow: {overflow}px"
    assert not console, f"console errors: {console}; HTTP: {failed}"
    assert not failed, f"HTTP errors: {failed}"
    return dict(language=language, width=width, console=console, failed=failed, detail_requests=len(detail_requests), overflow=overflow)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default="http://127.0.0.1:4177")
    parser.add_argument("--screenshots", default="qa-artifacts/ui-repair")
    args = parser.parse_args()
    out = Path(args.screenshots)
    out.mkdir(parents=True, exist_ok=True)
    reports = []
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(channel="chrome")
        for width, height in SIZES:
            for language in ("en", "ar"):
                context = browser.new_context(viewport={"width": width, "height": height},
                                              has_touch=width <= 768, is_mobile=width <= 768,
                                              reduced_motion="reduce")
                page = context.new_page()
                try:
                    reports.append(run(page, args.url, out, width, language))
                    print("PASS", language, width, flush=True)
                finally:
                    context.close()
        for mode in ("dark", "forced"):
            context = browser.new_context(viewport={"width": 390, "height": 844},
                                          color_scheme="dark" if mode == "dark" else "light",
                                          forced_colors="active" if mode == "forced" else "none",
                                          reduced_motion="reduce")
            page = context.new_page()
            page.route(args.url + "/api/**", lambda route: fixture(route, 7))
            page.goto(args.url + "/settings/reader")
            page.keyboard.press("Tab")
            expect(page.locator(".skip-link")).to_be_focused()
            page.screenshot(path=str(out / f"{mode}-390-settings.png"))
            assert page.evaluate("document.documentElement.scrollWidth - innerWidth") <= 1
            context.close()
        browser.close()
    (out / "report.json").write_text(json.dumps(reports, indent=2))


if __name__ == "__main__":
    main()
