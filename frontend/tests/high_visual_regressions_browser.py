"""Chromium regressions for I-54, I-55, and I-56. Requires a running Vite server."""
import argparse
from pathlib import Path
from urllib.parse import urlparse

from playwright.sync_api import sync_playwright

from layout_browser import COVER, fixture


WIDTHS = (390, 768, 1440)
HEIGHT = 844
ERROR = "Chapter pages are temporarily unavailable"


def browser_page(browser, url, language, width, *, page_error=False):
    page = browser.new_page(viewport={"width": width, "height": HEIGHT}, reduced_motion="reduce")
    page.add_init_script(f"localStorage.setItem('oneshelf.language', '{language}')")
    calls = {"pages": 0, "allow_success": False}

    def route(request):
        path = urlparse(request.request.url).path
        if path == "/api/reader/units/u0/pages" and page_error:
            calls["pages"] += 1
            if not calls["allow_success"]:
                return request.fulfill(status=503, json={"error": {"message": ERROR}})
        if path == "/api/reader/units/u0/pages":
            return request.fulfill(json={"reading_unit_id": "u0", "pages": [
                {"index": index, "label": str(index), "url": None} for index in (1, 2, 3)]})
        if path in ("/api/reader/units/u0/pages/2", "/api/reader/units/u0/pages/3"):
            return request.fulfill(content_type="image/svg+xml", body=COVER)
        if path == "/api/backups":
            return request.fulfill(json={"backups": [], "due": False, "location_warning": None})
        if path == "/api/auth/state":
            return request.fulfill(json={"access": "loopback", "remote_enabled": False,
                "canonical_hostname": None, "passkeys": [], "sessions": [],
                "recovery": {"configured": False, "created_at": None, "last_used_at": None},
                "network": {"trusted_networks": [], "trusted_proxies": [], "gateway_warning": None},
                "session_lifetimes": ["7d", "30d", "90d", "1y", "manual"]})
        if path == "/api/diagnostics":
            return request.fulfill(json={"entries": 0, "size_bytes": 0, "oldest_day": None,
                "max_bytes": 104857600, "max_age_days": 7, "directory": "/data/diagnostics"})
        return fixture(request, 3)

    page.route(url + "/api/**", route)
    return page, calls


def visible_controls(page, width):
    return page.evaluate("""() => [...document.querySelectorAll(
      '.reader__bar--top > .reader__button, .reader__bar--bottom .reader__button, .reader__bar--bottom input'
    )].map(el => {
      const r = el.getBoundingClientRect();
      const center = {x: r.left + r.width / 2, y: r.top + r.height / 2};
      const hit = document.elementFromPoint(center.x, center.y);
      return {name: el.textContent.trim() || el.getAttribute('aria-label'),
        left: r.left, right: r.right, top: r.top, bottom: r.bottom,
        hit: hit === el || el.contains(hit)};
    })""")


def test_reader_controls(browser, url, out):
    for language in ("en", "ar"):
        for width in WIDTHS:
            page, _ = browser_page(browser, url, language, width)
            try:
                page.goto(url + "/read/u0?work=w0&track=t0")
                page.locator(".reader__bar--top > .reader__button").first.wait_for()
                page.locator(".reader__stage img.reader__page").first.wait_for()
                page.locator(".reader__stage img.reader__page").first.evaluate("img => img.decode()")
                page.mouse.move(width / 2, 10)
                controls = visible_controls(page, width)
                page.screenshot(path=str(out / f"i54-{language}-{width}.png"))
                assert len(controls) >= 6, (language, width, controls)
                for control in controls:
                    assert control["left"] >= -1 and control["right"] <= width + 1, (language, width, control)
                    assert control["top"] >= -1 and control["bottom"] <= HEIGHT + 1, (language, width, control)
                    assert control["hit"], (language, width, "covered control", control)
                if width == 390:
                    page.evaluate("""() => {
                      document.querySelector('.reader__title').textContent = 'A very long work title '.repeat(18);
                      document.querySelector('.reader__unit').textContent = 'A very long chapter title '.repeat(12);
                    }""")
                    page.screenshot(path=str(out / f"i54-{language}-{width}-long-title.png"))
                    for control in visible_controls(page, width):
                        assert control["left"] >= -1 and control["right"] <= width + 1, (language, width, control)
                        assert control["top"] >= -1 and control["bottom"] <= HEIGHT + 1, (language, width, control)
                        assert control["hit"], (language, width, "long title covered control", control)
                    assert page.locator(".reader__bar--top").bounding_box()["height"] <= 220, (
                        language, width, "long titles consume the reading stage")

                top = page.locator(".reader__bar--top")
                top.get_by_role("button", name="Contents" if language == "en" else "المحتويات").click()
                page.get_by_role("dialog").wait_for()
                page.keyboard.press("Escape")
                top.get_by_role("button", name="Reader settings" if language == "en" else "إعدادات القارئ").click()
                page.get_by_role("dialog").wait_for()
                page.keyboard.press("Escape")
                top.get_by_role("button", name="More" if language == "en" else "المزيد").click()
                assert top.get_by_role("button", name="More" if language == "en" else "المزيد").get_attribute("aria-expanded") == "true"
                top.locator("#reader-more button").first.click()
                assert top.locator("#reader-more").count() == 0
                scrubber = page.locator('.reader__bar--bottom input[type="range"]')
                scrubber.fill("2")
                assert scrubber.input_value() == "2"
                assert "2 / 3" in page.locator(".reader__bar--bottom").inner_text()
                top.get_by_role("button", name="Full screen" if language == "en" else "ملء الشاشة").click()
                page.wait_for_function("document.fullscreenElement !== null")
                page.evaluate("document.exitFullscreen()")
                page.wait_for_function("document.fullscreenElement === null")
                top.locator("a.reader__button").first.click()
                page.wait_for_url(lambda current: urlparse(current).path == "/works/w0" and urlparse(current).query == "track=t0")
                print("PASS I-54", language, width, len(controls), flush=True)
            finally:
                page.close()


