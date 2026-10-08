"""Chromium regressions for Work Details I-57 and I-59."""
import argparse
from pathlib import Path
from urllib.parse import urlparse

from playwright.sync_api import expect, sync_playwright
from layout_browser import fixture

BASE_WORK = dict(id="w0", content_type="manga", content_type_source="source", aliases=[])
LONG_WORK = dict(BASE_WORK, title="The very long chronicle of a wandering reader seeking a story in several distant libraries",
                 original_title="سجل طويل آخر يصف رحلة القارئ عبر مكتبات متعددة حول العالم",
                 creator="A creator with an unusually long credited name that goes on and on across many editions",
                 description="A very long account of this work and its journey across many pages. " * 18)
LONG_WORK_AR = dict(BASE_WORK, title="سجل القارئ الطويل الذي يبحث عن قصة في مكتبات بعيدة متعددة حول العالم",
                    original_title="A second long title about a reader crossing many distant libraries",
                    creator="مؤلف ذو اسم طويل للغاية يمتد عبر إصدارات كثيرة ومكتبات متعددة",
                    description="وصف طويل لهذا العمل ورحلته عبر صفحات كثيرة ومكتبات متعددة. " * 18)
SHORT_WORK = dict(BASE_WORK, title="A quiet story", original_title=None, creator="A. Writer",
                  description="A short description remains available.")
UNIT = dict(id="u0", title="Chapter One", number="1", unit_type="chapter", volume=None, order=1,
            release_date=None, availability="available", url=None, downloaded=True, formats=["cbz"],
            read_state="unread", fraction=0, read_at=None, integrity="ok", is_new=False)


def setup(page, base, work):
    state = dict(favorite=False, pinned=False, calls=[], errors=[])
    page.on("pageerror", lambda error: state["errors"].append(str(error)))

    def route(request):
        path = urlparse(request.request.url).path
        if path == "/api/works/w0":
            return request.fulfill(json=dict(
                work=work, cover_url=None,
                shelf=dict(on_shelf=True, favorite=state["favorite"], pinned=state["pinned"], completed=False),
                follow=dict(following=False, preferred_source_id=None, track_id=None, language=None,
                            last_successful_at=None),
                tracks=[dict(id="t0", source_id="local", language="en", kind="local",
                             availability="available", unit_count=1)],
                selected_track_id="t0", continue_unit_id="u0", units=[UNIT]))
        if path == "/api/shelf/w0" and request.request.method == "POST":
            body = request.request.post_data_json
            state["calls"].append(body)
            state.update({key: body[key] for key in ("favorite", "pinned") if key in body})
            return request.fulfill(json={"work_id": "w0"})
        return fixture(request, 3)

    page.route(base + "/api/**", route)
    return state


def toggle_appearance(button):
    return button.evaluate("""e => {
      const mark = e.querySelector('.work__toggleMark');
      const style = getComputedStyle(e);
      const rect = e.getBoundingClientRect();
      return { pressed: e.getAttribute('aria-pressed'), mark: mark && getComputedStyle(mark).visibility,
        background: style.backgroundColor, border: style.borderColor,
        width: rect.width, height: rect.height, left: rect.left + scrollX, top: rect.top + scrollY };
    }""")


def check_toggles(page, state, language, width, out):
    labels = {"en": ("Favorite", "Pin"), "ar": ("مفضّلة", "تثبيت")}[language]
    for key, label in zip(("favorite", "pinned"), labels):
        button = page.get_by_role("button", name=label, exact=True)
        expect(button).to_have_attribute("aria-pressed", "false")
        off = toggle_appearance(button)
        assert off["mark"] == "hidden", f"{language} {width} {key}: missing reserved off marker: {off}"
        button.click()
        expect(button).to_have_attribute("aria-pressed", "true")
        on = toggle_appearance(button)
        assert on["mark"] == "visible", f"{language} {width} {key}: selected marker invisible: {on}"
        assert (on["background"], on["border"]) != (off["background"], off["border"]), (off, on)
        for dimension in ("width", "height", "left", "top"):
            assert abs(on[dimension] - off[dimension]) <= 1, f"{key} changed {dimension}: {off} -> {on}"
        assert state[key] is True and state["calls"][-1] == {key: True}, state
        page.screenshot(path=str(out / f"{language}-{width}-{key}-on.png"))
        button.click()
        expect(button).to_have_attribute("aria-pressed", "false")
        again = toggle_appearance(button)
        assert again["mark"] == "hidden" and state[key] is False, again
        for dimension in ("width", "height", "left", "top"):
            assert abs(again[dimension] - off[dimension]) <= 1, f"{key} changed {dimension} after off"
        assert state["calls"][-1] == {key: False}, state
    assert not state["errors"], state["errors"]


def check_action_placement(page, language, width, out, work, long_content):
    continue_link = page.locator('.work__actions a[href^="/read/"]').first
    expect(continue_link).to_be_visible()
    desc = page.locator(".work__description")
    expect(desc).to_be_visible()
    assert desc.text_content() == work["description"]
    action = continue_link.bounding_box()
    description = desc.bounding_box()
    assert action and description
    if long_content:
        assert action["y"] + action["height"] + 12 < description["y"], (action, description)
        if width == 390:
            bottom_nav = page.locator(".bottomnav").bounding_box()
            assert bottom_nav and action["y"] + action["height"] + 12 <= bottom_nav["y"], (action, bottom_nav)
    else:
        assert action["y"] < description["y"], (action, description)
    assert page.locator(".work__cover img").count() == 0
    overflow = page.evaluate("document.documentElement.scrollWidth - innerWidth")
    assert overflow <= 1, f"{language} {width}: Work content overflows horizontally by {overflow}px"
    page.screenshot(path=str(out / f"{language}-{width}-{'long' if long_content else 'short'}-work.png"),
                    full_page=width == 390)
    base = page.url.split("/works/")[0]
    continue_link.click()
    expect(page).to_have_url(base + "/read/u0?work=w0&track=t0")
    expect(page.locator(".reader")).to_have_count(1)


def run(base, out):
    out.mkdir(parents=True, exist_ok=True)
    checks = 0
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        for language in ("en", "ar"):
            for width in (390, 768, 1440):
                stress = LONG_WORK if language == "en" else LONG_WORK_AR
                for work, kind in ((stress, "long"), (SHORT_WORK, "short")):
                    page = browser.new_page(viewport={"width": width, "height": 844}, reduced_motion="reduce")
                    page.add_init_script(f"localStorage.setItem('oneshelf.language', '{language}')")
                    page.set_default_timeout(6000)
                    state = setup(page, base, work)
                    page.goto(base + "/works/w0")
                    try:
                        if kind == "long":
                            check_toggles(page, state, language, width, out)
                            checks += 4
                        check_action_placement(page, language, width, out, work, kind == "long")
                        checks += 1
                        assert not state["errors"], state["errors"]
                    finally:
                        page.close()
        browser.close()
    print(f"PASS: {checks} Work Details browser interaction/layout checks")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default="http://127.0.0.1:4175")
    parser.add_argument("--screenshots", default="/tmp/oneshelf-medium-ux-production")
    args = parser.parse_args()
    run(args.url.rstrip("/"), Path(args.screenshots))
