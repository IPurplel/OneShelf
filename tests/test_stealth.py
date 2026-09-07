"""Tests for the built-in Cloudflare solving path.

No browser is launched here. The parts worth testing are the decisions —
which driver, headless or headful, where to click, when to retry — and those
are all reachable with fakes. Whether Cloudflare actually accepts the click is
not something a test can assert; it is verified against the live site.
"""

from __future__ import annotations

import asyncio
import importlib

import pytest

from app import browser as browser_mod
from app import display as display_mod
from app.browser import Driver, browser_args, load_driver
from app.config import Settings
from app.display import VirtualDisplay
from app.session import ChallengeError, SessionManager, _is_closed_error


# --------------------------------------------------------------------- fakes


class FakeMouse:
    def __init__(self) -> None:
        self.moves: list[tuple[float, float]] = []
        self.downs = 0
        self.ups = 0

    async def move(self, x, y):
        self.moves.append((x, y))

    async def down(self):
        self.downs += 1

    async def up(self):
        self.ups += 1


class FakeElement:
    def __init__(self, attrs=None, box=None):
        self._attrs = attrs or {}
        self._box = box

    async def get_attribute(self, name):
        return self._attrs.get(name)

    async def bounding_box(self):
        return self._box


class FakePage:
    def __init__(self, iframes=(), widgets=None, title="Just a moment...",
                 content="<html>challenge-platform</html>"):
        self.iframes = list(iframes)
        self.widgets = widgets or {}
        self.mouse = FakeMouse()
        self.brought_to_front = False
        self.url = "https://example.net/manga/series/"
        self._titles = title if isinstance(title, list) else [title]
        self._contents = content if isinstance(content, list) else [content]
        self.load_states: list[str] = []

    async def query_selector_all(self, selector):
        assert selector == "iframe"
        return self.iframes

    async def query_selector(self, selector):
        return self.widgets.get(selector)

    async def bring_to_front(self):
        self.brought_to_front = True

    async def title(self):
        return self._titles[0] if len(self._titles) == 1 else self._titles.pop(0)

    async def content(self):
        return self._contents[0] if len(self._contents) == 1 else self._contents.pop(0)

    async def wait_for_load_state(self, state, timeout=None):
        self.load_states.append(state)


class FakeContext:
    def __init__(self, cookies=(), then=None):
        self._cookies = list(cookies)
        self._then = then
        self.cleared: list[str | None] = []
        self.reads = 0

    async def cookies(self):
        self.reads += 1
        # `then` models Cloudflare replacing the cookie once a challenge passes.
        if self._then is not None and self.reads > 1:
            return list(self._then)
        return self._cookies

    async def clear_cookies(self, domain=None):
        self.cleared.append(domain)


@pytest.fixture
def settings(tmp_path):
    return Settings(output_dir=tmp_path / "out", config_dir=tmp_path / "cfg")


@pytest.fixture
def manager(settings):
    return SessionManager(settings)


@pytest.fixture
def no_sleep(monkeypatch):
    """Collapse the polling delays so retry logic runs at full speed."""
    async def instant(_seconds):
        return None

    monkeypatch.setattr(asyncio, "sleep", instant)


# ------------------------------------------------------------------- driver


def test_load_driver_prefers_the_patched_build():
    driver = load_driver(prefer_stealth=True)
    assert driver.name == "patchright"
    assert driver.stealth is True
    # patchright reports navigator.webdriver false natively; injecting an init
    # script to "fix" it would reintroduce the leak it exists to remove.
    assert driver.needs_webdriver_patch is False


def test_load_driver_can_pin_stock_playwright():
    driver = load_driver(prefer_stealth=False)
    assert driver.name == "playwright"
    assert driver.stealth is False
    assert driver.needs_webdriver_patch is True


def test_load_driver_falls_back_when_patchright_is_absent(monkeypatch):
    real = importlib.import_module

    def missing_patchright(name, *args, **kwargs):
        if name.startswith("patchright"):
            raise ImportError("no patchright")
        return real(name, *args, **kwargs)

    monkeypatch.setattr(browser_mod.importlib, "import_module", missing_patchright)
    driver = load_driver(prefer_stealth=True)
    assert driver.name == "playwright"
    assert driver.needs_webdriver_patch is True


def test_load_driver_raises_when_nothing_is_installed(monkeypatch):
    def nothing(name, *args, **kwargs):
        raise ImportError(name)

    monkeypatch.setattr(browser_mod.importlib, "import_module", nothing)
    with pytest.raises(RuntimeError, match="No Playwright-compatible driver"):
        load_driver()


