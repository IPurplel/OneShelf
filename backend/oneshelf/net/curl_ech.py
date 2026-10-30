"""ECH-aware HTTP client using curl_cffi (Master §11 ECH path; the one K1 exception).

Some networks reset any TLS connection whose plaintext SNI names a source; Encrypted Client Hello hides it.
Python's ssl module cannot send ECH, so this client uses curl_cffi for its BoringSSL build and nothing
else: no browser impersonation, OneShelf's own User-Agent, every request through the Core EgressProxy
under the plugin's egress policy. The ledger K1 unit test holds that line.

The ECH key comes from the source's DNS HTTPS record, looked up through the DNS-over-HTTPS JSON endpoint
the person configures (ONESHELF_ECH_DOH_URL). That lookup is Core name resolution, like the system
resolver, so it does not go through the plugin's egress policy. With no endpoint configured, an ECH
source fails with a message saying so rather than contacting a resolver nobody chose.

Used automatically when a plugin manifest declares ``network.ech: true``.
"""
from __future__ import annotations

import base64
import json
import logging
import time
from urllib.parse import urlencode, urljoin, urlsplit

from curl_cffi import CurlOpt, requests as curl_requests
from multidict import CIMultiDict

from oneshelf.net.egress_proxy import EgressProxy
from oneshelf.net.http import (
    DEFAULT_MAX_BYTES,
    DEFAULT_MAX_REDIRECTS,
    USER_AGENT,
    CookieProvider,
    FetchFailed,
    HttpResponse,
    ResponseTooLarge,
    TooManyRedirects,
)
from oneshelf.net.policy import EgressPolicy

logger = logging.getLogger(__name__)

ECH_CACHE_TTL = 3600
DNS_TYPE_HTTPS = 65


async def _fetch_ech_config(doh_url: str, host: str) -> str | None:
    """The base64 ECHConfigList from the host's DNS HTTPS record, via a DoH JSON API (application/dns-json)."""
    try:
        async with curl_requests.AsyncSession(trust_env=False) as s:
            r = await s.get(f"{doh_url}?{urlencode({'name': host, 'type': 'HTTPS'})}",
                            headers={"Accept": "application/dns-json", "User-Agent": USER_AGENT}, timeout=10)
            data = json.loads(r.content)
            for answer in data.get("Answer", []):
                if answer.get("type") == DNS_TYPE_HTTPS:
                    for part in answer["data"].split():
                        if part.startswith("ech="):
                            value = part[4:]
                            base64.b64decode(value, validate=True)
                            # libcurl's CURLOPT_ECH takes "ecl:<base64>"; a hex list is rejected and the
                            # handshake goes out without ECH, which the network then resets.
                            return value
    except Exception as exc:
        logger.warning("failed to fetch ECH config for %s: %s", host, exc)
    return None


def _secure_redirect(policy: EgressPolicy, current: str, location: str) -> str:
    resolved = urljoin(current, location)
    policy.check_url(resolved)
    return resolved


class CurlEchClient:
    """HTTP client with ECH support, compatible with HttpClient's fetch interface (no stream_to: no downloads)."""

    def __init__(self, policy: EgressPolicy, *, doh_url: str | None, connect_timeout: float = 10,
                 read_timeout: float = 30) -> None:
        if doh_url is not None and urlsplit(doh_url).scheme != "https":
            raise ValueError("ONESHELF_ECH_DOH_URL must be an https:// DNS-over-HTTPS JSON endpoint")
        self.policy = policy
        self.doh_url = doh_url
        self._connect_timeout = connect_timeout
        self._read_timeout = read_timeout
        self._proxy: EgressProxy | None = None
        self._ech_configs: dict[str, tuple[str, float]] = {}

    async def __aenter__(self) -> CurlEchClient:
        self._proxy = await EgressProxy(self.policy).start()
        return self

    async def __aexit__(self, *exc) -> None:
        if self._proxy is not None:
            await self._proxy.stop()
            self._proxy = None

    async def _ech_config(self, host: str) -> str | None:
        cached = self._ech_configs.get(host)
        if cached is not None and time.monotonic() - cached[1] < ECH_CACHE_TTL:
            return cached[0]
        if self.doh_url is None:
            raise FetchFailed("this source needs Encrypted Client Hello: set ONESHELF_ECH_DOH_URL to a "
                              "DNS-over-HTTPS JSON endpoint")
        config = await _fetch_ech_config(self.doh_url, host)
        if config is None:
            self._ech_configs.pop(host, None)
        else:
            self._ech_configs[host] = (config, time.monotonic())
        return config

    async def _do_request(self, url: str, *, method: str, headers: dict[str, str] | None,
                          data: dict[str, str] | None) -> curl_requests.Response:
        if self._proxy is None:
            raise RuntimeError("CurlEchClient must be used as an async context manager")
        target = self.policy.check_url(url)
        ech_config = await self._ech_config(target.host)
        if not ech_config:
            # Without ECH the handshake would name the host in plaintext, which is exactly what fails.
            raise FetchFailed(f"no ECH key published for {target.host}")
        curl_options = {CurlOpt.ECH: f"ecl:{ech_config}"}
        request_headers = {"User-Agent": USER_AGENT, **(headers or {})}
        async with curl_requests.AsyncSession(
            curl_options=curl_options, trust_env=False
        ) as session:
            try:
                response = await session.request(
                    method, url,
                    headers=request_headers,
                    data=data,
                    # OneShelf's own TLS fingerprint and User-Agent; no browser is mimicked (ledger K1).
                    verify=True,
                    allow_redirects=False,
                    timeout=self._connect_timeout + self._read_timeout,
                    proxy=self._proxy.server_url,
                    proxy_auth=(self._proxy.username, self._proxy.password),
                )
            except Exception as exc:
                # Cloudflare rotates ECH keys; a stale config fails the handshake, so fetch a fresh one next time.
                self._ech_configs.pop(target.host, None)
                raise FetchFailed(f"ECH transport error: {exc}") from exc
        return response

    async def fetch(
        self,
        url: str,
        *,
        method: str = "GET",
        headers: dict[str, str] | None = None,
        data: dict[str, str] | None = None,
        max_bytes: int = DEFAULT_MAX_BYTES,
        max_redirects: int = DEFAULT_MAX_REDIRECTS,
        cookie_provider: CookieProvider | None = None,
    ) -> HttpResponse:
        redirects: list[str] = []
        current, current_method, current_data = url, method, data

        for _hop in range(max_redirects + 1):
            target = self.policy.check_url(current)
            req_headers = dict(headers or {})
            if cookie_provider:
                cookie = cookie_provider(target)
                if cookie:
                    req_headers["Cookie"] = cookie

            response = await self._do_request(current, method=current_method,
                                              headers=req_headers, data=current_data)
            location = response.headers.get("Location")
            if response.status_code in (301, 302, 303, 307, 308) and location:
                redirects.append(current)
                current = _secure_redirect(self.policy, current, location)
                if response.status_code == 303 or (response.status_code in (301, 302) and current_method == "POST"):
                    current_method, current_data = "GET", None
                continue

            body = response.content
            if len(body) > max_bytes:
                raise ResponseTooLarge(f"response exceeds {max_bytes} bytes")
            resp_headers = CIMultiDict()
            for key, value in response.headers.items():
                resp_headers.add(key, value)
            return HttpResponse(url=current, status=response.status_code,
                                headers=resp_headers, body=body, redirects=redirects)

        raise TooManyRedirects(f"more than {max_redirects} redirects")
