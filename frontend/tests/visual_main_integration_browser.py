"""Human-visible audit regressions. Run against Vite with a real Chromium browser."""
import argparse
import io
import json
from pathlib import Path
from urllib.parse import urlparse

from playwright.sync_api import sync_playwright
from pypdf import PdfWriter
from layout_browser import fixture, items


LONG = "A very long title, with an unexpectedly detailed subtitle about a book that refuses to fit on one line — الجزء الأول and an English ending"
pdf_buffer = io.BytesIO()
pdf_writer = PdfWriter()
pdf_writer.add_blank_page(width=400, height=600)
pdf_writer.write(pdf_buffer)
PDF = pdf_buffer.getvalue()


def contrast(foreground, background):
    def linear(value):
        value = int(value) / 255
        return value / 12.92 if value <= 0.04045 else ((value + 0.055) / 1.055) ** 2.4
    def luminance(color):
        channels = color.removeprefix("rgb(").removeprefix("rgba(").split(")")[0].split(",")[:3]
        return sum(weight * linear(channel.strip()) for weight, channel in zip((0.2126, 0.7152, 0.0722), channels))
    a, b = sorted((luminance(foreground), luminance(background)), reverse=True)
    return (a + 0.05) / (b + 0.05)


def new_page(browser, base, language, width, mode):
    page = browser.new_page(viewport={"width": width, "height": 900}, reduced_motion="reduce")
    page.add_init_script(f"localStorage.setItem('oneshelf.language', '{language}')")
    state = {"viewport": {"width": 1280, "height": 800}, "inputs": [], "opens": []}

    def route(request):
        path = urlparse(request.request.url).path
        if path == "/api/reader/units/u0/pages" and mode == "reader_error":
            return request.fulfill(status=503, json={"error": {"message": "Chapter unavailable"}})
        if path == "/api/reader/units/u0/context" and mode == "pdf":
            return request.fulfill(json={"work_id": "w0", "track_id": "t0", "formats": ["pdf"]})
        if path == "/api/reader/units/u0/file" and mode == "pdf":
            return request.fulfill(content_type="application/pdf", body=PDF)
        if path == "/api/works/w0":
            return request.fulfill(json=dict(
                work=dict(id="w0", title="Reader smoke test", original_title=None, creator="A. Reader",
                          description="A story about reading, finding a source, and continuing on another device.",
                          content_type="manga", content_type_source="source", aliases=["English Alias 42"]),
                shelf=dict(on_shelf=True, favorite=True, pinned=True, completed=False),
                follow=dict(following=False, preferred_source_id=None, track_id=None, language=None,
                            last_successful_at=None),
                tracks=[dict(id="t0", source_id="local", language="en", kind="local", availability="available",
                             unit_count=1)], selected_track_id="t0", continue_unit_id="u0",
                units=[dict(id="u0", title="Chapter One", number="1", unit_type="chapter", volume=None, order=1,
                            release_date=None, availability="available", url=None, downloaded=True, formats=["cbz"],
                            read_state="unread", fraction=0, read_at=None, integrity="ok", is_new=False)]))
        if path == "/api/shelf" and mode == "shelf_long":
            entry = {**items(1)[0], "title": LONG}
            return request.fulfill(json={"view": "all", "entries": [entry]})
        if path == "/api/search" and mode == "zero_source":
            update = dict(stage="complete", results=[], source_status={}, sources_total=0, sources_done=0, sources_failed=0)
            return request.fulfill(content_type="text/event-stream", body=f'event: complete\ndata: {json.dumps(update)}\n\n')
        if path == "/api/downloads/settings":
            return request.fulfill(json={"auto_download": {"enabled": False, "mode": "current",
                "read_ahead": 1, "threshold": 0}, "keep_partial_on_cancel": False,
                "extraction": {"method": None, "mode": "preferred_ask", "fallback_order": []}})
        if path == "/api/storage" and mode == "bidi":
            return request.fulfill(json={"roots": [dict(id="r0", name="Library", path="/library/English-books/file.epub",
                is_default=True, available=True, reason=None, total=500e9, free=120e9, reserve=5e9, state="ok")], "missing": 0})
        if path == "/api/sources" and mode == "bidi":
            return request.fulfill(json={"sources": [dict(id="alpha", name="English Source 42", state="active",
                version="1.2.0", trust_label="official", channel="bundled",
                capabilities=["search", "work"], auth_available=False, session_state="not_connected")]})
        if path == "/api/sources" and mode == "login":
            return request.fulfill(json={"sources": [dict(id="alpha", name="Example source", state="active",
                version="1.2.0", trust_label="official", channel="bundled",
                capabilities=["search", "work", "catalog", "reader"], auth_available=True, session_state="expired")]})
        if path == "/api/sources/alpha/login" and mode == "login":
            body = request.request.post_data_json or {}
            state["opens"].append(body)
            state["viewport"] = body.get("viewport", state["viewport"])
            return request.fulfill(json={"login_id": "l1", "status": "open", "viewport": state["viewport"]})
        if path == "/api/logins/l1/frame" and mode == "login":
            width_, height_ = state["viewport"]["width"], state["viewport"]["height"]
            svg = f'<svg xmlns="http://www.w3.org/2000/svg" width="{width_}" height="{height_}">' \
                  f'<rect width="100%" height="100%" fill="white"/><text x="18" y="40" font-size="16">Email address</text>' \
                  f'<rect x="18" y="50" width="220" height="42" fill="white" stroke="#777"/>' \
                  f'<text x="18" y="126" font-size="16">Password</text>' \
                  f'<rect x="18" y="136" width="220" height="42" fill="white" stroke="#777"/>' \
                  f'<rect x="18" y="208" width="130" height="42" fill="#245a8e"/>' \
                  f'<text x="50" y="235" fill="white" font-size="16">Sign in</text></svg>'
            return request.fulfill(content_type="image/svg+xml", body=svg)
        if path == "/api/logins/l1/input" and mode == "login":
            state["inputs"].append(request.request.post_data_json)
            return request.fulfill(json={"login_id": "l1", "status": "open"})
        if path == "/api/logins/l1" and mode == "login":
            return request.fulfill(json={})
        return fixture(request, 1)

    page.route(base + "/api/**", route)
    return page, state


