"""Master §43, DEF-diagnostics: local operational diagnostics, redacted at write time and bounded."""
from datetime import datetime, timedelta, UTC

import pytest

from oneshelf.diagnostics.store import DiagnosticsStore


@pytest.fixture
def clock():
    return {"now": datetime(2026, 9, 19, 12, 0, tzinfo=UTC)}


@pytest.fixture
def store(tmp_path, clock):
    return DiagnosticsStore(tmp_path / "diagnostics", clock=lambda: clock["now"],
                            max_bytes=4096, max_age=timedelta(days=7))


def test_a_record_is_written_and_read_back(store):
    store.record("network", "fetched a page", {"source_id": "mangadex", "status": 200})
    entries = store.recent()
    assert len(entries) == 1
    assert entries[0]["category"] == "network" and entries[0]["message"] == "fetched a page"
    assert entries[0]["data"]["status"] == 200


def test_anything_sensitive_is_redacted_as_it_is_written(store, tmp_path):
    store.record("network", "request failed", {
        "url": "https://example.org/x?token=abcdef&page=2",
        "headers": {"Cookie": "session=secret", "Accept": "text/html"},
        "note": "authorization: Bearer abcdef.ghijk",
    })

    written = (tmp_path / "diagnostics").read_text() if (tmp_path / "diagnostics").is_file() else "".join(
        p.read_text() for p in (tmp_path / "diagnostics").iterdir())
    for secret in ("abcdef", "secret", "ghijk"):
        assert secret not in written, f"{secret!r} reached the diagnostics store"
    entry = store.recent()[0]
    assert entry["data"]["headers"]["Cookie"] == "[redacted]"
    assert "page=2" in entry["data"]["url"]          # what is useful is kept


def test_rotation_drops_by_age(store, clock):
    store.record("job", "old", {})
    clock["now"] += timedelta(days=8)
    store.record("job", "new", {})
    store.rotate()
    assert [e["message"] for e in store.recent()] == ["new"]


def test_rotation_drops_by_size_whichever_binds_first(store):
    for index in range(400):
        store.record("job", f"entry {index}", {"padding": "x" * 64})
    store.rotate()
    assert store.size_bytes() <= 4096
    messages = [e["message"] for e in store.recent()]
    assert messages and messages[-1] == "entry 399"        # the newest survive, the oldest go


def test_clearing_leaves_nothing_behind(store):
    store.record("job", "something", {})
    assert store.size_bytes() > 0
    store.clear()
    assert store.recent() == [] and store.size_bytes() == 0


def test_what_the_application_logs_reaches_the_store_redacted(store):
    """§43: the operational record is what the app already says about itself, kept locally."""
    import logging

    from oneshelf.diagnostics.store import DiagnosticsHandler

    logger = logging.getLogger("oneshelf.downloads.runner")
    handler = DiagnosticsHandler(store)
    logger.addHandler(handler)
    try:
        logger.warning("fetch failed for %s with cookie=%s", "https://example.org/x?token=abc", "session=secret")
    finally:
        logger.removeHandler(handler)

    entry = store.recent()[-1]
    assert entry["category"] == "job"                    # from the logger it came through
    assert "secret" not in json_dump(entry) and "abc" not in json_dump(entry)


def json_dump(value) -> str:
    import json
    return json.dumps(value, ensure_ascii=False)
