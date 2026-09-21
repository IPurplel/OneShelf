"""The Official Source Registry and the plugin lifecycle it shares with bundled sources.

Bundled sources and the Registry are two delivery paths into one plugin architecture. These tests hold
the places where they meet: who owns updates to a plugin after the person acts, what a review commits
the person to, what trust a package can actually earn, and what a Registry index is allowed to make Core
fetch. Every package is a real official adapter built with the canonical builder, and every signing key
is generated here, at run time — no key of any kind is committed.
"""
import asyncio
import base64
import hashlib
import json
import shutil
from pathlib import Path

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

from oneshelf.plugins.bundled import build_package, sync_bundled
from oneshelf.plugins.manager import InstallRejected, PluginManager
from oneshelf.plugins.registry import (CachedRegistry, DirectoryRegistry, RegistryError, parse_index,
                                       resolve_package_url)

OFFICIAL = Path(__file__).resolve().parents[3] / "plugins" / "official"


def run(coro):
    return asyncio.run(asyncio.wait_for(coro, 120))


@pytest.fixture
def signer():
    """A test-only Ed25519 key, created for this run and never written anywhere."""
    key = Ed25519PrivateKey.generate()
    public = key.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
    return key, {"test-official-1": public}


def source_copy(tmp_path, plugin, *, version=None, extra_domain=None, name="src"):
    target = tmp_path / name / plugin
    shutil.copytree(OFFICIAL / plugin, target, dirs_exist_ok=True)
    manifest = target / "manifest.yaml"
    text = manifest.read_text(encoding="utf-8")
    if version:
        text = text.replace("version: 1.0.0", f"version: {version}", 1)
    if extra_domain:
        text = text.replace("  domains: [", f"  domains: [{extra_domain}, ", 1)
    manifest.write_text(text, encoding="utf-8")
    return target


def _field(manifest: str, key: str) -> str:
    return next(line.split(":", 1)[1].strip() for line in manifest.splitlines() if line.startswith(f"{key}:"))


def publish(root, sources, *, signer=None, trust="official", key_id="test-official-1", api=None):
    """A registry laid out as the official one is: index.json beside a packages/ directory."""
    root = Path(root)
    (root / "packages").mkdir(parents=True, exist_ok=True)
    entries = []
    for source in sources:
        manifest = (source / "manifest.yaml").read_text(encoding="utf-8")
        plugin, version, name = _field(manifest, "id"), _field(manifest, "version"), _field(manifest, "name")
        path = build_package(source, root / "packages" / f"{plugin}-{version}.osp")
        sha = hashlib.sha256(path.read_bytes()).hexdigest()
        entry = {"id": plugin, "name": name, "version": version, "file": f"packages/{path.name}",
                 "sha256": sha, "trust_label": trust}
        if api:
            entry["api"] = api
        if signer is not None:
            entry["signature"] = {"key_id": key_id, "value": base64.b64encode(signer.sign(sha.encode())).decode()}
        entries.append(entry)
    (root / "index.json").write_text(json.dumps({"schema": "oneshelf.registry/1", "plugins": entries}),
                                     encoding="utf-8")
    return DirectoryRegistry(root)


def rows(db):
    return {r["id"]: dict(r) for r in db.execute("SELECT * FROM plugins")}


def bundled_dir(tmp_path, plugin):
    directory = tmp_path / "bundled"
    shutil.copytree(OFFICIAL / plugin, directory / plugin)
    return directory


# -- review: what the person sees is what gets installed ----------------------------------------------

def test_a_review_validates_and_tests_the_real_package_without_installing_it(db, tmp_path, signer):
    key, trusted = signer
    manager = PluginManager(db, store_dir=tmp_path / "store", trusted_keys=trusted)
    registry = publish(tmp_path / "reg", [source_copy(tmp_path, "oneshelf.gutenberg")], signer=key)
    review = run(manager.review_from_registry(registry, "oneshelf.gutenberg"))
    assert (review.plugin_id, review.version, review.effective_trust) == ("oneshelf.gutenberg", "1.0.0", "official")
    assert review.tests_passed and review.test_cases >= 2
    assert review.permissions and review.added_permissions == review.permissions   # nothing approved yet
    assert review.capabilities and review.publisher == "OneShelf"
    assert review.state == "available" and len(review.sha256) == 64
    assert rows(db) == {}                                         # opening a review installs nothing
    assert not list((tmp_path / "store").rglob("*.osp"))