def check_reader_notice(page, base, language, width):
    page.goto(base + "/read/u0?work=w0&track=t0")
    notice = page.locator(".reader .notice--problem").first
    notice.wait_for()
    colors = notice.evaluate("e => ({fg:getComputedStyle(e).color,bg:getComputedStyle(e).backgroundColor})")
    assert contrast(colors["fg"], colors["bg"]) >= 4.5, (language, width, colors)


def check_contents(page, base, language, width):
    page.goto(base + "/read/u0?work=w0&track=t0")
    page.locator(".reader__bar--top .reader__button").filter(
        has_text="Contents" if language == "en" else "المحتويات").click()
    boxes = page.locator(".drawer__filters .chip").evaluate_all("""buttons => buttons.map(button => {
        const r = button.getBoundingClientRect(); const drawer = button.closest('.drawer').getBoundingClientRect();
        return {label:button.textContent,left:r.left,right:r.right,drawerLeft:drawer.left,drawerRight:drawer.right};
    })""")
    assert len(boxes) >= 4
    assert all(box["left"] >= box["drawerLeft"] - 1 and box["right"] <= min(width, box["drawerRight"]) + 1
               for box in boxes), (language, width, boxes)


def style(button):
    return button.evaluate("""e => ({background:getComputedStyle(e).backgroundColor,
        shadow:getComputedStyle(e).boxShadow, border:getComputedStyle(e).borderColor,
        color:getComputedStyle(e).color})""")


