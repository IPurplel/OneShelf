"""What another source can honestly offer for the unit being read (Master §26.16, INV-25).

Equivalence across sources is decided on the unit's own number and type, never on its position in the
track: two sources that both publish "chapter 12" agree about chapter 12, while two sources whose
twelfth entries happen to line up agree about nothing. When the answer is not exactly one candidate,
this says so and names no unit — the reader then offers the target track itself rather than a guess.

Language is held constant: an alternative is a different source for the same language, never a
different language (INV-02).
"""
from __future__ import annotations

import sqlite3

_UNIT = ("SELECT u.id, u.track_id, u.unit_type,"
         " COALESCE(u.user_number, u.source_number, u.derived_number) AS number"
         " FROM reading_units u WHERE u.id = ?")


def _comparable(number: str | None) -> str | None:
    """A number the two sources can be compared on, or nothing at all.

    "3.50" and "3.5" are the same chapter; "Extra" and "extra" are the same word. A unit with no number
    of its own has nothing comparable, and nothing is what it gets.
    """
    if number is None:
        return None
    text = number.strip()
    if not text:
        return None
    try:
        return format(float(text), ".6f")
    except ValueError:
        return text.casefold()


def alternatives(conn: sqlite3.Connection, unit_id: str) -> dict:
    """The same-language tracks this unit could be read from instead, and what each one can offer."""
    unit = conn.execute(_UNIT, (unit_id,)).fetchone()
    if unit is None:
        raise ValueError("this unit is not in your library")
    here = conn.execute("SELECT work_id, source_id, language FROM source_tracks WHERE id = ?",
                        (unit["track_id"],)).fetchone()
    wanted = _comparable(unit["number"])

    offers = []
    others = conn.execute(
        "SELECT id, source_id, language, kind, availability FROM source_tracks"
        " WHERE work_id = ? AND language = ? AND id != ?"
        " ORDER BY (kind = 'local') DESC, source_id",
        (here["work_id"], here["language"], unit["track_id"])).fetchall()
    for track in others:
        matches = []
        if wanted is not None:
            candidates = conn.execute(
                "SELECT id, display_title, raw_title,"
                " COALESCE(user_number, source_number, derived_number) AS number"
                " FROM reading_units WHERE track_id = ? AND unit_type = ? ORDER BY source_order",
                (track["id"], unit["unit_type"])).fetchall()
            matches = [row for row in candidates if _comparable(row["number"]) == wanted]
        confident = len(matches) == 1
        offers.append({
            "track_id": track["id"],
            "source_id": track["source_id"],
            "language": track["language"],
            "kind": track["kind"],
            "availability": track["availability"],
            "unit_id": matches[0]["id"] if confident else None,
            "unit_title": (matches[0]["display_title"] or matches[0]["raw_title"]) if confident else None,
            "confident": confident,
            # Why there is nothing to open, in the two ways it can happen — never a near miss offered anyway.
            "reason": None if confident else ("ambiguous" if len(matches) > 1 else "no_match"),
        })

    return {"unit_id": unit_id, "track_id": unit["track_id"], "source_id": here["source_id"],
            "language": here["language"], "alternatives": offers}
