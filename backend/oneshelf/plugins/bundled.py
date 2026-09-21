"""The official source adapters that ship with OneShelf, installed on a fresh library (release requirement).

A person who runs `./install.sh` should open OneShelf to find its official sources already there. This is
how, and it is deliberately narrow:

* **The normal pipeline, nothing else.** Each adapter is built with the same deterministic builder as
  every official package and installed with `PluginManager.install_file` — validation, packaged tests,
  atomic store move, registration, activation. Nothing writes a plugin row or a store file directly.
* **Once.** A durable marker in `app_meta` records that the bootstrap has run. A restart, a rebuilt
  image, `./update.sh` or a recreated container never runs it again, so a source the person disabled or
  removed stays that way. Plugin rows are kept after uninstall (0002), and that row is the evidence.
* **Permissions are approved only for a first install.** The owner chose this behaviour, and it covers
  the declared permissions of the adapters as shipped. An update approves nothing new: a version that
  asks for more waits for review like any other plugin's, and the approved version keeps working.
* **Only what is still ours.** Updates apply to adapters that arrived this way and are active. A disabled
  one is left alone — installing a version activates it, so updating would quietly re-enable it — and one
  the person reinstalled by hand is theirs.
* **Contained failure.** A broken adapter is recorded, raised as Needs Attention, and never active; the
  others install normally and the library starts (§3.3: local content never depends on a source).
"""
from __future__ import annotations

import hashlib
import json
import logging
import sqlite3
import tempfile
import zipfile
from dataclasses import dataclass
from pathlib import Path

from oneshelf.db.connection import transaction
from oneshelf.domain.clock import utcnow_iso
from oneshelf.plugins.manager import InstallRejected, PluginManager, _vkey
from oneshelf.plugins.package import PackageError, PluginPackage, load_package

logger = logging.getLogger(__name__)

BOOTSTRAP_VERSION = 1
MARKER = "official_sources_bootstrap_version"
CHANNEL, TRUST = "bundled", "official"


# -- building ------------------------------------------------------------------------------------------

def discover(directory: str | Path) -> list[Path]:
    root = Path(directory)
    if not root.is_dir():
        return []
    return sorted(p for p in root.iterdir() if p.is_dir() and (p / "manifest.yaml").is_file())


