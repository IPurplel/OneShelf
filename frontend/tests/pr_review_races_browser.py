"""Controlled Chromium races from PR #1 review: obsolete completion and login cleanup retry."""
import argparse
import json
from pathlib import Path
from urllib.parse import urlparse

from playwright.sync_api import expect, sync_playwright
from layout_browser import fixture
from targeted_ui_bugfix_browser import work


def run(base: str, output: Path) -> None:
    traces = {}
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        for language in ("en", "ar"):
            for width in (390, 768, 1440):
                tag = f"{language}-{width}"
                page = browser.new_page(viewport={"width": width, "height": 844}, reduced_motion="reduce")
                page.add_init_script(f"localStorage.setItem('oneshelf.language', '{language}')")
                page.set_default_timeout(6000)
                errors = []
                page.on("pageerror", lambda error: errors.append(str(error)))
                completion = {"completed": False, "pending": [], "calls": []}

                def completion_route(route):
                    path = urlparse(route.request.url).path
                    method = route.request.method
                    if path == "/api/works/w0":
                        return route.fulfill(json=work(completed=completion["completed"]))
                    if path == "/api/shelf/w0" and method == "POST":
                        value = route.request.post_data_json["completed"]
                        completion["calls"].append({"method": "POST", "path": path, "completed": value})
                        completion["completed"] = value
                        return route.fulfill(json={"work_id": "w0"})
                    if path == "/api/shelf/w0/removal-summary":
                        completion["calls"].append({"method": "GET", "path": path, "delayed": True})
                        completion["pending"].append(route)
                        return
                    if path.startswith("/api/works/") and path.endswith("/files") and method == "DELETE":
                        completion["calls"].append({"method": "DELETE", "path": path})
                        return route.fulfill(json={"deleted_files": 2})
                    return fixture(route, 3)

                page.route(base + "/api/**", completion_route)
                page.goto(base + "/works/w0")
                complete = page.locator(".work__actions button[aria-pressed]").first
                complete.click()
                expect(complete).to_have_attribute("aria-pressed", "true")
                page.wait_for_function("() => document.querySelector('.work__actions') !== null")
                assert len(completion["pending"]) == 1, completion
                complete.click()
                expect(complete).to_have_attribute("aria-pressed", "false")
                assert completion["completed"] is False
                with page.expect_response(lambda response: urlparse(response.url).path
                        == "/api/shelf/w0/removal-summary"):
                    completion["pending"].pop().fulfill(json={"work_id": "w0", "files": 2,
                        "bytes": 1000, "has_progress": False, "is_followed": False})
                expect(page.get_by_role("dialog")).to_have_count(0)
                assert not any(call["method"] == "DELETE" for call in completion["calls"])
                assert not errors, errors
                if width == 390:
                    page.screenshot(path=str(output / f"{tag}-completion-undone.png"), full_page=True)
                traces[f"{tag}-completion"] = completion["calls"]
                page.close()

                page = browser.new_page(viewport={"width": width, "height": 844}, reduced_motion="reduce")
                page.add_init_script(f"localStorage.setItem('oneshelf.language', '{language}')")
                page.set_default_timeout(6000)
                errors = []
                page.on("pageerror", lambda error: errors.append(str(error)))
                login = {"opens": 0, "old_pending": [], "old_deletes": 0, "calls": []}
                old_id = f"old-{tag}"
                new_id = f"new-{tag}"

                def login_route(route):
                    path = urlparse(route.request.url).path
                    method = route.request.method
                    if path == "/api/sources":
                        return route.fulfill(json={"sources": [dict(id="alpha", name="Reading Room Library",
                            state="active", version="1.0.0", trust_label="official", channel="bundled",
                            capabilities=["search", "work", "catalog", "reader"], auth_available=True,
                            session_state="none")]})
                    if path == "/api/sources/alpha/login" and method == "POST":
                        login["opens"] += 1
                        if login["opens"] == 1:
                            login["old_pending"].append(route)
                            return
                        return route.fulfill(json={"login_id": new_id, "status": "open"})
                    if path == f"/api/logins/{old_id}" and method == "DELETE":
                        login["old_deletes"] += 1
                        status = 503 if login["old_deletes"] == 1 else 200
                        login["calls"].append({"method": "DELETE", "path": path, "status": status})
                        return route.fulfill(status=status, json={"error": {"message": "Temporary failure"}}
                            if status == 503 else {"login_id": old_id, "status": "cancelled"})
                    if path == f"/api/logins/{new_id}" and method == "DELETE":
                        login["calls"].append({"method": "DELETE", "path": path})
                        return route.fulfill(json={})
                    if path == f"/api/logins/{new_id}/frame":
                        return route.fulfill(content_type="image/svg+xml", body=(
                            '<svg xmlns="http://www.w3.org/2000/svg" width="1280" height="800">'
                            '<rect width="1280" height="800" fill="#f5f3ee"/>'
                            '<text x="80" y="120" fill="#214632" font-size="40">Controlled sign-in frame</text>'
                            '</svg>'))
                    return fixture(route, 3)

                page.route(base + "/api/**", login_route)
                page.goto(base + "/sources")
                page.locator(".cards__row button").first.click()
                session_name = "Use my session" if language == "en" else "استخدم جلستي"
                open_name = "Open the sign-in window" if language == "en" else "افتح نافذة تسجيل الدخول"
                page.get_by_role("button", name=session_name).click()
                page.get_by_role("button", name=open_name).click()
                expect(page.get_by_role("dialog")).to_be_visible()
                page.keyboard.press("Escape")
                expect(page.get_by_role("dialog")).to_have_count(0)
                page.locator(".cards__row button").first.click()
                page.get_by_role("button", name=session_name).click()
                page.get_by_role("button", name=open_name).click()
                expect(page.get_by_role("img", name="Sign-in window" if language == "en"
                    else "نافذة تسجيل الدخول")).to_have_attribute("src", f"/api/logins/{new_id}/frame?f=0")
                assert len(login["old_pending"]) == 1
                with page.expect_response(lambda response: urlparse(response.url).path == f"/api/logins/{old_id}"
                        and response.request.method == "DELETE" and response.status == 200):
                    login["old_pending"].pop().fulfill(json={"login_id": old_id, "status": "open"})
                assert login["old_deletes"] == 2, login
                assert not any(call["path"] == f"/api/logins/{new_id}" for call in login["calls"])
                expect(page.get_by_role("dialog")).to_be_visible()
                assert not errors, errors
                if width == 390:
                    page.screenshot(path=str(output / f"{tag}-new-login-survives.png"), full_page=True)
                traces[f"{tag}-login"] = login["calls"]
                page.close()
                print("PASS review races", tag, flush=True)
        browser.close()
    (output / "request-trace.json").write_text(json.dumps(traces, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default="http://127.0.0.1:5173")
    parser.add_argument("--screenshots", default="/tmp/oneshelf-pr-review-races")
    options = parser.parse_args()
    output = Path(options.screenshots)
    output.mkdir(parents=True, exist_ok=True)
    run(options.url, output)