def test_install_is_bound_to_the_exact_package_that_was_reviewed(db, tmp_path, signer):
    """No TOCTOU: if the bytes change between review and install, the install is refused."""
    key, trusted = signer
    manager = PluginManager(db, store_dir=tmp_path / "store", trusted_keys=trusted)
    registry = publish(tmp_path / "reg", [source_copy(tmp_path, "oneshelf.gutenberg")], signer=key)
    review = run(manager.review_from_registry(registry, "oneshelf.gutenberg"))
    changed = source_copy(tmp_path, "oneshelf.gutenberg", name="changed")
    (changed / "tests" / "fixtures" / "note.txt").write_text("different bytes", encoding="utf-8")
    publish(tmp_path / "reg", [changed], signer=key)              # same version, different content
    with pytest.raises(InstallRejected, match="changed since it was reviewed"):
        run(manager.install_from_registry(registry, "oneshelf.gutenberg", approved_permissions=review.permissions,
                                          expected_sha256=review.sha256))
    assert rows(db) == {}


def test_an_incompatible_plugin_api_says_it_needs_a_newer_oneshelf(db, tmp_path):
    manager = PluginManager(db, store_dir=tmp_path / "store")
    source = source_copy(tmp_path, "oneshelf.gutenberg")
    manifest = source / "manifest.yaml"
    manifest.write_text(manifest.read_text(encoding="utf-8").replace("api: '1.0'", "api: '1.9'"), encoding="utf-8")
    registry = publish(tmp_path / "reg", [source], api="1.9")
    with pytest.raises(InstallRejected, match="requires a newer OneShelf"):
        run(manager.review_from_registry(registry, "oneshelf.gutenberg"))


# -- trust is earned by a locally trusted key, never claimed ------------------------------------------

def test_a_valid_official_signature_from_a_locally_trusted_key_earns_official(db, tmp_path, signer):
    key, trusted = signer
    manager = PluginManager(db, store_dir=tmp_path / "store", trusted_keys=trusted)
    registry = publish(tmp_path / "reg", [source_copy(tmp_path, "oneshelf.arxiv")], signer=key)
    review = run(manager.review_from_registry(registry, "oneshelf.arxiv"))
    run(manager.install_from_registry(registry, "oneshelf.arxiv", approved_permissions=review.permissions,
                                      expected_sha256=review.sha256))
    record = rows(db)["oneshelf.arxiv"]
    assert (record["trust_label"], record["channel"]) == ("official", "registry")


def test_an_unsigned_package_claiming_official_is_not_official(db, tmp_path, signer):
    _, trusted = signer
    manager = PluginManager(db, store_dir=tmp_path / "store", trusted_keys=trusted)
    registry = publish(tmp_path / "reg", [source_copy(tmp_path, "oneshelf.arxiv")], signer=None)
    assert run(manager.review_from_registry(registry, "oneshelf.arxiv")).effective_trust == "community"


def test_a_signature_from_an_unknown_key_is_not_official(db, tmp_path):
    stranger = Ed25519PrivateKey.generate()
    manager = PluginManager(db, store_dir=tmp_path / "store", trusted_keys={})
    registry = publish(tmp_path / "reg", [source_copy(tmp_path, "oneshelf.arxiv")], signer=stranger)
    assert run(manager.review_from_registry(registry, "oneshelf.arxiv")).effective_trust == "community"


