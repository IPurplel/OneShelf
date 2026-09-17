"""Master §6.5–6.9 / INV-03, INV-04, INV-27, INV-28: soft grouping vs durable mappings."""
import pytest

from oneshelf.domain.clock import utcnow_iso
from oneshelf.domain.ids import new_id
from oneshelf.search.grouping import LiveListing, group_results, persist_listing
from oneshelf.search.index import index_work
from oneshelf.search.mapping import MappingError, MappingService

NOW = utcnow_iso()


def add_work(db, title, content_type="manga"):
    work_id = new_id()
    db.execute("INSERT INTO works (id, display_title, content_type, created_at, updated_at) VALUES (?,?,?,?,?)",
               (work_id, title, content_type, NOW, NOW))
    index_work(db, work_id)
    return work_id


def listing(source, title, key=None, content_type="manga", language="en", cover=None):
    return LiveListing(source_id=source, listing_key=key or f"{source}-{title}", title=title, url=f"https://{source}/x",
                       content_type=content_type, language=language, cover_url=cover)


def counts(db):
    return {t: db.execute(f"SELECT count(*) FROM {t}").fetchone()[0]
            for t in ("source_listings", "source_tracks", "work_mappings", "works")}


@pytest.fixture
def mappings(db):
    return MappingService(db)


def test_soft_grouping_presents_one_work_without_writing_anything(db):
    work = add_work(db, "Solo Leveling")
    before = counts(db)
    results = group_results(db, [listing("mangadex", "Solo Leveling"), listing("3asq", "Solo Leveling", language="ar")])
    assert len(results) == 1
    result = results[0]
    assert result.work_id == work and result.soft is True
    assert {(p.source_id, p.language) for p in result.provenance} == {("mangadex", "en"), ("3asq", "ar")}
    assert counts(db) == before  # INV-03: presentation only


def test_unknown_titles_group_together_without_a_library_work(db):
    results = group_results(db, [listing("mangadex", "New Thing"), listing("3asq", "New Thing")])
    assert len(results) == 1 and results[0].work_id is None and results[0].soft is True
    assert counts(db)["works"] == 0


def test_adaptations_are_not_grouped(db):
    add_work(db, "Solo Leveling", content_type="manhwa")
    results = group_results(db, [listing("mangadex", "Solo Leveling", content_type="manhwa"),
                                 listing("gutenberg", "Solo Leveling", content_type="novel")])
    assert len(results) == 2
    assert {r.content_type for r in results} == {"manhwa", "novel"}


def test_covers_never_create_identity(db):
    results = group_results(db, [listing("a", "First Work", cover="https://cdn.example/same.png"),
                                 listing("b", "Totally Other", cover="https://cdn.example/same.png")])
    assert len(results) == 2


def test_hard_mapping_from_a_persisted_listing_is_used(db):
    work = add_work(db, "Berserk")
    persist_listing(db, listing("mangadex", "Berserk Deluxe"), work_id=work, decided_by="user")
    results = group_results(db, [listing("mangadex", "Berserk Deluxe")])
    assert results[0].work_id == work and results[0].soft is False


def test_actions_bind_to_the_concrete_listing_and_track(db):
    work = add_work(db, "Solo Leveling")
    entry = listing("3asq", "سولو ليفلينج", language="ar")
    binding = persist_listing(db, entry, work_id=work, decided_by="user")
    track = db.execute("SELECT * FROM source_tracks WHERE id = ?", (binding.track_id,)).fetchone()
    assert (track["source_id"], track["language"], track["work_id"]) == ("3asq", "ar", work)
    row = db.execute("SELECT * FROM source_listings WHERE id = ?", (binding.listing_id,)).fetchone()
    assert row["source_listing_key"] == entry.listing_key and row["work_id"] == work
    again = persist_listing(db, entry, work_id=work, decided_by="user")
    assert (again.listing_id, again.track_id) == (binding.listing_id, binding.track_id)


def test_never_match_prevents_grouping_and_persists(db, mappings):
    work = add_work(db, "Solo Leveling")
    entry = listing("mangadex", "Solo Leveling")
    binding = persist_listing(db, entry)
    mappings.never_match(binding.listing_id, work)
    results = group_results(db, [entry])
    assert results[0].work_id != work and results[0].soft is True
    assert db.execute("SELECT count(*) FROM work_mappings WHERE kind = 'never_match'").fetchone()[0] == 1


def test_unlink_survives_refresh_and_blocks_reassociation(db, mappings):
    work = add_work(db, "Solo Leveling")
    entry = listing("mangadex", "Solo Leveling")
    binding = persist_listing(db, entry, work_id=work, decided_by="evidence")
    mappings.unlink(binding.listing_id)
    assert db.execute("SELECT work_id FROM source_listings WHERE id = ?", (binding.listing_id,)).fetchone()[0] is None
    persist_listing(db, entry)  # a later source refresh must not re-attach it
    assert db.execute("SELECT work_id FROM source_listings WHERE id = ?", (binding.listing_id,)).fetchone()[0] is None
    assert group_results(db, [entry])[0].work_id != work


