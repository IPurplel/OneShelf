"""Follow scheduler: checks due follows about every 12 hours with jitter, grouped by source (§20)."""
from __future__ import annotations

import asyncio
import logging

from oneshelf.catalog.trust import CatalogTrust
from oneshelf.net.governor import Priority
from oneshelf.plugins.runtime import AuthRequired, CapabilityError, RateLimited

logger = logging.getLogger(__name__)


class FollowRunner:
    def __init__(self, conn, follows, sources, plugins, catalog: CatalogTrust, notifications=None, *,
                 interval_seconds: float = 300) -> None:
        self.conn = conn
        self.follows = follows
        self.sources = sources
        self.plugins = plugins
        self.catalog = catalog
        self.notifications = notifications
        self.interval_seconds = interval_seconds
        self._task: asyncio.Task | None = None

    async def check_work(self, work_id: str) -> dict:
        """One Follow check: refresh the catalog, then compare against the baseline (never numbers)."""
        row = self.conn.execute("SELECT * FROM follows WHERE work_id = ?", (work_id,)).fetchone()
        if row is None:
            raise ValueError("this work is not followed")
        listing = self.conn.execute(
            "SELECT l.source_listing_key FROM source_tracks t JOIN source_listings l ON l.id = t.listing_id"
            " WHERE t.id = ?", (row["track_id"],)).fetchone()
        if listing is None:
            self.follows.record_attempt(work_id, successful=False, category="no_listing")
            return {"work_id": work_id, "state": "degraded", "new_units": []}
        try:
            package = self.plugins.load_active(row["preferred_source_id"])
            result = await self.sources.run(row["preferred_source_id"], "catalog",
                                            {"listing_key": listing["source_listing_key"]}, priority=Priority.FOLLOW)
        except AuthRequired:
            self.follows.record_attempt(work_id, successful=False, category="auth_failure")
            if self.notifications:
                self.notifications.reconnect_required(row["preferred_source_id"])
            return {"work_id": work_id, "state": "reconnect_required", "new_units": []}
        except RateLimited as exc:
            self.follows.record_attempt(work_id, successful=False, category="rate_limit")
            return {"work_id": work_id, "state": "rate_limited", "retry_after": exc.retry_after, "new_units": []}
        except (CapabilityError, Exception) as exc:
            category = getattr(exc, "category", "transport")
            self.follows.record_attempt(work_id, successful=False, category=category)
            return {"work_id": work_id, "state": "degraded", "category": category, "new_units": []}
        outcome = self.catalog.refresh(row["track_id"], result, plugin_version=package.version)
        if outcome.state == "suspicious" and self.notifications:
            title = self.conn.execute("SELECT display_title FROM works WHERE id = ?", (work_id,)).fetchone()[0]
            self.notifications.catalog_suspicious(row["preferred_source_id"], title)
        check = self.follows.check(work_id)
        if check.new_units and self.notifications:
            title = self.conn.execute("SELECT display_title FROM works WHERE id = ?", (work_id,)).fetchone()[0]
            self.notifications.new_releases(work_id, title, check.new_units)
        return {"work_id": work_id, "state": check.state, "new_units": check.new_units,
                "catalog_state": outcome.state}

    async def check_all(self) -> list[dict]:
        return [await self.check_work(work_id) for work_id in self.follows.due_follows()]

    async def start(self) -> None:
        self._task = asyncio.create_task(self._loop())

    async def _loop(self) -> None:
        while True:
            try:
                await self.check_all()
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("follow check pass failed")
            await asyncio.sleep(self.interval_seconds)

    async def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
