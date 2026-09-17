"""Master §10 / §9.5 / ledger A1: atomic install, permission review, update/rollback, uninstall, registry."""
import asyncio
import base64
import copy
import hashlib
import json
import zipfile
from pathlib import Path

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

from oneshelf.domain.ids import new_id
from oneshelf.plugins.manager import (
    InstallRejected,
    PluginManager,
    PluginUnavailable,
)
from oneshelf.plugins.registry import DirectoryRegistry
from tests.fixtures.osp import MANIFEST, RECIPES, build_osp, variant

NOW = "2026-09-17T00:00:00+00:00"


def run(coro):
    return asyncio.run(coro)


@pytest.fixture
def manager(db, tmp_path):
    return PluginManager(db, store_dir=tmp_path / "app" / "plugins")


def osp(tmp_path, name="p.osp", version="1.0.0", manifest=None, **kw):
    m = copy.deepcopy(manifest or MANIFEST)
    m["version"] = version
    return build_osp(tmp_path / name, manifest=m, **kw)


def all_perms(path):
    from oneshelf.plugins.package import load_package
    return load_package(path).permissions


def install(manager, path, approve=True, **kw):
    return run(manager.install_file(path, approved_permissions=all_perms(path) if approve else frozenset(), **kw))


def test_fresh_install_with_approval_activates(manager, tmp_path, db):
    out = install(manager, osp(tmp_path))
    assert out.state == "active" and out.version == "1.0.0"
    assert out.steps == ["copied", "hash_verified", "manifest_valid", "api_compatible", "recipes_valid",
                         "static_checks", "tests_passed", "activated"]
    record = manager.get("example.books")
    assert record.trust_label == "local" and record.channel == "upload"
    assert manager.load_active("example.books").version == "1.0.0"
    assert not any((tmp_path / "app" / "plugins" / ".staging").glob("*"))


def test_install_without_permission_approval_waits_for_review(manager, tmp_path):
    path = osp(tmp_path)
    out = install(manager, path, approve=False)
    assert out.state == "pending_review" and out.added_permissions == all_perms(path)
    with pytest.raises(PluginUnavailable):
        manager.load_active("example.books")
    out = run(manager.approve("example.books", "1.0.0", approved_permissions=all_perms(path)))
    assert out.state == "active"


def test_malformed_package_is_rejected_without_side_effects(manager, tmp_path, db):
    bad = build_osp(tmp_path / "bad.osp", extra_files={"plugin.py": b"import os"})
    with pytest.raises(InstallRejected):
        run(manager.install_file(bad, approved_permissions=frozenset()))
    assert db.execute("SELECT count(*) FROM plugins").fetchone()[0] == 0
    assert not [p for p in (tmp_path / "app" / "plugins").rglob("*") if p.is_file()]


def test_failing_packaged_tests_reject_install(manager, tmp_path, db):
    tests = {"cases": [{"capability": "search", "inputs": {"query": "moon", "page": 1},
                        "fixtures": [{"url": "https://books.example/search?q=moon&page=1", "file": "fixtures/search.html"}],
                        "expect": {"min_items": 9}}]}
    path = osp(tmp_path, tests=tests)
    with pytest.raises(InstallRejected, match="packaged tests"):
        install(manager, path)
    assert db.execute("SELECT count(*) FROM plugins").fetchone()[0] == 0


def test_same_version_is_idempotent_but_immutable(manager, tmp_path):
    path = osp(tmp_path)
    install(manager, path)
    assert install(manager, path).state == "already_installed"
    recipes = copy.deepcopy(RECIPES)
    recipes["search"]["extract"]["fields"]["title"]["transforms"] = []
    changed = osp(tmp_path, name="changed.osp", recipes=recipes)
    with pytest.raises(InstallRejected, match="already installed with different content"):
        install(manager, changed)


def test_update_without_new_permissions_activates_and_rollback_restores(manager, tmp_path):
    install(manager, osp(tmp_path, version="1.0.0"))
    v2 = osp(tmp_path, name="v2.osp", version="1.1.0")
    out = run(manager.install_file(v2, approved_permissions=frozenset()))  # nothing new to approve
    assert out.state == "active" and manager.load_active("example.books").version == "1.1.0"
    manager.rollback("example.books")
    assert manager.load_active("example.books").version == "1.0.0"
    assert {v.version: v.status for v in manager.versions("example.books")} == {"1.0.0": "active", "1.1.0": "previous"}


def test_update_with_new_permissions_requires_review_and_keeps_old_version(manager, tmp_path):
    install(manager, osp(tmp_path, version="1.0.0"))
    m = variant(MANIFEST, network__cdn_domains=["*.cdn.books.example", "images.example"])
    v2 = osp(tmp_path, name="v2.osp", version="2.0.0", manifest=m)
    out = run(manager.install_file(v2, approved_permissions=frozenset()))
    assert out.state == "pending_review" and out.added_permissions == {"network:cdn:images.example"}
    assert manager.load_active("example.books").version == "1.0.0"
    assert manager.get("example.books").state == "active"
    out = run(manager.approve("example.books", "2.0.0", approved_permissions={"network:cdn:images.example"}))
    assert out.state == "active" and manager.load_active("example.books").version == "2.0.0"


def test_downgrade_via_install_is_rejected(manager, tmp_path):
    install(manager, osp(tmp_path, version="2.0.0"))
    with pytest.raises(InstallRejected, match="older"):
        install(manager, osp(tmp_path, name="old.osp", version="1.0.0"))


def test_disable_and_enable(manager, tmp_path):
    install(manager, osp(tmp_path))
    manager.disable("example.books")
    with pytest.raises(PluginUnavailable):
        manager.load_active("example.books")
    manager.enable("example.books")
    assert manager.load_active("example.books").version == "1.0.0"


