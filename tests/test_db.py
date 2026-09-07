"""Database state around deleted downloads."""

from __future__ import annotations

import pytest

from app.db import Database
from app.models import Chapter, Series


@pytest.fixture
async def db(tmp_path):
    database = Database(tmp_path / "test.db")
    await database.connect()
    try:
        yield database
    finally:
        await database.close()


@pytest.fixture
def series() -> Series:
    return Series(url="https://e.net/manga/s/", title="S", source="madara")


async def _seed(db, series, count=3):
    await db.upsert_series(series)
    chapters = [
        Chapter(url=f"{series.url}{i}/", title=str(i), number=str(i), index=i)
        for i in range(1, count + 1)
    ]
    await db.upsert_chapters(series.url, chapters)
    return chapters


async def test_clear_chapter_downloads_blanks_the_output_path(db, series):
    """set_chapter_status COALESCEs output_path, so it cannot blank one.

    Reusing it after deleting a file would leave a recorded path pointing at
    something that no longer exists, and the Library would keep counting the
    chapter as downloaded.
    """
    chapters = await _seed(db, series)
    await db.set_chapter_status(
        chapters[0].url, "done", pages_total=20, output_path="/data/s/c1.cbz")

    # The trap, demonstrated: passing None keeps the old path.
    await db.set_chapter_status(chapters[0].url, "pending", output_path=None)
    assert (await db.get_chapter_states(series.url))[chapters[0].url]["output_path"]

    cleared = await db.clear_chapter_downloads([chapters[0].url])

    row = (await db.get_chapter_states(series.url))[chapters[0].url]
    assert cleared == 1
    assert row["output_path"] is None
    assert row["status"] == "pending"
    assert row["pages_total"] == 0


async def test_clearing_updates_the_downloaded_count(db, series):
    chapters = await _seed(db, series)
    for chapter in chapters:
        await db.set_chapter_status(chapter.url, "done", output_path="/x.cbz")

    assert (await db.list_series())[0]["downloaded_count"] == 3

    await db.clear_chapter_downloads([chapters[0].url, chapters[1].url])

    row = (await db.list_series())[0]
    assert row["downloaded_count"] == 1
    assert row["chapter_count"] == 3  # the series and its chapters remain


async def test_clearing_leaves_other_chapters_alone(db, series):
    chapters = await _seed(db, series)
    for chapter in chapters:
        await db.set_chapter_status(chapter.url, "done", output_path="/x.cbz")

    await db.clear_chapter_downloads([chapters[0].url])

    states = await db.get_chapter_states(series.url)
    assert states[chapters[1].url]["status"] == "done"
    assert states[chapters[1].url]["output_path"] == "/x.cbz"


async def test_clearing_nothing_is_harmless(db, series):
    await _seed(db, series)
    assert await db.clear_chapter_downloads([]) == 0


# ------------------------------------------------------- what is "the library"
# Previewing a URL writes a series row — that is how the Add view knows which
# chapters you already hold. So row existence cannot mean "in the library", or
# every search result you merely clicked on gets filed as though you owned it.


async def test_previewing_a_series_does_not_put_it_in_the_library(db, series):
    await _seed(db, series)   # exactly what preview_series writes

    assert await db.list_series() == []
    # ...while the chapter rows it wrote are still there for the status merge.
    assert len(await db.get_chapter_states(series.url)) == 3


async def test_a_series_joins_the_library_when_a_chapter_finishes(db, series):
    chapters = await _seed(db, series)

    await db.set_chapter_status(chapters[0].url, "running")
    assert await db.list_series() == [], "starting is not finishing"

    await db.set_chapter_status(chapters[0].url, "done", output_path="/x.cbz")

    rows = await db.list_series()
    assert [row["url"] for row in rows] == [series.url]
    assert rows[0]["downloaded_count"] == 1
    assert rows[0]["chapter_count"] == 3   # the site's full list, not just ours


async def test_a_failed_download_does_not_create_a_library_entry(db, series):
    chapters = await _seed(db, series)
    await db.set_chapter_status(chapters[0].url, "failed", error="nope")

    assert await db.list_series() == []


async def test_deleting_every_file_keeps_the_series_in_the_library(db, series):
    """Documented behaviour: the files go, the series stays and can be refetched.

    'Remove from library' is the separate, deliberate act that drops the entry.
    """
    chapters = await _seed(db, series)
    for chapter in chapters:
        await db.set_chapter_status(chapter.url, "done", output_path="/x.cbz")

    await db.clear_chapter_downloads([c.url for c in chapters])

    rows = await db.list_series()
    assert [row["url"] for row in rows] == [series.url]
    assert rows[0]["downloaded_count"] == 0


async def test_the_join_time_is_the_first_download_not_the_latest(db, series):
    chapters = await _seed(db, series)
    await db.set_chapter_status(chapters[0].url, "done", output_path="/x.cbz")
    first = (await db.list_series())[0]["first_download_at"]

    await db.set_chapter_status(chapters[1].url, "done", output_path="/y.cbz")

    assert (await db.list_series())[0]["first_download_at"] == first


async def test_everything_is_still_reachable_for_diagnostics(db, series):
    await _seed(db, series)
    assert [row["url"] for row in await db.list_series(downloaded_only=False)] \
        == [series.url]


async def test_an_existing_library_survives_the_upgrade(tmp_path):
    """The column is added by ALTER, so pre-existing rows have to be backfilled.

    Without it, upgrading empties the Library: every series predates the column
    and would read as never downloaded.
    """
    import aiosqlite

    path = tmp_path / "old.db"
    # The v1 schema, exactly as it shipped — no first_download_at.
    async with aiosqlite.connect(path) as conn:
        await conn.executescript("""
            CREATE TABLE series (
                url TEXT PRIMARY KEY, title TEXT NOT NULL, source TEXT NOT NULL,
                cover_url TEXT, author TEXT, description TEXT,
                added_at REAL NOT NULL, updated_at REAL NOT NULL);
            CREATE TABLE chapters (
                url TEXT PRIMARY KEY, series_url TEXT NOT NULL, title TEXT NOT NULL,
                number TEXT, idx INTEGER NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending', pages_total INTEGER DEFAULT 0,
                output_path TEXT, error TEXT, updated_at REAL NOT NULL);
            INSERT INTO series VALUES
                ('https://e.net/kept/', 'Kept', 'madara', NULL, NULL, NULL, 1, 1),
                ('https://e.net/peeked/', 'Peeked', 'madara', NULL, NULL, NULL, 2, 2);
            INSERT INTO chapters VALUES
                ('https://e.net/kept/1', 'https://e.net/kept/', '1', '1', 1,
                 'done', 20, '/data/kept/1.cbz', NULL, 1),
                ('https://e.net/peeked/1', 'https://e.net/peeked/', '1', '1', 1,
                 'pending', 0, NULL, NULL, 2);
        """)
        await conn.commit()

    database = Database(path)
    await database.connect()
    try:
        rows = await database.list_series()
    finally:
        await database.close()

    # The downloaded one is carried over; the one that was only ever previewed
    # is not — which is the whole point of the change.
    assert [row["title"] for row in rows] == ["Kept"]