def test_detect_channel_prefers_real_chrome(monkeypatch):
    monkeypatch.setattr(browser_mod, "channel_available", lambda c: True)
    # Chrome over Edge: it is the browser Cloudflare sees most of.
    assert browser_mod.detect_channel("auto") == "chrome"


def test_detect_channel_falls_back_to_edge(monkeypatch):
    monkeypatch.setattr(browser_mod, "channel_available", lambda c: c == "msedge")
    assert browser_mod.detect_channel("auto") == "msedge"


def test_detect_channel_returns_none_when_no_real_browser(monkeypatch):
    monkeypatch.setattr(browser_mod, "channel_available", lambda c: False)
    # None means bundled Chromium - weaker against challenges, always present.
    assert browser_mod.detect_channel("auto") is None


def test_detect_channel_honours_an_explicit_choice(monkeypatch):
    monkeypatch.setattr(browser_mod, "channel_available", lambda c: True)
    assert browser_mod.detect_channel("msedge") == "msedge"
    assert browser_mod.detect_channel("chromium") is None


def test_detect_channel_does_not_pick_a_missing_browser(monkeypatch):
    monkeypatch.setattr(browser_mod, "channel_available", lambda c: False)
    # Asking for Chrome that is not installed must degrade, not crash at launch.
    assert browser_mod.detect_channel("chrome") is None


def test_container_flags_are_sent_on_linux(monkeypatch):
    monkeypatch.setattr(browser_mod, "_platform_key", lambda: "linux")
    args = browser_args(headless=True)
    # Without this Chromium dies on the container's 64 MB /dev/shm.
    assert "--disable-dev-shm-usage" in args
    # Unprivileged LXC has no user namespaces for the sandbox.
    assert "--no-sandbox" in args


@pytest.mark.parametrize("platform", ["win32", "darwin"])
def test_container_flags_are_never_sent_on_a_desktop(monkeypatch, platform):
    # No real desktop browser has ever run with --no-sandbox, so sending it
    # there is itself the anomaly we are trying not to present.
    monkeypatch.setattr(browser_mod, "_platform_key", lambda: platform)
    args = browser_args(headless=False)
    assert "--no-sandbox" not in args
    assert "--disable-setuid-sandbox" not in args
    assert "--disable-dev-shm-usage" not in args


def test_automation_controlled_flag_is_left_to_patchright():
    # Patchright adds it itself; passing it again is redundant.
    assert "--disable-blink-features=AutomationControlled" not in browser_args(False)


def test_browser_args_only_disable_gpu_when_headless():
    # Under Xvfb, Chromium picks SwiftShader and reports a plausible WebGL
    # renderer. Forcing --disable-gpu there reports none at all, which is
    # louder than the thing it was meant to hide.
    assert "--disable-gpu" in browser_args(headless=True)
    assert "--disable-gpu" not in browser_args(headless=False)


# --------------------------------------------------- launch options (stealth)


class RecordingChromium:
    """Captures the options a launch was attempted with."""

    def __init__(self):
        self.options = None

    async def launch_persistent_context(self, **options):
        self.options = options
        return AttachContext()


def _recording_manager(tmp_path, **overrides):
    settings = Settings(output_dir=tmp_path / "o", config_dir=tmp_path / "c",
                        **overrides)
    manager = SessionManager(settings)
    chromium = RecordingChromium()

    class FakePlaywright:
        pass

    FakePlaywright.chromium = chromium
    manager._driver = Driver(name="patchright", async_playwright=lambda: None)
    manager._playwright = FakePlaywright()
    return manager, chromium


async def test_launch_injects_no_fingerprint(tmp_path):
    """Patchright's requirement is "Chrome without fingerprint injection".

    Each of these is applied through a CDP override a bot check can see, and
    `viewport` is the worst: on a headful browser it forces a device-metrics
    override, so window.outerWidth/innerWidth/screen stop agreeing as they do
    in any real window. That mismatch damns the session permanently, which is
    a Cloudflare verify loop no click can escape.
    """
    manager, chromium = _recording_manager(tmp_path)
    manager._headless = False
    await manager._launch(tmp_path / "profile", user_agent=None)

    assert chromium.options["no_viewport"] is True
    for forbidden in ("viewport", "locale", "user_agent", "ignore_https_errors"):
        assert forbidden not in chromium.options, f"{forbidden} is fingerprint injection"


async def test_headful_never_gets_a_synthetic_user_agent(tmp_path):
    manager, chromium = _recording_manager(tmp_path)
    manager._headless = False
    await manager._launch(tmp_path / "profile", user_agent=None)
    assert "user_agent" not in chromium.options


