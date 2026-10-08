"""Controlled Chromium regressions for the nine post-PR1 UI audit findings.

Run against this worktree's Vite server. Responses are fixtures, not live-source evidence.
"""
import argparse
import json
from pathlib import Path
from urllib.parse import urlparse

from playwright.sync_api import expect, sync_playwright
from layout_browser import COVER, fixture


def save(output, name, value):
    (output / name).write_text(json.dumps(value, ensure_ascii=False, indent=2))


def new_page(browser, base, language="en", width=390):
    page = browser.new_page(viewport={"width": width, "height": 844}, reduced_motion="reduce")
    page.add_init_script(f"localStorage.setItem('oneshelf.language', '{language}')")
    page.set_default_timeout(6000)
    return page


def route_fixture(page, base):
    page.route(base + "/api/**", lambda route: fixture(route, 3))


def reader_checks(browser, base, output):
    geometry, repair_trace, empty_trace, tabs_trace = [], [], [], []
    for language in ("en", "ar"):
        for width in (390, 768, 1440):
            page = new_page(browser, base, language, width)
            route_fixture(page, base)
            page.goto(base + "/read/u0?work=w0&track=t0")
            page.wait_for_load_state("networkidle")
            row = page.evaluate("""() => {
              const controls = [...document.querySelectorAll('.reader__bar--top a,.reader__bar--top button')]
                .map(el => { const r=el.getBoundingClientRect(), x=r.left+r.width/2, y=r.top+r.height/2;
                  return {text:el.textContent.trim(), left:r.left, right:r.right, top:r.top, bottom:r.bottom,
                    inside:r.left>=0 && r.right<=innerWidth && r.top>=0 && r.bottom<=innerHeight,
                    hit:el===document.elementFromPoint(x,y)||el.contains(document.elementFromPoint(x,y))}; });
              const bottom=document.querySelector('.reader__bar--bottom').getBoundingClientRect();
              return {width:innerWidth, scrollWidth:document.documentElement.scrollWidth, controls,
                bottomInside:bottom.bottom<=innerHeight,
                appNavHidden:!document.querySelector('.bottomnav') || getComputedStyle(document.querySelector('.bottomnav')).display==='none'};
            }""")
            row["language"] = language
            geometry.append(row)
            assert row["scrollWidth"] <= width and row["bottomInside"] and row["appNavHidden"], row
            assert all(c["inside"] and c["hit"] for c in row["controls"]), row
            assert len(row["controls"]) >= 5, row
            if width == 390:
                page.screenshot(path=str(output / f"sequential-toolbar-{language}-390.png"), full_page=True)
                page.locator(".reader__bar--top button").filter(has_text="settings" if language == "en" else "إعدادات").click()
                expect(page.get_by_role("dialog")).to_be_visible()
                page.keyboard.press("Escape")
                page.locator(".reader__bar--top button").filter(has_text="More" if language == "en" else "المزيد").click()
                expect(page.locator("#reader-more")).to_be_visible()
            page.close()
        # Error recovery and empty state use the mobile viewport in each locale.
        page = new_page(browser, base, language)
        errors, calls = [], []
        page.on("pageerror", lambda error: errors.append(str(error)))
        ready = [False]
        def repair_route(route):
            path = urlparse(route.request.url).path
            if path == "/api/reader/units/u0/pages/1":
                return route.fulfill(content_type="image/svg+xml", body=COVER) if ready[0] else route.fulfill(status=503, body="offline")
            if path == "/api/downloads" and route.request.method == "POST":
                calls.append({"body": route.request.post_data_json, "status": 503 if not calls else 200})
                return route.fulfill(status=503, json={"error": {"message": "Repair unavailable"}}) if len(calls) == 1 else route.fulfill(json={"batch_id": "b1"})
            return fixture(route, 3)
        page.route(base + "/api/**", repair_route)
        page.goto(base + "/read/u0?work=w0&track=t0")
        failed = page.locator(".reader__failed")
        failed.wait_for()
        failed.locator("button").nth(1).click()
        alert = page.get_by_role("alert")
        expect(alert).to_be_visible()
        assert ("Repair" in alert.inner_text() if language == "en" else "الإصلاح" in alert.inner_text())
        page.screenshot(path=str(output / f"repair-error-{language}-390.png"), full_page=True)
        failed.locator("button").nth(1).click()
        expect(alert).to_have_count(0)
        ready[0] = True
        failed.locator("button").first.click()
        page.locator('.reader__frame[data-loaded="true"]').wait_for()
        assert not errors, errors
        repair_trace.append({"language": language, "repair_posts": calls, "pageerrors": errors,
                             "page_retry_recovered": page.locator(".reader__failed").count() == 0})
        page.close()

        page = new_page(browser, base, language)
        page_requests = []
        def empty_route(route):
            path = urlparse(route.request.url).path
            if path.startswith("/api/reader/units/u0/pages/"):
                page_requests.append(path)
            if path == "/api/reader/units/u0/pages":
                return route.fulfill(json={"reading_unit_id": "u0", "pages": []})
            return fixture(route, 3)
        page.route(base + "/api/**", empty_route)
        page.goto(base + "/read/u0?work=w0&track=t0")
        expect(page.get_by_role("alert")).to_be_visible()
        link = page.get_by_role("link", name="Back to the work" if language == "en" else "العودة إلى العمل")
        expect(link).to_have_attribute("href", "/works/w0?track=t0")
        assert not page_requests, page_requests
        assert "1 / 0" not in page.locator(".reader").inner_text()
        page.screenshot(path=str(output / f"empty-pages-{language}-390.png"), full_page=True)
        empty_trace.append({"language": language, "alert": page.get_by_role("alert").inner_text(),
                            "back": link.get_attribute("href"), "page_requests": page_requests})
        page.close()

        for width in (390, 768, 1440):
            page = new_page(browser, base, language, width)
            route_fixture(page, base)
            for path, keys in (("/works/w0", ("ArrowRight", "ArrowLeft")),
                               ("/shelf", ("ArrowRight", "ArrowLeft")),
                               ("/settings", ("ArrowDown", "ArrowUp"))):
                page.goto(base + path)
                page.wait_for_load_state("networkidle")
                tabs = page.get_by_role("tablist").get_by_role("tab")
                expect(tabs.first).to_be_enabled()
                if path == "/settings" and width < 900:
                    keys = ("ArrowRight", "ArrowLeft")  # responsive category strip is horizontal
                for key, expected_index in ((keys[0], 1), (keys[1], tabs.count() - 1),
                                            ("End", tabs.count() - 1), ("Home", 0)):
                    tabs.first.focus()
                    page.keyboard.press(key)
                    assert tabs.nth(expected_index).evaluate("el => document.activeElement === el"), (
                        language, width, path, key, expected_index,
                        page.evaluate("document.activeElement?.tagName"))
                    expect(tabs.nth(expected_index)).to_have_attribute("aria-selected", "true")
                    expect(tabs.nth(expected_index)).to_have_attribute("tabindex", "0")
                    tabs_trace.append({"language": language, "width": width, "path": path,
                                       "key": key, "selected": tabs.nth(expected_index).get_attribute("id")})
            page.close()
    save(output, "reader-toolbar-geometry.json", geometry)
    save(output, "reader-repair-trace.json", repair_trace)
    save(output, "reader-empty-trace.json", empty_trace)
    save(output, "tabs-keyboard-matrix.json", tabs_trace)
    return len(geometry) + len(repair_trace) + len(empty_trace) + len(tabs_trace)


