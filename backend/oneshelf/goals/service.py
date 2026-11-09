"""Reading goals (asked for 2026-11-10): books finished this year against a goal, and a daily reading streak.

A finished book is a Work marked Completed on My Shelf. A reading day is a day, in the reader's own time, with
any reading progress saved; the page sends its UTC offset, since the server's clock may be in another zone.
"""
from __future__ import annotations

import math
import sqlite3
from datetime import UTC, date, datetime, timedelta

from oneshelf.search.presentation import work_covers

GOAL_KEY = "goals.books_per_year"
MAX_BOOKS_GOAL = 1000
RECENT_FINISHED = 12


def record_reading(conn: sqlite3.Connection, at: datetime | None = None) -> None:
    """Note that reading happened this hour. Cheap and idempotent: one row per hour at most."""
    moment = (at or datetime.now(UTC)).astimezone(UTC)
    conn.execute("INSERT OR IGNORE INTO reading_activity (hour) VALUES (?)", (moment.strftime("%Y-%m-%dT%H"),))


def _local(moment: datetime, offset_minutes: int) -> datetime:
    """`offset_minutes` is JavaScript's getTimezoneOffset(): UTC minus local time."""
    return moment - timedelta(minutes=offset_minutes)


class GoalsService:
    def __init__(self, conn: sqlite3.Connection, settings) -> None:
        self.conn = conn
        self.settings = settings

    def set_books_goal(self, books: int | None) -> None:
        if books is None:
            self.settings.delete("global", None, GOAL_KEY)
            return
        if not 1 <= books <= MAX_BOOKS_GOAL:
            raise ValueError(f"a yearly goal is between 1 and {MAX_BOOKS_GOAL} books")
        self.settings.set("global", None, GOAL_KEY, int(books))

    def _reading_days(self, offset_minutes: int) -> set[date]:
        days = set()
        for (hour,) in self.conn.execute("SELECT hour FROM reading_activity"):
            moment = datetime.strptime(hour, "%Y-%m-%dT%H").replace(tzinfo=UTC)
            days.add(_local(moment, offset_minutes).date())
        return days

    @staticmethod
    def _streak(days: set[date], today: date) -> dict:
        read_today = today in days
        # Not read yet today: yesterday's streak still stands until the day ends.
        cursor = today if read_today else today - timedelta(days=1)
        current = 0
        while cursor in days:
            current += 1
            cursor -= timedelta(days=1)
        longest, run, previous = 0, 0, None
        for day in sorted(days):
            run = run + 1 if previous is not None and day - previous == timedelta(days=1) else 1
            longest, previous = max(longest, run), day
        return {"current": current, "longest": max(longest, current), "read_today": read_today,
                "last_7": [today - timedelta(days=back) in days for back in range(6, -1, -1)]}

    def _books(self, offset_minutes: int, today: date) -> dict:
        goal = self.settings.get("global", None, GOAL_KEY, None)
        rows = self.conn.execute(
            "SELECT w.id, w.display_title, s.completed_at FROM shelf_entries s JOIN works w ON w.id = s.work_id"
            " WHERE s.completed_at IS NOT NULL").fetchall()
        this_year = []
        for row in rows:
            completed = datetime.fromisoformat(row["completed_at"])
            if completed.tzinfo is None:
                completed = completed.replace(tzinfo=UTC)
            if _local(completed.astimezone(UTC), offset_minutes).year == today.year:
                this_year.append((row["completed_at"], row["id"], row["display_title"]))
        this_year.sort(reverse=True)
        recent = this_year[:RECENT_FINISHED]
        covers = work_covers(self.conn, [work_id for _, work_id, _ in recent])
        days_in_year = (date(today.year + 1, 1, 1) - date(today.year, 1, 1)).days
        expected = math.floor(goal * today.timetuple().tm_yday / days_in_year) if goal else None
        return {"year": today.year, "goal": goal, "finished": len(this_year),
                "expected_by_now": expected, "ahead": None if expected is None else len(this_year) - expected,
                "recent": [{"work_id": work_id, "title": title, "cover_url": covers.get(work_id), "completed_at": at}
                           for at, work_id, title in recent]}

    def summary(self, *, offset_minutes: int = 0, today: date | None = None) -> dict:
        today = today or _local(datetime.now(UTC), offset_minutes).date()
        return {"books": self._books(offset_minutes, today),
                "streak": self._streak(self._reading_days(offset_minutes), today)}
