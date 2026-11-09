"""Reading goals (asked for 2026-11-10): books finished this year against a goal, and a daily reading streak.

Days are the reader's own: the page sends its UTC offset, so reading at 1 a.m. in Riyadh is that day's reading.
"""
from datetime import UTC, date, datetime

from oneshelf.domain.ids import new_id
from oneshelf.downloads.contract import Settings
from oneshelf.goals.service import GoalsService, record_reading

RIYADH = -180          # JavaScript's getTimezoneOffset(): UTC minus local, in minutes


def read_at(db, *moments):
    for moment in moments:
        record_reading(db, datetime.fromisoformat(moment).replace(tzinfo=UTC))


def finished(db, title, completed_at):
    work_id = new_id()
    db.execute("INSERT INTO works (id, display_title, content_type, created_at, updated_at) VALUES (?,?,?,?,?)",
               (work_id, title, "novel", completed_at, completed_at))
    db.execute("INSERT INTO shelf_entries (work_id, added_at, completed_at) VALUES (?,?,?)",
               (work_id, completed_at, completed_at))
    return work_id


def test_a_streak_counts_consecutive_days_up_to_today(db):
    # 20:00 UTC on the 8th is 23:00 in Riyadh, still the 8th; 22:30 UTC on the 9th is 01:30 on the 10th there.
    read_at(db, "2026-11-07T09:00:00", "2026-11-08T20:00:00", "2026-11-09T09:00:00", "2026-11-09T22:30:00")
    streak = GoalsService(db, Settings(db)).summary(offset_minutes=RIYADH, today=date(2026, 11, 10))["streak"]
    assert streak["current"] == 4 and streak["read_today"] is True and streak["longest"] == 4
    assert streak["last_7"] == [False, False, False, True, True, True, True]


def test_a_streak_still_stands_until_today_ends(db):
    read_at(db, "2026-11-08T09:00:00", "2026-11-09T09:00:00")
    streak = GoalsService(db, Settings(db)).summary(offset_minutes=0, today=date(2026, 11, 10))["streak"]
    assert streak["current"] == 2 and streak["read_today"] is False


def test_a_missed_day_breaks_the_streak_but_keeps_the_longest(db):
    read_at(db, "2026-11-01T09:00:00", "2026-11-02T09:00:00", "2026-11-03T09:00:00", "2026-11-10T09:00:00")
    streak = GoalsService(db, Settings(db)).summary(offset_minutes=0, today=date(2026, 11, 10))["streak"]
    assert streak["current"] == 1 and streak["longest"] == 3


def test_books_finished_this_year_are_counted_against_the_goal_and_its_pace(db):
    goals = GoalsService(db, Settings(db))
    goals.set_books_goal(24)
    finished(db, "Last year", "2025-12-30T10:00:00+00:00")
    for month in ("01", "03", "05", "07", "09"):
        finished(db, f"Book {month}", f"2026-{month}-15T10:00:00+00:00")
    books = goals.summary(offset_minutes=0, today=date(2026, 7, 2))["books"]   # day 183 of 365: half a year
    assert books["year"] == 2026 and books["goal"] == 24 and books["finished"] == 5
    assert books["expected_by_now"] == 12 and books["ahead"] == -7
    assert [b["title"] for b in books["recent"]][:2] == ["Book 09", "Book 07"]


def test_no_goal_is_set_until_one_is_chosen_and_it_can_be_cleared(db):
    goals = GoalsService(db, Settings(db))
    assert goals.summary(offset_minutes=0, today=date(2026, 11, 10))["books"]["goal"] is None
    goals.set_books_goal(12)
    goals.set_books_goal(None)
    assert goals.summary(offset_minutes=0, today=date(2026, 11, 10))["books"]["goal"] is None