async def test_headless_may_scrub_its_own_marker(tmp_path):
    # Headless leaks "HeadlessChrome" in the UA and cannot pass an interactive
    # challenge anyway, so the override there is damage control, not stealth.
    manager, chromium = _recording_manager(tmp_path)
    manager._headless = True
    await manager._launch(tmp_path / "profile", user_agent="Mozilla/5.0 Chrome/149")
    assert chromium.options["user_agent"] == "Mozilla/5.0 Chrome/149"


# ------------------------------------------------------------------ settings


@pytest.mark.parametrize(
    "given,expected",
    [
        (True, "true"),
        (False, "false"),
        ("auto", "auto"),
        ("AUTO", "auto"),
        ("yes", "true"),
        ("off", "false"),
    ],
)
def test_headless_accepts_yaml_bools_and_auto(tmp_path, given, expected):
    # An existing `headless: true` in config.yaml must keep meaning what it did.
    assert Settings(config_dir=tmp_path, headless=given).headless == expected


def test_headless_rejects_nonsense(tmp_path):
    with pytest.raises(ValueError, match="headless must be"):
        Settings(config_dir=tmp_path, headless="maybe")


def test_auto_starts_headless_and_stays_escalatable(settings, manager):
    assert settings.headless == "auto"
    assert manager._headless is True
    assert manager._can_escalate() is True


def test_explicit_headless_is_never_overridden(tmp_path):
    # An operator who wrote `headless: true` gets headless, not a surprise
    # X server and a 300 MB resident browser.
    manager = SessionManager(Settings(config_dir=tmp_path, headless=True))
    assert manager._can_escalate() is False


def test_explicit_headful_starts_headful(tmp_path):
    manager = SessionManager(Settings(config_dir=tmp_path, headless=False))
    assert manager._headless is False


# ------------------------------------------------------------- widget lookup


async def test_locates_the_challenge_iframe_by_src(manager):
    page = FakePage(iframes=[
        FakeElement({"src": "https://ads.example/x"}, {"x": 0, "y": 0, "width": 300, "height": 60}),
        FakeElement({"src": "https://challenges.cloudflare.com/cdn-cgi/challenge"},
                    {"x": 100, "y": 200, "width": 300, "height": 65}),
    ])
    x, y = await manager._locate_widget(page)
    assert x == pytest.approx(130.0)          # 100 + checkbox offset
    assert y == pytest.approx(232.5)          # vertically centred


async def test_locates_the_iframe_by_title_when_src_is_blank(manager):
    # The iframe is created before its src is assigned, so early polls see only
    # the accessibility title.
    page = FakePage(iframes=[
        FakeElement({"title": "Widget containing a Cloudflare security challenge"},
                    {"x": 10, "y": 20, "width": 300, "height": 70}),
    ])
    assert await manager._locate_widget(page) == (40.0, 55.0)


async def test_ignores_unrelated_iframes(manager):
    page = FakePage(iframes=[
        FakeElement({"src": "https://www.youtube.com/embed/x"},
                    {"x": 0, "y": 0, "width": 560, "height": 315}),
    ])
    assert await manager._locate_widget(page) is None


async def test_skips_a_collapsed_widget(manager):
    # A zero-sized box means the widget is not laid out yet; clicking 0,0 would
    # hit the page background and do nothing useful.
    page = FakePage(iframes=[
        FakeElement({"src": "https://challenges.cloudflare.com/x"},
                    {"x": 0, "y": 0, "width": 0, "height": 0}),
    ])
    assert await manager._locate_widget(page) is None


async def test_falls_back_to_the_widget_placeholder(manager):
    page = FakePage(widgets={
        ".cf-turnstile": FakeElement(box={"x": 50, "y": 100, "width": 300, "height": 65}),
    })
    # y is clamped at 32 rather than the 32.5 centre - half a pixel, and it
    # keeps tall containers (below) from being aimed at their empty middle.
    assert await manager._locate_widget(page) == (80.0, 132.0)


async def test_placeholder_click_is_clamped_to_the_widget_top(manager):
    # #challenge-stage can be a tall container; its centre is empty page.
    page = FakePage(widgets={
        "#challenge-stage": FakeElement(box={"x": 0, "y": 0, "width": 600, "height": 900}),
    })
    _, y = await manager._locate_widget(page)
    assert y == 32.0


async def test_no_widget_means_no_click(manager):
    assert await manager._locate_widget(FakePage()) is None


# -------------------------------------------------------------------- clicks


async def test_click_moves_the_mouse_before_pressing(manager):
    page = FakePage(iframes=[
        FakeElement({"src": "https://challenges.cloudflare.com/x"},
                    {"x": 100, "y": 200, "width": 300, "height": 60}),
    ])
    assert await manager._click_challenge(page) is True

    # Turnstile watches for pointer movement preceding the click; a cursor that
    # teleports and clicks in the same tick is a signature.
    assert len(page.mouse.moves) > 5
    assert page.mouse.moves[-1] == (130.0, 230.0)   # lands exactly on target
    assert page.mouse.downs == 1 and page.mouse.ups == 1


