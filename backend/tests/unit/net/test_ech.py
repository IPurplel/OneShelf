"""Native transport must not weaken the existing source egress boundary."""
import asyncio
import base64
import json
import warnings
from types import SimpleNamespace

import pytest
from multidict import CIMultiDict
from curl_cffi.requests.headers import Headers
from curl_cffi.curl import ffi, lib, _CallbackContext, CURL_WRITEFUNC_ERROR

from oneshelf.net import ech
from oneshelf.net.http import HttpResponse, ResponseTooLarge, FetchFailed
from oneshelf.net.policy import EgressPolicy, DisallowedTarget

URL = 'https://www.noor-book.com/'
CONFIG = base64.b64encode(b'\x00\x06\xfe\x0d\x00\x02xx').decode()


def answer(**changes):
    return {'Status': 0, 'Question': [{'name': 'www.noor-book.com.', 'type': 65}],
            'Answer': [{'name': 'www.noor-book.com.', 'type': 65, 'TTL': 60,
                        'data': '1 . alpn="h2" ech="' + CONFIG + '"'}], **changes}


def test_config_is_bound_to_noor_https_answer_and_expires():
    config, ttl = ech.parse_ech_answer(json.dumps(answer()).encode())
    assert config == CONFIG and ttl == 60


@pytest.mark.parametrize('document', [
    answer(Status=2), answer(Question=[{'name': 'attacker.test.', 'type': 65}]),
    answer(Answer=[{'name': 'attacker.test.', 'type': 65, 'TTL': 60, 'data': '1 . ech="' + CONFIG + '"'}]),
    answer(Answer=[{'name': 'www.noor-book.com.', 'type': 1, 'TTL': 60, 'data': '1 . ech="' + CONFIG + '"'}]),
    answer(Answer=[{'name': 'www.noor-book.com.', 'type': 65, 'TTL': 0, 'data': '1 . ech="not-a-config"'}]),
])
def test_unrelated_or_invalid_dns_answer_cannot_configure_tls(document):
    with pytest.raises(FetchFailed):
        ech.parse_ech_answer(json.dumps(document).encode())


class Wire:
    """Only the external curl boundary is replaced; policy, limits and redirects are real."""
    def __init__(self, replies):
        self.replies = iter(replies)
        self.requests = []
        self.closed = 0
        self.chunks_received = 0

    def session(self, **options):
        assert options['trust_env'] is False
        assert options['curl_options'][ech.CurlOpt.ECH] == 'ecl:' + CONFIG
        wire = self
        class Session:
            async def __aenter__(self): return self
            async def __aexit__(self, *exc): wire.closed += 1
            async def request(self, method, url, **kw):
                wire.requests.append((method, url, kw))
                assert kw['verify'] is True and kw['allow_redirects'] is False
                assert kw['proxy'].startswith('http://127.0.0.1:')
                assert kw['discard_cookies'] is True
                status, headers, chunks = next(wire.replies)
                for chunk in chunks:
                    # Characterize curl_cffi's real callback boundary: returning 0 alone does NOT
                    # abort in this pinned version. It requires CURL_WRITEFUNC_ERROR.
                    context = ffi.new_handle(_CallbackContext(kw['content_callback']))
                    wire.chunks_received += 1
                    with warnings.catch_warnings():
                        warnings.simplefilter('ignore')
                        written = lib.write_callback(ffi.new('char[]', chunk), 1, len(chunk), context)
                    if written == CURL_WRITEFUNC_ERROR:
                        raise ech.RequestsError('write aborted')
                return SimpleNamespace(status_code=status, headers=Headers(headers))
        return Session()


def setup_wire(monkeypatch, replies):
    wire = Wire(replies)
    monkeypatch.setattr(ech, 'AsyncSession', wire.session)
    async def dns(self, url, **kwargs):
        assert url == ech.ECH_DNS_URL
        return HttpResponse(url, 200, CIMultiDict(), json.dumps(answer()).encode())
    monkeypatch.setattr(ech.HttpClient, 'fetch', dns)
    return wire


def test_body_limit_aborts_receipt_and_closes_session(monkeypatch):
    wire = setup_wire(monkeypatch, [(200, {}, [b'1234', b'5678', b'never receive'])])
    async def scenario():
        async with ech.EchClient(EgressPolicy(domains=('www.noor-book.com',))) as client:
            with pytest.raises(ResponseTooLarge):
                await client.fetch(URL, max_bytes=6)
    asyncio.run(scenario())
    assert wire.closed == 1
    assert wire.chunks_received == 2


def test_redirect_is_rechecked_and_cannot_leave_fixed_origin(monkeypatch):
    wire = setup_wire(monkeypatch, [(302, {'Location': 'https://attacker.test/'}, [b''])])
    async def scenario():
        async with ech.EchClient(EgressPolicy(domains=('www.noor-book.com', 'attacker.test'))) as client:
            with pytest.raises(DisallowedTarget):
                await client.fetch(URL)
    asyncio.run(scenario())
    assert len(wire.requests) == 1


def test_response_keeps_repeated_cookies_but_next_fetch_has_no_jar(monkeypatch):
    wire = setup_wire(monkeypatch, [(200, [('Set-Cookie', 'a=1'), ('Set-Cookie', 'b=2')], [b'ok']),
                                   (200, {}, [b'next'])])
    async def scenario():
        async with ech.EchClient(EgressPolicy(domains=('www.noor-book.com',))) as client:
            first = await client.fetch(URL)
            second = await client.fetch(URL)
            assert first.body == b'ok' and second.body == b'next'
            assert first.headers.getall('Set-Cookie') == ['a=1', 'b=2']
    asyncio.run(scenario())
    assert all('Cookie' not in call[2]['headers'] for call in wire.requests)
    assert wire.closed == 2


@pytest.mark.parametrize('url', ['http://www.noor-book.com/', 'https://user@www.noor-book.com/',
                                 'https://127.0.0.1/', 'https://www.noor-book.com:8443/'])
def test_invalid_target_rejected_before_network(monkeypatch, url):
    wire = setup_wire(monkeypatch, [])
    async def scenario():
        async with ech.EchClient(EgressPolicy(domains=('www.noor-book.com',))) as client:
            with pytest.raises(DisallowedTarget):
                await client.fetch(url)
    asyncio.run(scenario())
    assert wire.requests == []


def test_cancelled_initialization_closes_proxy_and_owned_resolver(monkeypatch):
    async def scenario():
        client = ech.EchClient(EgressPolicy(domains=('www.noor-book.com',)))
        entered = asyncio.Event()
        original = ech.HttpClient.__aenter__
        async def paused(self):
            await original(self)
            entered.set()
            await asyncio.Event().wait()
        monkeypatch.setattr(ech.HttpClient, '__aenter__', paused)
        task = asyncio.create_task(client.__aenter__())
        await entered.wait()
        backend = client._proxy.backend
        closed = []
        original_close = backend.close
        async def close():
            closed.append(True)
            await original_close()
        monkeypatch.setattr(backend, 'close', close)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        try:
            assert client._dns._session is None
            assert closed == [True]
            assert not client._proxy._server.is_serving()
        finally:
            await client.__aexit__(None, None, None)
    asyncio.run(scenario())
