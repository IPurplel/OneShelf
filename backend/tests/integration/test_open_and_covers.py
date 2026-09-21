"""Opening a search result, and the covers that go with it — against the live Test Source.

Both defects were found on the real UI (2026-09-21): a live result with no Work yet could be seen but not
opened, and no cover reached a single screen. Opening is an explicit choice of one concrete listing: it binds
exactly that listing, never the others it was shown with, and brings its details and catalogue so the Work can
be read at once. Covers are presentation that belongs to a listing (INV-28): they never group, match or merge
anything, and the browser only ever sees a same-origin path that Core serves through the source's own network
policy.
"""
import json
import sqlite3
from contextlib import closing
from urllib.parse import parse_qs, quote, urlsplit

import pytest

from oneshelf.search.grouping import LiveListing, group_results, persist_listing

from .test_library_api import TS, api  # noqa: F401  (the live Test Source fixture)

COVER = "http://cdn.testsource.example/covers/irregular.png"


def search(client, q):
    raw = client.get("/api/search", params={"q": q}).text
    return json.loads([l for l in raw.splitlines() if l.startswith("data: ")][-1][6:])


def durable(tmp_path):
    with closing(sqlite3.connect(tmp_path / "data" / "oneshelf.db")) as conn:
        return {t: conn.execute(f"SELECT count(*) FROM {t}").fetchone()[0]
                for t in ("works", "source_listings", "source_tracks", "work_mappings")}


def result_for(results, title):
    return next(r for r in results["results"] if r["title"] == title)


def open_listing(client, provenance, **extra):
    body = {"source_id": provenance["source_id"], "listing_key": provenance["listing_key"],
            "title": provenance["title"], "url": provenance["url"], "language": provenance["language"],
            "cover_url": provenance.get("cover_url"), **extra}
    return client.post("/api/listings/open", json=body)


def cover_request(client, url, source=TS, **headers):
    return client.get(f"/api/covers?source={source}&url={quote(url, safe='')}", headers=headers)


# -- search: shown, never stored ---------------------------------------------------------------------------------

def test_displaying_search_results_creates_nothing_durable(api):
    client, tmp_path = api
    before = durable(tmp_path)
    results = search(client, "chronicle")
    assert results["results"] and all(r["work_id"] is None for r in results["results"])
    assert durable(tmp_path) == before


def test_a_result_carries_its_source_cover_as_a_same_origin_path(api):
    client, _ = api
    result = result_for(search(client, "chronicle"), "The Irregular Chronicle")
    cover = result["cover_url"]
    assert cover.startswith("/api/covers?")
    query = parse_qs(urlsplit(cover).query)
    assert query == {"source": [TS], "url": [COVER]}
    assert result["provenance"][0]["cover_url"] == cover


# -- opening: exactly one listing, and something to read -----------------------------------------------------

def test_opening_an_unbound_result_binds_exactly_it_and_brings_its_units(api):
    client, tmp_path = api
    result = result_for(search(client, "chronicle"), "The Irregular Chronicle")
    opened = open_listing(client, result["provenance"][0])
    assert opened.status_code == 200, opened.text
    body = opened.json()
    assert body["work_id"] and body["track_id"] and body["catalog"] == "refreshed"
    details = client.get(f"/api/works/{body['work_id']}", params={"track_id": body["track_id"]}).json()
    assert details["selected_track_id"] == body["track_id"]
    assert len(details["units"]) == 9
    assert details["tracks"][0]["source_id"] == TS and details["tracks"][0]["language"] == "en"
    assert details["cover_url"] == result["cover_url"]
    assert durable(tmp_path)["source_listings"] == 1


def test_opening_one_provenance_leaves_everything_else_unbound(api):
    client, tmp_path = api
    results = search(client, "a")                          # several unrelated works
    assert len(results["results"]) > 1
    chosen = result_for(results, "The Irregular Chronicle")["provenance"][0]
    open_listing(client, chosen)
    with closing(sqlite3.connect(tmp_path / "data" / "oneshelf.db")) as conn:
        keys = [r[0] for r in conn.execute("SELECT source_listing_key FROM source_listings")]
        mappings = conn.execute("SELECT count(*) FROM work_mappings").fetchone()[0]
    assert keys == ["irregular"] and mappings == 0


