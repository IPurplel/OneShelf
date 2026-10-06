"""Chromium reproductions for the six 2026-10-06 UI fixes, with request traces."""
import argparse
import io
import json
import zipfile
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from playwright.sync_api import expect, sync_playwright
from layout_browser import fixture

WORK = dict(id="w0", title="Two Languages", original_title=None, creator=None, description=None,
            content_type="manga", content_type_source="source", aliases=[])
TRACKS = [dict(id="t-en", source_id="local", language="en", kind="local", availability="available", unit_count=1),
          dict(id="t-ar", source_id="alpha", language="ar", kind="source", availability="available", unit_count=1)]
UNIT = dict(id="u0", title="Chapter One", number="1", unit_type="chapter", volume=None, order=1,
            release_date=None, availability="available", url=None, downloaded=True, formats=["cbz"],
            read_state="unread", fraction=0, read_at=None, integrity="ok", is_new=False)


def work(track="t-en", completed=False):
    return dict(work=WORK, shelf=dict(on_shelf=True, favorite=False, pinned=False, completed=completed),
                follow=dict(following=False, preferred_source_id=None, track_id=None, language=None,
                            last_successful_at=None), tracks=TRACKS, selected_track_id=track,
                units=[UNIT], continue_unit_id="u0")


def epub(empty=False):
    data = io.BytesIO()
    with zipfile.ZipFile(data, "w") as archive:
        archive.writestr("META-INF/container.xml",
                         '<container><rootfiles><rootfile full-path="OEBPS/content.opf"/></rootfiles></container>')
        spine = "" if empty else '<itemref idref="c1"/>'
        archive.writestr("OEBPS/content.opf", '<package><metadata><title>Test Book</title></metadata>'
                         '<manifest><item id="c1" href="chapter.xhtml"/></manifest>'
                         f'<spine>{spine}</spine></package>')
        archive.writestr("OEBPS/chapter.xhtml", "<html><body><p>Text to read.</p></body></html>")
    return data.getvalue()


def setup(page, mode, base):
    state = dict(pending=[], calls=[], completed=False, errors=[], summary_attempts=0, marks=[])
    page.on("pageerror", lambda error: state["errors"].append(str(error)))

    def route(request):
        req = request.request
        parsed = urlparse(req.url)
        path = parsed.path
        query = parse_qs(parsed.query)
        if path == "/api/works/w0":
            track = query.get("track_id", ["t-en"])[0]
            if mode == "track" and track == "t-ar" and not state.get("arabic_released"):
                state["pending"].append(request)
                return
            return request.fulfill(json=work(track, state["completed"]))
        if path == "/api/follows/w0" and req.method == "POST":
            state["calls"].append(dict(method="POST", path=path, body=req.post_data_json))
            return request.fulfill(json={"work_id": "w0"})
        if path == "/api/sources":
            return request.fulfill(json={"sources": [dict(id="alpha", name="Reading Room Library", state="active",
                version="1.0.0", trust_label="official", channel="bundled",
                capabilities=["search", "work", "catalog", "reader"], auth_available=True, session_state="none")]})
        if path == "/api/sources/alpha/login" and mode == "login":
            state["pending"].append(request)
            return
        if path.startswith("/api/logins/") and req.method == "DELETE":
            state["calls"].append(dict(method="DELETE", path=path))
            return request.fulfill(json={})
        if path == "/api/shelf/w0" and req.method == "POST":
            state["calls"].append(dict(method="POST", path=path, body=req.post_data_json))
            state["completed"] = req.post_data_json.get("completed", False)
            return request.fulfill(json={})
        if path == "/api/shelf/w0/removal-summary" and mode == "completion":
            state["summary_attempts"] += 1
            status = 503 if state["summary_attempts"] == 1 else 200
            state["calls"].append(dict(method="GET", path=path, status=status))
            return request.fulfill(status=status, json={"error": {"message": "Summary unavailable"}}
                if status == 503 else dict(work_id="w0", files=2, bytes=1000, has_progress=False, is_followed=False))
        if path == "/api/reader/units/u0/context" and mode in ("epub", "bookmark"):
            return request.fulfill(json={"work_id": "w0", "track_id": "t-en", "formats": ["epub"]})
        if path == "/api/reader/units/u0/file" and mode in ("epub", "bookmark"):
            return request.fulfill(content_type="application/epub+zip", body=epub(mode == "epub"))
        if path == "/api/reader/units/u0/marks" and mode in ("epub", "bookmark"):
            return request.fulfill(json={"bookmarks": state["marks"], "highlights": []})
        if path == "/api/reader/units/u0/bookmarks" and mode == "bookmark" and req.method == "POST":
            attempt = len([call for call in state["calls"] if call.get("path") == path]) + 1
            state["calls"].append(dict(method="POST", path=path, body=req.post_data_json, attempt=attempt))
            if attempt == 1:
                return request.fulfill(status=503, json={"error": {"message": "Marks unavailable"}})
            made = dict(id="b1", locator=req.post_data_json["locator"], label=req.post_data_json["label"],
                        created_at="2026-10-06T00:00:00Z")
            state["marks"].append(made)
            return request.fulfill(json=made)
        return fixture(request, 3)

    page.route(base + "/api/**", route)
    return state


def new_page(browser, base, language, width, mode):
    page = browser.new_page(viewport={"width": width, "height": 844}, reduced_motion="reduce")
    page.add_init_script(f"try {{ localStorage.setItem('oneshelf.language', '{language}') }} catch {{}}")
    page.set_default_timeout(6000)
    return page, setup(page, mode, base)


