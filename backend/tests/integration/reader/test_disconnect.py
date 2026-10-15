"""A discarded browser preload releases its service interest."""
import asyncio
from types import SimpleNamespace

from starlette.requests import Request

from oneshelf.api import library


def test_disconnected_prefetch_releases_page_waiter(monkeypatch):
    async def scenario():
        incoming = asyncio.Queue()
        await incoming.put({"type": "http.request", "body": b"", "more_body": False})
        request = Request({"type": "http", "method": "GET", "headers": []}, incoming.get)
        started = asyncio.Event()
        cancelled = asyncio.Event()

        class Reader:
            async def page(self, unit_id, index, *, prefetch):
                started.set()
                try:
                    await asyncio.Event().wait()
                except asyncio.CancelledError:
                    cancelled.set()
                    raise

        monkeypatch.setattr(library, "services", lambda request: SimpleNamespace(reader=Reader()))
        response_task = asyncio.create_task(library.reader_page(request, "unit", 1, prefetch=True))
        await asyncio.wait_for(started.wait(), timeout=0.5)
        await incoming.put({"type": "http.disconnect"})
        response = await asyncio.wait_for(response_task, timeout=0.5)
        return response.status_code, cancelled.is_set()

    status, cancelled = asyncio.run(scenario())
    assert status == 204 and cancelled
