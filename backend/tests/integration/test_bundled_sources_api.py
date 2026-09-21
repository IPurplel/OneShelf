"""A fresh OneShelf opens with its official sources already there (release requirement, 2026-09-21).

This is the path a person actually takes: the application starts, and the Sources screen and First Run
read what the bootstrap left behind. Nothing here builds or uploads a package by hand.
"""
from pathlib import Path

import pytest
from starlette.testclient import TestClient

from oneshelf.api.app import AppConfig, create_app

OFFICIAL = Path(__file__).resolve().parents[2] / "plugins" / "official"
EIGHT = ["oneshelf.3asq", "oneshelf.arxiv", "oneshelf.gutenberg", "oneshelf.hindawi", "oneshelf.mangadex",
         "oneshelf.standard-ebooks", "oneshelf.tapas", "oneshelf.webtoon"]


def config(tmp_path, bundled=OFFICIAL):
    return AppConfig.from_env({
        "ONESHELF_DATA_DIR": str(tmp_path / "data"),
        "ONESHELF_ALLOWED_HOSTS": "testserver",
        "ONESHELF_SESSION_KEY_FILE": str(tmp_path / "keys" / "session.key"),
        "ONESHELF_BUNDLED_PLUGINS_DIR": str(bundled) if bundled else "",
    })


def start(tmp_path, **kwargs):
    return TestClient(create_app(config(tmp_path, **kwargs)), client=("127.0.0.1", 50000))


def test_a_fresh_start_lists_all_eight_official_sources_as_active(tmp_path):
    with start(tmp_path) as client:
        sources = client.get("/api/sources").json()["sources"]
    assert sorted(s["id"] for s in sources) == EIGHT
    for source in sources:
        assert (source["state"], source["trust_label"], source["channel"]) == ("active", "official", "bundled")
        assert source["capabilities"], f"{source['id']} loaded without capabilities"


def test_first_run_counts_the_sources_that_are_actually_active(tmp_path):
    with start(tmp_path) as client:
        assert client.get("/api/first-run").json()["sources_installed"] == 8
        client.delete("/api/sources/oneshelf.tapas")                       # the person removes one
        assert client.get("/api/first-run").json()["sources_installed"] == 7


def test_restarting_the_application_keeps_the_person_s_choices(tmp_path):
    with start(tmp_path) as client:
        assert client.post("/api/sources/oneshelf.webtoon/disable").status_code == 200
        assert client.delete("/api/sources/oneshelf.3asq").status_code in (200, 204)
    for _ in range(2):                                                     # restart, twice
        with start(tmp_path) as client:
            states = {s["id"]: s["state"] for s in client.get("/api/sources").json()["sources"]}
    assert states["oneshelf.webtoon"] == "disabled"
    assert states["oneshelf.3asq"] == "uninstalled"
    assert sum(1 for s in states.values() if s == "active") == 6


def test_readiness_reports_the_bootstrap_and_is_not_blocked_by_it(tmp_path):
    with start(tmp_path) as client:
        ready = client.get("/api/ready").json()
    assert ready["ready"] is True
    bundled = ready["bundled_sources"]
    assert sorted(bundled["installed"]) == EIGHT and bundled["failed"] == []


def test_a_broken_official_adapter_degrades_one_source_and_the_library_still_starts(tmp_path):
    """§3.3: local content never depends on a source, so a failed adapter must not block readiness."""
    import shutil

    bundled = tmp_path / "bundled"
    for name in ("oneshelf.gutenberg", "oneshelf.arxiv"):
        shutil.copytree(OFFICIAL / name, bundled / name)
    (bundled / "oneshelf.arxiv" / "manifest.yaml").write_text("schema: nonsense\n", encoding="utf-8")
    with start(tmp_path, bundled=bundled) as client:
        ready = client.get("/api/ready").json()
        assert ready["ready"] is True
        assert ready["bundled_sources"]["failed"] == ["oneshelf.arxiv"]
        assert [s["id"] for s in client.get("/api/sources").json()["sources"]] == ["oneshelf.gutenberg"]
        attention = client.get("/api/notifications?attention=true").json()["notifications"]
        assert [n["dedupe_key"] for n in attention] == ["source-bootstrap:oneshelf.arxiv"]


def test_without_a_bundled_directory_the_application_installs_nothing(tmp_path):
    """Development and the test suite start with an empty library unless a directory is given."""
    with start(tmp_path, bundled=None) as client:
        assert client.get("/api/sources").json()["sources"] == []
        assert client.get("/api/ready").json()["bundled_sources"] == {"installed": [], "failed": [],
                                                                      "pending_review": []}
