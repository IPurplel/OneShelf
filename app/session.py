"""Browser-backed session management and Cloudflare solving.

The target sites sit behind a Cloudflare JavaScript challenge, so a plain HTTP
client can never reach them: the edge returns an interstitial (or simply resets
the connection) until a real browser has executed the challenge script.

The strategy here is a *handoff*. One long-lived Chromium solves the challenge
and owns the resulting ``cf_clearance`` cookie; every bulk image download then
runs over fast parallel HTTP reusing that cookie. The browser is used for
challenges and HTML only, never for fetching hundreds of images.

Solving is built in and escalates on its own, cheapest option first:

1. **A patched driver.** Stock Playwright is detectable through the automation
   protocol rather than through the DOM, so no amount of ``navigator`` patching
   saves it; ``patchright`` removes those leaks. See :mod:`app.browser`.
2. **Wait it out.** The non-interactive challenge clears by itself once the
   script has run. Most Madara sites never get past this step.
3. **Click the Turnstile checkbox.** Located by the bounding box of its iframe
   and clicked with real mouse movement, because the checkbox lives in a closed
   shadow root inside a cross-origin frame where no selector can reach it.
4. **Escalate to headful.** Under a virtual display if there is no real one.
   Headless Chromium takes different rendering and input code paths, and those
   are readable from JavaScript; a Turnstile that stalls headless often passes
   headful. See :mod:`app.display`.
5. **Ask the user.** Only after all of the above: paste a cookie from your own
   browser. Retained because Cloudflare sometimes hard-blocks whole datacenter
   ranges, which is not a problem any automation can solve.

Two constraints drive the design and are easy to get wrong:

* ``cf_clearance`` is bound to the **IP address and the exact User-Agent** that
  solved the challenge. The HTTP client must therefore send the browser's own
  UA verbatim, and the browser must run in the same container as the downloader.
* Chromium inside an LXC/Docker container gets a very small ``/dev/shm`` and
  will crash without ``--disable-dev-shm-usage``.
"""

from __future__ import annotations

import asyncio
import logging
import os
import random
import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING
from urllib.parse import urlparse

from .browser import browser_args, detect_channel, load_driver
from .display import VirtualDisplay

if TYPE_CHECKING:  # pragma: no cover - import cost only matters at runtime
    from playwright.async_api import BrowserContext, Page

log = logging.getLogger(__name__)

CHALLENGE_TITLES = {
    "just a moment...",
    "just a moment",
    "please wait...",
    "attention required! | cloudflare",
    "checking your browser before accessing",
}

CHALLENGE_MARKERS = (
    "challenge-platform",
    "cf-browser-verification",
    "cf_chl_opt",
    "_cf_chl_opt",
    "turnstile",
)

#: Host of the iframe Cloudflare renders its widget into.
CHALLENGE_FRAME_HOST = "challenges.cloudflare.com"

#: Fallback containers, for sites embedding a standalone Turnstile widget
#: rather than serving the full interstitial.
WIDGET_SELECTORS = (
    "#cf-turnstile",
    ".cf-turnstile",
    "div[id^='cf-chl-widget']",
    "#challenge-stage",
    "#turnstile-wrapper",
)

#: Distance from the widget's left edge to the centre of its checkbox. The
#: widget is a fixed-size Cloudflare-rendered control, so this is stable.
CHECKBOX_OFFSET_X = 30.0

#: Don't re-click faster than this; the widget needs time to resolve, and
#: hammering it looks exactly like what it is.
CLICK_INTERVAL = 4.0
#: Generous, because a staged challenge presents a fresh widget per stage.
MAX_CLICKS = 8

#: Grace period for the post-challenge redirect to produce the real document.
CLEARANCE_SETTLE = 15.0

#: How many times to re-request a page that keeps coming back challenged.
PAGE_LOAD_ROUNDS = 3

#: Interstitials that move you on with a meta refresh or a script rather than
#: an HTTP redirect. `goto` follows HTTP redirects but returns as soon as this
#: shell is parsed, so without a second look the adapter parses the shell.
_REDIRECT_MARKERS = ("redirecting", "please wait while you are redirected")
REDIRECT_SETTLE_MS = 4000

#: Bounds for `scroll_for`, the lazily-built-list wait. Generous enough for a
#: long chapter, finite because a reader with an endless feed underneath it
#: would otherwise never stop. A round that adds nothing ends the loop, so
#: these are ceilings and not costs.
LAZY_SCROLL_ROUNDS = 60
LAZY_SCROLL_PIXELS = 20000
LAZY_SCROLL_SETTLE_MS = 700


def looks_like_redirect(html: str, title: str = "") -> bool:
    """True when a page is only an interstitial pointing somewhere else."""
    if title.strip().lower().rstrip(".") in ("redirecting", "redirect"):
        return True
    if len(html) > 20_000:
        return False  # a real page, whatever else it happens to contain
    lowered = html.lower()
    if 'http-equiv="refresh"' in lowered or "http-equiv='refresh'" in lowered:
        return True
    return any(marker in lowered for marker in _REDIRECT_MARKERS)

#: Shown in the window the app keeps open, so it does not read as debris.
KEEPER_HTML = """<!doctype html>
<title>Manga Downloader</title>
<style>
 body{font:16px/1.6 system-ui,sans-serif;margin:0;display:flex;height:100vh;
      align-items:center;justify-content:center;background:#14161a;color:#c9d1d9}
 div{max-width:34em;padding:2em;text-align:center}
 b{color:#e6edf3}
</style>
<div>
 <p><b>Manga Downloader is using this window.</b></p>
 <p>Leave it open while the app is running. If a site shows a
 "verify you are human" check, it will appear here — complete it once and
 the download continues on its own.</p>
</div>"""

#: Playwright reports a dead browser as a plain Error, so the message is all
#: there is to match on.
CLOSED_MARKERS = (
    "has been closed",
    "target closed",
    "browser closed",
    "connection closed",
)


def _is_closed_error(exc: BaseException) -> bool:
    """True when a call failed because the browser is gone."""
    text = str(exc).lower()
    return any(marker in text for marker in CLOSED_MARKERS)


DEFAULT_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)


class ChallengeError(RuntimeError):
    """Raised when the Cloudflare challenge could not be cleared."""