def test_opening_again_reuses_the_same_work_and_track(api):
    client, tmp_path = api
    provenance = result_for(search(client, "chronicle"), "The Irregular Chronicle")["provenance"][0]
    first, second = open_listing(client, provenance).json(), open_listing(client, provenance).json()
    assert (first["work_id"], first["track_id"]) == (second["work_id"], second["track_id"])
    assert second["catalog"] == "present"                  # units already there: the source is not asked again
    assert durable(tmp_path)["works"] == 1 and durable(tmp_path)["source_tracks"] == 1


def test_the_language_chosen_is_the_track_created(api):
    client, _ = api
    result = result_for(search(client, "القمر"), "حكاية القمر")
    body = open_listing(client, result["provenance"][0]).json()
    track = client.get(f"/api/works/{body['work_id']}").json()["tracks"][0]
    assert (track["source_id"], track["language"], track["unit_count"]) == (TS, "ar", 3)


def test_an_opened_unit_opens_in_the_reader(api):
    client, _ = api
    body = open_listing(client, result_for(search(client, "chronicle"), "The Irregular Chronicle")["provenance"][0]).json()
    unit = client.get(f"/api/works/{body['work_id']}").json()["units"][1]
    pages = client.get(f"/api/reader/units/{unit['id']}/pages")
    assert pages.status_code == 200 and pages.json()["pages"]
    page = client.get(f"/api/reader/units/{unit['id']}/pages/1")
    assert page.status_code == 200 and page.content[:4] == b"\x89PNG"


def test_a_catalogue_that_needs_a_session_still_opens_the_work(api):
    client, _ = api
    result = result_for(search(client, "members"), "Members Only")
    body = open_listing(client, result["provenance"][0])
    assert body.status_code == 200
    assert body.json()["work_id"] and body.json()["catalog"] == "session_required"


def test_open_refuses_a_source_that_is_not_installed(api):
    client, _ = api
    response = client.post("/api/listings/open", json={"source_id": "oneshelf.nope", "listing_key": "x", "title": "X"})
    assert response.status_code == 409


# -- covers: stored with the listing, chosen for presentation, never identity ----------------------------------

def test_a_known_cover_is_not_erased_by_a_result_without_one(db):
    listing = LiveListing(TS, "irregular", "The Irregular Chronicle", cover_url=COVER)
    persist_listing(db, listing)
    persist_listing(db, LiveListing(TS, "irregular", "The Irregular Chronicle"))
    assert db.execute("SELECT cover_url FROM source_listings").fetchone()[0] == COVER
    persist_listing(db, LiveListing(TS, "irregular", "The Irregular Chronicle", cover_url=COVER + "?v=2"))
    assert db.execute("SELECT cover_url FROM source_listings").fetchone()[0] == COVER + "?v=2"


def test_covers_never_group_or_split_results(db):
    same_cover = "http://cdn.testsource.example/covers/shared.png"
    groups = group_results(db, [
        LiveListing(TS, "a", "Alpha Story", cover_url=same_cover),
        LiveListing(TS, "b", "Beta Story", cover_url=same_cover),                 # same cover, different work
        LiveListing("oneshelf.other", "a2", "Alpha Story", cover_url="http://x.example/other.png"),
    ])
    assert sorted(len(g.provenance) for g in groups) == [1, 2]
    alpha = next(g for g in groups if g.title == "Alpha Story")
    assert [p.cover_url for p in alpha.provenance] == [same_cover, "http://x.example/other.png"]


def test_work_details_follow_the_selected_tracks_cover(api):
    client, _ = api
    irregular = result_for(search(client, "chronicle"), "The Irregular Chronicle")
    opened = open_listing(client, irregular["provenance"][0]).json()
    other_cover = f"/api/covers?source={TS}&url={quote('http://cdn.testsource.example/covers/arabic.png', safe='')}"
    second = client.post("/api/listings/bind", json={
        "source_id": TS, "listing_key": "arabic", "title": "حكاية القمر", "language": "ar",
        "work_id": opened["work_id"], "cover_url": other_cover}).json()
    first_view = client.get(f"/api/works/{opened['work_id']}", params={"track_id": opened["track_id"]}).json()
    second_view = client.get(f"/api/works/{opened['work_id']}", params={"track_id": second["track_id"]}).json()
    assert first_view["cover_url"] == irregular["cover_url"]
    assert second_view["cover_url"] == other_cover


def test_shelf_and_home_show_the_known_cover(api):
    client, _ = api
    irregular = result_for(search(client, "chronicle"), "The Irregular Chronicle")
    opened = open_listing(client, irregular["provenance"][0]).json()
    assert client.post(f"/api/shelf/{opened['work_id']}", json={}).status_code in (200, 201)
    entry = client.get("/api/shelf").json()["entries"][0]
    assert entry["cover_url"] == irregular["cover_url"]
    home = client.get("/api/home").json()
    assert home["recently_added"][0]["cover_url"] == irregular["cover_url"]


