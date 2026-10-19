"""I-92 (BE-002), I-94 (BE-004): one classifier for every entry path, one track per listing and language.

Master §9.2: user override > explicit source classification > plugin default > Unknown. The Test Source's
`unlabelled` work says nothing of its type or language, like 3asq and Safahat in the field, so only the
plugin's declared defaults (`en`, `manga`) can classify it. The requests below are the ones the web UI sends.
"""
import json
import sqlite3
from contextlib import closing

from .test_library_api import TS, api  # noqa: F401  (the live Test Source fixture)


def search(client, q):
    raw = client.get("/api/search", params={"q": q}).text
    return json.loads([l for l in raw.splitlines() if l.startswith("data: ")][-1][6:])


def open_as_the_ui_does(client, result, provenance):
    return client.post("/api/listings/open", json={
        "source_id": provenance["source_id"], "listing_key": provenance["listing_key"], "title": provenance["title"],
        "url": provenance["url"], "language": provenance["language"], "content_type": result["content_type"],
        "cover_url": provenance.get("cover_url")})


def tracks(tmp_path, listing_key):
    with closing(sqlite3.connect(tmp_path / "data" / "oneshelf.db")) as conn:
        return sorted(r[0] for r in conn.execute(
            "SELECT t.language FROM source_tracks t JOIN source_listings l ON l.id = t.listing_id"
            " WHERE l.source_listing_key = ?", (listing_key,)))


def test_i92_search_results_carry_the_plugin_defaults_when_the_source_is_silent(api):
    client, _ = api
    result = next(r for r in search(client, "unlabelled")["results"] if r["title"] == "Unlabelled Scans")
    assert result["content_type"] == "manga"
    assert [p["language"] for p in result["provenance"]] == ["en"]


def test_i92_an_explicit_source_value_still_beats_the_default(api):
    client, _ = api
    result = next(r for r in search(client, "قمر")["results"] if r["title"] == "حكاية القمر")
    assert result["content_type"] == "manga" and result["provenance"][0]["language"] == "ar"


def test_i92_opening_records_the_classification_and_where_it_came_from(api):
    client, tmp_path = api
    result = next(r for r in search(client, "unlabelled")["results"] if r["title"] == "Unlabelled Scans")
    opened = open_as_the_ui_does(client, result, result["provenance"][0])
    assert opened.status_code == 200, opened.text
    work = client.get(f"/api/works/{opened.json()['work_id']}").json()
    assert work["work"]["content_type"] == "manga" and work["work"]["content_type_source"] == "plugin_default"
    assert [t["language"] for t in work["tracks"]] == ["en"]


def test_i94_a_listing_opened_without_language_and_again_with_it_has_one_track(api):
    client, tmp_path = api
    bare = {"source_id": TS, "listing_key": "unlabelled", "title": "Unlabelled Scans",
            "url": "http://testsource.example/work/unlabelled"}
    first = client.post("/api/listings/open", json=bare)                 # an older client, or a bookmark
    second = client.post("/api/listings/open", json={**bare, "language": "en", "content_type": "manga"})
    assert first.status_code == second.status_code == 200
    assert first.json()["track_id"] == second.json()["track_id"]
    assert tracks(tmp_path, "unlabelled") == ["en"]


def test_i94_an_unknown_language_track_from_before_is_upgraded_not_duplicated(api):
    """Data created before I-92: the track says `und`. Opening it now must not create an `en` twin."""
    from oneshelf.db.connection import open_database
    from oneshelf.search.grouping import LiveListing, persist_listing
    client, tmp_path = api
    with open_database(tmp_path / "data" / "oneshelf.db") as conn:
        conn.execute("INSERT INTO works (id, display_title, content_type, created_at, updated_at)"
                     " VALUES ('w-old', 'Unlabelled Scans', 'unknown', '2026-10-01', '2026-10-01')")
        old = persist_listing(conn, LiveListing(source_id=TS, listing_key="unlabelled", title="Unlabelled Scans"),
                              work_id="w-old", decided_by="user")
    assert tracks(tmp_path, "unlabelled") == ["und"]
    result = next(r for r in search(client, "unlabelled")["results"] if r["title"] == "Unlabelled Scans")
    opened = open_as_the_ui_does(client, result, result["provenance"][0])
    assert opened.json()["track_id"] == old.track_id
    assert tracks(tmp_path, "unlabelled") == ["en"]