async def test_click_focuses_the_window_when_headful(manager):
    manager._headless = False
    page = FakePage(iframes=[
        FakeElement({"src": "https://challenges.cloudflare.com/x"},
                    {"x": 0, "y": 0, "width": 300, "height": 60}),
    ])
    await manager._click_challenge(page)
    # A background window gets no real input focus and the widget stays inert.
    assert page.brought_to_front is True


async def test_click_reports_false_when_there_is_nothing_to_click(manager):
    assert await manager._click_challenge(FakePage()) is False


async def test_click_survives_a_page_that_navigated_away(manager):
    class Exploding(FakePage):
        async def query_selector_all(self, selector):
            raise RuntimeError("Execution context was destroyed")

    # The page navigating mid-click is normal, not an error worth failing on.
    assert await manager._click_challenge(Exploding()) is False


# ------------------------------------------------------------------ clearance


async def test_clearance_matches_a_parent_domain_cookie(manager):
    manager._context = FakeContext(
        [{"name": "cf_clearance", "domain": ".example.net", "value": "abc"}])
    assert await manager._clearance_value("www.example.net") == "abc"


async def test_clearance_ignores_another_hosts_cookie(manager):
    manager._context = FakeContext(
        [{"name": "cf_clearance", "domain": ".other.net", "value": "abc"}])
    assert await manager._clearance_value("example.net") is None


async def test_clearance_ignores_ordinary_cookies(manager):
    manager._context = FakeContext(
        [{"name": "PHPSESSID", "domain": ".example.net", "value": "abc"}])
    assert await manager._clearance_value("example.net") is None


async def test_wait_returns_once_fresh_clearance_is_issued(manager, no_sleep):
    manager._context = FakeContext(
        [], then=[{"name": "cf_clearance", "domain": ".example.net", "value": "new"}])
    page = FakePage(
        title=["Just a moment...", "Berserk - Example"],
        content=["<html>challenge-platform</html>", "<html>chapters</html>"],
    )
    await manager._wait_for_clearance(page, "example.net")


async def test_a_stale_cookie_is_not_mistaken_for_a_solved_challenge(
    manager, no_sleep, settings
):
    # Regression: Cloudflare re-challenges an already-cleared session and only
    # replaces the cookie once the new challenge passes. Treating the leftover
    # cookie as success returns the interstitial HTML as if it were the page,
    # and every parse downstream then fails for no visible reason.
    settings.challenge_timeout = 0.3
    settings.challenge_click = False
    manager._context = FakeContext(
        [{"name": "cf_clearance", "domain": ".example.net", "value": "old"}])
    with pytest.raises(ChallengeError, match="did not clear"):
        await manager._wait_for_clearance(FakePage(), "example.net")


async def test_a_replaced_cookie_counts_as_solved(manager, no_sleep):
    manager._context = FakeContext(
        [{"name": "cf_clearance", "domain": ".example.net", "value": "old"}],
        then=[{"name": "cf_clearance", "domain": ".example.net", "value": "new"}],
    )
    page = FakePage(
        title=["Just a moment...", "Berserk - Example"],
        content=["<html>challenge-platform</html>", "<html>chapters</html>"],
    )
    await manager._wait_for_clearance(page, "example.net")


async def test_settling_gives_up_rather_than_hanging(manager, no_sleep, settings):
    # The redirect may never produce clean HTML. The clearance cookie is
    # already held, so this returns instead of burning the whole timeout.
    settings.challenge_timeout = 0.3
    await manager._settle_after_clearance(FakePage(), deadline=0.0)


async def test_wait_returns_when_the_page_clears_itself(manager, no_sleep):
    # The non-interactive challenge needs no click at all.
    manager._context = FakeContext()
    page = FakePage(
        title=["Just a moment...", "Berserk - Example"],
        content=["<html>challenge-platform</html>", "<html>chapters</html>"],
    )
    await manager._wait_for_clearance(page, "example.net")


async def test_wait_gives_up_with_a_useful_message(manager, no_sleep, settings):
    settings.challenge_timeout = 0.2
    settings.challenge_click = False
    manager._context = FakeContext()
    with pytest.raises(ChallengeError, match="did not clear"):
        await manager._wait_for_clearance(FakePage(), "example.net")


# ----------------------------------------------------------------- retrying