def test_a_work_with_no_known_cover_has_none(api):
    client, _ = api
    bound = client.post("/api/listings/bind", json={"source_id": TS, "listing_key": "manual", "title": "The Manual",
                                                    "language": "en"}).json()
    assert client.get(f"/api/works/{bound['work_id']}").json()["cover_url"] is None


# -- the cover route: the source's network policy, an image, and nothing else -----------------------------------

def test_a_cover_is_served_same_origin_as_a_safe_image(api):
    client, _ = api
    response = cover_request(client, COVER)
    assert response.status_code == 200 and response.content[:4] == b"\x89PNG"
    assert response.headers["content-type"] == "image/png"
    assert response.headers["x-content-type-options"] == "nosniff"
    assert "sandbox" in response.headers["content-security-policy"]
    assert response.headers["cross-origin-resource-policy"] == "same-origin"


@pytest.mark.parametrize("url", [
    "http://unapproved.example/cover.png",                    # outside the plugin's domains and CDNs
    "http://127.0.0.1/cover.png",                             # loopback literal
    "http://169.254.169.254/latest/meta-data",                # link-local metadata
    "http://10.0.0.8/cover.png",                              # private network
    "http://testsource.example/redirect-out",                 # an allowed host redirecting away
])
def test_a_cover_cannot_leave_the_sources_network_policy(api, url):
    client, _ = api
    assert cover_request(client, url).status_code in (403, 404, 502)


@pytest.mark.parametrize("path", ["/media/html-as-image.png", "/media/corrupt.png"])
def test_something_that_is_not_an_image_is_refused(api, path):
    client, _ = api
    assert cover_request(client, f"http://testsource.example{path}").status_code == 415


def test_an_oversized_cover_is_refused(api, monkeypatch):
    from oneshelf.api import covers
    monkeypatch.setattr(covers, "MAX_COVER_BYTES", 64)
    client, _ = api
    assert cover_request(client, COVER).status_code == 413


@pytest.mark.parametrize("url", ["file:///etc/passwd", "javascript:alert(1)", "ftp://cdn.testsource.example/x.png", ""])
def test_only_web_addresses_are_accepted(api, url):
    client, _ = api
    assert cover_request(client, url).status_code == 422


def test_an_unknown_source_has_no_covers(api):
    client, _ = api
    assert cover_request(client, COVER, source="oneshelf.nope").status_code == 404


def test_another_site_cannot_use_the_library_to_fetch_images(api):
    client, _ = api
    assert cover_request(client, COVER, **{"Sec-Fetch-Site": "cross-site"}).status_code == 403
    assert cover_request(client, COVER, **{"Sec-Fetch-Site": "same-origin"}).status_code == 200


# -- a source that cannot answer never costs the person the Work (found in the real-browser check) -------------

def test_a_source_that_cannot_answer_still_leaves_an_openable_work(api):
    client, _ = api
    response = client.post("/api/listings/open", json={"source_id": TS, "listing_key": "no-such-work",
                                                       "title": "Gone Upstream", "language": "en"})
    assert response.status_code == 200, response.text
    body = response.json()
    assert (body["details"], body["catalog"]) == ("failed", "failed")
    assert client.get(f"/api/works/{body['work_id']}").status_code == 200


def test_a_transport_failure_during_open_is_reported_not_raised(api, monkeypatch):
    from oneshelf.net.http import FetchFailed
    client, _ = api
    service = client.app.state.services.source_service
    original = service.run

    async def flaky(plugin_id, capability, inputs, **kwargs):
        if capability == "catalog":
            raise FetchFailed("SocketTimeoutError: Timeout on reading data from socket")
        return await original(plugin_id, capability, inputs, **kwargs)

    monkeypatch.setattr(service, "run", flaky)
    response = client.post("/api/listings/open", json={"source_id": TS, "listing_key": "irregular",
                                                       "title": "The Irregular Chronicle", "language": "en"})
    assert response.status_code == 200 and response.json()["catalog"] == "failed"


def test_a_single_document_capability_reports_page_failures_as_capability_errors(api):
    """The runtime's contract is CapabilityError; its private page failure used to escape it as a 500."""
    client, _ = api
    response = client.post("/api/resolve-url", json={"url": "http://testsource.example/work/no-such-work"})
    assert response.status_code == 502, response.text
    assert response.json()["error"]["message"].startswith("not_found")
