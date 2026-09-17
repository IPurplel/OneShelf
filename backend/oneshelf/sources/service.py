"""Source service: runs plugin capabilities through Core infrastructure and records passive health."""
from __future__ import annotations

import sqlite3
from typing import Any

from oneshelf.net.governor import Priority, TrafficGovernor
from oneshelf.net.http import HttpClient, HttpResponse
from oneshelf.net.policy import policy_for_plugin
from oneshelf.plugins.manager import PluginManager
from oneshelf.plugins.package import PluginPackage
from oneshelf.plugins.results import ListResult
from oneshelf.plugins.runtime import AuthRequired, CapabilityError, RateLimited, RecipeRuntime
from oneshelf.sessions.manager import SessionManager
from oneshelf.sources.fetcher import DevHostsResolver, SourceFetcher, raise_for_rate_limit
from oneshelf.sources.health import record_signal
from oneshelf.net.policy import TEST_SOURCE_ID
from oneshelf.sessions.manager import cookie_header_from_state
from oneshelf.sessions.store import SessionState
from oneshelf.sources.browser_fetcher import BrowserFetcher


class _CandidateSessions:
    """Session provider for validating a captured login before it replaces the stored session."""

    def __init__(self, session: SessionState) -> None:
        self.session = session

    def cookie_header(self, source_id, auth, *, capability, recipe_auth, url):
        return cookie_header_from_state(self.session, auth, capability=capability, recipe_auth=recipe_auth, url=url)

    def refresh_cookies(self, *args, **kwargs):
        return None


class SourceService:
    def __init__(self, conn: sqlite3.Connection, plugins: PluginManager, governor: TrafficGovernor,
                 sessions: SessionManager | None, *, dev_test_source: bool = False,
                 dev_hosts: dict[str, tuple[str, int]] | None = None, resolver_backend=None, browser=None) -> None:
        self.conn = conn
        self.plugins = plugins
        self.governor = governor
        self.sessions = sessions
        self.dev_test_source = dev_test_source
        self.dev_hosts = dev_hosts or {}
        self.resolver_backend = resolver_backend  # injectable DNS for tests; None = system resolver
        self.browser = browser
        self._clients: dict[tuple[str, str], HttpClient] = {}

    async def __aenter__(self) -> SourceService:
        return self

    async def __aexit__(self, *exc) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        for client in self._clients.values():
            await client.__aexit__(None, None, None)
        self._clients.clear()

    def policy_for(self, package: PluginPackage):
        network = package.manifest.network
        return policy_for_plugin(package.id, domains=list(network.domains), cdn_domains=list(network.cdn_domains),
                                 allow_http=network.allow_http, dev_test_source_enabled=self.dev_test_source)

    def resolver_for(self, package: PluginPackage, policy):
        if policy.dev_loopback_exception and package.id == TEST_SOURCE_ID:
            return DevHostsResolver(self.dev_hosts)
        return self.resolver_backend

    async def _client(self, package: PluginPackage) -> HttpClient:
        key = (package.id, package.sha256)
        if key not in self._clients:
            policy = self.policy_for(package)
            timeouts = package.source.timeouts
            client = HttpClient(policy, resolver_backend=self.resolver_for(package, policy),
                                connect_timeout=timeouts.connect_seconds, read_timeout=timeouts.read_seconds)
            self._clients[key] = await client.__aenter__()
        return self._clients[key]

    async def _fetcher(self, plugin_id: str, priority: Priority) -> tuple[PluginPackage, SourceFetcher]:
        package = self.plugins.load_active(plugin_id)
        limits = package.source.rate_limit
        self.governor.configure_source(plugin_id, concurrency=limits.concurrency,
                                       requests_per_minute=limits.requests_per_minute)
        return package, self._make_fetcher(package, await self._client(package), self.sessions, priority)

    def _make_fetcher(self, package: PluginPackage, client: HttpClient, sessions, priority: Priority) -> SourceFetcher:
        browser_fetcher = None
        if self.browser is not None:
            policy = self.policy_for(package)
            browser_fetcher = BrowserFetcher(package, self.browser, policy, self.resolver_for(package, policy),
                                             self.governor, sessions, priority)
        return SourceFetcher(package, client, self.governor, sessions, priority, browser=browser_fetcher)

    async def validate_candidate(self, plugin_id: str, session: SessionState) -> bool | None:
        """Check a not-yet-stored session with the plugin's check_session capability (None = cannot check)."""
        package = self.plugins.load_active(plugin_id)
        if "check_session" not in package.recipes:
            return None
        candidate = _CandidateSessions(session)
        fetcher = self._make_fetcher(package, await self._client(package), candidate, Priority.INTERACTIVE)
        try:
            result = await RecipeRuntime(package, fetcher).run("check_session", {})
        except CapabilityError:
            return False
        return result.logged_in

    def _record(self, package: PluginPackage, capability: str, outcome: str, category: str | None) -> None:
        record_signal(self.conn, package.id, capability, outcome, category, package.version)

    def _auth_failed(self, plugin_id: str) -> None:
        if self.sessions is not None and self.sessions.state(plugin_id) == "connected":
            self.sessions.mark_needs_reconnect(plugin_id, "source rejected the session")

    def sources_with_capability(self, capability: str) -> list[tuple[str, str]]:
        """Active plugins providing a capability, with their versions (used for cache namespacing)."""
        found = []
        for record in self.plugins.list():
            if record.state != "active":
                continue
            try:
                package = self.plugins.load_active(record.id)
            except Exception:
                continue
            if capability in package.recipes:
                found.append((record.id, package.version))
        return found

    def searchable_sources(self) -> list[tuple[str, str]]:
        return self.sources_with_capability("search")

    async def run(self, plugin_id: str, capability: str, inputs: dict[str, Any], *,
                  priority: Priority = Priority.INTERACTIVE):
        package, fetcher = await self._fetcher(plugin_id, priority)
        try:
            result = await RecipeRuntime(package, fetcher).run(capability, inputs)
        except AuthRequired:
            self._auth_failed(plugin_id)
            self._record(package, capability, "failure", "auth_failure")
            raise
        except RateLimited as exc:
            self._record(package, capability, "failure", "rate_limit")
            raise
        except CapabilityError as exc:
            self._record(package, capability, "failure", exc.category)
            raise
        if isinstance(result, ListResult) and result.evidence.issues:
            categories = [i.category for i in result.evidence.issues]
            failures = [c for c in categories if c != "not_found"]
            if failures:
                self._record(package, capability, "failure", failures[0])
            else:
                self._record(package, capability, "content_missing", "not_found")
        else:
            self._record(package, capability, "success", None)
        return result

    async def fetch_resource(self, plugin_id: str, url: str, *, capability: str,
                             priority: Priority = Priority.MANUAL, max_bytes: int | None = None) -> HttpResponse:
        """Fetch a resource descriptor URL (images, files) with the capability's session scope."""
        package, fetcher = await self._fetcher(plugin_id, priority)
        recipe = package.recipes.get(capability)
        auth_mode = recipe.request.auth if recipe is not None else "none"
        response = await fetcher.request(url, capability=capability, auth_mode=auth_mode, max_bytes=max_bytes)
        if response.status == 429:
            self._record(package, capability, "failure", "rate_limit")
            raise_for_rate_limit(response)
        if response.status in (401, 403) and auth_mode != "none":
            self._auth_failed(plugin_id)
            raise AuthRequired()
        return response
