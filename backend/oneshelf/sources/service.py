"""Source service: runs plugin capabilities through Core infrastructure and records passive health."""
from __future__ import annotations

import logging
import sqlite3
import time
from typing import Any

from oneshelf.net.governor import Priority, TrafficGovernor
from oneshelf.net.http import HttpClient, HttpResponse
from oneshelf.net.policy import policy_for_plugin
from oneshelf.plugins.manager import PluginManager
from oneshelf.plugins.package import PluginPackage
from oneshelf.plugins.schema import is_text_reader
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


logger = logging.getLogger(__name__)
HEALTH_EVENT_INTERVAL = 60.0


class SourceService:
    def __init__(self, conn: sqlite3.Connection, plugins: PluginManager, governor: TrafficGovernor,
                 sessions: SessionManager | None, *, dev_test_source: bool = False,
                 dev_hosts: dict[str, tuple[str, int]] | None = None, resolver_backend=None, browser=None,
                 events=None, clock=time.monotonic, ech_doh_url: str | None = None) -> None:
        self.conn = conn
        self.ech_doh_url = ech_doh_url
        self.events = events
        self.clock = clock
        self._health_published: dict[str, tuple[str, float]] = {}
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
            stale = [k for k in self._clients if k[0] == package.id and k[1] != package.sha256]
            for k in stale:
                await self._clients.pop(k).__aexit__(None, None, None)
            policy = self.policy_for(package)
            timeouts = package.source.timeouts
            if package.manifest.network.ech:
                from oneshelf.net.curl_ech import CurlEchClient
                client = CurlEchClient(policy, doh_url=self.ech_doh_url, connect_timeout=timeouts.connect_seconds,
                                       read_timeout=timeouts.read_seconds)
            else:
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
        self._publish_health(package.id, outcome)
        if outcome == "failure":
            # §43: what went wrong, as identifiers and a category — never the response that caused it.
            logger.warning("%s %s failed: %s (plugin %s)", package.id, capability, category, package.version)

    def _publish_health(self, source_id: str, outcome: str) -> None:
        """Tell open clients a source's health may have changed (UI-004): at once when the outcome changes,
        otherwise at most once a minute per source, so a busy search or reader never floods the event channel.
        """
        if self.events is None:
            return
        now = self.clock()
        previous = self._health_published.get(source_id)
        if previous is not None and previous[0] == outcome and now - previous[1] < HEALTH_EVENT_INTERVAL:
            return
        self._health_published[source_id] = (outcome, now)
        self.events.publish("source.health", {"source_id": source_id})

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

    def reads_text(self, plugin_id: str) -> bool:
        """Whether this source's reader yields text units rather than image pages (plugin API 1.2)."""
        try:
            package = self.plugins.load_active(plugin_id)
        except Exception:
            return False
        return is_text_reader(package.recipes.get("reader"))

    def available(self, plugin_id: str) -> bool:
        """Whether the source's plugin is installed and active right now."""
        try:
            self.plugins.load_active(plugin_id)
        except Exception:
            return False
        return True

    def record_outcome(self, plugin_id: str, capability: str, outcome: str, category: str | None) -> None:
        """A health signal from work done outside `run` (a reader page, for instance; §21)."""
        try:
            package = self.plugins.load_active(plugin_id)
        except Exception:
            return
        self._record(package, capability, outcome, category)

    def reads_online(self, plugin_id: str) -> bool:
        """Whether this source can be read without its file: a download-only source cannot."""
        try:
            package = self.plugins.load_active(plugin_id)
        except Exception:
            return False
        return "reader" in package.recipes

    def downloads(self, plugin_id: str) -> bool:
        """Whether this source can hand OneShelf a file for a unit (its `downloads` recipe)."""
        try:
            package = self.plugins.load_active(plugin_id)
        except Exception:
            return False
        return "downloads" in package.recipes

    def searchable_sources(self) -> list[tuple[str, str]]:
        return self.sources_with_capability("search")

    async def run(self, plugin_id: str, capability: str, inputs: dict[str, Any], *,
                  priority: Priority = Priority.INTERACTIVE):
        package, fetcher = await self._fetcher(plugin_id, priority)
        recipe = package.recipes.get(capability)
        if recipe is not None:
            # The core offers context (a track's language, for instance); a source that does not declare
            # an input simply does not receive it, instead of failing the call.
            inputs = {name: value for name, value in inputs.items() if name in recipe.inputs}
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

    async def fetch_resource_to(self, plugin_id: str, url: str, path, *, capability: str,
                                priority: Priority = Priority.MANUAL, max_bytes: int | None = None,
                                headers: dict[str, str] | None = None, resume_from: int = 0,
                                validator: str | None = None):
        """`fetch_resource`, with the body written to `path` instead of held in memory (I-101)."""
        package, fetcher = await self._fetcher(plugin_id, priority)
        recipe = package.recipes.get(capability)
        auth_mode = recipe.request.auth if recipe is not None else "none"
        declared = dict(recipe.resource_headers) if recipe is not None else {}
        declared.update(headers or {})
        response = await fetcher.stream(url, path, capability=capability, auth_mode=auth_mode, max_bytes=max_bytes,
                                        headers=declared or None, resume_from=resume_from, validator=validator)
        if response.status == 429:
            self._record(package, capability, "failure", "rate_limit")
            raise_for_rate_limit(response)
        if response.status in (401, 403) and auth_mode != "none":
            self._auth_failed(plugin_id)
            raise AuthRequired()
        return response

    async def fetch_resource(self, plugin_id: str, url: str, *, capability: str,
                             priority: Priority = Priority.MANUAL, max_bytes: int | None = None,
                             headers: dict[str, str] | None = None) -> HttpResponse:
        """Fetch a resource descriptor URL (images, files) with the capability's session scope."""
        package, fetcher = await self._fetcher(plugin_id, priority)
        recipe = package.recipes.get(capability)
        auth_mode = recipe.request.auth if recipe is not None else "none"
        # A recipe may declare what its own resources need — an image CDN that refuses a request without
        # a Referer, say. The caller still wins, and the transport still owns everything else (§9, §12).
        declared = dict(recipe.resource_headers) if recipe is not None else {}
        declared.update(headers or {})
        response = await fetcher.request(url, capability=capability, auth_mode=auth_mode, max_bytes=max_bytes,
                                         headers=declared or None)
        if response.status == 429:
            self._record(package, capability, "failure", "rate_limit")
            raise_for_rate_limit(response)
        if response.status in (401, 403) and auth_mode != "none":
            self._auth_failed(plugin_id)
            raise AuthRequired()
        return response