def test_merge_moves_tracks_and_keeps_alias_history(db, mappings):
    keep = add_work(db, "Solo Leveling")
    other = add_work(db, "Only I Level Up")
    persist_listing(db, listing("mangadex", "Solo Leveling"), work_id=keep, decided_by="user")
    persist_listing(db, listing("3asq", "الارتقاء بمفردي", language="ar"), work_id=other, decided_by="user")
    mappings.merge(keep, other)
    assert db.execute("SELECT count(*) FROM source_tracks WHERE work_id = ?", (keep,)).fetchone()[0] == 2
    assert db.execute("SELECT count(*) FROM works WHERE id = ?", (other,)).fetchone()[0] == 0
    aliases = {r[0] for r in db.execute("SELECT title FROM work_aliases WHERE work_id = ?", (keep,))}
    assert "Only I Level Up" in aliases
    assert db.execute("SELECT count(*) FROM work_mappings WHERE kind = 'merge' AND decided_by = 'user'").fetchone()[0] == 1


def test_merge_refuses_conflicting_source_and_language_tracks(db, mappings):
    keep = add_work(db, "A")
    other = add_work(db, "B")
    persist_listing(db, listing("mangadex", "A", key="a"), work_id=keep, decided_by="user")
    persist_listing(db, listing("mangadex", "B", key="b"), work_id=other, decided_by="user")
    with pytest.raises(MappingError):
        mappings.merge(keep, other)
    assert db.execute("SELECT count(*) FROM works").fetchone()[0] == 2


def test_split_detaches_a_listing_into_its_own_work(db, mappings):
    work = add_work(db, "Solo Leveling")
    entry = listing("3asq", "Solo Leveling: Ragnarok", language="ar")
    binding = persist_listing(db, entry, work_id=work, decided_by="evidence")
    new_work = mappings.split(binding.listing_id)
    assert new_work != work
    assert db.execute("SELECT work_id FROM source_listings WHERE id = ?", (binding.listing_id,)).fetchone()[0] == new_work
    assert db.execute("SELECT work_id FROM source_tracks WHERE id = ?", (binding.track_id,)).fetchone()[0] == new_work
    assert group_results(db, [entry])[0].work_id == new_work


def test_user_decisions_win_over_evidence_on_refresh(db, mappings):
    work = add_work(db, "Solo Leveling")
    entry = listing("mangadex", "Solo Leveling")
    binding = persist_listing(db, entry, work_id=work, decided_by="evidence")
    mappings.never_match(binding.listing_id, work)
    mappings.unlink(binding.listing_id)
    persist_listing(db, entry, work_id=work, decided_by="evidence")  # INV-04
    assert db.execute("SELECT work_id FROM source_listings WHERE id = ?", (binding.listing_id,)).fetchone()[0] is None


def test_results_represent_works_not_duplicated_source_cards(db):
    add_work(db, "Berserk")
    results = group_results(db, [listing("a", "Berserk"), listing("b", "Berserk", language="ar"),
                                 listing("c", "Berserk", language="ja")])
    assert len(results) == 1 and len(results[0].provenance) == 3
    assert results[0].availability == {"en": 1, "ar": 1, "ja": 1}


def test_evidence_never_overrides_a_user_mapping(db):
    chosen = add_work(db, "Solo Leveling")
    other = add_work(db, "Solo Leveling Returns")
    entry = listing("mangadex", "Solo Leveling")
    binding = persist_listing(db, entry, work_id=chosen, decided_by="user")
    persist_listing(db, entry, work_id=other, decided_by="evidence")  # INV-04
    row = db.execute("SELECT work_id, mapping_decided_by FROM source_listings WHERE id = ?", (binding.listing_id,)).fetchone()
    assert row["work_id"] == chosen and row["mapping_decided_by"] == "user"
    # a later explicit user decision still wins
    persist_listing(db, entry, work_id=other, decided_by="user")
    assert db.execute("SELECT work_id FROM source_listings WHERE id = ?", (binding.listing_id,)).fetchone()[0] == other


def test_source_title_changes_keep_the_previous_title_as_history(db):
    work = add_work(db, "Solo Leveling")
    entry = listing("mangadex", "Solo Leveling")
    binding = persist_listing(db, entry, work_id=work, decided_by="user")
    renamed = listing("mangadex", "Solo Leveling (Official)", key=entry.listing_key)
    persist_listing(db, renamed, work_id=work, decided_by="evidence")
    aliases = {(r["title"], r["kind"]) for r in db.execute("SELECT title, kind FROM work_aliases WHERE work_id = ?", (work,))}
    assert ("Solo Leveling", "source_title") in aliases
    row = db.execute("SELECT raw_title FROM source_listings WHERE id = ?", (binding.listing_id,)).fetchone()
    assert row["raw_title"] == "Solo Leveling (Official)"
    # the old title still finds the work locally
    from oneshelf.search.index import search_local
    assert [r.work_id for r in search_local(db, "Solo Leveling")] == [work]
