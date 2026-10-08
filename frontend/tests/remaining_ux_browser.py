"""Production Chromium checks for the original I-58 and I-60..I-67 failure modes."""
import argparse
import io
import zipfile
from pathlib import Path
from urllib.parse import urlparse

from playwright.sync_api import expect, sync_playwright
from layout_browser import fixture

WIDTHS = (390, 768, 1440)
LANGUAGES = ("en", "ar")


def epub_file(language, prose):
    data = io.BytesIO()
    with zipfile.ZipFile(data, "w") as archive:
        archive.writestr("META-INF/container.xml",
                         '<container><rootfiles><rootfile full-path="OEBPS/content.opf"/></rootfiles></container>')
        archive.writestr("OEBPS/content.opf", f'<package><metadata><title>Direction test</title><language>{language}</language></metadata>'
                         '<manifest><item id="c1" href="chapter.xhtml"/></manifest><spine><itemref idref="c1"/></spine></package>')
        archive.writestr("OEBPS/chapter.xhtml", f"<html><body><p>{prose}</p></body></html>")
    return data.getvalue()


def new_page(browser, base, language, width, routes):
    page = browser.new_page(viewport={"width": width, "height": 844}, reduced_motion="reduce")
    page.add_init_script(f"try {{ localStorage.setItem('oneshelf.language', '{language}') }} catch {{}}")
    page.set_default_timeout(7000)
    errors = []
    page.on("pageerror", lambda error: errors.append(str(error)))

    def handle(route):
        request = route.request
        key = (request.method, urlparse(request.url).path)
        target = routes.get(key, routes.get(key[1]))
        if callable(target):
            return target(route)
        if isinstance(target, (dict, list)):
            return route.fulfill(json=target)
        return fixture(route, 3)

    page.route(base + "/api/**", handle)
    return page, errors


def shot(page, out, language, width, name):
    page.screenshot(path=str(out / f"{language}-{width}-{name}.png"))


def clear(page, errors, label):
    assert not errors, f"{label}: browser errors: {errors}"
    overflow = page.evaluate("document.documentElement.scrollWidth - innerWidth")
    assert overflow <= 1, f"{label}: horizontal overflow {overflow}px"
    page.close()


def check_epub(browser, base, out, language, width):
    for content_language, prose, expected in (("en", "The quiet English chapter begins.", "ltr"),
                                               ("ar", "تبدأ هنا فقرة عربية للقراءة.", "rtl")):
        data = epub_file(content_language, prose)
        routes = {
            "/api/reader/units/u0/context": {"work_id": "w0", "track_id": "t0", "formats": ["epub"]},
            "/api/reader/units/u0/file": lambda route: route.fulfill(content_type="application/epub+zip", body=data),
        }
        page, errors = new_page(browser, base, language, width, routes)
        page.goto(base + "/read/u0?work=w0&track=t0")
        frame = page.frame_locator("iframe.book__frame")
        expect(frame.locator("p")).to_contain_text(prose)
        assert frame.locator("html").get_attribute("dir") == expected, (language, content_language)
        assert frame.locator("p").evaluate("e => getComputedStyle(e).direction") == expected
        shot(page, out, language, width, f"I-58-{content_language}-epub")
        clear(page, errors, "I-58")


