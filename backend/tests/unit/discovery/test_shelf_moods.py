"""What should I read now? (asked for 2026-11-10): a pick from the shelf that fits how long you have and what you
feel like, with the reason said in plain terms. OneShelf only uses what it knows: how far you are, how many
chapters are left, and what kind of work it is."""
import random

from oneshelf.discovery.discover import MOODS, DiscoverService
from oneshelf.domain.clock import utcnow_iso
from oneshelf.domain.ids import new_id

NOW = utcnow_iso()


def service(db):
    return DiscoverService(db, None, None, None, rng=random.Random(7))


def add(db, title, *, kind="manga", chapters=3, read=0, partial=0, completed=False, last_read="2026-11-01T10:00:00+00:00",
        shelf=True):
    """A work with `chapters` chapters, the first `read` read and the next `partial` started."""
    work, track = new_id(), new_id()
    db.execute("INSERT INTO works (id, display_title, content_type, created_at, updated_at) VALUES (?,?,?,?,?)",
               (work, title, kind, NOW, NOW))
    db.execute("INSERT INTO source_tracks (id, work_id, source_id, language, kind, created_at)"
               " VALUES (?,?,'s','en','source',?)", (track, work, NOW))
    for number in range(chapters):
        unit = new_id()
        db.execute("INSERT INTO reading_units (id, track_id, source_unit_key, unit_type, source_order, first_seen_at)"
                   " VALUES (?,?,?,'chapter',?,?)", (unit, track, f"{title}-{number}", number, NOW))
        state = "read" if number < read else "partial" if number < read + partial else None
        if state:
            db.execute("INSERT INTO reading_state (reading_unit_id, read_state, fraction, revision, updated_at)"
                       " VALUES (?,?,?,1,?)", (unit, state, 1.0 if state == "read" else 0.4, last_read))
    if shelf:
        db.execute("INSERT INTO shelf_entries (work_id, added_at, completed_at) VALUES (?,?,?)",
                   (work, NOW, NOW if completed else None))
    return work


def ids(pick):
    return None if pick is None else pick["work_id"]


def test_the_moods_are_the_ones_the_page_offers():
    assert MOODS == ("continue", "short", "light", "fresh")


def test_continue_offers_what_was_started_most_recently_first(db):
    old = add(db, "Old", read=1, last_read="2026-10-01T10:00:00+00:00")
    recent = add(db, "Recent", read=2, last_read="2026-11-09T10:00:00+00:00")
    add(db, "Untouched")
    add(db, "Done", read=3)                           # every chapter read: nothing left to continue
    add(db, "Finished", read=1, completed=True)       # marked completed by the reader
    first = service(db).suggest_from_shelf("continue")
    assert ids(first) == recent and first["reason"] == {"kind": "continue", "remaining": 1}
    assert first["more"] is True
    second = service(db).suggest_from_shelf("continue", exclude={recent})
    assert ids(second) == old and second["more"] is False


def test_a_chapter_in_progress_counts_as_started_and_not_yet_read(db):
    book = add(db, "A Novel", kind="novel", chapters=1, partial=1)
    pick = service(db).suggest_from_shelf("continue")
    assert ids(pick) == book and pick["reason"] == {"kind": "continue"}    # one file: no count of chapters


def test_short_prefers_the_fewest_chapters_left_and_says_how_many(db):
    two_left = add(db, "Nearly done", chapters=10, read=8)
    add(db, "Long", chapters=200)
    add(db, "Longish", chapters=30)
    pick = service(db).suggest_from_shelf("short")
    assert ids(pick) == two_left and pick["reason"] == {"kind": "short", "remaining": 2}


def test_short_knows_a_one_shot_and_a_paper_but_not_how_long_a_single_book_is(db):
    shot = add(db, "One-shot", kind="manga", chapters=1)
    paper = add(db, "A paper", kind="paper", chapters=1)
    add(db, "A Novel", kind="novel", chapters=1)       # one file: its length is not known
    seen = set()
    exclude = set()
    for _ in range(3):
        pick = service(db).suggest_from_shelf("short", exclude=exclude)
        if pick is None:
            break
        seen.add(ids(pick))
        exclude.add(ids(pick))
    assert seen == {shot, paper}
    assert pick is None


def test_light_is_a_comic_from_the_shelf(db):
    comic = add(db, "A Webtoon", kind="manhwa", chapters=40)
    add(db, "A Novel", kind="novel", chapters=1)
    add(db, "Read comic", kind="manga", chapters=3, completed=True)
    pick = service(db).suggest_from_shelf("light")
    assert ids(pick) == comic and pick["reason"] == {"kind": "light", "content_type": "manhwa"}
    assert pick["more"] is False


def test_fresh_is_something_not_started_and_is_the_old_behaviour(db):
    fresh = add(db, "Fresh")
    add(db, "Started", read=1)
    pick = service(db).suggest_from_shelf("fresh")
    assert ids(pick) == fresh and pick["reason"] == {"kind": "fresh"} and pick["more"] is False


def test_content_type_still_narrows_any_mood(db):
    add(db, "Manga", kind="manga", read=1)
    novel = add(db, "Novel", kind="novel", chapters=2, read=1)
    assert ids(service(db).suggest_from_shelf("continue", content_type="novel")) == novel


def test_nothing_to_offer_is_none_and_unknown_moods_are_refused(db):
    add(db, "Fresh")                                   # nothing started, so nothing to continue
    assert service(db).suggest_from_shelf("continue") is None
    try:
        service(db).suggest_from_shelf("sleepy")
    except ValueError:
        return
    raise AssertionError("an unknown mood must be refused")


def test_works_not_on_the_shelf_are_never_offered(db):
    add(db, "Elsewhere", read=1, shelf=False)
    assert service(db).suggest_from_shelf("continue") is None