def test_a_bad_signature_from_a_trusted_key_is_refused(db, tmp_path, signer):
    _, trusted = signer
    forger = Ed25519PrivateKey.generate()                         # signs under the trusted key's id
    manager = PluginManager(db, store_dir=tmp_path / "store", trusted_keys=trusted)
    registry = publish(tmp_path / "reg", [source_copy(tmp_path, "oneshelf.arxiv")], signer=forger)
    with pytest.raises(InstallRejected, match="signature verification failed"):
        run(manager.review_from_registry(registry, "oneshelf.arxiv"))


def test_a_public_key_offered_by_the_registry_is_never_trusted(db, tmp_path):
    """Keys come from local configuration only. An index that ships its own key earns nothing."""
    rogue = Ed25519PrivateKey.generate()
    publish(tmp_path / "reg", [source_copy(tmp_path, "oneshelf.arxiv")], signer=rogue)
    index = json.loads((tmp_path / "reg" / "index.json").read_text(encoding="utf-8"))
    index["keys"] = {"test-official-1": base64.b64encode(
        rogue.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)).decode()}
    (tmp_path / "reg" / "index.json").write_text(json.dumps(index), encoding="utf-8")
    manager = PluginManager(db, store_dir=tmp_path / "store", trusted_keys={})
    registry = DirectoryRegistry(tmp_path / "reg")
    assert run(manager.review_from_registry(registry, "oneshelf.arxiv")).effective_trust == "community"


# -- package integrity ----------------------------------------------------------------------------------

def test_a_package_whose_hash_does_not_match_is_refused(db, tmp_path):
    manager = PluginManager(db, store_dir=tmp_path / "store")
    registry = publish(tmp_path / "reg", [source_copy(tmp_path, "oneshelf.arxiv")])
    package = next((tmp_path / "reg" / "packages").glob("*.osp"))
    package.write_bytes(package.read_bytes() + b"tampered")
    with pytest.raises(InstallRejected, match="hash does not match"):
        run(manager.review_from_registry(registry, "oneshelf.arxiv"))


def test_a_truncated_package_is_refused_even_with_a_matching_hash(db, tmp_path):
    manager = PluginManager(db, store_dir=tmp_path / "store")
    registry = publish(tmp_path / "reg", [source_copy(tmp_path, "oneshelf.arxiv")])
    package = next((tmp_path / "reg" / "packages").glob("*.osp"))
    data = package.read_bytes()[:200]
    package.write_bytes(data)
    index = json.loads((tmp_path / "reg" / "index.json").read_text(encoding="utf-8"))
    index["plugins"][0]["sha256"] = hashlib.sha256(data).hexdigest()
    (tmp_path / "reg" / "index.json").write_text(json.dumps(index), encoding="utf-8")
    with pytest.raises(InstallRejected, match="invalid plugin package"):
        run(manager.review_from_registry(registry, "oneshelf.arxiv"))


def test_an_oversized_package_is_refused_before_it_is_read(db, tmp_path):
    manager = PluginManager(db, store_dir=tmp_path / "store")
    publish(tmp_path / "reg", [source_copy(tmp_path, "oneshelf.arxiv")])
    registry = DirectoryRegistry(tmp_path / "reg", max_package_bytes=100)
    with pytest.raises(InstallRejected, match="too large"):
        run(manager.review_from_registry(registry, "oneshelf.arxiv"))


@pytest.mark.parametrize("body", [
    b"not json", b"[]", b'{"schema": "other/1", "plugins": []}',
    b'{"schema": "oneshelf.registry/1", "plugins": [{"id": "x"}]}',
    b'{"schema": "oneshelf.registry/1", "plugins": [{"id": "oneshelf.x", "name": "x", "version": "one",'
    b' "file": "a.osp", "sha256": "' + b"0" * 64 + b'"}]}',
    b'{"schema": "oneshelf.registry/1", "plugins": [{"id": "oneshelf.x", "name": "x", "version": "1.0.0",'
    b' "file": "a.osp", "sha256": "not-a-hash"}]}',
])
def test_a_malformed_index_is_refused_cleanly(body):
    with pytest.raises(RegistryError):
        parse_index(body)