def race_checks(browser, base, output):
    # A late preflight must not describe archive B.
    backups = [dict(id=x, path=f"/backups/{x}.zip", kind="library", created_at="2026-10-07T00:00:00Z",
                    verified_at=None, size_bytes=1000, present=True) for x in ("A", "B")]
    def preflight(works):
        return dict(ok=True, compatible=True, kind="library", schema_version=16, counts={"works": works},
                    plugins=[], space_needed=100, issues=[])
    page = new_page(browser, base)
    pending, trace = [], []
    def backup_route(route):
        path = urlparse(route.request.url).path
        if path == "/api/backups":
            return route.fulfill(json={"backups": backups, "due": False, "location_warning": None})
        if path == "/api/restore/preflight":
            archive = route.request.post_data_json["path"]
            trace.append({"preflight": archive})
            if archive.endswith("A.zip"):
                pending.append(route)
                return
            return route.fulfill(json=preflight(222))
        if path == "/api/restore" and route.request.method == "POST":
            trace.append({"restore": route.request.post_data_json})
            return route.fulfill(json={})
        return fixture(route, 3)
    page.route(base + "/api/**", backup_route)
    page.goto(base + "/settings/backup")
    page.locator(".cards__row").first.get_by_role("button").click()
    page.get_by_role("dialog").get_by_role("button", name="Cancel").click()
    page.locator(".cards__row").nth(1).get_by_role("button").click()
    dialog = page.get_by_role("dialog")
    expect(dialog.get_by_text("222 works")).to_be_visible()
    pending[0].fulfill(json=preflight(111))
    page.wait_for_timeout(100)
    expect(dialog.get_by_text("222 works")).to_be_visible()
    assert dialog.get_by_text("111 works").count() == 0
    trace.append({"visible_after_late": dialog.inner_text()})
    page.screenshot(path=str(output / "backup-preflight-en-390.png"), full_page=True)
    dialog.get_by_role("button", name="Restore", exact=True).click()
    assert trace[-1]["restore"] == {"path": "/backups/B.zip", "mode": "merge"}, trace
    save(output, "backup-preflight-trace.json", trace)
    page.close()

    # A held destructive request must lock both pointer and keyboard activation.
    page = new_page(browser, base)
    pending, trace = [], []
    def restore_route(route):
        path = urlparse(route.request.url).path
        if path == "/api/backups":
            return route.fulfill(json={"backups": [backups[1]], "due": False, "location_warning": None})
        if path == "/api/restore/preflight":
            return route.fulfill(json=preflight(2))
        if path == "/api/restore" and route.request.method == "POST":
            trace.append({"body": route.request.post_data_json, "status": "pending"})
            pending.append(route)
            return
        return fixture(route, 3)
    page.route(base + "/api/**", restore_route)
    page.goto(base + "/settings/backup")
    page.locator(".cards__row").first.get_by_role("button").click()
    dialog = page.get_by_role("dialog")
    expect(dialog.get_by_text("2 works")).to_be_visible()
    dialog.get_by_role("radio", name="Replace my library").check()
    button = dialog.get_by_role("button", name="Restore", exact=True)
    button.evaluate("el => { el.click(); el.click(); }")
    expect(button).to_be_disabled()
    assert len(pending) == 1, trace
    page.screenshot(path=str(output / "restore-pending-en-390.png"), full_page=True)
    trace[0]["status"] = 503
    pending[0].fulfill(status=503, json={"error": {"message": "Retry restore"}})
    expect(button).to_be_enabled()
    button.click()
    assert len(pending) == 2, trace
    trace[1]["status"] = 200
    pending[1].fulfill(json={})
    expect(dialog).to_have_count(0)
    save(output, "restore-submit-trace.json", {"posts": trace, "first_failure_retry": True})
    page.close()

    # The visible review and the export body must both stay on B.
    page = new_page(browser, base)
    pending, trace = [], []
    def export_route(route):
        path = urlparse(route.request.url).path
        if path == "/api/export/preview":
            body = route.request.post_data_json
            trace.append({"preview": body})
            if body["destination"] == "/export/A":
                pending.append(route)
                return
            return route.fulfill(json={"files": 2, "total_bytes": 2000, "missing_units": [], "choices": [], "disclosure": None})
        if path == "/api/export":
            trace.append({"export": route.request.post_data_json})
            return route.fulfill(json={"job_id": "j1", "state": "completed", "copied": 2,
                                       "skipped": 0, "failed": 0, "errors": []})
        return fixture(route, 3)
    page.route(base + "/api/**", export_route)
    page.goto(base + "/works/w0")
    page.get_by_role("button", name="Export…", exact=True).click()
    dialog = page.get_by_role("dialog")
    for _ in range(2):
        dialog.get_by_role("button", name="Next").click()
    field = dialog.get_by_role("textbox")
    field.fill("/export/A")
    dialog.get_by_role("button", name="Next").click()
    field.fill("/export/B")
    dialog.get_by_role("button", name="Next").click()
    expect(dialog.get_by_text("2 files, 2.0 KB.")).to_be_visible()
    pending[0].fulfill(json={"files": 1, "total_bytes": 1000, "missing_units": ["u0"],
                             "choices": [], "disclosure": {"message": "Old A preview", "units": ["u0"], "choices": []}})
    page.wait_for_timeout(100)
    expect(dialog.get_by_text("2 files, 2.0 KB.")).to_be_visible()
    assert dialog.get_by_text("Old A preview").count() == 0
    trace.append({"review_after_late": dialog.inner_text()})
    page.screenshot(path=str(output / "export-preview-en-390.png"), full_page=True)
    dialog.get_by_role("button", name="Export", exact=True).click()
    assert trace[-1]["export"]["destination"] == "/export/B"
    save(output, "export-preview-trace.json", trace)
    page.close()

    # Storage Add also remains locked until the first request settles.
    page = new_page(browser, base)
    pending, posts = [], []
    added = [False]
    def storage_route(route):
        path = urlparse(route.request.url).path
        if path == "/api/storage":
            roots = [dict(id="r1", name="Second Disk", path="/library2", is_default=False,
                          available=True, reason=None, total=100000, free=50000, reserve=1000, state="ok")] if added[0] else []
            return route.fulfill(json={"roots": roots, "missing": 0})
        if path == "/api/storage/roots" and route.request.method == "POST":
            posts.append(route.request.post_data_json)
            pending.append(route)
            return
        return fixture(route, 3)
    page.route(base + "/api/**", storage_route)
    page.goto(base + "/settings/storage")
    page.get_by_role("button", name="Add a location").click()
    dialog = page.get_by_role("dialog")
    dialog.get_by_role("textbox", name="Folder on this machine").fill("/library2")
    dialog.get_by_role("textbox", name="Name").fill("Second Disk")
    button = dialog.get_by_role("button", name="Add", exact=True)
    button.evaluate("el => { el.click(); el.click(); }")
    expect(button).to_be_disabled()
    assert len(posts) == 1, posts
    added[0] = True
    pending[0].fulfill(json={"id": "r1"})
    expect(dialog).to_have_count(0)
    expect(page.get_by_text("Second Disk")).to_be_visible()
    assert page.get_by_role("alert").count() == 0
    page.screenshot(path=str(output / "storage-add-en-390.png"), full_page=True)
    save(output, "storage-add-trace.json", {"posts": posts, "root_visible": True, "alert_count": 0})
    page.close()
    return 4