async def test_solve_retries_then_escalates_then_explains(manager, settings, no_sleep):
    settings.challenge_attempts = 3
    attempts: list[bool] = []

    async def always_fail(url, host, attempt):
        attempts.append(manager._headless)
        raise ChallengeError("nope")

    async def fake_escalate():
        manager._headless = False
        manager._escalated = True

    manager._solve_once = always_fail
    manager._escalate_to_headful = fake_escalate
    manager._context = FakeContext()

    with pytest.raises(ChallengeError) as excinfo:
        await manager._solve("https://example.net/manga/series/")

    assert len(attempts) == 3
    # Headless first (cheap), headful afterwards (more likely to pass).
    assert attempts == [True, False, False]
    # Only when automation is genuinely out of options does the user get work.
    assert "Settings" in str(excinfo.value)
    assert "headful retry" in str(excinfo.value)
    # Each retry starts from a clean slate, or Cloudflare replays the same
    # failed challenge state and every attempt fails identically.
    assert manager._context.cleared == ["example.net", "example.net"]


async def test_solve_stops_at_the_first_success(manager, settings, no_sleep):
    settings.challenge_attempts = 3
    calls = []

    async def fail_once(url, host, attempt):
        calls.append(attempt)
        if attempt == 1:
            raise ChallengeError("first try")
        return "session"

    manager._solve_once = fail_once
    manager._escalate_to_headful = _noop
    manager._context = FakeContext()

    assert await manager._solve("https://example.net/x") == "session"
    assert calls == [1, 2]


async def test_escalation_without_a_display_stays_headless(manager):
    async def no_display():
        return None

    manager._acquire_display = no_display
    await manager._escalate_to_headful()

    # Launching headful with no X server is a guaranteed crash, so we stay put.
    assert manager._headless is True
    # ...but the attempt is not repeated on every subsequent failure.
    assert manager._escalated is True
    assert manager._can_escalate() is False


# ------------------------------------------------------------ virtual display


async def test_display_is_a_noop_where_one_already_exists(monkeypatch):
    monkeypatch.setattr(display_mod, "platform_needs_xvfb", lambda: False)
    monkeypatch.setenv("DISPLAY", ":0")
    assert await VirtualDisplay().start() == ":0"


async def test_display_on_windows_reports_a_native_desktop(monkeypatch):
    monkeypatch.setattr(display_mod, "platform_needs_xvfb", lambda: False)
    monkeypatch.delenv("DISPLAY", raising=False)
    # Truthy, not None: Windows and macOS always have somewhere to draw, and
    # None is reserved for "headful is impossible here".
    assert await VirtualDisplay().start() == "native"


async def test_display_reuses_an_inherited_x_server(monkeypatch):
    monkeypatch.setattr(display_mod, "platform_needs_xvfb", lambda: True)
    monkeypatch.setenv("DISPLAY", ":1")
    display = VirtualDisplay()
    assert await display.start() == ":1"
    assert display.status()["managed"] is False


async def test_display_reports_none_when_xvfb_is_missing(monkeypatch):
    monkeypatch.setattr(display_mod, "platform_needs_xvfb", lambda: True)
    monkeypatch.setattr(display_mod, "xvfb_available", lambda: False)
    monkeypatch.delenv("DISPLAY", raising=False)
    # None means "headful is impossible here" - the caller must stay headless
    # rather than launch into a certain crash.
    assert await VirtualDisplay().start() is None


def test_display_number_skips_a_server_already_running(monkeypatch, tmp_path):
    (tmp_path / "X99").touch()
    monkeypatch.setattr(display_mod, "X11_SOCKET_DIR", tmp_path)
    assert VirtualDisplay()._free_display_number() == 100


def test_display_number_is_exhaustible(monkeypatch, tmp_path):
    for number in display_mod.DISPLAY_RANGE:
        (tmp_path / f"X{number}").touch()
    monkeypatch.setattr(display_mod, "X11_SOCKET_DIR", tmp_path)
    assert VirtualDisplay()._free_display_number() is None


# ---------------------------------------------------------- assisted solving


async def test_headless_never_asks_the_user(manager, settings):
    # There would be no window to click in; asking would just stall.
    assert manager._headless is True
    assert manager._can_ask_user() is False


async def test_a_visible_window_can_ask_the_user(manager):
    manager._headless = False
    assert manager._can_ask_user() is True


async def test_assisted_solving_can_be_turned_off(manager, settings):
    manager._headless = False
    settings.assisted_solve = False
    assert manager._can_ask_user() is False