# -- what an index may make Core fetch ------------------------------------------------------------------

def _entry(location):
    return parse_index(json.dumps({"schema": "oneshelf.registry/1", "plugins": [{
        "id": "oneshelf.x", "name": "x", "version": "1.0.0", "file": location,
        "sha256": "0" * 64}]}).encode())[0]


@pytest.mark.parametrize("location", ["../outside.osp", "/etc/passwd.osp", "packages/../../outside.osp",
                                      "packages/./x.osp", "packages\\x.osp", "packages/x.txt",
                                      "a" * 300 + ".osp", "https://evil.example/x.osp", "packages//x.osp"])
def test_a_local_registry_refuses_any_path_that_could_leave_it(tmp_path, location):
    (tmp_path / "reg").mkdir()
    (tmp_path / "outside.osp").write_bytes(b"x")
    with pytest.raises(RegistryError):
        run(DirectoryRegistry(tmp_path / "reg").fetch(_entry(location)))


def test_a_local_registry_refuses_a_symlink_that_points_outside_it(tmp_path):
    (tmp_path / "reg" / "packages").mkdir(parents=True)
    (tmp_path / "outside.osp").write_bytes(b"secret")
    (tmp_path / "reg" / "packages" / "link.osp").symlink_to(tmp_path / "outside.osp")
    with pytest.raises(RegistryError, match="outside"):
        run(DirectoryRegistry(tmp_path / "reg").fetch(_entry("packages/link.osp")))


INDEX = "https://raw.githubusercontent.com/IPurplel/OneShelf/main/registry/index.json"


@pytest.mark.parametrize("location,expected", [
    ("packages/oneshelf.x-1.0.0.osp",
     "https://raw.githubusercontent.com/IPurplel/OneShelf/main/registry/packages/oneshelf.x-1.0.0.osp"),
    ("oneshelf.x-1.0.0.osp", "https://raw.githubusercontent.com/IPurplel/OneShelf/main/registry/oneshelf.x-1.0.0.osp"),
])
def test_an_https_registry_resolves_packages_only_beneath_its_own_directory(location, expected):
    assert resolve_package_url(INDEX, location) == expected


@pytest.mark.parametrize("location", [
    "../../../someone-else/repo/main/evil.osp",          # same host, another repository
    "https://raw.githubusercontent.com/someone/else/main/x.osp",
    "https://evil.example/x.osp", "http://raw.githubusercontent.com/IPurplel/OneShelf/main/registry/x.osp",
    "https://user:pw@raw.githubusercontent.com/IPurplel/OneShelf/main/registry/x.osp",
    "packages/x.osp?token=1", "packages/x.txt", "//evil.example/x.osp", "packages/%2e%2e/%2e%2e/x.osp",
])
def test_an_https_registry_refuses_any_package_url_that_escapes_it(location):
    with pytest.raises(RegistryError):
        resolve_package_url(INDEX, location)


def test_an_unreachable_registry_is_not_asked_again_immediately():
    calls = []

    class Down:
        location = "https://registry.example/index.json"

        async def entries(self):
            calls.append(1)
            raise RegistryError("unreachable")

        async def fetch(self, entry):
            raise RegistryError("unreachable")

    cached = CachedRegistry(Down(), ttl=300, failure_ttl=60)
    for _ in range(5):
        with pytest.raises(RegistryError):
            run(cached.entries())
    assert len(calls) == 1


# -- one lifecycle per plugin id -------------------------------------------------------------------------