def check_export(browser, base, out, language, width):
    calls = []
    def preview(route):
        calls.append(("preview", route.request.post_data_json))
        route.fulfill(json={"files": 1, "total_bytes": 123456, "missing_units": [], "choices": [], "disclosure": None})
    def run(route):
        calls.append(("run", route.request.post_data_json))
        route.fulfill(json={"job_id": "j1", "state": "completed", "copied": 1, "skipped": 0, "failed": 0, "errors": []})
    page, errors = new_page(browser, base, language, width,
                            {("POST", "/api/export/preview"): preview, ("POST", "/api/export"): run})
    page.goto(base + "/works/w0")
    page.locator(".work__actions button").last.click()
    dialog = page.get_by_role("dialog")
    expect(dialog).to_be_visible()
    dialog.locator(".confirm__actions .button--primary").click()
    dialog.locator('input[name="output"][value="zip"]').check()
    dialog.locator(".confirm__actions .button--primary").click()
    dialog.locator('input[type="text"]').fill("/mnt/archive/very-long-export-destination")
    dialog.locator('input[name="conflict"][value="keep_both"]').check()
    dialog.locator(".confirm__actions .button--primary").click()
    expect(dialog.locator(".export__review")).to_contain_text("ZIP")
    expect(dialog.locator(".export__review")).to_contain_text("/mnt/archive/very-long-export-destination")
    assert "1" in dialog.locator(".export__review + p").inner_text()
    shot(page, out, language, width, "I-60-export-review")
    dialog.locator(".confirm__actions button").nth(1).click()
    expect(dialog.locator('input[type="text"]')).to_have_value("/mnt/archive/very-long-export-destination")
    dialog.locator(".confirm__actions button").nth(1).click()
    expect(dialog.locator('input[name="output"][value="zip"]')).to_be_checked()
    dialog.locator(".confirm__actions .button--primary").click()
    dialog.locator(".confirm__actions .button--primary").click()
    dialog.locator(".confirm__actions .button--primary").click()
    assert calls[-1][0] == "run" and calls[-2][0] == "preview"
    assert all(calls[-1][1][key] == calls[-2][1][key] for key in
               ("work_id", "language", "source_id", "unit_ids", "destination", "output", "conflict"))
    clear(page, errors, "I-60")


def source(name, eligible):
    return {"id": name, "name": name, "state": "active", "version": "2.0.0", "trust_label": "official",
            "channel": "bundled", "capabilities": ["search"], "auth_available": False,
            "session_state": "none", "can_rollback": eligible}


def check_rollback(browser, base, out, language, width):
    state = {"rolled": False, "calls": 0}
    def sources(route):
        items = [source("Single Version", False), source("Two Versions", True)]
        if state["rolled"]: items[1]["version"] = "1.0.0"
        route.fulfill(json={"sources": items})
    def rollback(route):
        state["calls"] += 1
        state["rolled"] = True
        route.fulfill(json={"id": "Two Versions", "state": "active"})
    page, errors = new_page(browser, base, language, width,
                            {"/api/sources": sources, ("POST", "/api/sources/Two%20Versions/rollback"): rollback})
    page.goto(base + "/sources")
    rows = page.locator(".cards__row")
    expect(rows).to_have_count(2)
    rows.nth(0).locator("button").click()
    assert page.get_by_role("dialog").get_by_role("button", name="Roll back to the previous version" if language == "en"
                else "العودة إلى الإصدار السابق").count() == 0
    shot(page, out, language, width, "I-61-no-rollback")
    page.get_by_role("dialog").locator(".drawer__close").click()
    rows.nth(1).locator("button").click()
    button = page.get_by_role("dialog").get_by_role("button", name="Roll back to the previous version" if language == "en"
                else "العودة إلى الإصدار السابق")
    expect(button).to_be_visible()
    button.click()
    assert state["calls"] == 1
    rows.nth(1).locator("button").click()
    expect(page.get_by_role("dialog")).to_contain_text("1.0.0")
    shot(page, out, language, width, "I-61-rollback-available")
    clear(page, errors, "I-61")


EMPTY_LISTS = [
    ("/shelf", "/api/shelf", {"view": "all", "entries": []}),
    ("/following", "/api/follows", {"follows": []}),
    ("/downloads", "/api/downloads", {"batches": []}),
    ("/sources", "/api/sources", {"sources": []}),
    ("/settings/storage", "/api/storage", {"roots": []}),
    ("/settings/backup", "/api/backups", {"backups": [], "due": False, "location_warning": None}),
]


