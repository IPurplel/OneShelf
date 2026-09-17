"""Starts Chromium only when browser retrieval or a login actually needs it."""
from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from oneshelf.net.browser import BrowserContextHandle, BrowserManager


class LazyBrowser:
    def __init__(self) -> None:
        self._manager: BrowserManager | None = None
        self._lock = asyncio.Lock()

    async def _get(self) -> BrowserManager:
        async with self._lock:
            if self._manager is None:
                self._manager = await BrowserManager().__aenter__()
            return self._manager

    @asynccontextmanager
    async def context(self, policy, **kwargs) -> AsyncIterator[BrowserContextHandle]:
        manager = await self._get()
        async with manager.context(policy, **kwargs) as handle:
            yield handle

    async def aclose(self) -> None:
        if self._manager is not None:
            await self._manager.__aexit__(None, None, None)
            self._manager = None
