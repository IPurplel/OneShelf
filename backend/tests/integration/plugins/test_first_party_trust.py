"""First-party trust (owner decision, 2026-09-21): the configured OneShelf Registry needs no signature.

For the one Registry an installation names in ONESHELF_FIRST_PARTY_REGISTRY_URL — by default the
OneShelf-Adapters Registry — the repository-controlled tier is the trust: `official` is Official,
`verified_community` is Verified Community. Any other Registry claiming either stays Community unless a
trusted key signs it. Hashes, review and every network rule are unchanged; a valid signature is still
stronger evidence and is reported as such, and an invalid one from a trusted key is still refused.
Keys here are TEST-ONLY, generated in tmp directories.
"""
import asyncio
import json
import shutil
from pathlib import Path

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from starlette.testclient import TestClient

from oneshelf.api.app import AppConfig, create_app
from oneshelf.plugins import adapter_repo
from oneshelf.plugins.manager import InstallRejected, PluginManager
from oneshelf.plugins.registry import DirectoryRegistry, parse_index

OFFICIAL = Path(__file__).resolve().parents[3] / "plugins" / "official"


def run(coro):
    return asyncio.run(asyncio.wait_for(coro, 120))


def tree(root: Path) -> Path:
    """Official arXiv, a Verified Community and a Community adapter, as OneShelf-Adapters lays them out."""
    for tier in ("official", "verified-community", "community"):
        (root / "adapters" / tier).mkdir(parents=True)
    shutil.copytree(OFFICIAL / "oneshelf.arxiv", root / "adapters" / "official" / "oneshelf.arxiv")
    for tier, plugin in (("verified-community", "example.verified"), ("community", "example.books")):
        target = root / "adapters" / tier / plugin
        shutil.copytree(OFFICIAL / "oneshelf.gutenberg", target)
        manifest = target / "manifest.yaml"
        manifest.write_text(manifest.read_text(encoding="utf-8").replace("id: oneshelf.gutenberg", f"id: {plugin}"),
                            encoding="utf-8")
    return root


def key_pair(directory: Path):
    key = Ed25519PrivateKey.generate()                               # TEST-ONLY
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / "test-only.pem"
    path.write_bytes(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                       serialization.NoEncryption()))
    return path, key.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)


def publish(tmp_path: Path, name: str = "published", *, key: Path | None = None) -> Path:
    out = tmp_path / name
    args = ["build-registry", "--root", str(tree(tmp_path / f"{name}-src")), "--out", str(out)]
    if key is not None:
        args += ["--signing-key", str(key), "--key-id", "k1"]
    assert adapter_repo.main(args) == 0
    return out


def entry(out: Path, plugin: str):
    return next(e for e in parse_index((out / "index.json").read_bytes()) if e.id == plugin)


def review(manager, registry, plugin):
    return run(manager.review_from_registry(registry, plugin))


# -- the manager: one decision, with its basis ------------------------------------------------------------------

def test_first_party_tiers_map_to_their_trust_without_a_signature(db, tmp_path):          # 1, 2, 3
    out = publish(tmp_path)
    registry = DirectoryRegistry(out)
    manager = PluginManager(db, store_dir=tmp_path / "store", first_party_registry=registry.location)
    expected = {"oneshelf.arxiv": "official", "example.verified": "verified_community", "example.books": "community"}
    for plugin, trust in expected.items():
        result = review(manager, registry, plugin)
        assert (result.effective_trust, result.signed) == (trust, False), plugin
        assert result.trust_basis == ("first_party" if trust != "community" else "none"), plugin


def test_installing_from_the_first_party_registry_records_the_tier_trust(db, tmp_path):
    out = publish(tmp_path)
    registry = DirectoryRegistry(out)
    manager = PluginManager(db, store_dir=tmp_path / "store", first_party_registry=registry.location)
    for plugin in ("oneshelf.arxiv", "example.verified"):
        r = review(manager, registry, plugin)
        run(manager.install_from_registry(registry, plugin, approved_permissions=list(r.permissions),
                                          expected_sha256=r.sha256))
    assert manager.get("oneshelf.arxiv").trust_label == "official"
    assert manager.get("example.verified").trust_label == "verified_community"


@pytest.mark.parametrize("first_party", [None, "", "file:///somewhere/else/index.json"])
def test_any_other_registry_claiming_signed_tiers_stays_community(db, tmp_path, first_party):   # 4, 5, 7
    out = publish(tmp_path)
    registry = DirectoryRegistry(out)
    manager = PluginManager(db, store_dir=tmp_path / "store", first_party_registry=first_party)
    for plugin in ("oneshelf.arxiv", "example.verified", "example.books"):
        result = review(manager, registry, plugin)
        assert (result.effective_trust, result.trust_basis) == ("community", "none"), plugin
    r = review(manager, registry, "oneshelf.arxiv")
    run(manager.install_from_registry(registry, "oneshelf.arxiv", approved_permissions=list(r.permissions)))
    assert manager.get("oneshelf.arxiv").trust_label == "community"


