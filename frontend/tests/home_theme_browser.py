"""Production Chromium regressions for Search contrast, Home density, and app themes."""
import argparse
import re
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

sys.path.insert(0, str(Path(__file__).parent))
from layout_browser import fixture

WIDTHS = (390, 768, 1440)
LANGUAGES = ("en", "ar")


def rgb(value):
    channels = re.findall(r"[\d.]+", value)
    return [float(channel) / 255 for channel in channels[:3]]


def luminance(value):
    channels = [channel / 12.92 if channel <= 0.04045 else ((channel + 0.055) / 1.055) ** 2.4
                for channel in rgb(value)]
    return sum(channel * weight for channel, weight in zip(channels, (0.2126, 0.7152, 0.0722)))


def contrast(first, second):
    lighter, darker = sorted((luminance(first), luminance(second)), reverse=True)
    return (lighter + 0.05) / (darker + 0.05)


def open_page(browser, width, language, system_theme="dark", count=12):
    context = browser.new_context(viewport={"width": width, "height": 844}, color_scheme=system_theme)
    context.add_init_script(f"localStorage.setItem('oneshelf.language', '{language}')")
    page = context.new_page()
    page.route("**/api/**", lambda route: fixture(route, count))
    return context, page


def check_search(browser, base, screenshots):
    for language in LANGUAGES:
        for width in WIDTHS:
            for system_theme in ("light", "dark"):
                context, page = open_page(browser, width, language, system_theme=system_theme)
                page.goto(base + "/search")
                field = page.get_by_role("searchbox")
                field.fill("OneShelf search")
                colors = field.evaluate("""field => {
                  const style = getComputedStyle(field);
                  return { text: style.color, background: style.backgroundColor,
                           caret: style.caretColor, placeholder: getComputedStyle(field, '::placeholder').color };
                }""")
                assert contrast(colors["text"], colors["background"]) >= 4.5, (language, width, colors)
                assert contrast(colors["placeholder"], colors["background"]) >= 4.5, (language, width, colors)
                assert contrast(colors["caret"], colors["background"]) >= 3, (language, width, colors)
                assert field.input_value() == "OneShelf search"
                page.screenshot(path=str(screenshots / f"search-{language}-{width}-{system_theme}.png"))
                context.close()


def check_home(browser, base, screenshots):
    for language in LANGUAGES:
        for width in WIDTHS:
            context, page = open_page(browser, width, language)
            page.goto(base + "/")
            page.locator(".shelf").first.wait_for()
            rows = page.locator(".shelf__row")
            assert rows.count() == 4
            for row in rows.all():
                sizes = row.evaluate("e => ({scroll: e.scrollWidth, client: e.clientWidth})")
                assert sizes["scroll"] <= sizes["client"] + 1, (language, width, sizes)
                assert row.locator(".workcard").count() == 12
                last = row.locator(".workcard").last
                last.scroll_into_view_if_needed()
                assert last.is_visible()
            title_sizes = [row.locator(".workcard__title").first.evaluate("e => getComputedStyle(e).fontSize")
                           for row in rows.all()]
            assert len(set(title_sizes)) == 1, (language, width, title_sizes)
            assert page.evaluate("document.documentElement.scrollHeight > innerHeight")
            assert page.evaluate("document.documentElement.scrollWidth <= innerWidth + 1")
            page.screenshot(path=str(screenshots / f"home-{language}-{width}.png"), full_page=True)
            context.close()

            one_context, one_page = open_page(browser, width, language, count=1)
            one_page.goto(base + "/")
            one_page.locator(".shelf .workcard").first.wait_for()
            assert one_page.locator(".shelf__row").first.evaluate("e => e.scrollWidth <= e.clientWidth + 1")
            one_page.locator(".shelf .workcard").first.click()
            assert "/works/w0" in one_page.url
            one_context.close()

            empty_context, empty_page = open_page(browser, width, language, count=0)
            empty_page.goto(base + "/")
            empty = empty_page.locator(".home__empty")
            empty.wait_for()
            assert empty.get_by_role("link").count() == 2
            assert empty.evaluate("e => e.getBoundingClientRect().width") >= width - (64 if width < 900 else 340)
            assert empty_page.locator(".shelf").count() == 0
            action_colors = empty.evaluate("""e => {
              const action = e.querySelector('.button--primary');
              return { surface: getComputedStyle(e).backgroundColor,
                       button: getComputedStyle(action).backgroundColor,
                       text: getComputedStyle(action).color };
            }""")
            assert contrast(action_colors["button"], action_colors["surface"]) >= 3, action_colors
            assert contrast(action_colors["text"], action_colors["button"]) >= 4.5, action_colors
            empty_context.close()