def contrast(page):
    return page.locator(".reader__stage .notice[role=alert]").evaluate("""el => {
      const rgb = value => value.match(/[\\d.]+/g).slice(0, 3).map(Number);
      const lum = color => rgb(color).map(v => {
        v /= 255; return v <= .04045 ? v / 12.92 : ((v + .055) / 1.055) ** 2.4;
      }).reduce((sum, v, i) => sum + v * [.2126, .7152, .0722][i], 0);
      const style = getComputedStyle(el), a = lum(style.color), b = lum(style.backgroundColor);
      return {ratio: (Math.max(a, b) + .05) / (Math.min(a, b) + .05),
        color: style.color, background: style.backgroundColor};
    }""")


def test_reader_error(browser, url, out):
    for language in ("en", "ar"):
        for width in WIDTHS:
            for theme in ("black", "dark", "white"):
                page, calls = browser_page(browser, url, language, width, page_error=True)
                try:
                    page.goto(url + "/read/u0?work=w0&track=t0")
                    alert = page.locator(".reader__stage .notice[role=alert]")
                    alert.wait_for()
                    assert ERROR in alert.inner_text()
                    if theme != "black":
                        page.locator(".reader__bar--top").get_by_role(
                            "button", name="Reader settings" if language == "en" else "إعدادات القارئ").click()
                        page.get_by_role("dialog").locator(f'input[name="background"][value="{theme}"]').check()
                        page.keyboard.press("Escape")
                    color = contrast(page)
                    retry = page.locator(".reader__stage > button.button")
                    assert retry.is_visible() and alert.is_visible(), (language, width, theme)
                    page.screenshot(path=str(out / f"i55-{language}-{width}-{theme}.png"))
                    assert color["ratio"] >= 4.5, (language, width, theme, color)
                    calls["allow_success"] = True
                    retry.click()
                    page.locator(".reader__stage img.reader__page").first.wait_for()
                    assert calls["pages"] >= 2, (language, width, theme, calls)
                    print("PASS I-55", language, width, theme, round(color["ratio"], 2), flush=True)
                finally:
                    page.close()


def test_settings(browser, url, out):
    for language in ("en", "ar"):
        for width in WIDTHS:
            for category in ("backup", "advanced"):
                page, _ = browser_page(browser, url, language, width)
                try:
                    page.goto(url + "/settings/" + category)
                    page.locator(f'#settings-tab-{category}[aria-selected="true"]').wait_for()
                    page.evaluate("document.fonts.ready")
                    page.wait_for_timeout(100)
                    nav = page.locator(".settings__nav")
                    state = nav.evaluate("""nav => {
                      const active = nav.querySelector('[aria-selected="true"]').getBoundingClientRect();
                      const frame = nav.getBoundingClientRect();
                      return {overflow: nav.scrollWidth > nav.clientWidth + 1,
                        visible: active.left >= frame.left - 1 && active.right <= frame.right + 1,
                        left: active.left, right: active.right, frameLeft: frame.left, frameRight: frame.right,
                        scrollLeft: nav.scrollLeft};
                    }""")
                    page.screenshot(path=str(out / f"i56-{language}-{width}-{category}.png"))
                    assert state["visible"], (language, width, category, state)
                    if state["overflow"]:
                        cues = page.locator(".settings__navStep:visible")
                        assert cues.count() == 2, (language, width, category, "missing overflow controls")
                        before = state["scrollLeft"]
                        cues.first.click()
                        page.wait_for_function("before => Math.abs(document.querySelector('.settings__nav').scrollLeft - before) > 1", arg=before)
                    print("PASS I-56", language, width, category, state, flush=True)
                finally:
                    page.close()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default="http://127.0.0.1:5173")
    parser.add_argument("--screenshots", default="/tmp/oneshelf-high-ux-regressions")
    parser.add_argument("--case", choices=("reader-controls", "reader-error", "settings", "all"), default="all")
    args = parser.parse_args()
    out = Path(args.screenshots)
    out.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        try:
            if args.case in ("reader-controls", "all"):
                test_reader_controls(browser, args.url, out)
            if args.case in ("reader-error", "all"):
                test_reader_error(browser, args.url, out)
            if args.case in ("settings", "all"):
                test_settings(browser, args.url, out)
        finally:
            browser.close()


if __name__ == "__main__":
    main()
