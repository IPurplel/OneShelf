"""Import CBZ/PDF/EPUB into a Local Source Track (Master §4.6, §22, §37).

Flow: sniff → decide target (explicit Choose Work / Create Local Work; never an aggressive merge)
→ preflight root + space → copy into per-root staging → validate the staged copy → commit journal
→ (Move only) delete the original after the commit is done and the original is unchanged.
All database records are created inside the idempotent commit registration.
"""
from __future__ import annotations

import os
import shutil
import sqlite3
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

from oneshelf.db.connection import transaction
from oneshelf.domain.clock import utcnow_iso
from oneshelf.domain.ids import new_id
from oneshelf.integrity.validators import detect_format, validate
from oneshelf.settings.defaults import DEFAULTS
from oneshelf.storage.commit import CommitEngine, CommitError, CommitRequest
from oneshelf.storage.hashing import sha256_file
from oneshelf.storage.layout import asset_relative_path
from oneshelf.storage.roots import StorageRoot, check_availability, get_root, list_roots, preflight
from oneshelf.storage.staging import StagingError, new_staging_area

REGISTRAR_KIND = "local_import"
UNIT_TYPES = {"chapter", "special", "extra", "prologue", "epilogue", "one_shot", "other", "unknown"}
CONTENT_TYPES = {"manga", "manhwa", "manhua", "comic", "book", "novel", "paper", "other", "unknown"}


class ImportRejected(RuntimeError):
    pass


@dataclass(frozen=True)
class CreateLocalWork:
    title: str
    content_type: str = "unknown"
    language: str | None = None


@dataclass(frozen=True)
class ChooseWork:
    work_id: str


@dataclass(frozen=True)
class InspectResult:
    valid: bool
    format: str | None
    reason: str | None
    suggested_title: str
    language: str | None
    page_count: int | None
    warnings: list[str]


@dataclass
class ImportOutcome:
    import_id: str
    work_id: str
    track_id: str
    unit_id: str
    asset_id: str
    relative_path: str
    warnings: list[str] = field(default_factory=list)


def inspect_import(path: str | Path) -> InspectResult:
    path = Path(path)
    result = validate(path)
    return InspectResult(
        valid=result.ok,
        format=result.format,
        reason=result.reason,
        suggested_title=result.metadata.get("title") or path.stem,
        language=result.metadata.get("language"),
        page_count=result.page_count,
        warnings=result.warnings,
    )


def register_local_import(conn: sqlite3.Connection, p: dict) -> None:
    """Idempotent registration replayed by the commit journal."""
    work, unit, asset, now = p["work"], p["unit"], p["asset"], p["now"]
    if work["create"]:
        conn.execute(
            "INSERT OR IGNORE INTO works (id, display_title, content_type, content_type_source, created_at, updated_at)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            (work["id"], work["display_title"], work["content_type"], work["content_type_source"], now, now),
        )
    conn.execute(
        "INSERT OR IGNORE INTO source_tracks (id, work_id, source_id, language, kind, availability, created_at)"
        " VALUES (?, ?, 'local', ?, 'local', 'available', ?)",
        (p["track_id"], work["id"], p["language"], now),
    )
    track_id = conn.execute(
        "SELECT id FROM source_tracks WHERE work_id = ? AND source_id = 'local' AND language = ?",
        (work["id"], p["language"]),
    ).fetchone()[0]
    if unit["create"]:
        order = conn.execute(
            "SELECT coalesce(max(source_order), 0) + 1 FROM reading_units WHERE track_id = ?", (track_id,)
        ).fetchone()[0]
        conn.execute(
            "INSERT OR IGNORE INTO reading_units (id, track_id, source_unit_key, raw_title, display_title, unit_type,"
            " source_order, availability, first_seen_at) VALUES (?, ?, ?, ?, ?, ?, ?, 'available', ?)",
            (unit["id"], track_id, f"import:{p['import_id']}", unit["label"], unit["label"], unit["unit_type"], order, now),
        )
    conn.execute(
        "INSERT OR IGNORE INTO assets (id, reading_unit_id, format, storage_root_id, relative_path, size_bytes, sha256,"
        " page_count, integrity, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'ok', ?, ?)",
        (asset["id"], unit["id"], asset["format"], asset["storage_root_id"], asset["relative_path"],
         asset["size_bytes"], asset["sha256"], asset["page_count"], now, now),
    )
    if conn.execute("SELECT 1 FROM assets WHERE id = ?", (asset["id"],)).fetchone() is None:
        raise CommitError("asset registration conflicted with an existing record")
    if p["add_to_shelf"]:
        conn.execute("INSERT OR IGNORE INTO shelf_entries (work_id, added_at) VALUES (?, ?)", (work["id"], now))
    conn.execute(
        "UPDATE imports SET state = 'completed', work_id = ?, asset_id = ?, error = NULL, updated_at = ? WHERE id = ?",
        (work["id"], asset["id"], now, p["import_id"]),
    )


