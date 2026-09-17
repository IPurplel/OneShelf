"""Scheduled Library Backup (Master §33.8): every seven days, catching up after downtime."""
from __future__ import annotations

import asyncio
import logging

logger = logging.getLogger(__name__)


class BackupRunner:
    def __init__(self, backups, *, interval_seconds: float = 3600, notifications=None) -> None:
        self.backups = backups
        self.interval_seconds = interval_seconds
        self.notifications = notifications
        self._task: asyncio.Task | None = None

    async def run_once(self) -> str | None:
        """Runs at the next suitable opportunity if the scheduled backup was missed during downtime."""
        if not self.backups.due():
            return None
        try:
            record = self.backups.create("library")
        except Exception as exc:
            logger.exception("scheduled library backup failed")
            if self.notifications is not None:
                self.notifications.notify("important", dedupe_key="backup-failed", title="Backup failed",
                                          summary=str(exc), actions=["view_backups"])
            return None
        if self.notifications is not None:
            self.notifications.resolve("backup-failed")   # success is silent by default (§30.11)
        return record.path

    async def start(self) -> None:
        self._task = asyncio.create_task(self._loop())

    async def _loop(self) -> None:
        while True:
            await self.run_once()
            await asyncio.sleep(self.interval_seconds)

    async def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