def test_uninstall_preserves_library_and_provenance_and_allows_reinstall(manager, tmp_path, db):
    path = osp(tmp_path)
    install(manager, path)
    work, track = new_id(), new_id()
    db.execute("INSERT INTO works (id, display_title, created_at, updated_at) VALUES (?, 'W', ?, ?)", (work, NOW, NOW))
    db.execute("INSERT INTO source_tracks (id, work_id, source_id, language, kind, created_at) VALUES (?, ?, 'example.books', 'en', 'source', ?)",
               (track, work, NOW))
    db.execute("INSERT INTO shelf_entries (work_id, added_at) VALUES (?, ?)", (work, NOW))
    manager.uninstall("example.books")
    record = manager.get("example.books")
    assert record.state == "uninstalled" and record.name == "Example Books"
    assert db.execute("SELECT count(*) FROM source_tracks WHERE source_id = 'example.books'").fetchone()[0] == 1
    assert db.execute("SELECT count(*) FROM shelf_entries").fetchone()[0] == 1
    assert not [p for p in (tmp_path / "app" / "plugins" / "example.books").rglob("*") if p.is_file()]
    with pytest.raises(PluginUnavailable):
        manager.load_active("example.books")
    assert install(manager, path).state == "active"


def test_crash_after_store_move_is_reconciled(db, tmp_path):
    def fault(point):
        if point == "after_store_move":
            raise KeyboardInterrupt(point)

    crashing = PluginManager(db, store_dir=tmp_path / "app" / "plugins", fault=fault)
    path = osp(tmp_path)
    with pytest.raises(KeyboardInterrupt):
        install(crashing, path)
    fresh = PluginManager(db, store_dir=tmp_path / "app" / "plugins")
    removed = fresh.reconcile_store()
    assert removed == 1
    assert not [p for p in (tmp_path / "app" / "plugins").rglob("*.osp")]
    assert install(fresh, path).state == "active"


# -- registry (static index; ledger A1) --------------------------------------------------------------

def make_registry(tmp_path, entries, keys=None):
    root = tmp_path / "registry"
    root.mkdir(exist_ok=True)
    index = {"schema": "oneshelf.registry/1", "plugins": entries}
    (root / "index.json").write_text(json.dumps(index))
    return DirectoryRegistry(root)


def registry_entry(tmp_path, path, label="community", signer=None, key_id="k1"):
    data = path.read_bytes()
    target = tmp_path / "registry" / path.name
    target.parent.mkdir(exist_ok=True)
    target.write_bytes(data)
    sha = hashlib.sha256(data).hexdigest()
    entry = {"id": "example.books", "name": "Example Books", "version": "1.0.0", "file": path.name, "sha256": sha,
             "trust_label": label}
    if signer is not None:
        entry["signature"] = {"key_id": key_id, "value": base64.b64encode(signer.sign(sha.encode())).decode()}
    return entry


def test_registry_install_verifies_hash_and_labels_community(manager, tmp_path):
    path = osp(tmp_path)
    registry = make_registry(tmp_path, [registry_entry(tmp_path, path)])
    out = run(manager.install_from_registry(registry, "example.books", approved_permissions=all_perms(path)))
    assert out.state == "active"
    record = manager.get("example.books")
    assert record.channel == "registry" and record.trust_label == "community"


def test_registry_hash_mismatch_is_rejected(manager, tmp_path):
    path = osp(tmp_path)
    entry = registry_entry(tmp_path, path)
    entry["sha256"] = "0" * 64
    registry = make_registry(tmp_path, [entry])
    with pytest.raises(InstallRejected, match="hash"):
        run(manager.install_from_registry(registry, "example.books", approved_permissions=all_perms(path)))


def test_official_label_requires_locally_trusted_signature(db, tmp_path):
    key = Ed25519PrivateKey.generate()
    public = key.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
    path = osp(tmp_path)
    perms = all_perms(path)

    unsigned = make_registry(tmp_path, [registry_entry(tmp_path, path, label="official")])
    m1 = PluginManager(db, store_dir=tmp_path / "s1", trusted_keys={"k1": public})
    run(m1.install_from_registry(unsigned, "example.books", approved_permissions=perms))
    assert m1.get("example.books").trust_label == "community"  # unverified claim is downgraded
    m1.uninstall("example.books")
    db.execute("DELETE FROM plugin_versions")
    db.execute("DELETE FROM plugins")

    signed = make_registry(tmp_path, [registry_entry(tmp_path, path, label="official", signer=key)])
    m2 = PluginManager(db, store_dir=tmp_path / "s2", trusted_keys={"k1": public})
    run(m2.install_from_registry(signed, "example.books", approved_permissions=perms))
    assert m2.get("example.books").trust_label == "official"
    m2.uninstall("example.books")
    db.execute("DELETE FROM plugin_versions")
    db.execute("DELETE FROM plugins")

    forged = make_registry(tmp_path, [registry_entry(tmp_path, path, label="official", signer=Ed25519PrivateKey.generate())])
    m3 = PluginManager(db, store_dir=tmp_path / "s3", trusted_keys={"k1": public})
    with pytest.raises(InstallRejected, match="signature"):
        run(m3.install_from_registry(forged, "example.books", approved_permissions=perms))


def test_submission_bundle_is_exported_locally(manager, tmp_path):
    install(manager, osp(tmp_path))
    bundle = manager.export_submission("example.books", "1.0.0", tmp_path / "out")
    with zipfile.ZipFile(bundle) as z:
        names = set(z.namelist())
        summary = json.loads(z.read("submission.json"))
    assert names == {"package.osp", "submission.json"}
    assert summary["id"] == "example.books" and summary["tests"]["passed"] is True
    assert len(summary["sha256"]) == 64 and "permissions" in summary