def plural_checks(browser, base, output):
    rows = []
    for count, expected in ((0, "0 files"), (1, "1 file"), (2, "2 files")):
        page = new_page(browser, base)
        def route(request):
            if urlparse(request.request.url).path == "/api/export/preview":
                return request.fulfill(json={"files": count, "total_bytes": count*1000,
                                             "missing_units": [], "choices": [], "disclosure": None})
            return fixture(request, 3)
        page.route(base + "/api/**", route)
        page.goto(base + "/works/w0")
        page.get_by_role("button", name="Export…", exact=True).click()
        dialog = page.get_by_role("dialog")
        for _ in range(2):
            dialog.get_by_role("button", name="Next").click()
        dialog.get_by_role("textbox").fill(f"/export/{count}")
        dialog.get_by_role("button", name="Next").click()
        expect(dialog.get_by_text(expected + ",", exact=False)).to_be_visible()
        assert "file(s)" not in dialog.inner_text()
        rows.append({"files": count, "review": dialog.inner_text()})
        if count == 1:
            page.screenshot(path=str(output / "export-one-file-en-390.png"), full_page=True)
        page.close()
    save(output, "export-plural-trace.json", rows)
    return len(rows)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--base", default="http://127.0.0.1:5173")
    parser.add_argument("--output", type=Path, default=Path(__file__).parents[2] / "docs/plan/evidence/2026-10-07-post-pr1-ui")
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        cases = reader_checks(browser, args.base, args.output)
        cases += race_checks(browser, args.base, args.output)
        cases += plural_checks(browser, args.base, args.output)
        browser.close()
    print(f"post-PR1 Chromium: {cases} checks passed; evidence: {args.output}")


if __name__ == "__main__":
    main()
