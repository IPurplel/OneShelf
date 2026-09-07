"""A virtual X display, so a headful browser can run in a headless container.

Headful Chromium clears Cloudflare's interactive challenge markedly more often
than headless does. Headless mode is not merely "a browser without a window":
it takes different code paths for rendering, input and permissions, and those
differences are measurable from JavaScript. Fingerprinting scripts read them.

An LXC container has no X server, so the usual advice is "you can't run headful
there". You can — ``Xvfb`` is a display server that renders into memory and
needs no hardware. Chromium is then genuinely headful; it simply draws into a
framebuffer nobody looks at.

This module is a no-op on Windows and macOS, which have a real display already.
"""

from __future__ import annotations

import asyncio
import logging
import os
import shutil
import sys
from pathlib import Path

log = logging.getLogger(__name__)

X11_SOCKET_DIR = Path("/tmp/.X11-unix")

#: Display numbers to try. :0 is a real user session; stay well clear of it.
DISPLAY_RANGE = range(99, 120)

STARTUP_TIMEOUT = 10.0


def platform_needs_xvfb() -> bool:
    """True on platforms with no display server of their own."""
    return sys.platform.startswith("linux")


def xvfb_available() -> bool:
    return shutil.which("Xvfb") is not None


class VirtualDisplay:
    """Starts and owns an ``Xvfb`` process.

    Idempotent: :meth:`start` returns the existing display if one is already
    usable, and only spawns a server when there is nothing to attach to.
    """

    def __init__(self, width: int = 1366, height: int = 900, depth: int = 24) -> None:
        self._width = width
        self._height = height
        self._depth = depth
        self._process: asyncio.subprocess.Process | None = None
        self._display: str | None = None
        self._owned = False

    @property
    def display(self) -> str | None:
        """The ``DISPLAY`` value in use, or ``None`` if none was obtained."""
        return self._display

    @property
    def running(self) -> bool:
        return self._process is not None and self._process.returncode is None

    async def start(self) -> str | None:
        """Obtain a display. Returns its ``DISPLAY`` value, or ``None``.

        ``None`` means a headful browser is not possible here — the caller
        should stay headless rather than launching into a certain crash.
        """
        if self._display is not None:
            return self._display

        if not platform_needs_xvfb():
            # Windows and macOS draw to a real desktop; nothing to arrange.
            # "native" rather than "" so callers can distinguish "a display
            # exists" from "no display could be obtained", which is None.
            self._display = os.environ.get("DISPLAY") or "native"
            return self._display

        existing = os.environ.get("DISPLAY")
        if existing:
            log.info("Using the existing X display %s", existing)
            self._display = existing
            return existing

        if not xvfb_available():
            log.warning(
                "Cannot run a headful browser: no DISPLAY and Xvfb is not installed. "
                "Install it with: apt-get install -y xvfb"
            )
            return None

        number = self._free_display_number()
        if number is None:
            log.warning("No free X display number in %r", DISPLAY_RANGE)
            return None

        display = f":{number}"
        log.info("Starting Xvfb on %s (%dx%dx%d)",
                 display, self._width, self._height, self._depth)
        self._process = await asyncio.create_subprocess_exec(
            "Xvfb",
            display,
            "-screen", "0", f"{self._width}x{self._height}x{self._depth}",
            # No TCP listener: the socket is local-only, which is both faster
            # and one less thing exposed inside the container.
            "-nolisten", "tcp",
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )

        if not await self._wait_until_ready(number):
            log.warning("Xvfb did not come up on %s", display)
            await self.stop()
            return None

        os.environ["DISPLAY"] = display
        self._display = display
        self._owned = True
        return display

    async def stop(self) -> None:
        if self._process is not None and self._process.returncode is None:
            self._process.terminate()
            try:
                await asyncio.wait_for(self._process.wait(), timeout=5.0)
            except asyncio.TimeoutError:  # pragma: no cover - stubborn server
                self._process.kill()
                await self._process.wait()
        self._process = None
        if self._owned and os.environ.get("DISPLAY") == self._display:
            # Only unset what we set. A caller-supplied DISPLAY is not ours.
            os.environ.pop("DISPLAY", None)
        self._display = None
        self._owned = False

    # ----------------------------------------------------------- internals

    def _free_display_number(self) -> int | None:
        """First display number with no server socket already bound."""
        for number in DISPLAY_RANGE:
            if not (X11_SOCKET_DIR / f"X{number}").exists():
                return number
        return None

    async def _wait_until_ready(self, number: int) -> bool:
        """Poll for the X socket.

        Xvfb forks and returns before the socket exists, so launching Chromium
        immediately after spawn is a race that fails maybe one time in five.
        """
        socket = X11_SOCKET_DIR / f"X{number}"
        deadline = asyncio.get_running_loop().time() + STARTUP_TIMEOUT
        while asyncio.get_running_loop().time() < deadline:
            if self._process is not None and self._process.returncode is not None:
                return False  # died on startup, no point waiting out the clock
            if socket.exists():
                return True
            await asyncio.sleep(0.1)
        return False

    def status(self) -> dict:
        return {
            "display": self._display,
            "managed": self._owned,
            "running": self.running,
        }
