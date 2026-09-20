"""§26.16, INV-25: what the reader may offer when the reader asks for another source.

Equivalence across sources is either confident or it is not. There is no third answer, and there is
never a guess: a source that numbers its chapters differently gets "we could not find it", not the
unit that happens to sit at the same index.
"""
import pytest

from oneshelf.domain.ids import new_id
from oneshelf.reader.alternatives import alternatives

NOW = "2026-01-01T00:00:00+00:00"


@pytest.fixture
def work(db):
    work_id = new_id()
    db.execute("INSERT INTO works (id, display_title, content_type, created_at, updated_at) VALUES (?,?,?,?,?)",
               (work_id, "The Irregular Chronicle", "manga", NOW, NOW))

    def track(source, language="en", kind="source"):
        track_id = new_id()
        db.execute("INSERT INTO source_tracks (id, work_id, source_id, language, kind, created_at)"
                   " VALUES (?,?,?,?,?,?)", (track_id, work_id, source, language, kind, NOW))
        return track_id

    def unit(track_id, key, number, order, unit_type="chapter", title=None):
        unit_id = new_id()
        db.execute("INSERT INTO reading_units (id, track_id, source_unit_key, display_title, unit_type,"
                   " source_number, source_order, first_seen_at) VALUES (?,?,?,?,?,?,?,?)",
                   (unit_id, track_id, key, title, unit_type, number, order, NOW))
        return unit_id

    return work_id, track, unit


def test_a_same_language_source_with_the_same_chapter_is_offered_confidently(work, db):
    _, track, unit = work
    a, b = track("source-a"), track("source-b")
    here = unit(a, "a-12", "12", 12.0)
    there = unit(b, "b-12", "12", 3.0)          # a different position in its own track
    unit(b, "b-13", "13", 4.0)

    offer = alternatives(db, here)
    assert offer["source_id"] == "source-a" and offer["language"] == "en"
    assert [alt["source_id"] for alt in offer["alternatives"]] == ["source-b"]
    alt = offer["alternatives"][0]
    assert alt["track_id"] == b and alt["unit_id"] == there and alt["confident"] is True


def test_another_language_is_never_offered_as_an_alternative(work, db):
    """INV-02: switching source must not become switching language."""
    _, track, unit = work
    a, b = track("source-a"), track("source-b", language="ar")
    here = unit(a, "a-1", "1", 1.0)
    unit(b, "b-1", "1", 1.0)

    assert alternatives(db, here)["alternatives"] == []


def test_a_source_that_does_not_have_this_chapter_says_so_rather_than_guessing(work, db):
    _, track, unit = work
    a, b = track("source-a"), track("source-b")
    here = unit(a, "a-12", "12", 12.0)
    unit(b, "b-1", "1", 1.0)                    # the same position in order, a different chapter

    alt = alternatives(db, here)["alternatives"][0]
    assert alt["confident"] is False and alt["unit_id"] is None and alt["reason"] == "no_match"


def test_two_candidates_with_the_same_number_are_not_a_confident_match(work, db):
    _, track, unit = work
    a, b = track("source-a"), track("source-b")
    here = unit(a, "a-10", "10", 10.0)
    unit(b, "b-10a", "10", 10.0)
    unit(b, "b-10b", "10", 10.5)

    alt = alternatives(db, here)["alternatives"][0]
    assert alt["confident"] is False and alt["unit_id"] is None and alt["reason"] == "ambiguous"


def test_a_unit_with_no_number_of_its_own_is_never_matched_by_position(work, db):
    _, track, unit = work
    a, b = track("source-a"), track("source-b")
    here = unit(a, "a-special", None, 5.0, unit_type="special", title="A Side Story")
    unit(b, "b-special", None, 5.0, unit_type="special", title="Something Else")

    alt = alternatives(db, here)["alternatives"][0]
    assert alt["confident"] is False and alt["unit_id"] is None and alt["reason"] == "no_match"


def test_a_chapter_and_a_special_sharing_a_number_are_not_the_same_unit(work, db):
    _, track, unit = work
    a, b = track("source-a"), track("source-b")
    here = unit(a, "a-4", "4", 4.0)
    unit(b, "b-4-special", "4", 4.0, unit_type="special")

    alt = alternatives(db, here)["alternatives"][0]
    assert alt["confident"] is False and alt["unit_id"] is None


def test_the_local_files_track_is_an_alternative_like_any_other(work, db):
    """INV-10: Files are independent, but a local copy of chapter 12 is still chapter 12."""
    _, track, unit = work
    a, local = track("source-a"), track("local", kind="local")
    here = unit(a, "a-12", "12", 12.0)
    mine = unit(local, "local-12", "12", 1.0)

    alt = alternatives(db, here)["alternatives"][0]
    assert alt["unit_id"] == mine and alt["confident"] is True and alt["kind"] == "local"