async def test_the_user_is_asked_only_after_automation_has_tried(
    manager, settings, no_sleep
):
    settings.challenge_timeout = 0.2
    settings.assisted_timeout = 0.6
    manager._headless = False
    manager._context = FakeContext()

    seen: list[str | None] = []

    class WatchingPage(FakePage):
        async def content(self):
            seen.append(manager._awaiting_user)
            return "<html>challenge-platform</html>"

    with pytest.raises(ChallengeError, match="Nobody completed the check"):
        await manager._wait_for_clearance(WatchingPage(), "example.net")

    # Automation gets the first window uninterrupted, then the user is asked.
    assert seen[0] is None
    assert "example.net" in seen
    # And the flag is cleared afterwards, so a later solve does not inherit it.
    assert manager._awaiting_user is None


async def test_unattended_solving_still_clicks(manager, settings, no_sleep):
    # Headless there is nobody to ask, and a synthetic click is measurably
    # better than none: with clicking off, the live site never issued
    # clearance at all.
    settings.challenge_timeout = 0.4
    manager._headless = True
    manager._context = FakeContext()

    page = FakePage(iframes=[
        FakeElement({"src": "https://challenges.cloudflare.com/x"},
                    {"x": 0, "y": 0, "width": 300, "height": 60}),
    ])
    with pytest.raises(ChallengeError):
        await manager._wait_for_clearance(page, "example.net")

    assert page.mouse.downs >= 1


async def test_a_visible_window_never_gets_a_synthetic_click(manager, settings, no_sleep):
    # Turnstile marks synthetic events untrusted and loops that session for
    # good, so clicking first would spend the user's session before they
    # touched it - the "verify, reload, verify again" loop.
    settings.challenge_timeout = 0.2
    settings.assisted_timeout = 0.5
    manager._headless = False
    manager._context = FakeContext()

    page = FakePage(iframes=[
        FakeElement({"src": "https://challenges.cloudflare.com/x"},
                    {"x": 0, "y": 0, "width": 300, "height": 60}),
    ])
    with pytest.raises(ChallengeError):
        await manager._wait_for_clearance(page, "example.net")

    assert page.mouse.downs == 0


async def test_waiting_for_the_user_stops_synthetic_clicking(manager, settings, no_sleep):
    # A synthetic click landing while someone is interacting can reset the
    # widget under them - the one thing worse than not helping.
    settings.challenge_timeout = 0.0
    settings.assisted_timeout = 0.4
    manager._headless = False
    manager._context = FakeContext()

    page = FakePage(iframes=[
        FakeElement({"src": "https://challenges.cloudflare.com/x"},
                    {"x": 0, "y": 0, "width": 300, "height": 60}),
    ])
    with pytest.raises(ChallengeError):
        await manager._wait_for_clearance(page, "example.net")

    assert page.mouse.downs == 0
    assert page.brought_to_front is True


async def test_the_flag_clears_when_the_user_succeeds(manager, settings, no_sleep):
    settings.challenge_timeout = 0.0
    settings.assisted_timeout = 5.0
    manager._headless = False
    manager._context = FakeContext(
        [], then=[{"name": "cf_clearance", "domain": ".example.net", "value": "v"}])

    page = FakePage(
        title=["Just a moment...", "Berserk"],
        content=["<html>challenge-platform</html>", "<html>chapters</html>"],
    )
    await manager._wait_for_clearance(page, "example.net", require_content=False)
    assert manager._awaiting_user is None


def test_status_exposes_the_pending_request(manager):
    manager._awaiting_user = "example.net"
    assert manager.status()["awaiting_user"] == "example.net"


# ------------------------------------------------------------ attach over CDP


class FakeBrowser:
    def __init__(self, contexts=()):
        self.contexts = list(contexts)
        self.closed = False
        self.new_contexts = 0

    async def new_context(self, **kwargs):
        self.new_contexts += 1
        ctx = AttachContext()
        self.contexts.append(ctx)
        return ctx

    async def close(self):
        self.closed = True


class AttachContext(FakeContext):
    def __init__(self, cookies=(), ua="Mozilla/5.0 RealBrowser/1.0", pages=None):
        super().__init__(cookies)
        self.closed = False
        self.timeout = None
        self._ua = ua
        self.pages = list(pages) if pages else []
        self.handlers: dict[str, list] = {}
        self.opened = 0

    def set_default_navigation_timeout(self, value):
        self.timeout = value

    def on(self, event, handler):
        self.handlers.setdefault(event, []).append(handler)

    def emit(self, event):
        for handler in self.handlers.get(event, []):
            handler(self)

    async def new_page(self):
        self.opened += 1
        page = AttachPage(self._ua)
        self.pages.append(page)
        return page

    async def close(self):
        self.closed = True


class AttachPage:
    def __init__(self, ua):
        self._ua = ua

    async def evaluate(self, script):
        return self._ua

    async def close(self):
        return None