def registrars() -> dict:
    return {REGISTRAR_KIND: register_local_import}


def _set_import(conn, import_id: str, state: str, error: str | None = None) -> None:
    with transaction(conn):
        conn.execute(
            "UPDATE imports SET state = ?, error = ?, updated_at = ? WHERE id = ?", (state, error, utcnow_iso(), import_id)
        )


def _resolve_root(conn, root_id: str | None) -> StorageRoot:
    if root_id is not None:
        return get_root(conn, root_id)
    for root in list_roots(conn):
        if root.is_default:
            return root
    raise ImportRejected("no storage location configured")


def import_file(
    conn: sqlite3.Connection,
    source: str | Path,
    *,
    decision: CreateLocalWork | ChooseWork,
    mode: Literal["copy", "move"] = DEFAULTS.importing.default_mode,
    root_id: str | None = None,
    language: str | None = None,
    unit_id: str | None = None,
    unit_label: str | None = None,
    unit_type: str = "unknown",
    add_to_shelf: bool = True,
    fault: Callable[[str], None] | None = None,
) -> ImportOutcome:
    source = Path(source)
    if mode not in ("copy", "move"):
        raise ValueError(f"invalid import mode {mode!r}")
    if unit_type not in UNIT_TYPES:
        raise ValueError(f"invalid unit type {unit_type!r}")
    now = utcnow_iso()
    import_id = new_id()
    with transaction(conn):
        conn.execute(
            "INSERT INTO imports (id, original_filename, mode, state, created_at, updated_at)"
            " VALUES (?, ?, ?, 'validating', ?, ?)",
            (import_id, source.name, mode, now, now),
        )

    def reject(message: str, state: str = "rejected") -> ImportRejected:
        _set_import(conn, import_id, state, message)
        return ImportRejected(message)

    if not source.is_file() or source.is_symlink():
        raise reject("source is not a regular file")
    fmt = detect_format(source)
    if fmt is None:
        raise reject("unrecognized or unsupported format")

    # Target Work (explicit decision only).
    if isinstance(decision, ChooseWork):
        row = conn.execute("SELECT * FROM works WHERE id = ?", (decision.work_id,)).fetchone()
        if row is None:
            raise reject("chosen work does not exist")
        work = {"id": row["id"], "create": False, "display_title": row["display_title"],
                "content_type": row["content_type"], "content_type_source": row["content_type_source"]}
        decided_language = None
    else:
        if decision.content_type not in CONTENT_TYPES:
            raise ValueError(f"invalid content type {decision.content_type!r}")
        work = {"id": new_id(), "create": True, "display_title": decision.title.strip() or source.stem,
                "content_type": decision.content_type,
                "content_type_source": "user" if decision.content_type != "unknown" else "unknown"}
        decided_language = decision.language

    # Target Reading Unit.
    unit_language = None
    if unit_id is not None:
        row = conn.execute(
            "SELECT u.id, u.display_title, t.language FROM reading_units u JOIN source_tracks t ON t.id = u.track_id"
            " WHERE u.id = ? AND t.work_id = ? AND t.kind = 'local'",
            (unit_id, work["id"]),
        ).fetchone()
        if row is None:
            raise reject("chosen reading unit does not belong to this work's local track")
        if conn.execute("SELECT 1 FROM assets WHERE reading_unit_id = ? AND format = ?", (unit_id, fmt)).fetchone():
            raise reject(f"this reading unit already has a {fmt} file; it will not be replaced")
        unit = {"id": unit_id, "create": False, "label": row["display_title"], "unit_type": unit_type}
        unit_language = row["language"]
    else:
        unit = {"id": new_id(), "create": True, "label": (unit_label or source.stem).strip() or source.stem,
                "unit_type": unit_type}

    # Root and space preflight.
    try:
        root = _resolve_root(conn, root_id)
    except ImportRejected as exc:
        raise reject(str(exc), "failed") from exc
    availability = check_availability(root)
    if not availability.available:
        raise reject(f"storage location unavailable ({availability.reason})", "failed")
    usage = shutil.disk_usage(root.path)
    size = source.stat().st_size
    if not preflight(total=usage.total, free=usage.free, expected_bytes=size, override=root.reserve_override_bytes).allowed:
        raise reject("not enough free space above the storage reserve", "failed")

    # Stage and validate the copy (not the original, which could change underneath us).
    try:
        area, area_rel = new_staging_area(root, purpose="import", owner_id=import_id)
    except StagingError as exc:
        raise reject(str(exc), "failed") from exc
    staged = area / f"artifact.{fmt}"
    with open(source, "rb") as src, open(staged, "wb") as dst:
        shutil.copyfileobj(src, dst, length=1024 * 1024)
        dst.flush()
        os.fsync(dst.fileno())
    result = validate(staged)
    if not result.ok or result.format != fmt:
        shutil.rmtree(area)
        raise reject(result.reason or "file changed during import")

    language = language or decided_language or unit_language or result.metadata.get("language") or "und"
    if unit_language is not None and language != unit_language:
        shutil.rmtree(area)
        raise reject("language does not match the chosen reading unit's track")

    relative_path = asset_relative_path(
        work["content_type"], work["display_title"], work["id"], language, "local", unit["label"], unit["id"], fmt
    )
    sha, staged_size = sha256_file(staged)
    asset_id = new_id()
    payload = {
        "import_id": import_id, "now": utcnow_iso(), "language": language, "track_id": new_id(),
        "work": work, "unit": unit, "add_to_shelf": add_to_shelf,
        "asset": {"id": asset_id, "format": fmt, "storage_root_id": root.id, "relative_path": relative_path,
                  "size_bytes": staged_size, "sha256": sha, "page_count": result.page_count},
    }
    _set_import(conn, import_id, "committing")
    engine = CommitEngine(conn, registrars=registrars(), fault=fault)
    try:
        engine.commit(
            CommitRequest(root_id=root.id, staging_relpath=f"{area_rel}/{staged.name}", final_relpath=relative_path,
                          registration={"kind": REGISTRAR_KIND, "payload": payload})
        )
    except CommitError as exc:
        raise reject(f"commit failed: {exc}", "failed") from exc
    shutil.rmtree(area, ignore_errors=True)

    warnings = list(result.warnings)
    if mode == "move":
        if sha256_file(source) == (sha, staged_size):
            source.unlink()
        else:
            warnings.append("the original changed during import and was kept")

    track_id = conn.execute(
        "SELECT track_id FROM reading_units WHERE id = ?", (unit["id"],)
    ).fetchone()[0]
    return ImportOutcome(import_id, work["id"], track_id, unit["id"], asset_id, relative_path, warnings)
