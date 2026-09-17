"""Use My Session login in a Core-owned, policy-bound browser context (Master §13).

The user logs in personally through a screencast of the isolated context and forwards input events.
OneShelf never reads form values or stores passwords. On completion the captured state (cookies,
localStorage, IndexedDB, sessionStorage) is scoped to the declared session domains, validated with
check_session, and only then atomically replaces the stored session.
"""
from __future__ import annotations

import asyncio
import base64
import re
import time
from contextlib import AsyncExitStack
from typing import TYPE_CHECKING

from oneshelf.domain.ids import new_id
from oneshelf.net.browser import BrowserManager
from oneshelf.net.governor import Priority, TrafficGovernor
from oneshelf.sessions.manager import SessionManager, _origin_allowed, scope_to_session_domains
from oneshelf.sessions.store import SessionState

if TYPE_CHECKING:
    from oneshelf.sources.service import SourceService

MAX_ACTIVE = 2
LOGIN_TTL_SECONDS = 600
MAX_TYPED_CHARS = 512
_KEY = re.compile(r"^[A-Za-z0-9+]{1,32}$")


class LoginError(RuntimeError):
    pass


class LoginSession:
    def __init__(self, controller: LoginController, plugin_id: str) -> None:
        self.id = new_id()
        self.plugin_id = plugin_id
        self.status = "starting"
        self.expires_at = time.monotonic() + LOGIN_TTL_SECONDS
        self.controller = controller
        self.page = None
        self._stack = AsyncExitStack()
        self._frame: bytes | None = None
        self._frame_event = asyncio.Event()

    async def _open(self) -> None:
        service, controller = self.controller.service, self.controller
        package = service.plugins.load_active(self.plugin_id)
        auth = package.manifest.auth
        if auth is None:
            raise LoginError("this source does not support account connection")
        policy = service.policy_for(package)
        await self._stack.enter_async_context(controller.governor.acquire(self.plugin_id, Priority.INTERACTIVE, kind="browser"))
        previous = controller.sessions.stored_state(self.plugin_id)
        reuse = scope_to_session_domains(previous, auth) if previous is not None else None
        handle = await self._stack.enter_async_context(controller.browser.context(
            policy, resolver_backend=service.resolver_for(package, policy),
            storage_state=reuse.storage_state if reuse else None,
            session_storage=reuse.session_storage if reuse else None,
        ))
        self._context = handle.context
        self._auth = auth
        self.page = await handle.context.new_page()
        cdp = await handle.context.new_cdp_session(self.page)

        async def on_frame(params: dict) -> None:
            self._frame = base64.b64decode(params["data"])
            self._frame_event.set()
            try:
                await cdp.send("Page.screencastFrameAck", {"sessionId": params["sessionId"]})
            except Exception:
                pass

        cdp.on("Page.screencastFrame", lambda params: asyncio.ensure_future(on_frame(params)))
        await cdp.send("Page.startScreencast", {"format": "jpeg", "quality": 60, "maxWidth": 1280, "maxHeight": 800})
        await self.page.goto(auth.login_url, wait_until="load")
        self.status = "open"

    def _require_open(self) -> None:
        if self.status != "open":
            raise LoginError(f"login session is {self.status}")
        if time.monotonic() > self.expires_at:
            raise LoginError("login session expired")

    async def frame(self, timeout: float = 5.0) -> bytes:
        self._require_open()
        if self._frame is None:
            await asyncio.wait_for(self._frame_event.wait(), timeout)
        return self._frame

    async def click(self, x: float, y: float) -> None:
        self._require_open()
        if not (0 <= x <= 1280 and 0 <= y <= 800):
            raise LoginError("click outside the login view")
        await self.page.mouse.click(x, y)

    async def type_text(self, text: str) -> None:
        self._require_open()
        if len(text) > MAX_TYPED_CHARS:
            raise LoginError("input too long")
        await self.page.keyboard.type(text)  # never logged or stored

    async def press(self, key: str) -> None:
        self._require_open()
        if not _KEY.match(key):
            raise LoginError("unsupported key")
        await self.page.keyboard.press(key)

    async def scroll(self, dy: float) -> None:
        self._require_open()
        await self.page.mouse.wheel(0, max(-5000.0, min(5000.0, dy)))

    async def complete(self) -> str:
        self._require_open()
        for page in self._context.pages:
            try:  # let an in-flight form submission or redirect settle before capturing state
                await page.wait_for_load_state("networkidle", timeout=3000)
            except Exception:
                pass
        state = await self._context.storage_state(indexed_db=True)
        session_storage: dict[str, dict[str, str]] = {}
        for page in self._context.pages:
            try:
                origin = await page.evaluate("location.origin")
                if _origin_allowed(origin, self._auth):
                    values = await page.evaluate("Object.fromEntries(Object.entries(sessionStorage))")
                    if values:
                        session_storage[origin] = {str(k): str(v) for k, v in values.items()}
            except Exception:
                continue
        candidate = scope_to_session_domains(SessionState(storage_state=state, session_storage=session_storage), self._auth)
        valid = await self.controller.service.validate_candidate(self.plugin_id, candidate)
        if valid is False:
            return "not_logged_in"
        self.controller.sessions.connect(self.plugin_id, candidate)
        await self._close("connected")
        return "connected"

    async def cancel(self) -> None:
        if self.status in ("open", "starting"):
            await self._close("cancelled")

    async def _close(self, status: str) -> None:
        self.status = status
        await self._stack.aclose()
        self.controller._active.pop(self.id, None)


class LoginController:
    def __init__(self, service: SourceService, browser: BrowserManager, sessions: SessionManager,
                 governor: TrafficGovernor) -> None:
        self.service = service
        self.browser = browser
        self.sessions = sessions
        self.governor = governor
        self._active: dict[str, LoginSession] = {}

    async def start(self, plugin_id: str) -> LoginSession:
        for login in list(self._active.values()):
            if time.monotonic() > login.expires_at:
                await login.cancel()
        if len(self._active) >= MAX_ACTIVE:
            raise LoginError("too many login sessions are open")
        login = LoginSession(self, plugin_id)
        self._active[login.id] = login
        try:
            await login._open()
        except BaseException:
            await login._close("failed")
            raise
        return login

    def get(self, login_id: str) -> LoginSession:
        login = self._active.get(login_id)
        if login is None:
            raise LoginError("unknown login session")
        return login
