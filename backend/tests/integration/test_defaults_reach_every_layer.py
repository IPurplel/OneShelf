"""Meta Prompt D2 (DEF-other): one registry of defaults, and every layer reads it.

A default that is written down twice is a default that will disagree with itself. The registry holds
the approved values; the API serves them, the interface falls back to them, and nothing else in the
product spells them out again.
"""
import re
from pathlib import Path

import pytest
from starlette.testclient import TestClient

from oneshelf.api.app import AppConfig, create_app
from oneshelf.settings.defaults import DEFAULTS

BACKEND = Path(__file__).resolve().parents[2]
READER_SCREEN = BACKEND.parent / "frontend" / "src" / "features" / "reader" / "ReaderScreen.tsx"


@pytest.fixture
def api(tmp_path):
    config = AppConfig.from_env({"ONESHELF_DATA_DIR": str(tmp_path / "data"),
                                 "ONESHELF_ALLOWED_HOSTS": "testserver",
                                 "ONESHELF_SESSION_KEY_FILE": str(tmp_path / "keys" / "session.key")})
    with TestClient(create_app(config), client=("127.0.0.1", 50000)) as client:
        yield client


def test_the_api_serves_the_registry_rather_than_its_own_numbers(api):
    reader = api.get("/api/reader/settings").json()
    assert reader["auto_mark_read_threshold"] == DEFAULTS.reader.auto_mark_read_threshold
    assert reader["remember_per_work"] is DEFAULTS.reader.remember_per_work
    assert reader["preload_next"] == DEFAULTS.reader.preload_next
    assert reader["preload_previous"] == DEFAULTS.reader.preload_previous
    assert (reader["smart_controls_hide_after_ms"]
            == DEFAULTS.reader.smart_controls_hide_after.total_seconds() * 1000)

    auto = api.get("/api/downloads/settings").json()["auto_download"]
    assert auto["enabled"] is DEFAULTS.auto_download.enabled                     # INV-08: off
    assert auto["threshold"] == DEFAULTS.auto_download.engagement_threshold
    assert auto["read_ahead"] == DEFAULTS.auto_download.read_ahead_units

    diagnostics = api.get("/api/diagnostics").json()
    assert diagnostics["max_bytes"] == DEFAULTS.diagnostics.max_bytes
    assert diagnostics["max_age_days"] == DEFAULTS.diagnostics.max_age.days


def test_the_reader_falls_back_to_the_same_numbers_the_library_would_have_given():
    """The interface holds a fallback for the moment before the library answers. It must not drift."""
    source = READER_SCREEN.read_text(encoding="utf-8")
    fallback = re.search(r"const PRELOAD: ReaderDefaults = \{ preload_next: (\d+), preload_previous: (\d+) \}",
                         source)
    assert fallback is not None, "the reader's fallback is not where this test can check it"
    assert int(fallback.group(1)) == DEFAULTS.reader.preload_next
    assert int(fallback.group(2)) == DEFAULTS.reader.preload_previous


def test_no_other_module_writes_an_approved_default_down_again():
    values = {"0.97": "the auto-mark-read threshold", "0.12": "the engagement threshold"}
    offenders = []
    for path in (BACKEND / "oneshelf").rglob("*.py"):
        if path.name == "defaults.py":
            continue
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            bare = line.split("#", 1)[0]
            for literal, what in values.items():
                if literal in bare:
                    offenders.append(f"{path.relative_to(BACKEND)}:{number} repeats {what}")
    assert offenders == []