def _attached_manager(tmp_path, browser, endpoint="http://127.0.0.1:9222"):
    settings = Settings(output_dir=tmp_path / "o", config_dir=tmp_path / "c",
                        browser_cdp=endpoint)
    manager = SessionManager(settings)

    class FakeChromium:
        async def connect_over_cdp(self, url):
            manager.connected_to = url
            return browser

    class FakePlaywright:
        chromium = FakeChromium()

    manager._driver = Driver(name="patchright", async_playwright=lambda: None)
    manager._playwright = FakePlaywright()
    return manager, settings


@pytest.mark.parametrize(
    "given,expected",
    [
        ("127.0.0.1:9222", "http://127.0.0.1:9222"),
        ("http://127.0.0.1:9222/", "http://127.0.0.1:9222"),
        ("", None),
        ("  ", None),
    ],
)
def test_cdp_endpoint_is_normalised(tmp_path, given, expected):
    # "127.0.0.1:9222" is what a person types; accept it.
    assert Settings(config_dir=tmp_path, browser_cdp=given).browser_cdp == expected


async def test_attaching_reuses_the_existing_context(tmp_path):
    # The running browser's default context holds the user's cookies - which
    # includes the challenge they already cleared by hand. Making a new one
    # would throw that away and be back at square one.
    existing = AttachContext()
    manager, _ = _attached_manager(tmp_path, FakeBrowser([existing]))
    await manager._open_context()

    assert manager._context is existing
    assert manager._attached is True
    assert manager._browser.new_contexts == 0
    assert manager.user_agent == "Mozilla/5.0 RealBrowser/1.0"


async def test_attaching_creates_a_context_only_if_there_is_none(tmp_path):
    browser = FakeBrowser([])
    manager, _ = _attached_manager(tmp_path, browser)
    await manager._open_context()
    assert browser.new_contexts == 1


async def test_attached_browser_is_never_closed(tmp_path):
    # It is the user's window, with the user's tabs in it.
    existing = AttachContext()
    browser = FakeBrowser([existing])
    manager, _ = _attached_manager(tmp_path, browser)
    await manager._open_context()
    await manager._close_context()

    assert existing.closed is False
    assert browser.closed is False
    assert manager._context is None


async def test_attaching_is_headful_by_definition(tmp_path):
    manager, _ = _attached_manager(tmp_path, FakeBrowser([AttachContext()]))
    await manager._open_context()
    # There is nothing to escalate to; we are already in a real browser.
    assert manager._headless is False
    assert manager._can_escalate() is False


async def test_a_missing_browser_explains_how_to_start_one(tmp_path):
    class Refusing:
        async def connect_over_cdp(self, url):
            raise OSError("connection refused")

    manager, _ = _attached_manager(tmp_path, FakeBrowser())
    manager._playwright.chromium = Refusing()

    with pytest.raises(ChallengeError, match="remote-debugging-port"):
        await manager._open_context()


def test_status_reports_the_attachment(tmp_path):
    manager, _ = _attached_manager(tmp_path, FakeBrowser())
    manager._attached = True
    status = manager.status()
    assert status["attached"] is True
    assert status["cdp_endpoint"] == "http://127.0.0.1:9222"


# ------------------------------------------------------- browser lifecycle


class DyingContext(AttachContext):
    """Raises Playwright's closed-browser error a set number of times."""

    def __init__(self, failures=1, **kwargs):
        super().__init__(**kwargs)
        self.failures = failures
        self.attempts = 0

    async def new_page(self):
        self.attempts += 1
        if self.attempts <= self.failures:
            raise RuntimeError(
                "BrowserContext.new_page: Target page, context or browser has "
                "been closed"
            )
        return await super().new_page()


def _relaunching_manager(tmp_path, first, second):
    """Manager whose next launch yields `second` after `first` is discarded."""
    settings = Settings(output_dir=tmp_path / "o", config_dir=tmp_path / "c")
    manager = SessionManager(settings)
    manager._driver = Driver(name="patchright", async_playwright=lambda: None)
    manager._playwright = object()
    manager._context = first
    manager.launches = 0

    async def fake_open():
        manager.launches += 1
        manager._context = second

    manager._open_context = fake_open
    return manager


def test_closed_error_is_recognised():
    assert _is_closed_error(
        RuntimeError("Target page, context or browser has been closed")) is True
    assert _is_closed_error(RuntimeError("net::ERR_NAME_NOT_RESOLVED")) is False


async def test_a_dead_browser_is_relaunched_once(tmp_path):
    """The exact production failure: a closed window bricked every request.

    _ensure_context caches the context and only checks it is not None, so
    without this the same corpse is handed out until the app restarts.
    """
    dead, fresh = DyingContext(failures=99), AttachContext()
    manager = _relaunching_manager(tmp_path, dead, fresh)

    page = await manager._new_page()

    assert manager.launches == 1
    assert page in fresh.pages


