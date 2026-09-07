"""Browser driver selection.

Playwright is trivially detectable. Not through anything the page can see in
the DOM, but through the automation protocol itself: stock Playwright enables
CDP's ``Runtime`` domain to bootstrap its bindings, and injects its init scripts
into the page's main world. Both leave residue a challenge script can look for,
which is why "solve Cloudflare with Playwright" fails no matter how many
``navigator`` properties you paper over.

``patchright`` is a drop-in redistribution of Playwright with those leaks
patched out. Identical API, so it is imported by name and everything else in
this module stays the same. If it is not installed we fall back to stock
Playwright, which still clears the *non-interactive* challenge that most Madara
sites use — the difference only shows up against interactive Turnstile.

The rules for staying quiet under patchright are narrow and easy to violate by
accident, so they are encoded here rather than left to comments:

* **No main-world init scripts.** ``add_init_script`` re-introduces exactly the
  leak patchright removes. Stock Playwright needs one to hide
  ``navigator.webdriver``; patchright already reports ``false`` natively.
* **Persistent context, not ``launch()``.** A throwaway profile with no history
  is itself a signal.
"""

from __future__ import annotations

import importlib
import logging
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

log = logging.getLogger(__name__)

#: Preference order. First importable wins.
DRIVER_NAMES = ("patchright", "playwright")

#: Real installed browsers, best first. Playwright's bundled Chromium is a
#: developer build: unsigned, missing the proprietary codecs a shipped browser
#: has, and carrying a distinct binary fingerprint. A challenge can tell the
#: difference, so drive a browser the user actually has where possible.
CHANNEL_PATHS: dict[str, dict[str, tuple[str, ...]]] = {
    "chrome": {
        "win32": (
            r"C:\Program Files\Google\Chrome\Application\chrome.exe",
            r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
        ),
        "linux": (
            "/usr/bin/google-chrome",
            "/usr/bin/google-chrome-stable",
            "/opt/google/chrome/chrome",
        ),
        "darwin": (
            "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
        ),
    },
    "msedge": {
        "win32": (
            r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
            r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
        ),
        "linux": (
            "/usr/bin/microsoft-edge",
            "/usr/bin/microsoft-edge-stable",
        ),
        "darwin": (
            "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
        ),
    },
}

#: Command names to fall back on when the fixed paths miss (custom installs).
CHANNEL_COMMANDS = {
    "chrome": ("google-chrome", "google-chrome-stable", "chrome"),
    "msedge": ("microsoft-edge", "microsoft-edge-stable"),
}


def _platform_key() -> str:
    if sys.platform.startswith("linux"):
        return "linux"
    if sys.platform == "darwin":
        return "darwin"
    return "win32"


def channel_available(channel: str) -> bool:
    """Whether a real install of ``channel`` exists on this machine."""
    key = _platform_key()
    for candidate in CHANNEL_PATHS.get(channel, {}).get(key, ()):
        if Path(candidate).exists():
            return True
    return any(shutil.which(cmd) for cmd in CHANNEL_COMMANDS.get(channel, ()))


def detect_channel(preference: str = "auto") -> str | None:
    """Resolve which browser to drive.

    Returns a Playwright channel name, or ``None`` for the bundled Chromium.
    ``auto`` picks the best real browser present and falls back to bundled.
    """
    if preference == "chromium":
        return None
    if preference != "auto":
        if channel_available(preference):
            return preference
        log.warning("Browser channel %r is not installed; using bundled Chromium",
                    preference)
        return None

    for channel in ("chrome", "msedge"):
        if channel_available(channel):
            return channel
    return None


@dataclass(frozen=True)
class Driver:
    """A resolved Playwright-compatible driver."""

    name: str
    async_playwright: Callable[[], Any]

    @property
    def stealth(self) -> bool:
        """True when the driver has the CDP leaks patched out."""
        return self.name == "patchright"

    @property
    def needs_webdriver_patch(self) -> bool:
        """True when we must hide ``navigator.webdriver`` ourselves.

        Only stock Playwright does; doing it under patchright would undo the
        very thing that makes patchright work.
        """
        return not self.stealth


def available_drivers() -> list[str]:
    """Driver names that can actually be imported, in preference order."""
    found = []
    for name in DRIVER_NAMES:
        try:
            importlib.import_module(f"{name}.async_api")
        except ImportError:
            continue
        found.append(name)
    return found


def load_driver(prefer_stealth: bool = True) -> Driver:
    """Resolve the best available driver.

    ``prefer_stealth=False`` pins stock Playwright, which is useful for
    reproducing a bug without the patched driver in the picture.
    """
    names = DRIVER_NAMES if prefer_stealth else ("playwright",)
    for name in names:
        try:
            module = importlib.import_module(f"{name}.async_api")
        except ImportError:
            continue
        if name == "playwright" and prefer_stealth:
            log.info(
                "patchright is not installed - falling back to stock Playwright. "
                "Interactive Cloudflare challenges are unlikely to clear. "
                "Install it with: pip install patchright && patchright install chromium"
            )
        return Driver(name=name, async_playwright=module.async_playwright)

    raise RuntimeError(
        "No Playwright-compatible driver installed. "
        "Run: pip install -r requirements.txt && playwright install chromium"
    )


def browser_args(headless: bool) -> list[str]:
    """Chromium flags, tuned for containers and for not standing out.

    Kept deliberately short. Every extra flag is a fingerprint, and the long
    "stealth" flag lists found online mostly make a browser *more* distinctive,
    not less.

    Notably absent: ``--disable-blink-features=AutomationControlled``.
    Patchright adds that itself (its release notes list it under "Command Flags
    Leaks"), so passing it again is redundant.
    """
    args = [
        # Background tabs get their timers throttled to near zero, which stalls
        # the challenge script at exactly the moment it needs to run.
        "--disable-background-timer-throttling",
        "--disable-renderer-backgrounding",
        "--disable-backgrounding-occluded-windows",
    ]

    if _platform_key() == "linux":
        # Container survival flags, and Linux-only on purpose: no desktop
        # browser on Windows or macOS has ever run with --no-sandbox, so
        # sending it there is itself the anomaly we are trying to avoid.
        args += [
            # Containers cap /dev/shm at 64 MB; without this Chromium dies on
            # large pages, surfacing as an unexplained timeout.
            "--disable-dev-shm-usage",
            # Required in an unprivileged LXC, where user namespaces are gone.
            "--no-sandbox",
            "--disable-setuid-sandbox",
        ]

    if headless:
        # Headless has no GPU path worth using and crashes trying. Under Xvfb,
        # Chromium picks SwiftShader by itself and reports a plausible WebGL
        # renderer; forcing --disable-gpu there reports none at all, which is
        # a much louder signal than the one it would hide.
        args.append("--disable-gpu")
    return args
