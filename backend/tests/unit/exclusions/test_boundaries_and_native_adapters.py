"""§9.6, §52, §50: what the architecture promised, held mechanically.

A subsystem that knows a source's name has stopped being generic, and a native adapter that nobody
reviewed has stopped being an exception. Both are easy to add by accident and hard to notice later.
"""
import importlib.util
import re

from .conftest import BACKEND, code_lines, python_sources

# The §41 suite, by name. None of these may appear in the generic machinery.
SOURCE_NAMES = re.compile(r"\b(mangadex|3asq|aasheq|webtoon|tapas|safahat|hindawi|gutenberg|arxiv|"
                          r"standardebooks|standard_ebooks)\b", re.IGNORECASE)
GENERIC = ("downloads", "storage", "db", "reader", "library", "follow", "backup", "export")
WASM_PACKAGES = ["wasmtime", "wasmer", "pywasm", "wasm3"]


def test_the_generic_machinery_never_names_a_source():
    """§52: source-specific logic lives in .osp packages, never in the queue, the store or the schema."""
    offenders = []
    for directory in GENERIC:
        for path, number, line in code_lines(sorted((BACKEND / "oneshelf" / directory).rglob("*.py"))):
            if SOURCE_NAMES.search(line):
                offenders.append(f"{path.relative_to(BACKEND)}:{number}: {line.strip()}")
    assert offenders == []


def test_the_schema_never_names_a_source_either():
    offenders = [f"{path.name}:{number}"
                 for path in sorted((BACKEND / "oneshelf" / "db" / "schema").glob("*.sql"))
                 for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1)
                 if SOURCE_NAMES.search(line) and not line.strip().startswith("--")]
    assert offenders == []


def test_there_are_no_native_adapters_by_default():
    """§9.6: a native adapter is a rare reviewed exception, so the default state is none at all."""
    native = BACKEND / "oneshelf" / "plugins" / "native"
    assert not native.exists() or [p for p in native.rglob("*.py") if p.name != "__init__.py"] == []
    offenders = [f"{path.relative_to(BACKEND)}:{number}: {line.strip()}"
                 for path, number, line in code_lines(python_sources())
                 if re.search(r"\bnative_adapter|NativeAdapter|load_native\b", line)]
    assert offenders == []


def test_no_wasm_runtime_is_installed():
    """§9.6, §50: WASM is not v1, and a runtime in the tree is how it arrives early."""
    assert [n for n in WASM_PACKAGES if importlib.util.find_spec(n) is not None] == []


def test_unknown_is_never_treated_as_unavailable(db):
    """INV-06, §3.2: unknown quality or metadata does not hide, reject or block content."""
    from oneshelf.domain.ids import new_id

    now = "2026-01-01T00:00:00+00:00"
    work, track = new_id(), new_id()
    db.execute("INSERT INTO works (id, display_title, content_type, created_at, updated_at) VALUES (?,?,?,?,?)",
               (work, "A Work With Unknowns", "unknown", now, now))
    db.execute("INSERT INTO source_tracks (id, work_id, source_id, language, kind, created_at)"
               " VALUES (?,?,?,?,?,?)", (track, work, "some-source", "en", "source", now))
    unknown, available = new_id(), new_id()
    for unit_id, availability in ((unknown, "unknown"), (available, "available")):
        db.execute("INSERT INTO reading_units (id, track_id, source_unit_key, display_title, unit_type,"
                   " source_order, availability, first_seen_at) VALUES (?,?,?,?,?,?,?,?)",
                   (unit_id, track, unit_id, "A Unit", "unknown", 1.0, availability, now))

    from oneshelf.api.works import _units

    units = _units(db, track)
    assert {u["id"] for u in units} == {unknown, available}, "an unknown unit was hidden"
    shown = next(u for u in units if u["id"] == unknown)
    assert shown["availability"] == "unknown" and shown["availability"] != "unavailable"
    assert shown["integrity"] == "none"        # nothing downloaded yet — which is not "bad quality"
