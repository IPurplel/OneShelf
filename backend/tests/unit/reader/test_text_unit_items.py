"""A text reader result with many items (one per verse) is read as one unit (plugin API 1.2)."""
import asyncio

from oneshelf.plugins.results import ListResult, Evidence, ResourceDescriptor
from oneshelf.reader.service import ReaderService

NOW = "2026-01-01T00:00:00+00:00"


class VerseSource:
    def __init__(self):
        self.calls = 0

    def reads_text(self, source_id):
        return True

    async def run(self, source_id, capability, inputs, priority=None):
        self.calls += 1
        verses = [ResourceDescriptor(url=None, index=i, html=f"<p><sup>{i + 1}</sup> In the beginning {i + 1}.</p>",
                                     title="בראשית א" if i == 0 else None) for i in range(31)]
        return ListResult("reader", verses, True, Evidence())


def test_verses_become_one_unit_with_the_first_title(db):
    db.execute("INSERT INTO works (id, display_title, created_at, updated_at) VALUES ('w', 'Genesis', ?, ?)", (NOW, NOW))
    db.execute("INSERT INTO source_tracks (id, work_id, source_id, language, kind, created_at)"
               " VALUES ('t', 'w', 'oneshelf.sefaria', 'he', 'source', ?)", (NOW,))
    db.execute("INSERT INTO reading_units (id, track_id, source_unit_key, source_order, first_seen_at)"
               " VALUES ('u', 't', 'Genesis.1', 1, ?)", (NOW,))
    unit, origin = asyncio.run(ReaderService(db, VerseSource(), cache=None).text("u"))
    assert origin == "online" and unit.direction == "rtl" and unit.language == "he"
    assert len(unit.sections) == 1 and unit.sections[0].title == "בראשית א"
    assert unit.sections[0].html.count("<p>") == 31