def check_theme(browser, base, screenshots):
    for language in LANGUAGES:
        for width in WIDTHS:
            context, page = open_page(browser, width, language)
            page.goto(base + "/settings/general")
            theme = page.get_by_role("group", name="Appearance" if language == "en" else "المظهر")
            system = theme.get_by_role("button", name="System" if language == "en" else "النظام")
            light = theme.get_by_role("button", name="Light" if language == "en" else "فاتح")
            dark = theme.get_by_role("button", name="Dark" if language == "en" else "داكن")
            assert system.get_attribute("aria-pressed") == "true"
            dark_canvas = page.locator("body").evaluate("e => getComputedStyle(e).backgroundColor")
            light.click()
            assert light.get_attribute("aria-pressed") == "true"
            light_canvas = page.locator("body").evaluate("e => getComputedStyle(e).backgroundColor")
            assert dark_canvas != light_canvas
            page.reload()
            assert light.get_attribute("aria-pressed") == "true"
            dark.click()
            assert dark.get_attribute("aria-pressed") == "true"
            assert page.locator("body").evaluate("e => getComputedStyle(e).backgroundColor") == dark_canvas
            pressed = dark.evaluate("""e => {
              const style = getComputedStyle(e);
              return { background: style.backgroundColor, underline: style.boxShadow.match(/rgb\\([^)]*\\)/)?.[0] };
            }""")
            assert pressed["underline"] and contrast(pressed["underline"], pressed["background"]) >= 3, pressed
            system.click()
            page.emulate_media(color_scheme="light")
            page.wait_for_function("document.documentElement.dataset.resolvedTheme === 'light'")
            assert page.locator("body").evaluate("e => getComputedStyle(e).backgroundColor") == light_canvas
            page.emulate_media(color_scheme="dark")
            page.wait_for_function("document.documentElement.dataset.resolvedTheme === 'dark'")
            assert page.locator("body").evaluate("e => getComputedStyle(e).backgroundColor") == dark_canvas
            page.screenshot(path=str(screenshots / f"theme-{language}-{width}.png"))
            context.close()


def check_dark_surfaces(browser, base, screenshots):
    axe = Path(__file__).parents[1] / "node_modules/axe-core/axe.min.js"
    routes = ("/", "/search", "/shelf", "/following", "/downloads", "/sources",
              "/settings/general", "/settings/storage", "/settings/backup", "/works/w0")
    for language in LANGUAGES:
        for width in WIDTHS:
            context, page = open_page(browser, width, language, count=4)
            for route in routes:
                page.goto(base + route)
                page.get_by_role("heading", level=1).first.wait_for()
                page.wait_for_timeout(80)
                assert page.evaluate("document.documentElement.dataset.resolvedTheme") == "dark"
                assert page.evaluate("document.documentElement.scrollWidth <= innerWidth + 1"), (language, width, route)
                page.add_script_tag(path=str(axe))
                result = page.evaluate("""async () => axe.run(document, {
                  runOnly: { type: 'rule', values: ['color-contrast'] }
                })""")
                violations = [(node["target"], node["failureSummary"])
                              for violation in result["violations"] for node in violation["nodes"]]
                assert not violations, (language, width, route, violations)
                page.screenshot(path=str(screenshots / f"surface-{language}-{width}-{route.strip('/').replace('/', '-') or 'home'}.png"))

            page.goto(base + "/")
            page.locator(".header__controls button").last.click()
            drawer = page.locator("dialog.modal.drawer")
            drawer.wait_for(state="visible")
            drawer.evaluate("e => e.getAnimations().length && Promise.all(e.getAnimations().map(a => a.finished))")
            page.add_script_tag(path=str(axe))
            result = page.evaluate("""async () => axe.run(document, {
              runOnly: { type: 'rule', values: ['color-contrast'] }
            })""")
            assert not result["violations"], (language, width, "drawer", result["violations"])
            page.screenshot(path=str(screenshots / f"drawer-{language}-{width}.png"))
            page.keyboard.press("Escape")
            assert drawer.count() == 0

            page.goto(base + "/shelf")
            page.locator(".toolbar__end .iconbutton").last.click()
            page.locator(".shelfview__manage").first.click()
            modal = page.locator("dialog.modal.confirm")
            modal.wait_for(state="visible")
            page.add_script_tag(path=str(axe))
            result = page.evaluate("""async () => axe.run(document, {
              runOnly: { type: 'rule', values: ['color-contrast'] }
            })""")
            assert not result["violations"], (language, width, "modal", result["violations"])
            page.screenshot(path=str(screenshots / f"modal-{language}-{width}.png"))
            page.keyboard.press("Escape")
            assert modal.count() == 0
            context.close()

    reader_backgrounds = []
    for system_theme in ("light", "dark"):
        context, page = open_page(browser, 390, "en", system_theme=system_theme, count=1)
        page.goto(base + "/read/u0?work=w0&track=t0")
        reader = page.locator(".reader")
        reader.wait_for()
        reader_backgrounds.append(reader.evaluate("e => getComputedStyle(e).backgroundColor"))
        context.close()
    assert reader_backgrounds[0] == reader_backgrounds[1], reader_backgrounds


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--base", default="http://127.0.0.1:4179")
    parser.add_argument("--check", choices=("search", "home", "theme", "surfaces", "all"), default="all")
    parser.add_argument("--screenshots", default="/tmp/oneshelf-home-theme-screenshots")
    args = parser.parse_args()
    shots = Path(args.screenshots)
    shots.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        for name, check in (("search", check_search), ("home", check_home),
                            ("theme", check_theme), ("surfaces", check_dark_surfaces)):
            if args.check in (name, "all"):
                check(browser, args.base, shots)
                print(f"PASS {name}: EN/AR at 390, 768, and 1440 px")
        browser.close()
