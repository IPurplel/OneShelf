"""Reviewed Noor ECH transport; all source TLS stays inside Core's policy proxy.

ECH config is public DNS data, kept only in memory. No browser/session cookies are
stored here. curl's callback bounds decoded bytes *during* receipt (not afterwards).
"""
from __future__ import annotations

import asyncio
import base64
import binascii
import json
import re
import time
from urllib.parse import urljoin

from curl_cffi import CurlOpt
from curl_cffi.curl import CURL_WRITEFUNC_ERROR
from curl_cffi.requests import AsyncSession, RequestsError
from multidict import CIMultiDict

from oneshelf.net.egress_proxy import EgressProxy
from oneshelf.net.http import FetchFailed, HttpClient, HttpResponse, ResponseTooLarge, TooManyRedirects
from oneshelf.net.policy import DisallowedTarget, EgressPolicy

HOST = 'www.noor-book.com'
ECH_DNS_URL = 'https://dns.google/resolve?name=www.noor-book.com&type=HTTPS'
MAX_BYTES = 8 * 1024 * 1024
REDIRECTS = {301, 302, 303, 307, 308}
_HOP_HEADERS = {'host', 'content-length', 'connection', 'proxy-authorization', 'proxy-connection',
                'transfer-encoding', 'accept-encoding', 'user-agent'}


def parse_ech_answer(body: bytes) -> tuple[str, int]:
    """Accept only a bounded ECHConfigList for the fixed source HTTPS question."""
    try:
        obj = json.loads(body)
        questions = obj['Question']
        if (obj['Status'] != 0 or len(questions) != 1 or questions[0]['type'] != 65
                or questions[0]['name'].rstrip('.').lower() != HOST):
            raise ValueError('wrong DNS answer')
        for record in obj.get('Answer', [])[:16]:
            if record.get('type') != 65 or record.get('name', '').rstrip('.').lower() != HOST:
                continue
            match = re.search(r'(?:^|\s)ech="?([A-Za-z0-9+/=]+)(?:"|\s|$)', record.get('data', ''))
            ttl = int(record.get('TTL', 0))
            if not match or ttl <= 0:
                continue
            encoded = match.group(1)
            if len(encoded) > 4096:
                continue
            raw = base64.b64decode(encoded, validate=True)
            if len(raw) < 8 or int.from_bytes(raw[:2], 'big') != len(raw) - 2:
                continue
            return encoded, min(ttl, 3600)
    except (ValueError, TypeError, KeyError, AttributeError, binascii.Error):
        pass
    raise FetchFailed('No valid Noor HTTPS ECH configuration')


class EchClient:
    def __init__(self, policy: EgressPolicy, *, resolver_backend=None, timeout: float = 30) -> None:
        self.policy = policy
        self.timeout = timeout
        self._backend = resolver_backend
        self._proxy = EgressProxy(policy, resolver_backend=resolver_backend)
        self._dns = HttpClient(EgressPolicy(domains=('dns.google',)), read_timeout=15)
        self._config: tuple[str, float] | None = None
        self._config_lock = asyncio.Lock()
        self._slots = asyncio.Semaphore(4)
        self._open = False

    async def __aenter__(self):
        try:
            await self._proxy.start()
            await self._dns.__aenter__()
        except BaseException:
            await self.__aexit__(None, None, None)
            raise
        self._open = True
        return self

    async def __aexit__(self, *exc):
        self._open = False
        self._config = None
        try:
            await self._dns.__aexit__(*exc)
        finally:
            try:
                await self._proxy.stop()
            finally:
                if self._backend is None and self._proxy.backend is not None:
                    await self._proxy.backend.close()
                    self._proxy.backend = None

    async def _configuration(self) -> str:
        async with self._config_lock:
            if self._config is None or time.monotonic() >= self._config[1]:
                response = await self._dns.fetch(ECH_DNS_URL, max_bytes=32 * 1024, max_redirects=0)
                if response.status != 200:
                    raise FetchFailed('Noor ECH resolver unavailable')
                encoded, ttl = parse_ech_answer(response.body)
                self._config = (encoded, time.monotonic() + ttl)
            return self._config[0]

    def check_url(self, url: str) -> None:
        target = self.policy.check_url(url)
        if target.host != HOST or target.scheme != 'https' or target.port != 443:
            raise DisallowedTarget('Noor ECH transport requires its fixed HTTPS origin')

    async def fetch(self, url: str, *, method: str = 'GET', headers: dict[str, str] | None = None,
                    data: bytes | None = None, max_bytes: int | None = None,
                    follow_redirects: bool = True, max_redirects: int = 5) -> HttpResponse:
        self.check_url(url)
        if not self._open:
            raise RuntimeError('EchClient requires an async context')
        if method not in ('GET', 'POST', 'HEAD'):
            raise DisallowedTarget('Unsupported Noor HTTP method')
        limit = MAX_BYTES if max_bytes is None else min(MAX_BYTES, max_bytes)
        if limit < 1 or len(data or b'') > 64 * 1024:
            raise ResponseTooLarge('Noor request/response limit exceeded')
        # Browser-scoped Cookie is permitted only for this individual request. curl never stores it.
        clean = {k: v for k, v in (headers or {}).items()
                 if k.lower() not in _HOP_HEADERS and not k.lower().startswith(('sec-ch-ua', 'proxy-'))}
        redirects: list[str] = []
        async with self._slots:
            try:
                async with asyncio.timeout(self.timeout):
                    for hop in range(max_redirects + 1):
                        self.check_url(url)
                        response = await self._request(url, method, clean, data, limit)
                        location = response.headers.get('Location')
                        if not follow_redirects or response.status not in REDIRECTS or not location:
                            response.redirects = redirects
                            return response
                        if hop == max_redirects:
                            raise TooManyRedirects('Noor redirect limit exceeded')
                        url = urljoin(url, location)
                        self.check_url(url)
                        redirects.append(url)
                        if response.status == 303 or response.status in (301, 302) and method == 'POST':
                            method, data = 'GET', None
                            clean = {k: v for k, v in clean.items() if k.lower() != 'content-type'}
            except TimeoutError:
                raise FetchFailed('Noor transport timed out') from None
        raise TooManyRedirects('Noor redirect limit exceeded')

    async def _request(self, url, method, headers, data, limit) -> HttpResponse:
        config = await self._configuration()
        body = bytearray()
        oversized = False

        def receive(chunk):
            nonlocal oversized
            if len(body) + len(chunk) > limit:
                oversized = True
                return CURL_WRITEFUNC_ERROR
            body.extend(chunk)
            return len(chunk)

        # One ephemeral session per request: no cookie jar or reused TLS/config state crosses requests.
        try:
            async with AsyncSession(trust_env=False, max_clients=1,
                                    curl_options={CurlOpt.ECH: 'ecl:' + config}) as session:
                response = await session.request(method, url, headers=headers, data=data,
                    impersonate='chrome', timeout=self.timeout, verify=True, allow_redirects=False,
                    proxy=self._proxy.server_url, proxy_auth=(self._proxy.username, self._proxy.password),
                    discard_cookies=True, content_callback=receive)
        except RequestsError:
            if oversized:
                raise ResponseTooLarge('Noor response exceeds decoded byte limit') from None
            # Do not log curl's URL-bearing exception: reader URLs contain transient source tokens.
            self._config = None
            raise FetchFailed('Noor ECH request failed') from None
        if oversized:
            raise ResponseTooLarge('Noor response exceeds decoded byte limit')
        result_headers = CIMultiDict((k, v) for k, v in response.headers.multi_items() if v is not None)
        return HttpResponse(url, response.status_code, result_headers, bytes(body))