def check_pressed(page, base, language, width):
    page.goto(base + "/settings/general")
    pressed = page.locator('.toolbar__tabs .chip[aria-pressed="true"]')
    unpressed = page.locator('.toolbar__tabs .chip[aria-pressed="false"]')
    assert style(pressed) != style(unpressed), (language, width, "language selection")
    page.goto(base + "/works/w0")
    favorite = page.locator('.work__actions button[aria-pressed="true"]').filter(has_text="Favorite" if language == "en" else "مفضّلة")
    follow = page.locator('.work__actions button[aria-pressed]').nth(1)
    assert style(favorite) != style(follow), (language, width, "favorite selection")
    pin = page.locator('.work__actions button[aria-pressed="true"]').filter(has_text="Pin" if language == "en" else "تثبيت")
    assert style(pin) != style(follow), (language, width, "pin selection")
    before = follow.bounding_box()
    unselected = style(follow)
    follow.evaluate("e => e.setAttribute('aria-pressed', 'true')")
    assert style(follow) != unselected, (language, width, "follow selection")
    assert follow.bounding_box() == before, (language, width, "pressed layout shift")
    page.goto(base + "/shelf")
    assert style(page.locator('.iconbutton[aria-pressed="true"]')) != style(
        page.locator('.iconbutton[aria-pressed="false"]')), (language, width, "shelf layout selection")
    page.goto(base + "/read/u0?work=w0&track=t0")
    page.locator(".reader__bar--top .reader__button").filter(
        has_text="Contents" if language == "en" else "المحتويات").click()
    assert style(page.locator('.drawer__filters .chip[aria-pressed="true"]')) != style(
        page.locator('.drawer__filters .chip[aria-pressed="false"]').first), (
            language, width, "contents filter selection")


def check_pdf_pressed(page, base, language, width):
    page.goto(base + "/read/u0?work=w0&track=t0")
    selected = page.locator('.reader__button[aria-pressed="true"]')
    selected.wait_for()
    unselected = page.locator('.reader__button[aria-pressed="false"]')
    assert style(selected) != style(unselected), (language, width, "PDF fit selection")


def check_settings(page, base, language, width):
    for category in ("general", "reader", "downloads", "storage", "sources", "notifications", "backup",
                     "remote", "advanced", "developer"):
        page.goto(base + "/settings/" + category)
        result = page.locator('.settings__tab[aria-selected="true"]').evaluate("""tab => {
            const t = tab.getBoundingClientRect(), n = tab.parentElement.getBoundingClientRect();
            return {left:t.left,right:t.right,navLeft:n.left,navRight:n.right};
        }""")
        assert result["left"] >= result["navLeft"] - 1 and result["right"] <= result["navRight"] + 1, (
            language, width, category, result)


def check_bidi(page, base, language, width):
    page.goto(base + "/works/w0")
    for selector in (".work__title", ".work__meta [dir]", ".units__title"):
        node = page.locator(selector).first
        node.wait_for()
        assert node.get_attribute("dir") == "auto", (language, width, selector)
    assert page.locator(".work__description").evaluate("e => getComputedStyle(e).direction") == "ltr"
    page.locator("#work-tab-details").click()
    assert page.locator(".details bdi").first.inner_text() == "English Alias 42"
    page.locator("#work-tab-sources").click()
    assert page.locator(".tracks__name bdi").first.inner_text() == "local"
    page.goto(base + "/sources")
    source = page.locator(".cards__name").first
    source.wait_for()
    assert source.evaluate("e => getComputedStyle(e).direction") == "ltr", (language, width, "source name")
    page.goto(base + "/settings/storage")
    page.locator(".cards__row .cards__meta").first.wait_for()
    assert page.locator(".cards__row .cards__meta").first.evaluate("e => getComputedStyle(e).direction") == "ltr"


def check_shelf(page, base, language, width):
    page.goto(base + "/shelf")
    title = page.locator(".shelfview .workcard__title").first
    title.wait_for()
    metrics = title.evaluate("""e => ({lines:e.getBoundingClientRect().height / parseFloat(getComputedStyle(e).lineHeight),
        titleWidth:e.getBoundingClientRect().width,
        plank:e.closest('.shelf__case').querySelector('.shelf__plank').getBoundingClientRect().width})""")
    assert metrics["lines"] <= 3.5 and metrics["titleWidth"] >= 165 and metrics["plank"] <= 320, (language, width, metrics)


