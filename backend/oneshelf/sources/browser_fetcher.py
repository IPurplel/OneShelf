"""Browser retrieval for recipes that declare fetch: browser (Master §12.1, §14; Meta Prompt G1).

The rendered DOM is returned for normal declarative extraction; screenshots are never used for content.
The browser lease is held for the page lifetime so the governor can preempt background work.
"""
from __future__ import annotations

from oneshelf.net.browser import BrowserManager
from oneshelf.net.governor import Priority, TrafficGovernor
from oneshelf.net.http import FetchFailed
from oneshelf.net.policy import EgressPolicy
from oneshelf.plugins.package import PluginPackage
from oneshelf.plugins.runtime import FetchedResponse, RecipeRequest

PAGE_TIMEOUT_MS = 30_000
SETTLE_TIMEOUT_MS = 3_000


class BrowserFetcher:
    def __init__(self, package: PluginPackage, browser: BrowserManager, policy: EgressPolicy, resolver_backend,
                 governor: TrafficGovernor, sessions, priority: Priority) -> None:
        self.package = package
        self.browser = browser
        self.policy = policy
        self.resolver_backend = resolver_backend
        self.governor = governor
        self.sessions = sessions
        self.priority = priority

    async def fetch(self, request: RecipeRequest) -> FetchedResponse:
        if request.method != "GET":
            raise FetchFailed("browser retrieval supports GET navigation only")
        self.policy.check_url(request.url)
        session = None
        if self.sessions is not None and hasattr(self.sessions, "browser_state"):
            session = self.sessions.browser_state(self.package.id, self.package.manifest.auth,
                                                  capability=request.capability, recipe_auth=request.auth)
        async with self.governor.acquire(self.package.id, self.priority, kind="browser"):
            async with self.browser.context(
                self.policy, resolver_backend=self.resolver_backend,
                storage_state=session.storage_state if session else None,
                session_storage=session.session_storage if session else None,
            ) as handle:
                page = await handle.context.new_page()
                try:
                    response = await page.goto(request.url, wait_until="load", timeout=PAGE_TIMEOUT_MS)
                except Exception as exc:  # net::ERR_* from blocked or failed navigations
                    raise FetchFailed(f"browser navigation failed: {type(exc).__name__}") from exc
                try:
                    await page.wait_for_load_state("networkidle", timeout=SETTLE_TIMEOUT_MS)
                except Exception:
                    pass
                html = await page.content()
                status = response.status if response is not None else 200
                return FetchedResponse(page.url, status, {"Content-Type": "text/html"}, html.encode("utf-8"))