def test_first_party_identity_is_the_exact_location_not_a_lookalike(db, tmp_path):
    out = publish(tmp_path)
    registry = DirectoryRegistry(out)
    for lookalike in (registry.location + "/", registry.location + "x", registry.location.upper()):
        manager = PluginManager(db, store_dir=tmp_path / "store", first_party_registry=lookalike)
        assert manager.registry_trust(entry(out, "oneshelf.arxiv"), registry.location) == ("community", "none")


def test_a_package_that_does_not_match_its_hash_is_refused_even_first_party(db, tmp_path):    # 8
    out = publish(tmp_path)
    index = json.loads((out / "index.json").read_text(encoding="utf-8"))
    item = next(p for p in index["plugins"] if p["id"] == "oneshelf.arxiv")
    (out / item["file"]).write_bytes((out / item["file"]).read_bytes() + b"tampered")
    registry = DirectoryRegistry(out)
    manager = PluginManager(db, store_dir=tmp_path / "store", first_party_registry=registry.location)
    with pytest.raises(InstallRejected, match="hash"):
        review(manager, registry, "oneshelf.arxiv")
    with pytest.raises(InstallRejected, match="hash"):
        run(manager.install_from_registry(registry, "oneshelf.arxiv", approved_permissions=[]))


def test_a_valid_trusted_signature_is_stronger_evidence_anywhere(db, tmp_path):                # 9
    key, public = key_pair(tmp_path / "keys")
    out = publish(tmp_path, key=key)
    registry = DirectoryRegistry(out)
    for n, first_party in enumerate((None, registry.location)):
        manager = PluginManager(db, store_dir=tmp_path / f"store-{n}", trusted_keys={"k1": public},
                                first_party_registry=first_party)
        for plugin, trust in (("oneshelf.arxiv", "official"), ("example.verified", "verified_community")):
            result = review(manager, registry, plugin)
            assert (result.effective_trust, result.trust_basis, result.signed) == (trust, "signature", True)


def test_an_invalid_signature_from_a_trusted_key_is_refused_even_first_party(db, tmp_path):   # 10
    key, _ = key_pair(tmp_path / "keys")
    _, other_public = key_pair(tmp_path / "other")
    out = publish(tmp_path, key=key)
    registry = DirectoryRegistry(out)
    manager = PluginManager(db, store_dir=tmp_path / "store", trusted_keys={"k1": other_public},
                            first_party_registry=registry.location)
    with pytest.raises(InstallRejected, match="signature"):
        review(manager, registry, "oneshelf.arxiv")
    with pytest.raises(InstallRejected, match="signature"):
        run(manager.install_from_registry(registry, "oneshelf.arxiv", approved_permissions=[]))
    assert manager.registry_trust(entry(out, "oneshelf.arxiv"), registry.location) == ("invalid_signature", "none")


# -- the application: configuration decides, and only exactly -----------------------------------------------------

def start(tmp_path, registry_url, first_party):
    env = {"ONESHELF_DATA_DIR": str(tmp_path / "data"), "ONESHELF_ALLOWED_HOSTS": "testserver",
           "ONESHELF_SESSION_KEY_FILE": str(tmp_path / "keys" / "session.key"),
           "ONESHELF_REGISTRY_URL": registry_url}
    if first_party is not None:
        env["ONESHELF_FIRST_PARTY_REGISTRY_URL"] = first_party
    return TestClient(create_app(AppConfig.from_env(env)), client=("127.0.0.1", 50000))


def trust_of(client):
    return {p["id"]: (p["effective_trust"], p["trust_basis"]) for p in client.get("/api/registry").json()["plugins"]}


def test_the_configured_first_party_registry_reads_by_tier(tmp_path):
    url = publish(tmp_path).as_uri()
    with start(tmp_path / "app", url, url) as client:
        assert trust_of(client) == {"oneshelf.arxiv": ("official", "first_party"),
                                    "example.verified": ("verified_community", "first_party"),
                                    "example.books": ("community", "none")}


def test_pointing_the_registry_elsewhere_does_not_inherit_first_party_trust(tmp_path):         # 6
    first_party = publish(tmp_path, "first-party").as_uri()
    custom = publish(tmp_path, "custom").as_uri()                          # claims official and verified too
    with start(tmp_path / "app", custom, first_party) as client:
        assert set(trust_of(client).values()) == {("community", "none")}


@pytest.mark.parametrize("first_party", [None, ""])
def test_without_a_first_party_setting_nothing_is_first_party(tmp_path, first_party):           # 7
    url = publish(tmp_path).as_uri()
    with start(tmp_path / "app", url, first_party) as client:
        assert set(trust_of(client).values()) == {("community", "none")}


def test_the_review_reports_the_basis_so_the_screen_never_overclaims(tmp_path):
    url = publish(tmp_path).as_uri()
    with start(tmp_path / "app", url, url) as client:
        body = client.post("/api/registry/review-package", json={"plugin_id": "oneshelf.arxiv"}).json()
    assert (body["effective_trust"], body["trust_basis"], body["signed"]) == ("official", "first_party", False)


def test_a_default_install_still_names_no_first_party_registry_in_code(tmp_path):
    assert AppConfig.from_env({"ONESHELF_DATA_DIR": str(tmp_path)}).first_party_registry_url is None