@dataclass
class HostSession:
    """Credentials harvested for one host."""

    host: str
    cookies: dict[str, str] = field(default_factory=dict)
    user_agent: str = DEFAULT_UA
    solved_at: float = 0.0
    manual: bool = False
    """True when supplied by the user rather than solved by the browser."""

    @property
    def has_clearance(self) -> bool:
        return "cf_clearance" in self.cookies

    def cookie_header(self) -> str:
        return "; ".join(f"{k}={v}" for k, v in self.cookies.items())

    def age(self) -> float:
        return time.time() - self.solved_at


def is_challenge(html: str, title: str = "", status: int = 200) -> bool:
    """Heuristically detect a Cloudflare interstitial.

    Checks title, the well-known inline script markers, and the status codes
    Cloudflare uses for managed challenges.
    """
    if title.strip().lower() in CHALLENGE_TITLES:
        return True
    if status in (403, 503) and any(m in html for m in CHALLENGE_MARKERS):
        return True
    lowered = html[:20000].lower()
    if "just a moment" in lowered and "challenge" in lowered:
        return True
    return False


class SessionManager:
    """Owns the Chromium instance and the per-host clearance cookies."""

    def __init__(self, settings, db=None) -> None:
        self._settings = settings
        self._db = db
        self._driver = None
        self._playwright = None
        self._context: BrowserContext | None = None
        self._sessions: dict[str, HostSession] = {}
        self._launch_lock = asyncio.Lock()
        # Serialise challenge solving: parallel workers hitting a 403 at the
        # same moment must not each spawn their own solve.
        self._solve_locks: dict[str, asyncio.Lock] = {}
        self._user_agent: str | None = None
        self._channel: str | None = None
        self._browser = None
        self._keeper = None
        """A page held open for the context's lifetime.

        Every operation here opens a page and closes it again, so without one
        page that is never closed the window count reaches zero and the browser
        quits — after which every request fails until the app is restarted.
        """
        self._attached = False
        """True when driving a browser we did not start - and must not close."""
        self._awaiting_user: str | None = None
        """Host whose challenge is currently waiting on a human."""
        self._display = VirtualDisplay()
        self._headless: bool = settings.start_headless
        self._escalated = False
        """Set once we have moved to a headful browser, so escalation is
        attempted at most once per process rather than on every failure."""

    # ------------------------------------------------------------- lifecycle

    async def start(self) -> None:
        await self._ensure_context()

    async def _ensure_context(self) -> BrowserContext:
        if self._context is not None:
            return self._context
        async with self._launch_lock:
            if self._context is not None:
                return self._context
            await self._open_context()
            return self._context

    async def _open_context(self) -> None:
        """Launch the browser. Caller must hold ``_launch_lock``."""
        if self._driver is None:
            self._driver = load_driver(prefer_stealth=self._settings.stealth)
            self._channel = detect_channel(self._settings.browser_channel)
            log.info("Browser driver: %s (stealth=%s, channel=%s)",
                     self._driver.name, self._driver.stealth,
                     self._channel or "bundled chromium")

        if self._playwright is None:
            self._playwright = await self._driver.async_playwright().start()

        if self._settings.browser_cdp:
            await self._attach_over_cdp()
            return

        if not self._headless:
            display = await self._acquire_display()
            if display is None:
                log.warning("Falling back to headless: no display available")
                self._headless = True

        profile = self._settings.browser_profile_dir
        profile.mkdir(parents=True, exist_ok=True)

        log.info("Launching Chromium (headless=%s, profile=%s)",
                 self._headless, profile)
        self._context = await self._launch(profile, user_agent=None)
        await self._prepare_context(self._context)
        self._user_agent = await self._read_user_agent(self._context)

        # Headless Chromium advertises itself in the User-Agent as
        # "HeadlessChrome/<version>", one of the cheapest and most reliable
        # automation tells there is. Relaunch once with the marker removed so
        # the UA matches a normal desktop Chrome. The version and platform stay
        # genuine — only the giveaway goes — and because the same string is
        # later replayed by the HTTP client, both halves of the session agree.
        if self._user_agent and "HeadlessChrome" in self._user_agent:
            honest_ua = self._user_agent.replace("HeadlessChrome", "Chrome")
            log.info("Rewriting headless UA marker -> %s", honest_ua)
            await self._context.close()
            self._context = await self._launch(profile, user_agent=honest_ua)
            await self._prepare_context(self._context)
            self._user_agent = await self._read_user_agent(self._context)

        log.info("Browser user agent: %s", self._user_agent)

    async def _prepare_context(self, context: BrowserContext) -> None:
        """Make a freshly launched context survive normal use.

        Two jobs, both learned the hard way:

        *Keep a window open.* A persistent context starts with one blank window,
        and every operation here opens a page and closes it again. That blank
        window is therefore the only thing holding the browser open — and it is
        exactly the sort of stray window a person tidies away. Once it is gone,
        the next fetch closes the last window, Chrome exits, and every request
        afterwards fails. So we adopt a page and never close it.

        *Notice if it dies anyway.* A crash, an update, or a user closing the
        window should not brick the app until it is restarted.
        """
        self._keeper = context.pages[0] if context.pages else await context.new_page()
        try:
            await self._keeper.set_content(KEEPER_HTML)
        except Exception:  # pragma: no cover - cosmetic only
            log.debug("Could not label the keeper window", exc_info=True)

        def on_close(*_args) -> None:
            # Guarded: a late close event from a context we have already
            # replaced must not null out its successor.
            if self._context is context:
                log.warning("The browser went away; it will be relaunched on "
                            "the next request")
                self._context = None
                self._keeper = None

        context.on("close", on_close)

    async def _attach_over_cdp(self) -> None:
        """Drive a browser the user is already running.

        The dependable answer to an interactive Turnstile: rather than trying to
        look like a person to the challenge, use the browser in which a person
        already satisfied it. Nothing here has to win a detection arms race.

        Two things follow from the browser not being ours. We never close it —
        that would shut a window out from under the user — and we never inject
        init scripts or override its User-Agent, because its genuine identity is
        the entire point.
        """
        endpoint = self._settings.browser_cdp
        log.info("Attaching to the browser at %s", endpoint)
        try:
            self._browser = await self._playwright.chromium.connect_over_cdp(endpoint)
        except Exception as exc:
            raise ChallengeError(
                f"Could not attach to a browser at {endpoint}: {exc}. Start one "
                f"with --remote-debugging-port, e.g.\n"
                f'  chrome.exe --remote-debugging-port=9222 --user-data-dir="C:\\cdp-profile"\n'
                "then load the site and clear any check by hand."
            ) from exc

        # A browser started this way already has its default context holding the
        # user's tabs - and their cookies, including the cleared session.
        contexts = self._browser.contexts
        self._context = contexts[0] if contexts else await self._browser.new_context()
        self._context.set_default_navigation_timeout(
            self._settings.navigation_timeout * 1000
        )
        self._attached = True
        self._headless = False
        self._user_agent = await self._read_user_agent(self._context)
        log.info("Attached to %s (%d existing context(s)); user agent: %s",
                 endpoint, len(contexts), self._user_agent)

        if self._settings.browser_proxy_config is not None:
            # Worth saying plainly: an attached browser keeps its own network
            # path, so it will not follow the app's proxy. If the two exits
            # differ, clearance earned in the browser is void for the
            # downloader, which shows up as a wall of 403s.
            log.warning(
                "A proxy is configured but the attached browser routes itself. "
                "Ensure both use the same exit IP, or the clearance will not "
                "carry over to the downloader."
            )

    async def _new_page(self):
        """Open a page, relaunching the browser once if it has died.

        Without this a closed browser is fatal for the lifetime of the process:
        ``_ensure_context`` caches the context and only checks that it is not
        None, so every later call is handed the same corpse.
        """
        context = await self._ensure_context()
        try:
            return await context.new_page()
        except Exception as exc:
            if not _is_closed_error(exc):
                raise
            if self._attached:
                # Launching our own browser here would quietly contradict an
                # explicit configuration choice. Ask instead.
                raise ChallengeError(
                    f"The browser at {self._settings.browser_cdp} was closed. "
                    "Reopen it with --remote-debugging-port, load the site, and "
                    "try again."
                ) from exc
            log.warning("Browser was gone when opening a page; relaunching")
            await self._discard_context()
            context = await self._ensure_context()
            return await context.new_page()

    async def _discard_context(self) -> None:
        """Forget a dead context without trying to close it."""
        async with self._launch_lock:
            self._context = None
            self._keeper = None
            self._browser = None

    async def _acquire_display(self) -> str | None:
        if not self._settings.virtual_display:
            # Xvfb is disabled, so only a display someone else provides counts.
            return os.environ.get("DISPLAY") or None
        return await self._display.start()

    async def _launch(self, profile, user_agent: str | None):
        # Deliberately minimal. Every option below that is *absent* is absent
        # for a reason: patchright's requirement is "Chrome without fingerprint
        # injection", and each of viewport / locale / user_agent /
        # ignore_https_errors is applied through a CDP override that a bot
        # check can see. `viewport` is the worst of them — on a headful browser
        # it forces a device-metrics override, so window.outerWidth,
        # window.innerWidth and screen stop agreeing the way they do in any
        # real window. That mismatch is cheap to detect and damns the session
        # permanently, which is a verify loop no amount of clicking escapes.
        #
        # Do not "tidy" these back in. Tests assert their absence.
        options: dict = {
            "user_data_dir": str(profile),
            "headless": self._headless,
            "args": browser_args(self._headless),
            "no_viewport": True,
        }

        if user_agent:
            # Only ever set to scrub the "HeadlessChrome" marker out of a
            # headless launch. That mode cannot pass an interactive challenge
            # regardless, so the override is damage control, not stealth —
            # and it must never reach a headful browser, whose UA is honest.
            options["user_agent"] = user_agent

        if self._channel:
            options["channel"] = self._channel

        proxy = self._settings.browser_proxy_config
        if proxy is not None:
            options["proxy"] = proxy.for_browser()
            log.info("Browser egress via proxy %s", proxy.describe())
        else:
            log.info("Browser egress direct (Chromium's own ECH/DoH)")

        try:
            context = await self._playwright.chromium.launch_persistent_context(**options)
        except Exception as exc:
            if not self._channel:
                raise
            # A detected install can still fail to launch (a partial upgrade, a
            # locked profile). Bundled Chromium is weaker against challenges but
            # is always there, and running is better than not running.
            log.warning("Could not launch %s (%s); falling back to bundled Chromium",
                        self._channel, exc)
            self._channel = None
            options.pop("channel", None)
            context = await self._playwright.chromium.launch_persistent_context(**options)
        context.set_default_navigation_timeout(
            self._settings.navigation_timeout * 1000
        )

        if self._driver.needs_webdriver_patch:
            # Stock Playwright leaves navigator.webdriver set, so hide it. Under
            # patchright this is actively harmful: an init script re-introduces
            # the main-world residue patchright exists to remove, and webdriver
            # already reports false there.
            await context.add_init_script(
                "Object.defineProperty(navigator, 'webdriver', {get: () => undefined});"
            )
        return context

    async def _read_user_agent(self, context: BrowserContext) -> str:
        # Uses the keeper rather than a throwaway page: opening and closing one
        # here is what can drop the window count to zero and quit the browser.
        page = self._keeper or (context.pages[0] if context.pages else None)
        if page is not None:
            return await page.evaluate("() => navigator.userAgent")
        page = await context.new_page()
        try:
            return await page.evaluate("() => navigator.userAgent")
        finally:
            await page.close()

    async def _close_context(self) -> None:
        if self._context is not None and not self._attached:
            try:
                await self._context.close()
            except Exception:  # pragma: no cover - best effort teardown
                log.debug("Error closing browser context", exc_info=True)
        elif self._attached:
            # Someone else's browser and someone else's tabs. Dropping the
            # driver connection detaches; closing would shut their window.
            log.debug("Detaching from the external browser without closing it")
        self._context = None
        self._browser = None
        self._keeper = None

    async def close(self) -> None:
        await self._close_context()
        if self._playwright is not None:
            try:
                await self._playwright.stop()
            except Exception:  # pragma: no cover
                log.debug("Error stopping Playwright", exc_info=True)
            self._playwright = None
        await self._display.stop()

    @property
    def user_agent(self) -> str:
        return self._user_agent or DEFAULT_UA

    @property
    def running(self) -> bool:
        return self._context is not None

    # -------------------------------------------------------------- sessions

    def _lock_for(self, host: str) -> asyncio.Lock:
        return self._solve_locks.setdefault(host, asyncio.Lock())

    async def load_persisted(self, host: str) -> HostSession | None:
        """Restore a previously harvested session from SQLite."""
        if self._db is None:
            return None
        record = await self._db.load_session(host)
        if not record:
            return None
        session = HostSession(
            host=host,
            cookies={c["name"]: c["value"] for c in record["cookies"]},
            user_agent=record["user_agent"],
            solved_at=record["updated_at"],
        )
        self._sessions[host] = session
        return session

    async def peek_session(self, url: str) -> HostSession | None:
        """Return a session already held for ``url``'s host, or ``None``.

        The passive counterpart to :meth:`get_session`, for callers that want
        whatever credentials exist but must not provoke a challenge solve. The
        bulk downloader is exactly that caller: most image hosts have no bot
        check at all, and solving one speculatively means driving a browser to
        an image URL on every CDN a series happens to use.
        """
        host = urlparse(url).netloc
        return self._sessions.get(host) or await self.load_persisted(host)

    async def get_session(self, url: str, *, force: bool = False) -> HostSession:
        """Return a usable session for ``url``, solving the challenge if needed."""
        host = urlparse(url).netloc
        if not force:
            session = self._sessions.get(host) or await self.load_persisted(host)
            # A manual session is the user's explicit override: never discard it
            # behind their back, only on an explicit force-refresh.
            if session and (session.manual or session.cookies):
                return session

        async with self._lock_for(host):
            # Another worker may have solved it while we waited on the lock.
            existing = self._sessions.get(host)
            if existing and not force and existing.cookies:
                return existing
            return await self._solve(url)

    async def refresh(self, url: str) -> HostSession:
        """Force a re-solve, e.g. after a mid-download 403."""
        host = urlparse(url).netloc
        current = self._sessions.get(host)
        if current and current.manual:
            # A pasted cookie has gone stale; the browser cannot fix it because
            # clearance is IP-bound. Surface it rather than silently looping.
            raise ChallengeError(
                f"The manually supplied session for {host} was rejected. "
                "Paste a fresh cf_clearance cookie and User-Agent in Settings."
            )
        return await self.get_session(url, force=True)

    def set_manual_session(self, url: str, cookie_string: str, user_agent: str) -> HostSession:
        """Install a session copied out of the user's own browser.

        The last resort, for when Cloudflare hard-blocks the whole address range
        the container sits in — which no amount of browser realism fixes.
        """
        host = urlparse(url).netloc or url
        cookies: dict[str, str] = {}
        for part in cookie_string.split(";"):
            name, sep, value = part.strip().partition("=")
            if sep and name:
                cookies[name.strip()] = value.strip()
        if not cookies:
            raise ValueError("No cookies parsed from the supplied string")

        session = HostSession(
            host=host,
            cookies=cookies,
            user_agent=user_agent.strip() or self.user_agent,
            solved_at=time.time(),
            manual=True,
        )
        self._sessions[host] = session
        log.info("Installed manual session for %s (%d cookies)", host, len(cookies))
        return session

    def get_cached(self, url: str) -> HostSession | None:
        return self._sessions.get(urlparse(url).netloc)

    # ------------------------------------------------------------ challenges

    async def _solve(self, url: str) -> HostSession:
        """Solve for ``url``, retrying and escalating before giving up."""
        host = urlparse(url).netloc
        attempts = max(1, self._settings.challenge_attempts)
        last: Exception | None = None

        for attempt in range(1, attempts + 1):
            try:
                return await self._solve_once(url, host, attempt)
            except ChallengeError as exc:
                last = exc
                log.warning("Challenge attempt %d/%d failed for %s: %s",
                            attempt, attempts, host, exc)
                if attempt < attempts:
                    if self._can_escalate():
                        await self._escalate_to_headful()
                    # A fresh challenge, not a replay of the failed one.
                    await self._clear_host_cookies(host)
                    await asyncio.sleep(2.0)

        raise ChallengeError(
            f"Could not clear the challenge for {host} after {attempts} attempts"
            f"{' (including a headful retry)' if self._escalated else ''}. "
            "Cloudflare may be blocking this address range outright. Paste a "
            "cf_clearance cookie and User-Agent from your own browser in Settings."
        ) from last

    async def _solve_once(self, url: str, host: str, attempt: int) -> HostSession:
        page = await self._new_page()
        try:
            log.info("Solving challenge for %s (attempt %d, headless=%s)",
                     host, attempt, self._headless)
            await page.goto(url, wait_until="domcontentloaded")
            # Only the cookie is needed here; the downloader fetches its own
            # pages over HTTP once it has one.
            await self._wait_for_clearance(page, host, require_content=False)
            session = await self._harvest(page.context, host)
        finally:
            await page.close()

        # No cookies is not a failure. _wait_for_clearance already raises if the
        # challenge is still up, so reaching here means the page is genuinely
        # loadable — and a site with no bot check sets nothing at all.
        if not session.cookies:
            log.debug("%s set no cookies; proceeding without any", host)

        self._sessions[host] = session
        if self._db is not None:
            await self._db.save_session(
                host,
                [{"name": k, "value": v} for k, v in session.cookies.items()],
                session.user_agent,
            )
        log.info("Session ready for %s (clearance=%s)", host, session.has_clearance)
        return session

    def _can_ask_user(self) -> bool:
        """Whether there is a window a person could actually click in.

        Asking for help from a headless browser would just stall for the whole
        assisted timeout with nothing on screen to act on.
        """
        if not self._settings.assisted_solve:
            return False
        return self._attached or not self._headless

    def _can_escalate(self) -> bool:
        """Whether moving to a headful browser is still worth trying.

        Only under ``headless: auto``. An explicit ``headless: true`` is an
        operator decision, not a default to be overridden.
        """
        return self._headless and self._settings.headless_is_auto and not self._escalated

    async def _escalate_to_headful(self) -> None:
        """Relaunch headful, obtaining a virtual display if needed.

        In-flight browser work is cancelled by this; the queue retries such
        chapters. Image downloads are unaffected — they run over HTTP, not
        through the browser.
        """
        async with self._launch_lock:
            if not self._headless or self._escalated:
                return
            self._escalated = True

            display = await self._acquire_display()
            if display is None:
                log.warning(
                    "Cannot escalate to a headful browser - no display. "
                    "In a container: apt-get install -y xvfb"
                )
                return

            log.info("Escalating to a headful browser (DISPLAY=%s)", display)
            await self._close_context()
            self._headless = False
            await self._open_context()

    async def _wait_for_clearance(
        self, page: Page, host: str | None = None, *, require_content: bool = True
    ) -> None:
        """Work the page until the challenge is done, or patience runs out.

        ``require_content=False`` returns as soon as a fresh ``cf_clearance``
        cookie is issued, which is all :meth:`_solve` needs — the parallel HTTP
        downloader wants the cookie, not this page's HTML.

        Callers that need the *document* must leave it True. Cloudflare stages
        challenges: clearing one can redirect to another interstitial, and each
        stage may present its own widget. Returning on the first cookie hands
        back stage two's HTML, so the loop keeps going — clicking as needed —
        until the page is genuinely no longer a challenge.
        """
        host = host or urlparse(page.url).netloc
        started = time.monotonic()
        automatic = self._settings.challenge_timeout

        # Interactive Turnstile validates that input came from the operating
        # system, so automation cannot pass it however convincing the browser
        # is. When there is a window a person can actually click in, give
        # automation its usual turn and then simply wait for them, rather than
        # failing at a challenge that is one click from being done.
        assisted = self._can_ask_user()
        deadline = started + (
            max(automatic, self._settings.assisted_timeout) if assisted else automatic
        )

        # Cloudflare re-challenges an already-cleared session whenever it feels
        # like it, and issues a *replacement* cookie when that challenge passes.
        # So the test is not "is a cf_clearance cookie present" - one from an
        # earlier solve usually is - but "has it changed since we got here".
        # Without this, a stale cookie makes every re-challenge look instantly
        # solved and the interstitial gets returned as though it were the page.
        initial_clearance = await self._clearance_value(host)

        try:
            await self._poll_until_cleared(
                page, host, deadline, started, automatic, assisted,
                initial_clearance, require_content,
            )
        finally:
            # Whether it cleared, timed out or blew up, we are no longer
            # asking anything of the user.
            self._awaiting_user = None

    async def _poll_until_cleared(
        self, page, host, deadline, started, automatic, assisted,
        initial_clearance, require_content,
    ) -> None:
        clicks = 0
        last_click = 0.0

        while time.monotonic() < deadline:
            try:
                title = await page.title()
                content = await page.content()
            except Exception:
                # Navigating away mid-poll invalidates the frame; retry shortly.
                await asyncio.sleep(1.0)
                continue

            if not is_challenge(content, title):
                return

            if not require_content:
                current = await self._clearance_value(host)
                if current is not None and current != initial_clearance:
                    # Freshly issued clearance. Let the redirect land so the
                    # cookie jar is complete, then hand it over.
                    await self._settle_after_clearance(page, deadline)
                    return

            now = time.monotonic()
            # >= so that challenge_timeout: 0 means "skip automation, ask me
            # straight away" rather than depending on clock resolution.
            if assisted and self._awaiting_user is None and now - started >= automatic:
                # Automation has had its turn and lost. Hand over.
                self._awaiting_user = host
                log.warning(
                    "Cloudflare needs a person for %s. Complete the check in the "
                    "browser window that just opened; waiting up to %.0fs.",
                    host, self._settings.assisted_timeout,
                )
                try:
                    await page.bring_to_front()
                except Exception:
                    log.debug("Could not raise the window", exc_info=True)

            if (
                self._settings.challenge_click
                and clicks < MAX_CLICKS
                and now - last_click >= CLICK_INTERVAL
                # Never fake a click when a person could make a real one.
                #
                # Turnstile marks synthetic events untrusted, and a session that
                # fails that way is looped permanently - reload, re-verify,
                # reload - so a genuine click afterwards cannot rescue it. Our
                # "help" would spend the user's session before they touch it.
                # Unattended, a synthetic click is the only chance and measurably
                # better than none; attended, it is strictly harmful.
                and not assisted
            ):
                last_click = now
                if await self._click_challenge(page):
                    clicks += 1
                    log.info("Clicked the Turnstile checkbox (%d)", clicks)

            await asyncio.sleep(1.0)

        if assisted:
            raise ChallengeError(
                f"Nobody completed the check for {host} within "
                f"{self._settings.assisted_timeout:.0f}s. Look for the browser "
                "window, finish the check there, and try again."
            )
        raise ChallengeError(
            f"Challenge did not clear within "
            f"{self._settings.challenge_timeout:.0f}s for {page.url}"
        )

    async def _settle_after_clearance(self, page: Page, deadline: float) -> None:
        """Wait briefly for the post-challenge redirect to land.

        Bounded, and never fatal: the clearance cookie is already in hand, so
        the worst case is that a caller reloads the page itself.
        """
        limit = min(deadline, time.monotonic() + CLEARANCE_SETTLE)
        while time.monotonic() < limit:
            try:
                if not is_challenge(await page.content(), await page.title()):
                    return
            except Exception:
                pass  # navigating away invalidates the frame; that is progress
            await asyncio.sleep(0.5)

    async def _click_challenge(self, page: Page) -> bool:
        """Click the Turnstile checkbox. Returns True if a click was issued.

        The checkbox cannot be reached with a selector: it lives in a closed
        shadow root inside a cross-origin iframe. What *is* reachable is the
        iframe element in the host document, so we take its bounding box and
        click a fixed offset into it with the mouse — the same coordinates a
        person's cursor would land on.
        """
        try:
            box = await self._locate_widget(page)
            if box is None:
                return False
            if not self._headless:
                # A background window receives no real input focus, and the
                # widget refuses to activate without it.
                await page.bring_to_front()
            await self._human_click(page, *box)
            return True
        except Exception:
            log.debug("Turnstile click attempt failed", exc_info=True)
            return False

    async def _locate_widget(self, page: Page) -> tuple[float, float] | None:
        """Screen coordinates of the challenge checkbox, if one is on screen."""
        for frame_el in await page.query_selector_all("iframe"):
            src = (await frame_el.get_attribute("src")) or ""
            title = (await frame_el.get_attribute("title")) or ""
            if CHALLENGE_FRAME_HOST not in src and "cloudflare" not in title.lower():
                continue
            box = await frame_el.bounding_box()
            if box and box["width"] > 0 and box["height"] > 0:
                return (box["x"] + CHECKBOX_OFFSET_X, box["y"] + box["height"] / 2)

        # No iframe yet (it is injected late) - aim at the placeholder instead.
        for selector in WIDGET_SELECTORS:
            element = await page.query_selector(selector)
            if element is None:
                continue
            box = await element.bounding_box()
            if box and box["width"] > 0 and box["height"] > 0:
                # Placeholders can be tall containers; the widget sits at the
                # top of one, so clamp rather than aiming at the true centre.
                offset_y = min(box["height"] / 2, 32.0)
                return (box["x"] + CHECKBOX_OFFSET_X, box["y"] + offset_y)
        return None

    async def _human_click(self, page: Page, x: float, y: float) -> None:
        """Move the mouse there in steps, then click with a realistic dwell.

        Turnstile watches for pointer movement preceding the click. A cursor
        that teleports to the exact centre of the checkbox and clicks in the
        same millisecond is a signature, not a person.
        """
        steps = random.randint(8, 14)
        start_x = x - random.uniform(80, 180)
        start_y = y - random.uniform(40, 120)
        await page.mouse.move(start_x, start_y)
        for step in range(1, steps + 1):
            ratio = step / steps
            # Ease-out, so the pointer decelerates into the target.
            eased = 1 - (1 - ratio) ** 3
            await page.mouse.move(
                start_x + (x - start_x) * eased + random.uniform(-1.5, 1.5),
                start_y + (y - start_y) * eased + random.uniform(-1.5, 1.5),
            )
            await asyncio.sleep(random.uniform(0.008, 0.025))

        await page.mouse.move(x, y)
        await asyncio.sleep(random.uniform(0.05, 0.15))
        await page.mouse.down()
        await asyncio.sleep(random.uniform(0.04, 0.11))
        await page.mouse.up()

    async def _clearance_value(self, host: str) -> str | None:
        """Current ``cf_clearance`` value for ``host``, if any.

        The *value* matters, not just presence: a re-challenge is only passed
        once Cloudflare replaces the cookie it issued last time.
        """
        if self._context is None:
            return None
        try:
            cookies = await self._context.cookies()
        except Exception:  # pragma: no cover - context torn down mid-poll
            return None
        for cookie in cookies:
            if cookie.get("name") != "cf_clearance":
                continue
            if host.endswith(str(cookie.get("domain", "")).lstrip(".")):
                return str(cookie.get("value", ""))
        return None

    async def _has_clearance(self, host: str) -> bool:
        return await self._clearance_value(host) is not None

    async def _clear_host_cookies(self, host: str) -> None:
        """Drop a host's cookies so the next attempt gets a fresh challenge.

        Without this, Cloudflare replays the same failed ``cf_chl`` state and
        every retry fails identically.
        """
        if self._context is None:
            return
        try:
            await self._context.clear_cookies(domain=host)
        except TypeError:  # pragma: no cover - older driver without the filter
            await self._context.clear_cookies()
        except Exception:  # pragma: no cover
            log.debug("Could not clear cookies for %s", host, exc_info=True)

    async def _harvest(self, context: BrowserContext, host: str) -> HostSession:
        raw = await context.cookies()
        cookies = {
            c["name"]: c["value"]
            for c in raw
            if host.endswith(str(c.get("domain", "")).lstrip("."))
        }
        return HostSession(
            host=host,
            cookies=cookies,
            user_agent=self.user_agent,
            solved_at=time.time(),
        )

    # ---------------------------------------------------------- page fetching

    async def fetch_html(
        self,
        url: str,
        *,
        referer: str | None = None,
        wait_for: str | None = None,
        wait_ms: int = 0,
        scroll_for: str | None = None,
        wait_timeout: float | None = None,
    ) -> str:
        """Render a page in the browser and return its HTML.

        Used for series and chapter pages, which may be challenged at any time
        and (on some installs) build their content with JavaScript.

        ``wait_for`` is a CSS selector to wait for before reading the document,
        and ``wait_ms`` a bounded settle delay. Both default to off, so every
        existing adapter keeps today's behaviour and today's speed — only the
        sites that inject content after ``domcontentloaded`` pay for the wait.

        ``scroll_for`` is for the readers that mount their content as it
        scrolls into view: the document is scrolled until that selector stops
        gaining matches. Off by default, and it costs one scroll on a page that
        was already complete. Without it such a reader hands back whatever
        happened to be on screen, which parses and packages perfectly and is
        simply missing most of the chapter.
        """
        page = await self._new_page()
        try:
            # Passed to goto() rather than set as an extra HTTP header:
            # overriding headers is fingerprint injection, while goto's referer
            # is the ordinary one a real navigation would carry.
            content = await self._load_cleared(
                page, url, referer=referer, wait_for=wait_for, wait_ms=wait_ms,
                scroll_for=scroll_for, wait_timeout=wait_timeout,
            )

            host = urlparse(url).netloc
            self._sessions[host] = await self._harvest(page.context, host)
            return content
        finally:
            await page.close()

    async def fetch_html_after_click(
        self,
        url: str,
        *,
        click_texts: tuple[str, ...],
        wait_for: str | None = None,
        consent_texts: tuple[str, ...] = (),
        referer: str | None = None,
    ) -> str:
        """Render a page, click one named action, then return the updated DOM.

        This is for legitimate download pages that create their file link only
        after an ordinary browser interaction. Consent text is explicit at the
        call site so unrelated adapters never accept a site's cookie prompt.
        """
        page = await self._new_page()
        try:
            content = await self._load_cleared(page, url, referer=referer)

            for text in consent_texts:
                locator = page.get_by_text(text, exact=True)
                if await locator.count():
                    try:
                        await locator.last.click(timeout=2_000)
                        break
                    except Exception:
                        log.debug(
                            "Could not click consent text %r on %s",
                            text, url, exc_info=True,
                        )

            clicked = False
            for text in click_texts:
                locator = page.get_by_text(text, exact=True)
                for index in range(await locator.count() - 1, -1, -1):
                    try:
                        await locator.nth(index).click(timeout=5_000)
                        clicked = True
                        break
                    except Exception:
                        log.debug(
                            "Could not click action text %r on %s",
                            text, url, exc_info=True,
                        )
                if clicked:
                    break

            if clicked:
                content = await self._settled_content(page, wait_for, 0)
            else:
                log.warning("None of %r was clickable on %s", click_texts, url)

            host = urlparse(url).netloc
            self._sessions[host] = await self._harvest(page.context, host)
            return content
        finally:
            await page.close()

    async def _load_cleared(
        self,
        page: Page,
        url: str,
        *,
        referer: str | None = None,
        wait_for: str | None = None,
        wait_ms: int = 0,
        scroll_for: str | None = None,
        wait_timeout: float | None = None,
    ) -> str:
        """Navigate to ``url`` and return the real document, not a challenge.

        Cloudflare re-challenges an established session whenever it likes, and
        the retry matters: once clearance is held, simply requesting the page
        again returns the actual content. Without this the caller silently gets
        interstitial HTML, and every downstream parse fails for no visible
        reason — which looks like a broken adapter, not a blocked request.
        """
        host = urlparse(url).netloc
        for attempt in range(1, PAGE_LOAD_ROUNDS + 1):
            await page.goto(url, wait_until="domcontentloaded", referer=referer)
            content = await self._settled_content(
                page, wait_for, wait_ms, scroll_for, wait_timeout)

            # Some sites answer with a shell that moves you on via meta refresh
            # or script. goto() returns once that shell is parsed, so without a
            # second look the adapter parses "Redirecting..." and finds nothing.
            if looks_like_redirect(content, await page.title()):
                log.info("%s served a redirect shell; waiting for it to land", url)
                await page.wait_for_timeout(REDIRECT_SETTLE_MS)
                content = await self._settled_content(
                    page, wait_for, wait_ms, scroll_for, wait_timeout)

            if not is_challenge(content, await page.title()):
                return content

            await self._wait_for_clearance(page, host, require_content=True)
            content = await self._settled_content(page, wait_for, wait_ms)
            if not is_challenge(content, await page.title()):
                return content
            log.info("%s still challenged after round %d; re-requesting",
                     url, attempt)

        raise ChallengeError(
            f"{url} kept returning a Cloudflare challenge after "
            f"{PAGE_LOAD_ROUNDS} attempts"
        )

    async def _settled_content(
        self, page: Page, wait_for: str | None, wait_ms: int,
        scroll_for: str | None = None, wait_timeout: float | None = None,
    ) -> str:
        """Read the document, optionally after content has been injected.

        Neither wait is fatal. A selector that never appears means the page did
        not have that content — the adapter's own parse error says far more than
        a timeout here would, and a challenge page will never carry the
        selector anyway.

        ``wait_timeout`` overrides the configured one for this call. It exists
        for the case where the selector's *absence* is a real answer rather
        than a fault — a search whose results legitimately do not exist — and
        the caller would otherwise pay the full timeout to learn "nothing
        found". Measured on riwayatarab: an unanswerable query cost **12.2s**
        against 1.0s for a site that settles quickly, and in a thirteen-site
        book fan-out that one site pushed the whole search to its ceiling.
        """
        limit = self._settings.wait_timeout if wait_timeout is None else wait_timeout
        matched = False
        if wait_for:
            try:
                await page.wait_for_selector(wait_for, timeout=limit * 1000)
                matched = True
            except Exception:
                # Warn, not debug: this costs real seconds on every page it
                # happens to, and it used to do so entirely silently.
                log.warning("Selector %r did not appear within %.0fs on %s",
                            wait_for, limit, page.url)
        # The selector arriving *is* the signal, so the settle delay is only
        # for pages that had none or missed. Paying it anyway cost 1.2s on
        # every page of a 24-page chapter list, for nothing.
        if wait_ms and not matched:
            await page.wait_for_timeout(wait_ms)
        if scroll_for:
            await self._scroll_until_settled(page, scroll_for)
        return await page.content()

    async def _scroll_until_settled(self, page: Page, selector: str) -> None:
        """Scroll to the end of a lazily-built list, then stop.

        A reader that mounts its pages as they scroll into view hands
        ``page.content()`` only what has been reached so far, and the result
        parses perfectly, packs into a valid archive, and is *wrong*.
        Measured on comix.to 2026-09-08: Attack on Titan chapter 1 answered
        **3 images** after the settle delay and **12** after scrolling — a CBZ
        of the first quarter of the chapter, with nothing downstream able to
        tell.

        Stops as soon as a round adds nothing, so a page that was already
        complete pays one scroll and one interval.
        """
        seen = await page.locator(selector).count()
        for _ in range(LAZY_SCROLL_ROUNDS):
            await page.mouse.wheel(0, LAZY_SCROLL_PIXELS)
            await page.wait_for_timeout(LAZY_SCROLL_SETTLE_MS)
            now = await page.locator(selector).count()
            if now == seen:
                break
            seen = now
        else:
            log.warning("Still loading %r after %d scrolls on %s; kept %d",
                        selector, LAZY_SCROLL_ROUNDS, page.url, seen)
        log.info("Lazy list settled at %d matches for %r", seen, selector)

    async def fetch_html_capturing(
        self,
        url: str,
        *,
        url_contains: str,
        referer: str | None = None,
        wait_for: str | None = None,
        wait_ms: int = 0,
    ) -> tuple[str, list[bytes]]:
        """Load a page and keep the API responses it makes along the way.

        For sites whose data is behind a token we cannot mint: the page holds
        its own token and calls its own API, so rather than replay the call we
        read the answer. comix.to's chapter list is exactly this — paginating
        it by reloading the page cost two minutes, while its own first request
        carries the same data.

        Returns the document and the captured bodies, oldest first.
        """
        captured: list[bytes] = []

        def on_response(response) -> None:
            if url_contains not in response.url:
                return

            async def keep() -> None:
                try:
                    captured.append(await response.body())
                except Exception:  # pragma: no cover - body already discarded
                    log.debug("Could not read %s", response.url, exc_info=True)

            # The body must be read while the response is still alive, so the
            # read is scheduled on the loop rather than deferred to the caller.
            asyncio.ensure_future(keep())

        page = await self._new_page()
        page.on("response", on_response)
        try:
            content = await self._load_cleared(
                page, url, referer=referer, wait_for=wait_for, wait_ms=wait_ms,
            )
            host = urlparse(url).netloc
            self._sessions[host] = await self._harvest(page.context, host)
            log.info("Captured %d response(s) matching %r from %s",
                     len(captured), url_contains, url)
            return content, list(captured)
        finally:
            await page.close()

    async def post_form_direct(self, url: str, data: dict, *, referer: str | None = None) -> str:
        """Anonymous HTTP form request, with browser fallback owned by adapters."""
        import httpx

        headers = {"X-Requested-With": "XMLHttpRequest"}
        if referer:
            headers["Referer"] = str(httpx.URL(referer))
        async with self.direct_http_client() as client:
            response = await client.post(url, data=data, headers=headers)
            response.raise_for_status()
            if is_challenge(response.text, status=response.status_code):
                raise RuntimeError("The HTTP form response is a browser challenge")
            return response.text

    def direct_http_client(self):
        """A scoped HTTP session for anonymous multi-request reader protocols.

        The caller owns the async context. Cookies persist within that context,
        never importing an attached browser's authenticated state.
        """
        import httpx

        options = {"timeout": self._settings.request_timeout,
                   "follow_redirects": True,
                   "headers": {"User-Agent": self.user_agent}}
        if self._settings.proxy_config is not None:
            options["proxy"] = self._settings.proxy_config.for_httpx()
        return httpx.AsyncClient(**options)

    async def fetch_json_direct(self, url: str, params=None):
        """GET JSON over plain HTTP, honouring the app's proxy.

        For open APIs that need no browser at all. Driving a tab to reach a
        documented endpoint would be slower and no more capable — the browser
        exists to clear bot checks, and there is nothing here to clear.
        """
        import httpx

        options: dict = {"timeout": 30.0, "follow_redirects": True}
        proxy = self._settings.proxy_config
        if proxy is not None:
            options["proxy"] = proxy.for_httpx()

        async with httpx.AsyncClient(**options) as client:
            response = await client.get(
                url, params=params, headers={"User-Agent": self.user_agent}
            )
            response.raise_for_status()
            return response.json()

    async def fetch_text_direct(self, url: str, *, referer: str | None = None) -> str:
        """GET a document over plain HTTP, honouring the app's proxy.

        The sibling of :meth:`fetch_json_direct`, for sites that server-render
        everything they know: no challenge to clear and no script to run, so a
        browser tab would only add seconds. It also reaches hosts the browser
        cannot, because this path goes through the DPI bypass while the browser
        deliberately does not.
        """
        import httpx

        options: dict = {"timeout": self._settings.request_timeout,
                         "follow_redirects": True}
        proxy = self._settings.proxy_config
        if proxy is not None:
            options["proxy"] = proxy.for_httpx()

        headers = {
            "User-Agent": self.user_agent,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "ar,en-US;q=0.9,en;q=0.8",
        }
        if referer:
            headers["Referer"] = referer

        async with httpx.AsyncClient(**options) as client:
            response = await client.get(url, headers=headers)
            response.raise_for_status()
            return response.text

    async def get_via_page(self, url: str, *, referer: str | None = None) -> str:
        """GET a URL with a same-origin ``fetch`` from inside the page.

        Stronger than :meth:`fetch_bytes`, which issues from the browser's
        request context: that carries cookies but not the ``Referer`` and
        ``Sec-Fetch-*`` headers a real page request sends. comix.to's API
        answers **403** to everything except an in-page fetch, so the request
        has to originate from a document on its own origin — the same reason
        :meth:`post_form` exists for Madara's AJAX.
        """
        page = await self._new_page()
        try:
            parsed = urlparse(url)
            origin = referer or f"{parsed.scheme}://{parsed.netloc}/"
            await self._load_cleared(page, origin)
            return await page.evaluate(
                """
                async (endpoint) => {
                    const res = await fetch(endpoint, {
                        credentials: 'include',
                        headers: {
                            'Accept': 'application/json, text/plain, */*',
                            'X-Requested-With': 'XMLHttpRequest',
                        },
                    });
                    return await res.text();
                }
                """,
                url,
            )
        finally:
            await page.close()

    async def post_form(
        self, url: str, data: dict[str, str], *, referer: str | None = None
    ) -> str:
        """POST a form from inside the browser context.

        Madara's chapter list is an AJAX endpoint. Issuing the request from the
        page itself means it automatically carries the clearance cookie and
        same-origin headers the edge expects.
        """
        page = await self._new_page()
        try:
            origin = referer or f"{urlparse(url).scheme}://{urlparse(url).netloc}/"
            # Must be a cleared page: fetch() from an interstitial inherits its
            # origin state and the AJAX call comes back challenged too.
            await self._load_cleared(page, origin)

            return await page.evaluate(
                """
                async ([endpoint, payload]) => {
                    const body = new URLSearchParams(payload).toString();
                    const res = await fetch(endpoint, {
                        method: 'POST',
                        credentials: 'include',
                        headers: {
                            'Content-Type': 'application/x-www-form-urlencoded; charset=UTF-8',
                            'X-Requested-With': 'XMLHttpRequest',
                        },
                        body,
                    });
                    return await res.text();
                }
                """,
                [url, data],
            )
        finally:
            await page.close()

    async def fetch_bytes(
        self, url: str, *, referer: str | None = None
    ) -> tuple[bytes, str]:
        """Fetch a binary resource through the browser's own network stack.

        The escape hatch for sites where clearance is bound to the client's TLS
        fingerprint as well as its IP and User-Agent. There, a cookie replayed
        from Python is rejected however correct it is, because the handshake
        does not look like a browser's. Issuing the request from the browser
        sidesteps the question: same connection, same fingerprint, same cookies.

        Slower than the HTTP pool, so it is a fallback, not the default path.
        """
        headers = {"Referer": referer} if referer else {}
        context = await self._ensure_context()
        try:
            response = await context.request.get(
                url, headers=headers, timeout=self._settings.request_timeout * 1000
            )
        except Exception as exc:
            # Same one-shot recovery as _new_page: this runs mid-download, when
            # failing outright would abandon a chapter over a closed window.
            if not _is_closed_error(exc) or self._attached:
                raise
            log.warning("Browser was gone when fetching %s; relaunching", url)
            await self._discard_context()
            context = await self._ensure_context()
            response = await context.request.get(
                url, headers=headers, timeout=self._settings.request_timeout * 1000
            )
        try:
            if response.status >= 400:
                raise ChallengeError(f"HTTP {response.status} for {url}")
            body = await response.body()
            content_type = (response.headers or {}).get("content-type", "")
            return body, content_type
        finally:
            await response.dispose()

    def status(self) -> dict:
        """Health snapshot for the API and the Settings view."""
        return {
            "browser_running": self.running,
            "user_agent": self._user_agent,
            "driver": self._driver.name if self._driver else None,
            "stealth": self._driver.stealth if self._driver else None,
            "channel": self._channel or ("chromium" if self._driver else None),
            "attached": self._attached,
            "cdp_endpoint": self._settings.browser_cdp,
            "awaiting_user": self._awaiting_user,
            "headless": self._headless,
            "headless_mode": self._settings.headless,
            "escalated": self._escalated,
            "display": self._display.display,
            "hosts": [
                {
                    "host": host,
                    "has_clearance": session.has_clearance,
                    "manual": session.manual,
                    "cookie_count": len(session.cookies),
                    "age_seconds": round(session.age(), 1),
                }
                for host, session in self._sessions.items()
            ],
        }