async def test_relaunching_is_not_retried_forever(tmp_path):
    # If the fresh browser is also dead something else is wrong; failing is
    # better than a relaunch loop.
    manager = _relaunching_manager(
        tmp_path, DyingContext(failures=99), DyingContext(failures=99))

    with pytest.raises(RuntimeError, match="has been closed"):
        await manager._new_page()
    assert manager.launches == 1


async def test_an_unrelated_error_is_not_swallowed(tmp_path):
    class Broken(AttachContext):
        async def new_page(self):
            raise RuntimeError("net::ERR_NAME_NOT_RESOLVED")

    manager = _relaunching_manager(tmp_path, Broken(), AttachContext())
    with pytest.raises(RuntimeError, match="ERR_NAME_NOT_RESOLVED"):
        await manager._new_page()
    assert manager.launches == 0


async def test_an_attached_browser_is_never_relaunched(tmp_path):
    # Starting our own browser would quietly contradict browser_cdp.
    manager = _relaunching_manager(
        tmp_path, DyingContext(failures=99), AttachContext())
    manager._attached = True
    manager._settings.browser_cdp = "http://127.0.0.1:9222"

    with pytest.raises(ChallengeError, match="remote-debugging-port"):
        await manager._new_page()
    assert manager.launches == 0


async def test_the_close_event_clears_the_cached_context(tmp_path):
    manager, _ = _recording_manager(tmp_path)
    context = AttachContext()
    await manager._prepare_context(context)
    manager._context = context

    context.emit("close")

    assert manager._context is None
    assert manager._keeper is None


async def test_a_late_close_event_cannot_kill_its_successor(tmp_path):
    # A stale event from a context we already replaced must not null the new one.
    manager, _ = _recording_manager(tmp_path)
    old = AttachContext()
    await manager._prepare_context(old)
    new = AttachContext()
    manager._context = new

    old.emit("close")

    assert manager._context is new


async def test_a_keeper_page_is_held_open(tmp_path):
    """One page must outlive every operation.

    Each fetch opens a page and closes it in a finally. The browser's initial
    blank window was the only thing keeping Chrome alive; once a user closed
    it, the next fetch dropped the window count to zero and Chrome quit.
    """
    manager, _ = _recording_manager(tmp_path)
    context = AttachContext()
    await manager._prepare_context(context)

    assert manager._keeper is not None
    assert manager._keeper in context.pages


async def test_the_initial_window_is_adopted_rather_than_duplicated(tmp_path):
    existing = AttachPage("ua")
    context = AttachContext(pages=[existing])
    manager, _ = _recording_manager(tmp_path)

    await manager._prepare_context(context)

    assert manager._keeper is existing
    assert context.opened == 0


async def test_reading_the_user_agent_opens_no_page(tmp_path):
    # This ran at launch and is exactly the open/close churn that can quit
    # the browser, so it reuses the keeper instead.
    manager, _ = _recording_manager(tmp_path)
    context = AttachContext()
    await manager._prepare_context(context)
    before = context.opened

    assert await manager._read_user_agent(context) == "Mozilla/5.0 RealBrowser/1.0"
    assert context.opened == before


# ------------------------------------------------------------------- status


def test_status_reports_the_solving_posture(manager):
    manager._driver = Driver(name="patchright", async_playwright=lambda: None)
    status = manager.status()
    assert status["driver"] == "patchright"
    assert status["stealth"] is True
    assert status["headless"] is True
    assert status["headless_mode"] == "auto"
    assert status["escalated"] is False


async def _noop(*args, **kwargs):
    return None


# ------------------------------------------------------- redirect shells


@pytest.mark.parametrize(
    "html,title",
    [
        ("<html><body>Redirecting...</body></html>", "Redirecting..."),
        ('<html><head><meta http-equiv="refresh" content="0;url=/x"></head></html>', ""),
        ("<html><body>Please wait while you are redirected</body></html>", ""),
    ],
)
def test_redirect_shells_are_recognised(html, title):
    """goto() returns once the shell parses, so it must be spotted and waited out."""
    from app.session import looks_like_redirect

    assert looks_like_redirect(html, title) is True


def test_a_real_page_is_not_mistaken_for_a_redirect():
    from app.session import looks_like_redirect

    # Long pages are never shells, even if the word appears somewhere in them.
    assert looks_like_redirect("<html>" + "chapter " * 5000 + "redirecting</html>") is False
    assert looks_like_redirect("<html><body><h1>One Piece</h1></body></html>") is False
