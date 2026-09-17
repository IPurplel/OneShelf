"""Plugin installation and management (Master §9.5, §10; ledger A1).

Install pipeline: copy → hash/signature → manifest → API compatibility → recipes/domains/capabilities
→ static checks → packaged tests → atomic activation. Activation requires the user's approval of every
permission not previously approved; updates needing review wait while the current version stays active.
Uninstall removes plugin files only; library records keep their provenance.
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
import shutil
import sqlite3
import zipfile
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from pathlib import Path

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

from oneshelf.db.connection import transaction
from oneshelf.domain.clock import utcnow_iso
from oneshelf.domain.ids import new_id
from oneshelf.plugins.package import PackageError, PluginPackage, load_package
from oneshelf.plugins.registry import Registry, RegistryError, pick
from oneshelf.plugins.runtime import run_packaged_tests

STAGING = ".staging"
SIGNED_LABELS = {"official", "verified_community"}
STEPS_VALIDATION = ["manifest_valid", "api_compatible", "recipes_valid", "static_checks"]


class InstallRejected(RuntimeError):
    pass


class PluginUnavailable(RuntimeError):
    pass


@dataclass(frozen=True)
class InstallOutcome:
    plugin_id: str
    version: str
    state: str  # active | pending_review | already_installed
    steps: list[str]
    added_permissions: frozenset[str] = frozenset()
    auth_available: bool = False


@dataclass(frozen=True)
class PluginRecord:
    id: str
    name: str
    state: str
    active_version: str | None
    trust_label: str
    channel: str


@dataclass(frozen=True)
class VersionRecord:
    version: str
    status: str
    sha256: str
    permissions: frozenset[str]
    approved_permissions: frozenset[str]


def _vkey(version: str) -> tuple[int, ...]:
    return tuple(int(p) for p in version.split("."))


class PluginManager:
    def __init__(self, conn: sqlite3.Connection, *, store_dir: str | Path,
                 trusted_keys: dict[str, bytes] | None = None, fault: Callable[[str], None] | None = None) -> None:
        self.conn = conn
        self.store = Path(store_dir)
        self.trusted_keys = trusted_keys or {}
        self.fault = fault or (lambda _p: None)
        self._cache: dict[tuple[str, str, str], PluginPackage] = {}

    # -- queries ----------------------------------------------------------------------------------

    def get(self, plugin_id: str) -> PluginRecord:
        row = self.conn.execute("SELECT * FROM plugins WHERE id = ?", (plugin_id,)).fetchone()
        if row is None:
            raise PluginUnavailable(f"plugin {plugin_id!r} is not installed")
        return PluginRecord(row["id"], row["name"], row["state"], row["active_version"], row["trust_label"], row["channel"])

    def list(self) -> list[PluginRecord]:
        return [self.get(r[0]) for r in self.conn.execute("SELECT id FROM plugins ORDER BY name")]

    def versions(self, plugin_id: str) -> list[VersionRecord]:
        return [
            VersionRecord(r["version"], r["status"], r["sha256"], frozenset(json.loads(r["permissions_json"])),
                          frozenset(json.loads(r["approved_permissions_json"] or "[]")))
            for r in self.conn.execute("SELECT * FROM plugin_versions WHERE plugin_id = ? ORDER BY installed_at", (plugin_id,))
        ]

    def _version_row(self, plugin_id: str, version: str) -> sqlite3.Row | None:
        return self.conn.execute(
            "SELECT * FROM plugin_versions WHERE plugin_id = ? AND version = ?", (plugin_id, version)
        ).fetchone()

    def _active_row(self, plugin_id: str) -> sqlite3.Row | None:
        return self.conn.execute(
            "SELECT * FROM plugin_versions WHERE plugin_id = ? AND status = 'active'", (plugin_id,)
        ).fetchone()

    def _store_path(self, relpath: str) -> Path:
        path = (self.store / relpath).resolve()
        if os.path.commonpath([path, self.store.resolve()]) != str(self.store.resolve()):
            raise PluginUnavailable("plugin store path escapes the store")
        return path

    def load_active(self, plugin_id: str) -> PluginPackage:
        record = self.get(plugin_id)
        row = self._active_row(plugin_id)
        if record.state != "active" or row is None:
            raise PluginUnavailable(f"plugin {plugin_id!r} is {record.state}")
        key = (plugin_id, row["version"], row["sha256"])
        if key not in self._cache:
            path = self._store_path(row["store_relpath"])
            if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != row["sha256"]:
                raise PluginUnavailable(f"plugin {plugin_id!r} package is missing or modified; reinstall it")
            self._cache[key] = load_package(path)
        return self._cache[key]

    # -- install ----------------------------------------------------------------------------------

    async def install_file(
        self,
        path: str | Path,
        *,
        approved_permissions: Iterable[str],
        channel: str = "upload",
        trust_label: str = "local",
        registry_url: str | None = None,
        expected_sha256: str | None = None,
    ) -> InstallOutcome:
        steps: list[str] = []
        (self.store / STAGING).mkdir(parents=True, exist_ok=True)
        staged = self.store / STAGING / f"{new_id()}.osp"
        try:
            shutil.copyfile(path, staged)
            steps.append("copied")
            sha = hashlib.sha256(staged.read_bytes()).hexdigest()
            if expected_sha256 is not None and sha != expected_sha256.lower():
                raise InstallRejected("package hash does not match the registry entry")
            steps.append("hash_verified")
            try:
                package = load_package(staged)
            except PackageError as exc:
                raise InstallRejected(f"invalid plugin package: {exc}") from exc
            steps.extend(STEPS_VALIDATION)

            existing = self._version_row(package.id, package.version)
            if existing is not None and existing["status"] != "retired":
                if existing["sha256"] == sha:
                    return InstallOutcome(package.id, package.version, "already_installed", steps)
                raise InstallRejected(f"version {package.version} is already installed with different content")
            active = self._active_row(package.id)
            if active is not None and _vkey(package.version) < _vkey(active["version"]):
                raise InstallRejected("package is older than the installed version; use rollback instead")

            report = await run_packaged_tests(package)
            if not report.passed:
                raise InstallRejected("packaged tests failed: " + "; ".join(report.failures))
            steps.append("tests_passed")

            baseline = frozenset(json.loads(active["approved_permissions_json"] or "[]")) if active else frozenset()
            approved = baseline | frozenset(approved_permissions)
            added = package.permissions - approved
            relpath = f"{package.id}/{package.version}.osp"
            target = self._store_path(relpath)
            target.parent.mkdir(parents=True, exist_ok=True)
            os.replace(staged, target)
            self.fault("after_store_move")
            report_json = json.dumps({"passed": report.passed, "cases": report.cases, "failures": report.failures})
            status = "pending_review" if added else "active"
            self._record(package, sha, relpath, status, approved & package.permissions if not added else None,
                         trust_label, channel, registry_url, report_json)
            if added:
                return InstallOutcome(package.id, package.version, "pending_review", steps, frozenset(added),
                                      package.manifest.auth is not None)
            steps.append("activated")
            return InstallOutcome(package.id, package.version, "active", steps, frozenset(),
                                  package.manifest.auth is not None)
        finally:
            if staged.exists():
                staged.unlink()

    def _record(self, package: PluginPackage, sha: str, relpath: str, status: str, approved: frozenset[str] | None,
                trust_label: str, channel: str, registry_url: str | None, report_json: str) -> None:
        now = utcnow_iso()
        with transaction(self.conn):
            plugin = self.conn.execute("SELECT * FROM plugins WHERE id = ?", (package.id,)).fetchone()
            has_active = plugin is not None and plugin["state"] in ("active", "disabled") and plugin["active_version"]
            if status == "active":
                state, active_version = "active", package.version
            elif has_active:
                state, active_version = plugin["state"], plugin["active_version"]
            else:
                state, active_version = "pending_review", None
            if status == "active" or plugin is None or not has_active:
                label, chan = trust_label, channel
            else:
                label, chan = plugin["trust_label"], plugin["channel"]
            self.conn.execute(
                "INSERT INTO plugins (id, name, state, active_version, trust_label, channel, registry_url, installed_at, updated_at)"
                " VALUES (?,?,?,?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET name=excluded.name, state=excluded.state,"
                " active_version=excluded.active_version, trust_label=excluded.trust_label, channel=excluded.channel,"
                " registry_url=coalesce(excluded.registry_url, plugins.registry_url), updated_at=excluded.updated_at",
                (package.id, package.manifest.name, state, active_version, label, chan, registry_url, now, now),
            )
            if status == "active":
                self.conn.execute("UPDATE plugin_versions SET status = 'retired' WHERE plugin_id = ? AND status = 'previous'",
                                  (package.id,))
                self.conn.execute("UPDATE plugin_versions SET status = 'previous' WHERE plugin_id = ? AND status = 'active'",
                                  (package.id,))
            self.conn.execute(
                "INSERT INTO plugin_versions (plugin_id, version, sha256, permissions_json, approved_permissions_json, status,"
                " trust_label, test_report_json, store_relpath, installed_at) VALUES (?,?,?,?,?,?,?,?,?,?)"
                " ON CONFLICT(plugin_id, version) DO UPDATE SET sha256=excluded.sha256, permissions_json=excluded.permissions_json,"
                " approved_permissions_json=excluded.approved_permissions_json, status=excluded.status,"
                " trust_label=excluded.trust_label, test_report_json=excluded.test_report_json,"
                " store_relpath=excluded.store_relpath, installed_at=excluded.installed_at",
                (package.id, package.version, sha, json.dumps(sorted(package.permissions)),
                 json.dumps(sorted(approved)) if approved is not None else None, status, trust_label, report_json, relpath, now),
            )

    async def approve(self, plugin_id: str, version: str, *, approved_permissions: Iterable[str]) -> InstallOutcome:
        row = self._version_row(plugin_id, version)
        if row is None or row["status"] != "pending_review":
            raise InstallRejected(f"no pending review for {plugin_id} {version}")
        active = self._active_row(plugin_id)
        baseline = frozenset(json.loads(active["approved_permissions_json"] or "[]")) if active else frozenset()
        permissions = frozenset(json.loads(row["permissions_json"]))
        approved = baseline | frozenset(approved_permissions)
        remaining = permissions - approved
        if remaining:
            return InstallOutcome(plugin_id, version, "pending_review", [], remaining)
        path = self._store_path(row["store_relpath"])
        if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != row["sha256"]:
            raise InstallRejected("stored package is missing or modified; install it again")
        package = load_package(path)
        record = self.conn.execute("SELECT * FROM plugins WHERE id = ?", (plugin_id,)).fetchone()
        self._record(package, row["sha256"], row["store_relpath"], "active", approved & permissions, row["trust_label"],
                     record["channel"], record["registry_url"], row["test_report_json"])
        return InstallOutcome(plugin_id, version, "active", ["activated"], frozenset(), package.manifest.auth is not None)

    async def install_from_registry(self, registry: Registry, plugin_id: str, *, version: str | None = None,
                                    approved_permissions: Iterable[str]) -> InstallOutcome:
        try:
            entry = pick(await registry.entries(), plugin_id, version)
            data = await registry.fetch(entry)
        except RegistryError as exc:
            raise InstallRejected(str(exc)) from exc
        sha = hashlib.sha256(data).hexdigest()
        if sha != entry.sha256:
            raise InstallRejected("package hash does not match the registry entry")
        label = self._verified_label(entry)
        (self.store / STAGING).mkdir(parents=True, exist_ok=True)
        download = self.store / STAGING / f"download-{new_id()}.osp"
        download.write_bytes(data)
        try:
            outcome = await self.install_file(download, approved_permissions=approved_permissions, channel="registry",
                                              trust_label=label, registry_url=registry.location, expected_sha256=entry.sha256)
        finally:
            if download.exists():
                download.unlink()
        if outcome.plugin_id != entry.id or outcome.version != entry.version:
            raise InstallRejected("package identity does not match the registry entry")
        return outcome

    def _verified_label(self, entry) -> str:
        claimed = entry.trust_label if entry.trust_label in SIGNED_LABELS | {"community"} else "community"
        if claimed not in SIGNED_LABELS:
            return "community"
        if not entry.signature or entry.signature_key_id not in self.trusted_keys:
            return "community"
        try:
            Ed25519PublicKey.from_public_bytes(self.trusted_keys[entry.signature_key_id]).verify(
                base64.b64decode(entry.signature), entry.sha256.encode()
            )
        except (InvalidSignature, ValueError) as exc:
            raise InstallRejected("registry signature verification failed") from exc
        return claimed

    # -- management -------------------------------------------------------------------------------

    def _set_state(self, plugin_id: str, state: str, active_version: str | None) -> None:
        with transaction(self.conn):
            self.conn.execute("UPDATE plugins SET state = ?, active_version = ?, updated_at = ? WHERE id = ?",
                              (state, active_version, utcnow_iso(), plugin_id))

    def disable(self, plugin_id: str) -> None:
        record = self.get(plugin_id)
        if record.active_version is None:
            raise PluginUnavailable("only installed plugins can be disabled")
        self._set_state(plugin_id, "disabled", record.active_version)

    def enable(self, plugin_id: str) -> None:
        record = self.get(plugin_id)
        if record.state != "disabled" or record.active_version is None:
            raise PluginUnavailable("plugin is not disabled")
        self._set_state(plugin_id, "active", record.active_version)

    def rollback(self, plugin_id: str) -> None:
        previous = self.conn.execute(
            "SELECT version FROM plugin_versions WHERE plugin_id = ? AND status = 'previous'", (plugin_id,)
        ).fetchone()
        active = self._active_row(plugin_id)
        if previous is None or active is None:
            raise PluginUnavailable("no previous version to roll back to")
        with transaction(self.conn):
            self.conn.execute("UPDATE plugin_versions SET status = 'previous' WHERE plugin_id = ? AND version = ?",
                              (plugin_id, active["version"]))
            self.conn.execute("UPDATE plugin_versions SET status = 'active' WHERE plugin_id = ? AND version = ?",
                              (plugin_id, previous["version"]))
            self.conn.execute("UPDATE plugins SET active_version = ?, state = 'active', updated_at = ? WHERE id = ?",
                              (previous["version"], utcnow_iso(), plugin_id))

    def uninstall(self, plugin_id: str) -> None:
        self.get(plugin_id)
        with transaction(self.conn):
            self.conn.execute("UPDATE plugin_versions SET status = 'retired' WHERE plugin_id = ?", (plugin_id,))
            self.conn.execute(
                "UPDATE plugins SET state = 'uninstalled', active_version = NULL, updated_at = ? WHERE id = ?",
                (utcnow_iso(), plugin_id),
            )
        directory = self._store_path(plugin_id)
        if directory.is_dir():
            shutil.rmtree(directory)
        self._cache = {k: v for k, v in self._cache.items() if k[0] != plugin_id}

    def reconcile_store(self) -> int:
        """Remove staging leftovers and store files no version record references (crash recovery)."""
        removed = 0
        staging = self.store / STAGING
        if staging.is_dir():
            for item in staging.iterdir():
                item.unlink()
                removed += 1
        referenced = {r[0] for r in self.conn.execute(
            "SELECT store_relpath FROM plugin_versions WHERE status <> 'retired'")}
        if self.store.is_dir():
            for path in self.store.glob("*/*.osp"):
                relpath = f"{path.parent.name}/{path.name}"
                if relpath not in referenced:
                    path.unlink()
                    removed += 1
        return removed

    def export_submission(self, plugin_id: str, version: str, destination: str | Path) -> Path:
        """Explicit, local-only community submission bundle (never published automatically)."""
        row = self._version_row(plugin_id, version)
        if row is None or row["status"] == "retired":
            raise PluginUnavailable("version not available for export")
        package_path = self._store_path(row["store_relpath"])
        package = load_package(package_path)
        destination = Path(destination)
        destination.mkdir(parents=True, exist_ok=True)
        bundle = destination / f"{plugin_id}-{version}.submission.zip"
        summary = {
            "id": plugin_id, "name": package.manifest.name, "version": version, "sha256": row["sha256"],
            "permissions": sorted(package.permissions), "capabilities": list(package.manifest.capabilities),
            "tests": json.loads(row["test_report_json"]), "exported_at": utcnow_iso(),
        }
        with zipfile.ZipFile(bundle, "w") as z:
            z.write(package_path, "package.osp")
            z.writestr("submission.json", json.dumps(summary, indent=2))
        return bundle
