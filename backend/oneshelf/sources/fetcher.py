"""Core fetcher used by recipes: governor lease + egress policy + scoped session cookies (Master §11, §13, §15)."""
from __future__ import annotations

import socket
from contextlib import asynccontextmanager
from urllib.parse import urlsplit

from oneshelf.net.governor import Lane, Priority, TrafficGovernor, TrafficShed
from oneshelf.net.http import FetchFailed, HttpClient, HttpResponse
from oneshelf.plugins.package import PluginPackage
from oneshelf.plugins.runtime import FetchedResponse, RateLimited, RecipeRequest, TrafficDeferred, parse_retry_after
from oneshelf.sessions.manager import SessionManager

DEFAULT_RETRY_AFTER = 60.0


def outcome_for_status(status: int) -> str:
    """How a host's answer counts for the governor's ban protection (net/governor.py)."""
    if status in (429, 503):
        return "throttled"
    if status == 403:
        return "refused"
    if status in (404, 410):
        return "not_found"
    if status >= 500:
        return "server_error"
    if status >= 400:
        return "client_error"
    return "ok"


class DevHostsResolver:
    """Development-only resolver mapping Test Source hostnames to a local address and port."""

    def __init__(self, hosts: dict[str, tuple[str, int]]) -> None:
        self.hosts = hosts

    async def resolve(self, host: str, port: int = 0, family: int = socket.AF_INET):
        if host not in self.hosts:
            raise OSError(f"unknown development host {host}")
        ip, mapped_port = self.hosts[host]
        return [{"hostname": host, "host": ip, "port": mapped_port, "family": socket.AF_INET, "proto": 0,
                 "flags": socket.AI_NUMERICHOST}]

    async def close(self) -> None:
        pass


class SourceFetcher:
    def __init__(self, package: PluginPackage, client: HttpClient, governor: TrafficGovernor,
                 sessions: SessionManager | None, priority: Priority, browser=None) -> None:
        self.browser = browser
        self.package = package
        self.client = client
        self.governor = governor
        self.sessions = sessions
        self.priority = priority

    @asynccontextmanager
    async def _lease(self, url: str, lane: Lane):
        """The governor's lease for one request, with what the host answered fed back into its backoff."""
        plugin_id = self.package.id
        host = (urlsplit(url).hostname or "*").lower()
        try:
            lease_context = self.governor.acquire(plugin_id, self.priority, kind="http", host=host, lane=lane)
            lease = await lease_context.__aenter__()
        except TrafficShed as exc:
            raise TrafficDeferred(exc.retry_after) from None
        try:
            yield host
        except (FetchFailed, TimeoutError):
            self.governor.observe(plugin_id, host, "transport_error")
            raise
        finally:
            await lease_context.__aexit__(None, None, None)

    def _after(self, host: str, response) -> None:
        plugin_id = self.package.id
        self.governor.observe(plugin_id, host, outcome_for_status(response.status))
        if response.status == 429:
            retry_after = parse_retry_after(response.headers.get("Retry-After"))
            self.governor.set_retry_after(plugin_id, retry_after if retry_after is not None else DEFAULT_RETRY_AFTER)

    async def request(self, url: str, *, capability: str, auth_mode: str, method: str = "GET",
                      headers: dict[str, str] | None = None, form: dict[str, str] | None = None,
                      max_bytes: int | None = None, lane: Lane = "page") -> HttpResponse:
        plugin_id = self.package.id
        auth = self.package.manifest.auth

        def cookies(target):
            if self.sessions is None:
                return None
            return self.sessions.cookie_header(plugin_id, auth, capability=capability, recipe_auth=auth_mode, url=target.url)

        kwargs = {"max_bytes": max_bytes} if max_bytes else {}
        async with self._lease(url, lane) as host:
            response = await self.client.fetch(url, method=method, headers=headers, data=form, cookie_provider=cookies,
                                               **kwargs)
        self._after(host, response)
        set_cookies = response.headers.getall("Set-Cookie", [])
        if self.sessions is not None and set_cookies and auth_mode != "none":
            self.sessions.refresh_cookies(plugin_id, auth, url=response.url, set_cookie_headers=set_cookies)
        return response

    async def stream(self, url: str, path, *, capability: str, auth_mode: str, headers: dict[str, str] | None = None,
                     resume_from: int = 0, validator: str | None = None, max_bytes: int | None = None,
                     lane: Lane = "resource"):
        """Like `request`, but the body goes straight to `path` (Master §16; I-101)."""
        plugin_id = self.package.id
        auth = self.package.manifest.auth

        def cookies(target):
            if self.sessions is None:
                return None
            return self.sessions.cookie_header(plugin_id, auth, capability=capability, recipe_auth=auth_mode, url=target.url)

        kwargs = {"max_bytes": max_bytes} if max_bytes else {}
        async with self._lease(url, lane) as host:
            response = await self.client.stream_to(url, path, resume_from=resume_from, validator=validator,
                                                   headers=headers, cookie_provider=cookies, **kwargs)
        self._after(host, response)
        set_cookies = response.headers.getall("Set-Cookie", [])
        if self.sessions is not None and set_cookies and auth_mode != "none":
            self.sessions.refresh_cookies(plugin_id, auth, url=response.url, set_cookie_headers=set_cookies)
        return response

    async def fetch(self, request: RecipeRequest) -> FetchedResponse:
        if request.fetch == "browser":
            if self.browser is None:
                raise FetchFailed("browser retrieval is not configured")
            return await self.browser.fetch(request)
        response = await self.request(request.url, capability=request.capability, auth_mode=request.auth,
                                      method=request.method, headers=request.headers, form=request.form)
        return FetchedResponse(response.url, response.status, dict(response.headers), response.body)


def raise_for_rate_limit(response: HttpResponse) -> None:
    if response.status == 429:
        raise RateLimited(parse_retry_after(response.headers.get("Retry-After")))