def run(base, out):
    traces = {}
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        for language in ("en", "ar"):
            for width in (390, 768, 1440):
                tag = f"{language}-{width}"
                # 1. Work track switch: the previous actions disappear before the AR response.
                page, state = new_page(browser, base, language, width, "track")
                page.goto(base + "/works/w0?track=t-en")
                expect(page.locator(".work__actions")).to_be_visible()
                page.get_by_role("tab").last.click()
                page.locator(".tracks__row").last.locator("button").first.click()
                expect(page).to_have_url(base + "/works/w0?track=t-ar")
                expect(page.locator(".work__actions")).to_have_count(0)
                assert not state["calls"]
                if width == 390: page.screenshot(path=str(out / f"{tag}-track-pending.png"), full_page=True)
                state["arabic_released"] = True
                for pending in state["pending"]: pending.fulfill(json=work("t-ar"))
                follow = page.locator(".work__actions button[aria-pressed]").nth(1)
                expect(follow).to_be_visible()
                with page.expect_response(lambda response: urlparse(response.url).path == "/api/follows/w0"
                        and response.request.method == "POST"):
                    follow.click()
                assert state["calls"] and state["calls"][0]["body"] == {
                    "language": "ar", "source_id": "alpha", "track_id": "t-ar"}, state["calls"]
                traces[f"{tag}-track"] = state["calls"]
                assert not state["errors"], state["errors"]
                page.close()

                # 3. A late-created login is deleted, including after the dialog closes.
                page, state = new_page(browser, base, language, width, "login")
                page.goto(base + "/sources")
                page.locator(".cards__row button").first.click()
                page.get_by_role("button", name="Use my session" if language == "en" else "استخدم جلستي").click()
                page.get_by_role("button", name="Open the sign-in window" if language == "en" else "افتح نافذة تسجيل الدخول").click()
                expect(page.get_by_role("dialog")).to_be_visible()
                page.keyboard.press("Escape")
                expect(page.get_by_role("dialog")).to_have_count(0)
                assert len(state["pending"]) == 1
                with page.expect_response(lambda response: urlparse(response.url).path == f"/api/logins/late-{tag}"
                        and response.request.method == "DELETE"):
                    state["pending"].pop().fulfill(json={"login_id": f"late-{tag}", "status": "ready"})
                assert state["calls"] == [dict(method="DELETE", path=f"/api/logins/late-{tag}")], state["calls"]
                traces[f"{tag}-login"] = state["calls"]
                assert not state["errors"], state["errors"]
                page.close()

                # 4. Empty EPUB has a localized failure instead of a zero-chapter counter.
                page, state = new_page(browser, base, language, width, "epub")
                page.goto(base + "/read/u0?work=w0&track=t-en")
                expect(page.get_by_role("alert")).to_be_visible()
                expect(page.get_by_role("link", name="Back to the work" if language == "en"
                    else "العودة إلى العمل")).to_be_visible()
                assert "1 of 0" not in page.locator("body").inner_text()
                assert not state["errors"], state["errors"]
                if width == 390: page.screenshot(path=str(out / f"{tag}-empty-epub.png"), full_page=True)
                page.close()

                # 5. Completion remains true after the optional summary fails; retry is GET only.
                page, state = new_page(browser, base, language, width, "completion")
                page.goto(base + "/works/w0")
                page.locator(".work__actions button[aria-pressed]").first.click()
                expect(page.get_by_role("alert")).to_be_visible()
                completed = page.locator(".work__actions button[aria-pressed]").first
                expect(completed).to_have_attribute("aria-pressed", "true")
                assert state["completed"] and state["summary_attempts"] == 1
                if width == 390: page.screenshot(path=str(out / f"{tag}-completed-summary-warning.png"), full_page=True)
                page.get_by_role("button", name="Retry cleanup information" if language == "en"
                    else "أعد تحميل معلومات تنظيف الملفات").click()
                expect(page.get_by_role("dialog")).to_be_visible()
                assert len([call for call in state["calls"] if call["method"] == "POST"]) == 1
                traces[f"{tag}-completion"] = state["calls"]
                page.close()

                # 6. Bookmark failure is visible, retry succeeds, and no browser rejection escapes.
                page, state = new_page(browser, base, language, width, "bookmark")
                page.goto(base + "/read/u0?work=w0&track=t-en")
                page.get_by_role("status").filter(has_text="1").wait_for()
                page.locator(".reader__bar--top button").nth(2).click()
                expect(page.get_by_role("alert")).to_be_visible()
                assert "Marks unavailable" in page.get_by_role("alert").inner_text()
                assert not state["marks"]
                assert not state["errors"], state["errors"]
                if width == 390: page.screenshot(path=str(out / f"{tag}-bookmark-error.png"), full_page=True)
                page.get_by_role("button", name="Retry saving mark" if language == "en" else "أعد حفظ العلامة").click()
                expect(page.get_by_role("alert")).to_have_count(0)
                assert len(state["marks"]) == 1 and not state["errors"]
                traces[f"{tag}-bookmark"] = state["calls"]
                page.close()
                print("PASS targeted", tag, flush=True)
        browser.close()
    (out / "request-trace.json").write_text(json.dumps(traces, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default="http://127.0.0.1:5173")
    parser.add_argument("--screenshots", default="/tmp/oneshelf-targeted-fixes-20261006")
    arguments = parser.parse_args()
    output = Path(arguments.screenshots)
    output.mkdir(parents=True, exist_ok=True)
    run(arguments.url, output)