def test_a_removed_bundled_source_reinstalls_from_the_registry_as_the_same_plugin(db, tmp_path, signer):
    key, trusted = signer
    manager = PluginManager(db, store_dir=tmp_path / "store", trusted_keys=trusted)
    bundled = bundled_dir(tmp_path, "oneshelf.tapas")
    run(sync_bundled(db, manager, bundled))
    manager.uninstall("oneshelf.tapas")
    registry = publish(tmp_path / "reg", [source_copy(tmp_path, "oneshelf.tapas")], signer=key)
    review = run(manager.review_from_registry(registry, "oneshelf.tapas"))
    assert review.state == "available"
    run(manager.install_from_registry(registry, "oneshelf.tapas", approved_permissions=review.permissions,
                                      expected_sha256=review.sha256))
    assert db.execute("SELECT count(*) FROM plugins WHERE id = 'oneshelf.tapas'").fetchone()[0] == 1
    assert db.execute("SELECT count(*) FROM plugin_versions WHERE plugin_id = 'oneshelf.tapas'").fetchone()[0] == 1
    assert rows(db)["oneshelf.tapas"]["state"] == "active"
    for _ in range(2):                                          # the image's copy never takes it back
        [outcome] = run(sync_bundled(db, manager, bundled))
        assert outcome.result == "left_alone"
    assert rows(db)["oneshelf.tapas"]["channel"] == "registry"


def test_a_registry_version_is_never_downgraded_by_the_bundled_image(db, tmp_path, signer):
    key, trusted = signer
    manager = PluginManager(db, store_dir=tmp_path / "store", trusted_keys=trusted)
    bundled = bundled_dir(tmp_path, "oneshelf.arxiv")
    run(sync_bundled(db, manager, bundled))
    registry = publish(tmp_path / "reg", [source_copy(tmp_path, "oneshelf.arxiv", version="1.2.0")], signer=key)
    review = run(manager.review_from_registry(registry, "oneshelf.arxiv"))
    assert review.state == "update_available" and review.installed_version == "1.0.0"
    run(manager.install_from_registry(registry, "oneshelf.arxiv", approved_permissions=[],
                                      expected_sha256=review.sha256))
    for _ in range(3):
        run(sync_bundled(db, manager, bundled))
    record = rows(db)["oneshelf.arxiv"]
    assert (record["active_version"], record["channel"]) == ("1.2.0", "registry")
    assert {v.version: v.status for v in manager.versions("oneshelf.arxiv")} == {"1.0.0": "previous",
                                                                                  "1.2.0": "active"}


def test_asking_the_registry_for_an_update_hands_it_ownership_even_while_it_waits_for_review(db, tmp_path, signer):
    """An explicit Registry action is the person's choice of who updates this plugin; it must persist."""
    key, trusted = signer
    manager = PluginManager(db, store_dir=tmp_path / "store", trusted_keys=trusted)
    bundled = bundled_dir(tmp_path, "oneshelf.hindawi")
    run(sync_bundled(db, manager, bundled))
    registry = publish(tmp_path / "reg", [source_copy(tmp_path, "oneshelf.hindawi", version="1.1.0",
                                                      extra_domain="www.hindawi.org")], signer=key)
    review = run(manager.review_from_registry(registry, "oneshelf.hindawi"))
    assert review.added_permissions == frozenset({"network:domain:www.hindawi.org"})
    outcome = run(manager.install_from_registry(registry, "oneshelf.hindawi", approved_permissions=[],
                                                expected_sha256=review.sha256))
    assert outcome.state == "pending_review"                     # nothing new approved, even for Official
    assert rows(db)["oneshelf.hindawi"]["active_version"] == "1.0.0"
    assert rows(db)["oneshelf.hindawi"]["channel"] == "registry"
    shutil.rmtree(bundled / "oneshelf.hindawi")                  # a newer image ships 1.0.5 — still not its
    shutil.copytree(source_copy(tmp_path, "oneshelf.hindawi", version="1.0.5", name="img"),
                    bundled / "oneshelf.hindawi")
    [outcome] = run(sync_bundled(db, manager, bundled))
    assert outcome.result == "left_alone"
    assert rows(db)["oneshelf.hindawi"]["active_version"] == "1.0.0"


