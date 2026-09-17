"""Background download runner: keeps the queue moving while the application is running."""
from __future__ import annotations

import asyncio
import logging

logger = logging.getLogger(__name__)


class DownloadRunner:
    def __init__(self, engine, *, idle_seconds: float = 0.5) -> None:
        self.engine = engine
        self.idle_seconds = idle_seconds
        self._task: asyncio.Task | None = None

    async def start(self) -> None:
        await self.engine.recover()
        self._task = asyncio.create_task(self._loop())

    async def _loop(self) -> None:
        while True:
            try:
                await self.engine.run_once()
            except asyncio.CancelledError:
                raise
            except Exception:  # a failing pass must never stop the queue
                logger.exception("download pass failed")
            await asyncio.sleep(self.idle_seconds)

    async def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
