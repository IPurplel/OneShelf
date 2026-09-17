"""Core-owned Chromium for browser retrieval and Use My Session login (Master §9.3, §11, §13; ledger K2).

Every context gets its own egress proxy bound to one plugin's policy. Chromium is prevented from reaching
anything directly: loopback may not bypass the proxy, it cannot resolve host names itself, QUIC and
non-proxied WebRTC UDP are disabled, downloads and service workers are off.
"""
from __future__ import annotations

import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass

from playwright.async_api import Browser, BrowserContext, Playwright, Route, async_playwright

from oneshelf.net.egress_proxy import EgressProxy
from oneshelf.net.policy import EgressPolicy

CHROMIUM_ARGS = [
    "--proxy-bypass-list=<-loopback>",
    "--host-resolver-rules=MAP * ~NOTFOUND , EXCLUDE 127.0.0.1",
    "--disable-quic",
    "--force-webrtc-ip-handling-policy=disable_non_proxied_udp",
    "--webrtc-ip-handling-policy=disable_non_proxied_udp",
    "--disable-background-networking",
    "--disable-component-update",
    "--disable-domain-reliability",
    "--disable-sync",
    "--no-first-run",
    "--no-pings",
    "--disable-features=DnsOverHttps,NetworkPrediction",
]


@dataclass
class BrowserContextHandle:
    context: BrowserContext
    proxy: EgressProxy


async def _scheme_guard(route: Route) -> None:
    if route.request.url.split(":", 1)[0].lower() in ("http", "https"):
        await route.continue_()
    else:
        await route.abort("blockedbyclient")


def _session_storage_script(session_storage: dict[str, dict[str, str]]) -> str:
    return (
        "(() => { const data = " + json.dumps(session_storage) + ";"
        " const values = data[location.origin]; if (!values) return;"
        " for (const [k, v] of Object.entries(values)) { try { if (sessionStorage.getItem(k) === null)"
        " sessionStorage.setItem(k, v); } catch (e) {} } })();"
    )


class BrowserManager:
    def __init__(self, *, headless: bool = True) -> None:
        self.headless = headless
        self._playwright: Playwright | None = None
        self._browser: Browser | None = None

    async def __aenter__(self) -> BrowserManager:
        self._playwright = await async_playwright().start()
        self._browser = await self._playwright.chromium.launch(headless=self.headless, args=CHROMIUM_ARGS)
        return self

    async def __aexit__(self, *exc) -> None:
        if self._browser is not None:
            await self._browser.close()
        if self._playwright is not None:
            await self._playwright.stop()

    @asynccontextmanager
    async def context(self, policy: EgressPolicy, *, resolver_backend=None, storage_state: dict | None = None,
                      session_storage: dict[str, dict[str, str]] | None = None) -> AsyncIterator[BrowserContextHandle]:
        if self._browser is None:
            raise RuntimeError("BrowserManager is not started")
        proxy = await EgressProxy(policy, resolver_backend=resolver_backend).start()
        context = None
        try:
            context = await self._browser.new_context(
                proxy={"server": proxy.server_url, "username": proxy.username, "password": proxy.password,
                       "bypass": "<-loopback>"},
                accept_downloads=False,
                service_workers="block",
                storage_state=storage_state,
                viewport={"width": 1280, "height": 800},
            )
            await context.route("**/*", _scheme_guard)
            if session_storage:
                await context.add_init_script(script=_session_storage_script(session_storage))
            yield BrowserContextHandle(context, proxy)
        finally:
            if context is not None:
                await context.close()
            await proxy.stop()
