"""Live: the product's own journey for sequential sources (I-92, I-93).

Unlike `test_source_suite.py`, which calls recipes directly, these tests go exactly where a person goes: the
real application with the bundled adapters, a search or a pasted URL, opening the result with the payload the
web UI sends (it echoes the result's language and type and nothing else), then one chapter downloaded through
the normal Download Engine. Nothing supplies a content type that the product itself did not derive, which is
how I-93 stayed hidden from the suite. One small unit per source; the artifact is opened, not just counted.
"""
import json
import os
import time
import zipfile
from pathlib import Path

import pytest
from starlette.testclient import TestClient

from oneshelf.api.app import AppConfig, create_app

pytestmark = pytest.mark.live

LIVE = os.environ.get("ONESHELF_LIVE_SOURCES") == "1"
skip_unless_live = pytest.mark.skipif(not LIVE, reason="set ONESHELF_LIVE_SOURCES=1 to run live source checks")
BUNDLED = Path(__file__).resolve().parents[2] / "plugins" / "official"
IMAGE_SUFFIXES = (".png", ".jpg", ".jpeg", ".webp", ".gif")


@pytest.fixture
def app(tmp_path):
    config = AppConfig.from_env({"ONESHELF_DATA_DIR": str(tmp_path / "data"), "ONESHELF_ALLOWED_HOSTS": "testserver",
                                 "ONESHELF_SESSION_KEY_FILE": str(tmp_path / "keys" / "session.key"),
                                 "ONESHELF_BUNDLED_PLUGINS_DIR": str(BUNDLED)})
    with TestClient(create_app(config), client=("127.0.0.1", 50000)) as client:
        (tmp_path / "library").mkdir()
        assert client.post("/api/storage/roots", json={"name": "Library",
                                                      "path": str(tmp_path / "library")}).status_code == 200
        yield client, tmp_path


def search(client, query, source_id):
    raw = client.get("/api/search", params={"q": query}).text
    final = json.loads([line for line in raw.splitlines() if line.startswith("data: ")][-1][6:])
    for result in final["results"]:
        for provenance in result["provenance"]:
            if provenance["source_id"] == source_id:
                return result, provenance
    status = final["source_status"].get(source_id, {})
    pytest.skip(f"{source_id} returned nothing for {query!r} right now: {status}")


def by_url(client, url):
    resolved = client.post("/api/resolve-url", json={"url": url})
    if resolved.status_code != 200:
        pytest.skip(f"{url} could not be resolved right now: {resolved.text[:200]}")
    result = resolved.json()["result"]
    return result, result["provenance"][0]


def open_as_the_ui_does(client, result, provenance):
    opened = client.post("/api/listings/open", json={
        "source_id": provenance["source_id"], "listing_key": provenance["listing_key"], "title": provenance["title"],
        "url": provenance["url"], "language": provenance["language"], "content_type": result["content_type"],
        "cover_url": provenance.get("cover_url")})
    assert opened.status_code == 200, opened.text
    if opened.json()["catalog"] != "refreshed":
        pytest.skip(f"catalogue unavailable right now: {opened.json()['catalog_reason']}")
    return client.get(f"/api/works/{opened.json()['work_id']}").json()


def download_one(client, tmp_path, unit_id):
    batch = client.post("/api/downloads", json={"unit_ids": [unit_id]})
    assert batch.status_code == 200, batch.text
    deadline = time.monotonic() + 240
    while time.monotonic() < deadline:
        state = client.get(f"/api/downloads/{batch.json()['batch_id']}").json()
        if state["state"] not in ("active",):
            break
        time.sleep(2)
    job = state["jobs"][0]
    if job["error_category"] in ("transport", "timeout", "rate_limit"):
        pytest.skip(f"source unreachable right now: {job['error_category']} {job['last_error']}")
    assert job["state"] == "COMPLETED", job
    files = [p for p in (tmp_path / "library").rglob("*.cbz") if ".oneshelf" not in p.parts]
    assert len(files) == 1
    with zipfile.ZipFile(files[0]) as archive:
        assert archive.testzip() is None
        pages = [n for n in archive.namelist() if n.lower().endswith(IMAGE_SUFFIXES)]
    assert pages, "a CBZ with no pages is not a chapter"
    return files[0], pages


def assert_classified(work, *, language, content_types):
    assert work["work"]["content_type"] in content_types, work["work"]
    assert work["work"]["content_type_source"] in ("source", "plugin_default")
    assert [t["language"] for t in work["tracks"]] == [language]


@skip_unless_live
def test_mangadex_from_search_downloads_a_chapter_as_cbz(app):
    client, tmp_path = app
    result, provenance = search(client, "Oneshot", "oneshelf.mangadex")
    work = open_as_the_ui_does(client, result, provenance)
    assert work["units"], "a chapter list"
    download_one(client, tmp_path, work["units"][0]["id"])


@skip_unless_live
def test_3asq_from_an_arabic_search_is_arabic_manga_and_downloads_as_cbz(app):
    client, tmp_path = app
    result, provenance = search(client, "ون بيس", "oneshelf.3asq")
    work = open_as_the_ui_does(client, result, provenance)
    assert_classified(work, language="ar", content_types={"manga"})
    # Older 3asq chapters have lost their images at the source; the newest is the one still served.
    download_one(client, tmp_path, work["units"][-1]["id"])


@skip_unless_live
def test_webtoon_from_a_url_downloads_an_episode_as_cbz(app):
    client, tmp_path = app
    result, provenance = by_url(client, "https://www.webtoons.com/en/comedy/safely-endangered/list?title_no=352")
    work = open_as_the_ui_does(client, result, provenance)
    assert [t["language"] for t in work["tracks"]] == ["en"]
    download_one(client, tmp_path, work["units"][0]["id"])


@skip_unless_live
def test_tapas_from_a_url_is_comic_and_downloads_an_episode_as_cbz(app):
    client, tmp_path = app
    result, provenance = by_url(client, "https://tapas.io/series/534/info")
    work = open_as_the_ui_does(client, result, provenance)
    assert_classified(work, language="en", content_types={"comic"})
    download_one(client, tmp_path, work["units"][0]["id"])