def check_loading(browser, base, out, language, width):
    for path, endpoint, empty in EMPTY_LISTS:
        state = {"mode": "pending", "pending": []}
        def response(route):
            if state["mode"] == "pending": state["pending"].append(route)
            elif state["mode"] == "error": route.fulfill(status=503, json={"error": {
                "code": "SERVICE_UNAVAILABLE", "message": "Service temporarily unavailable"}})
            else: route.fulfill(json=empty)
        page, errors = new_page(browser, base, language, width, {endpoint: response})
        page.goto(base + path)
        expect(page.locator(".loading-state")).to_be_visible()
        assert state["pending"], (path, "no pending request")
        if path == "/following": assert page.get_by_role("button", name="Check all" if language == "en" else "تحقّق من الكل").count() == 0
        if path in ("/settings/backup", "/settings/storage"):
            pending_action = page.locator(".firstrun__actions button").first
            assert pending_action.is_disabled()
            assert float(pending_action.evaluate("e => getComputedStyle(e).opacity")) < 1
        shot(page, out, language, width, f"I-62-loading-{path.strip('/').replace('/', '-')}")
        state["pending"].pop().fulfill(json=empty)
        expect(page.locator(".loading-state")).to_have_count(0)
        state["mode"] = "error"
        page.reload()
        expect(page.get_by_role("alert").first).to_be_visible()
        assert "Service temporarily unavailable" not in page.get_by_role("alert").first.inner_text() if language == "ar" else True
        shot(page, out, language, width, f"I-62-error-{path.strip('/').replace('/', '-')}")
        clear(page, errors, "I-62 " + path)


def check_path(browser, base, out, language, width):
    path = "/media/Very-Long-Archive-Name/collection/works/English-Title-1234567890/volume-one/chapter.pdf"
    roots = {"roots": [{"id": "r1", "name": "Archive", "path": path, "is_default": True,
                       "available": True, "reason": None, "total": 500000000, "free": 100000000, "reserve": 0}]}
    page, errors = new_page(browser, base, language, width, {"/api/storage": roots})
    page.goto(base + "/settings/storage")
    literal = page.locator("bdi.literal-path")
    expect(literal).to_have_text(path)
    assert literal.get_attribute("dir") == "ltr"
    assert page.locator("html").get_attribute("dir") == ("rtl" if language == "ar" else "ltr")
    literal.dblclick()
    assert page.evaluate("String(window.getSelection())")
    shot(page, out, language, width, "I-63-storage-path")
    clear(page, errors, "I-63")


def check_service_language(browser, base, out, language, width):
    routes = {
        "/api/backups": {"backups": [], "due": False, "location_warning": {
            "same_device_as_library": True, "message": "Backups sit on the same disk as your library."}},
        ("POST", "/api/backups"): lambda route: route.fulfill(status=422, json={"error": {
            "code": "BACKUP_FAILED", "message": "Disk service failed"}}),
    }
    page, errors = new_page(browser, base, language, width, routes)
    page.goto(base + "/settings/backup")
    warning = page.locator(".notice--problem").first
    expect(warning).to_be_visible()
    if language == "ar": assert "Backups sit" not in warning.inner_text()
    page.locator(".firstrun__actions button").first.click()
    alert = page.get_by_role("alert")
    expect(alert).to_be_visible()
    if language == "ar": assert "Disk service failed" not in alert.inner_text()
    else: assert "Disk service failed" in alert.inner_text()
    shot(page, out, language, width, "I-64-backup-language")
    clear(page, errors, "I-64")


def check_hero(browser, base, out, language, width):
    for cover in ("/api/covers/broken", None):
        home = {"hero": {"work_id": "w0", "title": "حكاية القمر", "cover_url": cover,
                         "reason": "pinned", "description": "A story to read."},
                "continue_reading": [], "trending": [], "latest": [], "recently_added": []}
        page, errors = new_page(browser, base, language, width, {"/api/home": home})
        page.goto(base + "/")
        expect(page.locator(".hero__blank.workcard__blank")).to_be_visible()
        assert page.locator(".hero img").count() == 0
        shot(page, out, language, width, "I-65-hero-" + ("failed" if cover else "missing"))
        clear(page, errors, "I-65")