def test_a_registry_update_of_a_disabled_source_keeps_it_disabled(db, tmp_path, signer):
    key, trusted = signer
    manager = PluginManager(db, store_dir=tmp_path / "store", trusted_keys=trusted)
    run(sync_bundled(db, manager, bundled_dir(tmp_path, "oneshelf.webtoon")))
    manager.disable("oneshelf.webtoon")
    registry = publish(tmp_path / "reg", [source_copy(tmp_path, "oneshelf.webtoon", version="1.1.0")], signer=key)
    review = run(manager.review_from_registry(registry, "oneshelf.webtoon"))
    assert review.state == "update_available" and review.plugin_state == "disabled"
    run(manager.install_from_registry(registry, "oneshelf.webtoon", approved_permissions=[],
                                      expected_sha256=review.sha256))
    record = rows(db)["oneshelf.webtoon"]
    assert (record["state"], record["active_version"]) == ("disabled", "1.1.0")


def test_approving_a_pending_update_of_a_disabled_source_keeps_it_disabled(db, tmp_path, signer):
    key, trusted = signer
    manager = PluginManager(db, store_dir=tmp_path / "store", trusted_keys=trusted)
    run(sync_bundled(db, manager, bundled_dir(tmp_path, "oneshelf.webtoon")))
    manager.disable("oneshelf.webtoon")
    registry = publish(tmp_path / "reg", [source_copy(tmp_path, "oneshelf.webtoon", version="1.1.0",
                                                      extra_domain="extra.webtoons.com")], signer=key)
    review = run(manager.review_from_registry(registry, "oneshelf.webtoon"))
    run(manager.install_from_registry(registry, "oneshelf.webtoon", approved_permissions=[],
                                      expected_sha256=review.sha256))
    run(manager.approve("oneshelf.webtoon", "1.1.0", approved_permissions=review.permissions))
    record = rows(db)["oneshelf.webtoon"]
    assert (record["state"], record["active_version"]) == ("disabled", "1.1.0")


def test_an_upload_update_of_a_disabled_source_keeps_it_disabled_too(db, tmp_path):
    """The rule lives in the manager, so every path honours it — not only the Registry."""
    manager = PluginManager(db, store_dir=tmp_path / "store")
    run(sync_bundled(db, manager, bundled_dir(tmp_path, "oneshelf.webtoon")))
    manager.disable("oneshelf.webtoon")
    package = build_package(source_copy(tmp_path, "oneshelf.webtoon", version="1.1.0"), tmp_path / "w.osp")
    run(manager.install_file(package, approved_permissions=[]))
    record = rows(db)["oneshelf.webtoon"]
    assert (record["state"], record["active_version"]) == ("disabled", "1.1.0")


def test_an_installed_version_newer_than_the_registry_is_not_offered_as_an_update(db, tmp_path, signer):
    key, trusted = signer
    manager = PluginManager(db, store_dir=tmp_path / "store", trusted_keys=trusted)
    newer = publish(tmp_path / "new", [source_copy(tmp_path, "oneshelf.arxiv", version="1.2.0", name="n")],
                    signer=key)
    review = run(manager.review_from_registry(newer, "oneshelf.arxiv"))
    run(manager.install_from_registry(newer, "oneshelf.arxiv", approved_permissions=review.permissions,
                                      expected_sha256=review.sha256))
    older = publish(tmp_path / "old", [source_copy(tmp_path, "oneshelf.arxiv", version="1.1.0", name="o")],
                    signer=key)
    assert run(manager.review_from_registry(older, "oneshelf.arxiv")).state == "installed_newer"
    with pytest.raises(InstallRejected, match="older"):
        run(manager.install_from_registry(older, "oneshelf.arxiv", approved_permissions=[]))


def test_the_same_version_already_installed_reads_as_installed(db, tmp_path, signer):
    key, trusted = signer
    manager = PluginManager(db, store_dir=tmp_path / "store", trusted_keys=trusted)
    run(sync_bundled(db, manager, bundled_dir(tmp_path, "oneshelf.gutenberg")))
    registry = publish(tmp_path / "reg", [source_copy(tmp_path, "oneshelf.gutenberg")], signer=key)
    assert run(manager.review_from_registry(registry, "oneshelf.gutenberg")).state == "installed"