def check_login(page, base, language, width, state):
    page.goto(base + "/sources")
    page.locator(".cards__row button").first.click()
    page.get_by_role("button", name="Use my session" if language == "en" else "استخدم جلستي").click()
    page.locator(".confirm__actions .button--primary").click()
    frame = page.locator(".login__frame")
    frame.wait_for()
    image = frame.evaluate("""e => ({width:e.getBoundingClientRect().width,naturalWidth:e.naturalWidth,
        height:e.getBoundingClientRect().height,naturalHeight:e.naturalHeight})""")
    assert state["opens"] and "viewport" in state["opens"][0], (language, width, state["opens"])
    assert image["naturalWidth"] > 0 and image["width"] / image["naturalWidth"] >= 0.9, (language, width, image)
    assert page.evaluate("document.documentElement.scrollWidth - innerWidth") <= 1
    frame.click(position={"x": 100, "y": 74})
    page.wait_for_timeout(100)
    clicks = [entry for entry in state["inputs"] if entry.get("type") == "click"]
    assert clicks and abs(clicks[-1]["x"] - 100) <= 3 and abs(clicks[-1]["y"] - 74) <= 3, clicks
    frame.focus()
    page.keyboard.type("a")
    page.wait_for_timeout(100)
    assert any(entry == {"type": "type", "text": "a"} for entry in state["inputs"]), state["inputs"]
    frame.hover()
    page.mouse.wheel(0, 120)
    page.wait_for_timeout(100)
    assert any(entry.get("type") == "scroll" and entry.get("dy") == 120 for entry in state["inputs"]), state["inputs"]


def check_zero_source(page, base, language, width):
    page.goto(base + "/search?q=missing")
    status = page.locator(".search__status")
    status.wait_for()
    assert "0 of 0" not in status.inner_text()
    assert page.locator(".search__results .workcard").count() == 0
    assert page.locator(".shelf__empty").count() == 0
    link = status.locator('a[href="/sources"]')
    assert link.count() == 1
    link.click()
    assert urlparse(page.url).path == "/sources"
    page.go_back()
    status.wait_for()


def check_advanced(page, base, language, width):
    sections = (("reader", "Reader", "القارئ"), ("downloads", "Downloads", "التنزيلات"),
                ("sources", "Sources", "المصادر"))
    for route, english, arabic in sections:
        page.goto(base + "/settings/" + route)
        button = page.locator(".panel__advanced button").first
        button.wait_for()
        collapsed = button.inner_text()
        if language == "en":
            assert collapsed == f"Show advanced {english} settings", (language, width, route, collapsed)
        else:
            assert arabic in collapsed and "متقدّمة" in collapsed, (language, width, route, collapsed)
        button.click()
        assert button.get_attribute("aria-expanded") == "true"
        if language == "en":
            assert button.inner_text() == f"Hide advanced {english} settings"
        else:
            assert arabic in button.inner_text() and "أخفِ" in button.inner_text()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default="http://127.0.0.1:5189")
    parser.add_argument("--screenshots", default="/tmp/oneshelf-visual-logical-browser")
    parser.add_argument("--chromium", default=None)
    args = parser.parse_args()
    out = Path(args.screenshots)
    out.mkdir(parents=True, exist_ok=True)
    failures = []
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(executable_path=args.chromium, headless=True)
        checks = [("reader-error", "reader_error", check_reader_notice),
                  ("contents", "normal", check_contents),
                  ("pressed", "normal", check_pressed),
                  ("pdf-fit", "pdf", check_pdf_pressed),
                  ("settings", "normal", check_settings),
                  ("bidi", "bidi", check_bidi),
                  ("shelf", "shelf_long", check_shelf),
                  ("zero-source", "zero_source", check_zero_source),
                  ("advanced", "normal", check_advanced)]
        for language in ("en", "ar"):
            for width in (390, 768, 1440):
                for name, mode, check in checks + [("login", "login", check_login)]:
                    page, state = new_page(browser, args.url, language, width, mode)
                    try:
                        if name == "login":
                            check(page, args.url, language, width, state)
                        else:
                            check(page, args.url, language, width)
                        print("PASS", name, language, width, flush=True)
                    except Exception as exc:
                        failures.append(f"{name} {language} {width}: {exc}")
                        print("FAIL", failures[-1], flush=True)
                    finally:
                        page.screenshot(path=str(out / f"{language}-{width}-{name}.png"), full_page=False)
                        page.close()
        browser.close()
    (out / "results.json").write_text(json.dumps({"failures": failures}, indent=2))
    assert not failures, f"{len(failures)} visual/logical regressions: " + "; ".join(failures)


if __name__ == "__main__":
    main()
