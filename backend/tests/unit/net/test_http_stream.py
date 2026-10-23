"""I-101 (BE-011), I-97 (BE-007), I-109 (BE-019): streaming transport, honest resume, no leaked connections."""
import asyncio
import gc
import tracemalloc
import warnings

import pytest
from aiohttp import web

from oneshelf.net.http import FetchFailed, HttpClient, ResponseTooLarge
from oneshelf.net.policy import EgressPolicy
from tests.unit.net.test_policy import FakeDNS, server_factory  # noqa: F401

BIG = 48 * 1024 * 1024
POLICY = EgressPolicy(domains=("testsource.example",), allow_http=True, dev_loopback_exception=True)


def run(coro):
    return asyncio.run(coro)


async def streamed(request):
    response = web.StreamResponse(headers={"Content-Length": str(BIG), "ETag": '"v1"'})
    await response.prepare(request)
    chunk = b"\0" * (1024 * 1024)
    for _ in range(BIG // len(chunk)):
        await response.write(chunk)
    return response


def versioned(body: bytes, etag: str):
    async def handler(request):
        headers = {"ETag": etag, "Accept-Ranges": "bytes"}
        rng = request.headers.get("Range")
        if rng and request.headers.get("If-Range") in (None, etag):
            start = int(rng[6:].split("-")[0])
            if start >= len(body):
                return web.Response(status=416, headers={"Content-Range": f"bytes */{len(body)}"})
            headers["Content-Range"] = f"bytes {start}-{len(body) - 1}/{len(body)}"
            return web.Response(status=206, body=body[start:], headers=headers)
        return web.Response(body=body, headers=headers)
    return handler


def test_i101_a_large_body_goes_to_disk_without_being_held_in_memory(server_factory, tmp_path):
    async def scenario():
        runner, port = await server_factory([web.get("/big", streamed)])
        async with HttpClient(POLICY, resolver_backend=FakeDNS({"testsource.example": ["127.0.0.1"]})) as client:
            tracemalloc.start()
            response = await client.stream_to(f"http://testsource.example:{port}/big", tmp_path / "big.bin")
            _, peak = tracemalloc.get_traced_memory()
            tracemalloc.stop()
        await runner.cleanup()
        return response, peak

    response, peak = run(scenario())
    assert response.status == 200 and response.bytes_written == BIG
    assert (tmp_path / "big.bin").stat().st_size == BIG
    assert peak < 8 * 1024 * 1024, f"peak {peak / 2**20:.1f} MiB while streaming {BIG / 2**20:.0f} MiB"


def test_i101_the_size_cap_still_holds_and_leaves_no_partial_claim(server_factory, tmp_path):
    async def scenario():
        runner, port = await server_factory([web.get("/big", streamed)])
        async with HttpClient(POLICY, resolver_backend=FakeDNS({"testsource.example": ["127.0.0.1"]})) as client:
            with pytest.raises(ResponseTooLarge):
                await client.stream_to(f"http://testsource.example:{port}/big", tmp_path / "big.bin",
                                       max_bytes=1024 * 1024)
        await runner.cleanup()
    run(scenario())


def test_i97_a_matching_partial_response_continues_the_file(server_factory, tmp_path):
    body = bytes(range(256)) * 400
    target = tmp_path / "f.bin"
    target.write_bytes(body[:1000])

    async def scenario():
        runner, port = await server_factory([web.get("/f", versioned(body, '"v1"'))])
        async with HttpClient(POLICY, resolver_backend=FakeDNS({"testsource.example": ["127.0.0.1"]})) as client:
            response = await client.stream_to(f"http://testsource.example:{port}/f", target, resume_from=1000,
                                              validator='"v1"')
        await runner.cleanup()
        return response

    response = run(scenario())
    assert response.status == 206 and response.resumed is True
    assert target.read_bytes() == body


def test_i97_a_changed_version_replaces_the_file_and_is_never_spliced(server_factory, tmp_path):
    new = b"N" * 5000
    target = tmp_path / "f.bin"
    target.write_bytes(b"O" * 1000)

    async def scenario():
        runner, port = await server_factory([web.get("/f", versioned(new, '"v2"'))])
        async with HttpClient(POLICY, resolver_backend=FakeDNS({"testsource.example": ["127.0.0.1"]})) as client:
            response = await client.stream_to(f"http://testsource.example:{port}/f", target, resume_from=1000,
                                              validator='"v1"')
        await runner.cleanup()
        return response

    response = run(scenario())
    assert response.status == 200 and response.resumed is False
    assert target.read_bytes() == new


def test_i97_asking_past_the_end_is_a_clean_restart_not_a_failure(server_factory, tmp_path):
    body = b"X" * 4000
    target = tmp_path / "f.bin"
    target.write_bytes(body)

    async def scenario():
        runner, port = await server_factory([web.get("/f", versioned(body, '"v1"'))])
        async with HttpClient(POLICY, resolver_backend=FakeDNS({"testsource.example": ["127.0.0.1"]})) as client:
            response = await client.stream_to(f"http://testsource.example:{port}/f", target, resume_from=4000,
                                              validator='"v1"')
        await runner.cleanup()
        return response

    response = run(scenario())
    assert response.status == 200 and response.resumed is False and target.read_bytes() == body


def test_i109_a_read_timeout_releases_its_connection(server_factory, tmp_path):
    async def stall(request):
        response = web.StreamResponse(headers={"Content-Length": "100000"})
        await response.prepare(request)
        await response.write(b"partial")
        await asyncio.sleep(5)
        return response

    async def scenario():
        runner, port = await server_factory([web.get("/stall", stall)])
        client = HttpClient(POLICY, resolver_backend=FakeDNS({"testsource.example": ["127.0.0.1"]}), read_timeout=0.3)
        async with client:
            with pytest.raises(FetchFailed):
                await client.fetch(f"http://testsource.example:{port}/stall")
            with pytest.raises(FetchFailed):
                await client.stream_to(f"http://testsource.example:{port}/stall", tmp_path / "s.bin")
        await runner.cleanup()

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        run(scenario())
        gc.collect()
    leaks = [w for w in caught if issubclass(w.category, ResourceWarning)]
    assert leaks == [], [str(w.message) for w in leaks]


# -- I-104 (BE-014): a same-host redirect to plain http is followed over https, never over http -------------

from oneshelf.net.http import secure_redirect  # noqa: E402


@pytest.mark.parametrize("previous, target, allow_http, expected", [
    # Safahat: an uppercase Latin query is canonicalised to an http:// address on the same host.
    ("https://www.safahat.org/search/keyword/Frankenstein/", "http://www.safahat.org/search/keyword/frankenstein/",
     False, "https://www.safahat.org/search/keyword/frankenstein/"),
    ("https://www.safahat.org/a", "http://WWW.Safahat.org/b?q=1", False, "https://WWW.Safahat.org/b?q=1"),
    # Another host keeps its http:// address, which the policy then refuses.
    ("https://www.safahat.org/a", "http://evil.example/b", False, "http://evil.example/b"),
    # An explicit port is never guessed into https.
    ("https://www.safahat.org/a", "http://www.safahat.org:8080/b", False, "http://www.safahat.org:8080/b"),
    # A downgrade from an http page, or a policy that allows http, is left as the source sent it.
    ("http://www.safahat.org/a", "http://www.safahat.org/b", False, "http://www.safahat.org/b"),
    ("https://www.safahat.org/a", "http://www.safahat.org/b", True, "http://www.safahat.org/b"),
])
def test_i104_secure_redirect(previous, target, allow_http, expected):
    policy = EgressPolicy(domains=("www.safahat.org",), allow_http=allow_http)
    assert secure_redirect(policy, previous, target) == expected