def check_filepicker(browser, base, out, language, width):
    for path, label, filename, upload in (
        ("/sources", "Choose an .osp package" if language == "en" else "اختر حزمة ‎.osp",
         "source.osp", "/api/sources/uploads"),
        ("/settings/storage", "Choose a file" if language == "en" else "اختر ملفًا",
         "قصة chapter.pdf", "/api/import/uploads"),
    ):
        review = ({"upload_id": "u1", "id": "test.source", "name": "Test", "version": "1.0.0",
                   "description": None, "publisher": None, "sha256": "a" * 64, "capabilities": [],
                   "browser_capabilities": [], "permissions": [], "auth_available": False,
                   "tests": {"passed": False, "cases": 0, "failures": []}} if path == "/sources" else
                  {"upload_id": "u1", "format": "pdf", "suggested_title": "Story", "language": "en",
                   "page_count": 1, "warnings": [], "suggestions": []})
        page, errors = new_page(browser, base, language, width, {("POST", upload): review})
        page.goto(base + path)
        picker = page.get_by_label(label, exact=True)
        assert picker.get_attribute("type") == "file"
        label_el = picker.locator("xpath=..")
        expect(label_el.locator(".filepicker__button")).to_have_text("Choose file" if language == "en" else "اختر ملفًا")
        expect(label_el.locator(".filepicker__name")).to_have_text("No file selected" if language == "en" else "لم يُحدَّد ملف")
        picker.focus()
        with page.expect_file_chooser() as chooser_info:
            picker.press("Enter")
        chooser_info.value.set_files({"name": filename, "mimeType": "application/octet-stream", "buffer": b"PK\x03\x04sample"})
        expect(label_el.locator(".filepicker__name")).to_have_text(filename)
        label_el.evaluate("e => e.scrollIntoView({block: 'center'})")
        shot(page, out, language, width, "I-66-filepicker-" + ("sources" if path == "/sources" else "storage"))
        clear(page, errors, "I-66")


def check_following(browser, base, out, language, width):
    state = {"follows": [], "checks": 0}
    def follows(route): route.fulfill(json={"follows": state["follows"]})
    def check(route):
        state["checks"] += 1
        route.fulfill(json={"checked": 1})
    page, errors = new_page(browser, base, language, width,
                            {"/api/follows": follows, ("POST", "/api/follows/check-all"): check})
    page.goto(base + "/following")
    assert page.get_by_role("button", name="Check all" if language == "en" else "تحقّق من الكل").count() == 0
    search = page.get_by_role("link", name="Find works to follow" if language == "en" else "ابحث عن أعمال لمتابعتها")
    expect(search).to_be_visible()
    shot(page, out, language, width, "I-67-empty-following")
    search.click()
    expect(page).to_have_url(base + "/search")
    state["follows"] = [{"work_id": "w0", "work_title": "Story", "track_id": "t0", "source_id": "local",
                         "language": "en", "state": "up_to_date", "last_attempted_at": None,
                         "last_successful_at": None, "unseen_releases": 0}]
    page.goto(base + "/following")
    button = page.get_by_role("button", name="Check all" if language == "en" else "تحقّق من الكل")
    expect(button).to_be_visible()
    button.click()
    assert state["checks"] == 1
    clear(page, errors, "I-67")


def run(base, out):
    out.mkdir(parents=True, exist_ok=True)
    checks = 0
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        for language in LANGUAGES:
            for width in WIDTHS:
                for check in (check_epub, check_export, check_rollback, check_loading, check_path,
                              check_service_language, check_hero, check_filepicker, check_following):
                    check(browser, base, out, language, width)
                    checks += 1
                print(f"PASS {language} {width}: I-58, I-60..I-67", flush=True)
        browser.close()
    print(f"PASS {checks} issue/locale/viewport groups")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default="http://127.0.0.1:4177")
    parser.add_argument("--screenshots", default="/tmp/oneshelf-remaining-ux-production")
    args = parser.parse_args()
    run(args.url.rstrip("/"), Path(args.screenshots))