def build_package(source_dir: str | Path, destination: str | Path) -> Path:
    """Deterministic `.osp`: sorted entries and a fixed timestamp, so the same sources are the same bytes.

    That is what lets a rebuilt image recognise its own adapters as already installed instead of
    offering them again as a new version.
    """
    source_dir, destination = Path(source_dir), Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(destination, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(p for p in source_dir.rglob("*") if p.is_file()):
            info = zipfile.ZipInfo(path.relative_to(source_dir).as_posix(), date_time=(2026, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            archive.writestr(info, path.read_bytes())
    return destination


# -- state ------------------------------------------------------------------------------------------------

def bootstrap_version(conn: sqlite3.Connection) -> int:
    row = conn.execute("SELECT value FROM app_meta WHERE key = ?", (MARKER,)).fetchone()
    return int(row[0]) if row else 0


def _set_marker(conn: sqlite3.Connection) -> None:
    with transaction(conn):
        conn.execute("INSERT INTO app_meta (key, value, updated_at) VALUES (?,?,?) ON CONFLICT(key) DO UPDATE"
                     " SET value = excluded.value, updated_at = excluded.updated_at",
                     (MARKER, str(BOOTSTRAP_VERSION), utcnow_iso()))


def _note(conn: sqlite3.Connection, plugin_id: str, status: str, version: str, sha: str | None,
          detail: str | None) -> None:
    with transaction(conn):
        conn.execute(
            "INSERT INTO bundled_plugins (plugin_id, status, bundled_version, bundled_sha256, detail, updated_at)"
            " VALUES (?,?,?,?,?,?) ON CONFLICT(plugin_id) DO UPDATE SET status = excluded.status,"
            " bundled_version = excluded.bundled_version, bundled_sha256 = excluded.bundled_sha256,"
            " detail = excluded.detail, updated_at = excluded.updated_at",
            (plugin_id, status, version, sha, detail, utcnow_iso()))


# -- the sync -------------------------------------------------------------------------------------------------

@dataclass(frozen=True)
class BundledOutcome:
    plugin_id: str
    version: str
    # installed | updated | unchanged | pending_review | failed | skipped | left_alone
    result: str
    detail: str | None = None


@dataclass(frozen=True)
class _Built:
    plugin_id: str
    version: str
    path: Path
    sha: str
    package: PluginPackage | None
    error: str | None


def _build(sources: list[Path], workdir: Path) -> list[_Built]:
    built = []
    for source in sources:
        path = build_package(source, workdir / f"{source.name}.osp")
        sha = hashlib.sha256(path.read_bytes()).hexdigest()
        try:
            package = load_package(path)
            built.append(_Built(package.id, package.version, path, sha, package, None))
        except PackageError as exc:
            built.append(_Built(source.name, "unknown", path, sha, None, f"invalid plugin package: {exc}"))
    return built


async def sync_bundled(conn: sqlite3.Connection, manager: PluginManager, bundled_dir: str | Path | None, *,
                       notifications=None) -> list[BundledOutcome]:
    if not bundled_dir:
        return []
    sources = discover(bundled_dir)
    if not sources:
        return []
    with tempfile.TemporaryDirectory(prefix="oneshelf-bundled-") as workdir:
        built = _build(sources, Path(workdir))
        if bootstrap_version(conn) < BOOTSTRAP_VERSION:
            outcomes = await _bootstrap(conn, manager, built, notifications)
            _set_marker(conn)
        else:
            outcomes = [await _maintain(conn, manager, item, notifications) for item in built]
    for outcome in outcomes:
        if outcome.result == "failed":
            logger.warning("official source %s %s could not be installed: %s",
                           outcome.plugin_id, outcome.version, outcome.detail)
    return outcomes


async def _bootstrap(conn, manager, built: list[_Built], notifications) -> list[BundledOutcome]:
    """The first run. A library whose owner already chose sources is recorded and left as it is."""
    ids = [item.plugin_id for item in built]
    placeholders = ",".join("?" for _ in ids)
    # Rows this bootstrap wrote itself (channel 'bundled') are not the owner's choices: they are what an
    # interrupted earlier run already did, and the job is to finish it rather than conclude it is done.
    owned = conn.execute(f"SELECT id FROM plugins WHERE id IN ({placeholders}) AND channel <> ?",
                         (*ids, CHANNEL)).fetchall()
    if owned:
        detail = "this library already managed its own sources, so none were added automatically"
        for item in built:
            _note(conn, item.plugin_id, "skipped", item.version, item.sha, detail)
        return [BundledOutcome(item.plugin_id, item.version, "skipped", detail) for item in built]
    return [await _first_install(conn, manager, item, notifications) for item in built]


async def _first_install(conn, manager, item: _Built, notifications) -> BundledOutcome:
    if item.error is not None:
        return _failed(conn, item, item.error, notifications)
    try:
        # The one place permissions are approved without a review: the adapters as shipped, on first
        # install, because the owner asked for exactly that.
        outcome = await manager.install_file(item.path, approved_permissions=item.package.permissions,
                                             channel=CHANNEL, trust_label=TRUST)
    except InstallRejected as exc:
        return _failed(conn, item, str(exc), notifications)
    _note(conn, item.plugin_id, "installed", item.version, item.sha, None)
    _resolve(notifications, item.plugin_id)
    result = "installed" if outcome.state == "active" else "unchanged"
    return BundledOutcome(item.plugin_id, item.version, result)


async def _maintain(conn, manager, item: _Built, notifications) -> BundledOutcome:
    """After the bootstrap: keep our own active adapters current, and touch nothing else."""
    plugin = conn.execute("SELECT * FROM plugins WHERE id = ?", (item.plugin_id,)).fetchone()
    note = conn.execute("SELECT * FROM bundled_plugins WHERE plugin_id = ?", (item.plugin_id,)).fetchone()

    if note is not None and note["status"] == "failed" and note["bundled_sha256"] == item.sha:
        return BundledOutcome(item.plugin_id, item.version, "failed",
                              f"{note['detail']} (not retried: the bundled package has not changed)")

    if plugin is None:
        if note is not None and note["status"] == "failed":
            return await _first_install(conn, manager, item, notifications)      # a changed package
        return BundledOutcome(item.plugin_id, item.version, "left_alone",
                              "not installed here; sources are only added to a library on its first run")

    if plugin["channel"] != CHANNEL:
        return BundledOutcome(item.plugin_id, item.version, "left_alone",
                              "installed by hand, so it is the owner's to update")
    if plugin["state"] != "active":
        return BundledOutcome(item.plugin_id, item.version, "left_alone",
                              f"{plugin['state']} by the owner; updating it would re-enable it")
    if item.error is not None:
        return _failed(conn, item, item.error, notifications)
    if _vkey(item.version) < _vkey(plugin["active_version"]):
        return BundledOutcome(item.plugin_id, item.version, "left_alone", "a newer version is already installed")

    try:
        # Nothing new is approved here: the approved baseline carries forward and anything beyond it
        # goes to review, exactly as for an uploaded or registry plugin.
        outcome = await manager.install_file(item.path, approved_permissions=frozenset(),
                                             channel=CHANNEL, trust_label=TRUST)
    except InstallRejected as exc:
        return _failed(conn, item, str(exc), notifications)

    version_row = conn.execute("SELECT status FROM plugin_versions WHERE plugin_id = ? AND version = ?",
                               (item.plugin_id, item.version)).fetchone()
    if outcome.state == "pending_review" or (version_row is not None and version_row["status"] == "pending_review"):
        active = conn.execute("SELECT approved_permissions_json FROM plugin_versions WHERE plugin_id = ?"
                              " AND status = 'active'", (item.plugin_id,)).fetchone()
        approved = frozenset(json.loads(active[0] or "[]")) if active else frozenset()
        added = sorted(item.package.permissions - approved)
        detail = "asks for permissions it did not have before, so it waits for review: " + ", ".join(added)
        _note(conn, item.plugin_id, "installed", item.version, item.sha, detail)
        if notifications is not None:
            notifications.plugin_update_available(item.plugin_id, item.version)
        return BundledOutcome(item.plugin_id, item.version, "pending_review", detail)

    _note(conn, item.plugin_id, "installed", item.version, item.sha, None)
    _resolve(notifications, item.plugin_id)
    return BundledOutcome(item.plugin_id, item.version, "updated" if outcome.state == "active" else "unchanged")


def _failed(conn, item: _Built, detail: str, notifications) -> BundledOutcome:
    _note(conn, item.plugin_id, "failed", item.version, item.sha, detail)
    if notifications is not None:
        notifications.bundled_source_failed(item.plugin_id, detail)
    return BundledOutcome(item.plugin_id, item.version, "failed", detail)


def _resolve(notifications, plugin_id: str) -> None:
    if notifications is not None:
        notifications.resolve(f"source-bootstrap:{plugin_id}")
