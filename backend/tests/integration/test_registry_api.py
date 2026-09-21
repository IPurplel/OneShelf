"""Sources → Registry, through the API a person's browser actually calls.

A fresh library already has its eight official sources, so the Registry must read them as installed —
not offer to install them again. These start the real application with a bundled directory and a local
registry holding the same eight packages, built by the canonical builder, and walk the flows the Sources
screen offers: review, install, reinstall, update, and what happens when the Registry is down.
"""
import hashlib
import json
import shutil
from pathlib import Path

from starlette.testclient import TestClient

from oneshelf.api.app import AppConfig, create_app
from oneshelf.plugins.bundled import build_package

OFFICIAL = Path(__file__).resolve().parents[2] / "plugins" / "official"
EIGHT = ["oneshelf.3asq", "oneshelf.arxiv", "oneshelf.gutenberg", "oneshelf.hindawi", "oneshelf.mangadex",
         "oneshelf.standard-ebooks", "oneshelf.tapas", "oneshelf.webtoon"]


def _field(manifest, key):
    return next(line.split(":", 1)[1].strip() for line in manifest.splitlines() if line.startswith(f"{key}:"))


def registry_dir(tmp_path, overrides=None, *, api=None):
    """A registry with every official package; `overrides` swaps in edited sources by plugin id."""
    root = tmp_path / "registry"
    (root / "packages").mkdir(parents=True, exist_ok=True)
    entries = []
    for plugin in EIGHT:
        source = (overrides or {}).get(plugin, OFFICIAL / plugin)
        manifest = (source / "manifest.yaml").read_text(encoding="utf-8")
        version, name = _field(manifest, "version"), _field(manifest, "name")
        path = build_package(source, root / "packages" / f"{plugin}-{version}.osp")
        entry = {"id": plugin, "name": name, "version": version, "file": f"packages/{path.name}",
                 "sha256": hashlib.sha256(path.read_bytes()).hexdigest(), "trust_label": "official"}
        if api and plugin in api:
            entry["api"] = api[plugin]
        entries.append(entry)
    (root / "index.json").write_text(json.dumps({"schema": "oneshelf.registry/1", "plugins": entries}),
                                     encoding="utf-8")
    return root


def edited(tmp_path, plugin, *, version, extra_domain=None):
    target = tmp_path / "edited" / plugin
    shutil.copytree(OFFICIAL / plugin, target, dirs_exist_ok=True)
    manifest = target / "manifest.yaml"
    text = manifest.read_text(encoding="utf-8").replace("version: 1.0.0", f"version: {version}", 1)
    if extra_domain:
        text = text.replace("  domains: [", f"  domains: [{extra_domain}, ", 1)
    manifest.write_text(text, encoding="utf-8")
    return target


def start(tmp_path, registry=None, bundled=OFFICIAL):
    if isinstance(registry, Path):
        registry = registry.as_uri()
    config = AppConfig.from_env({
        "ONESHELF_DATA_DIR": str(tmp_path / "data"),
        "ONESHELF_ALLOWED_HOSTS": "testserver",
        "ONESHELF_SESSION_KEY_FILE": str(tmp_path / "keys" / "session.key"),
        "ONESHELF_BUNDLED_PLUGINS_DIR": str(bundled) if bundled else "",
        "ONESHELF_REGISTRY_URL": registry or "",
    })
    return TestClient(create_app(config), client=("127.0.0.1", 50000))


def listing(client):
    return {p["id"]: p for p in client.get("/api/registry").json()["plugins"]}


def test_a_fresh_library_reads_all_eight_official_sources_as_installed(tmp_path):
    with start(tmp_path, registry_dir(tmp_path)) as client:
        plugins = listing(client)
    assert sorted(plugins) == EIGHT
    for plugin in plugins.values():
        assert plugin["state"] == "installed", plugin
        assert plugin["installed_version"] == plugin["version"] == "1.0.0"
        assert (plugin["channel"], plugin["installed_trust"]) == ("bundled", "official")


def test_an_unsigned_official_claim_reads_as_community_in_the_listing(tmp_path):
    with start(tmp_path, registry_dir(tmp_path)) as client:
        plugin = listing(client)["oneshelf.tapas"]
    assert (plugin["trust_label"], plugin["signed"], plugin["effective_trust"]) == ("official", False, "community")


def test_a_removed_source_reads_as_available_and_reinstalls_through_review(tmp_path):
    with start(tmp_path, registry_dir(tmp_path)) as client:
        assert client.delete("/api/sources/oneshelf.tapas").status_code in (200, 204)
        assert listing(client)["oneshelf.tapas"]["state"] == "available"

        review = client.post("/api/registry/review-package", json={"plugin_id": "oneshelf.tapas"}).json()
        assert review["state"] == "available" and review["tests_passed"] is True
        assert review["added_permissions"] == review["permissions"] and review["permissions"]

        installed = client.post("/api/registry/install", json={
            "plugin_id": "oneshelf.tapas", "approved_permissions": review["permissions"],
            "sha256": review["sha256"]}).json()
        assert installed["state"] == "active"
        sources = [s for s in client.get("/api/sources").json()["sources"] if s["id"] == "oneshelf.tapas"]
        assert len(sources) == 1 and sources[0]["state"] == "active" and sources[0]["channel"] == "registry"
        assert listing(client)["oneshelf.tapas"]["state"] == "installed"


def test_a_newer_version_reads_as_an_update_and_installs_with_rollback(tmp_path):
    registry = registry_dir(tmp_path, {"oneshelf.arxiv": edited(tmp_path, "oneshelf.arxiv", version="1.1.0")})
    with start(tmp_path, registry) as client:
        plugin = listing(client)["oneshelf.arxiv"]
        assert (plugin["state"], plugin["installed_version"], plugin["version"]) == ("update_available", "1.0.0", "1.1.0")
        review = client.post("/api/registry/review-package", json={"plugin_id": "oneshelf.arxiv"}).json()
        assert review["added_permissions"] == []
        outcome = client.post("/api/registry/install", json={
            "plugin_id": "oneshelf.arxiv", "approved_permissions": [], "sha256": review["sha256"]}).json()
        assert outcome["state"] == "active"
        assert listing(client)["oneshelf.arxiv"]["state"] == "installed"
        assert client.post("/api/sources/oneshelf.arxiv/rollback").status_code == 200


def test_an_update_asking_for_more_is_reviewed_not_approved(tmp_path):
    registry = registry_dir(tmp_path, {"oneshelf.hindawi": edited(tmp_path, "oneshelf.hindawi", version="1.1.0",
                                                                  extra_domain="www.hindawi.org")})
    with start(tmp_path, registry) as client:
        review = client.post("/api/registry/review-package", json={"plugin_id": "oneshelf.hindawi"}).json()
        assert review["added_permissions"] == ["network:domain:www.hindawi.org"]
        outcome = client.post("/api/registry/install", json={
            "plugin_id": "oneshelf.hindawi", "approved_permissions": [], "sha256": review["sha256"]}).json()
        assert outcome["state"] == "pending_review"
        assert listing(client)["oneshelf.hindawi"]["state"] == "pending_review"
        hindawi = next(s for s in client.get("/api/sources").json()["sources"] if s["id"] == "oneshelf.hindawi")
        assert (hindawi["state"], hindawi["version"]) == ("active", "1.0.0")      # approved version still runs


def test_opening_the_registry_never_enables_a_disabled_source(tmp_path):
    registry = registry_dir(tmp_path, {"oneshelf.webtoon": edited(tmp_path, "oneshelf.webtoon", version="1.1.0")})
    with start(tmp_path, registry) as client:
        client.post("/api/sources/oneshelf.webtoon/disable")
        for _ in range(3):
            plugin = listing(client)["oneshelf.webtoon"]
        assert (plugin["plugin_state"], plugin["state"]) == ("disabled", "update_available")
        state = next(s for s in client.get("/api/sources").json()["sources"] if s["id"] == "oneshelf.webtoon")
        assert state["state"] == "disabled"


def test_an_install_whose_package_changed_after_review_is_refused(tmp_path):
    with start(tmp_path, registry_dir(tmp_path)) as client:
        client.delete("/api/sources/oneshelf.tapas")
        review = client.post("/api/registry/review-package", json={"plugin_id": "oneshelf.tapas"}).json()
        response = client.post("/api/registry/install", json={
            "plugin_id": "oneshelf.tapas", "approved_permissions": review["permissions"], "sha256": "0" * 64})
    assert response.status_code == 422 and "reviewed" in response.json()["error"]["message"]


def test_an_adapter_for_a_newer_oneshelf_is_labelled_as_such_and_not_installed(tmp_path):
    with start(tmp_path, registry_dir(tmp_path, api={"oneshelf.tapas": "1.9"})) as client:
        client.delete("/api/sources/oneshelf.tapas")
        assert listing(client)["oneshelf.tapas"]["state"] == "incompatible"
        response = client.post("/api/registry/review-package", json={"plugin_id": "oneshelf.tapas"})
    assert response.status_code == 422 and "newer OneShelf" in response.json()["error"]["message"]


def test_when_the_registry_is_unreachable_everything_else_still_works(tmp_path):
    with start(tmp_path, "https://registry.invalid/index.json") as client:
        registry = client.get("/api/registry")
        assert registry.status_code == 502 and registry.json()["error"]["code"] == "REGISTRY_UNAVAILABLE"
        assert client.get("/api/ready").json()["ready"] is True
        sources = client.get("/api/sources").json()["sources"]
        assert len(sources) == 8 and all(s["state"] == "active" for s in sources)
        assert client.get("/api/registry").status_code == 502


def test_a_malformed_registry_is_reported_not_crashed_on(tmp_path):
    root = tmp_path / "registry"
    root.mkdir()
    (root / "index.json").write_text('{"schema": "oneshelf.registry/1", "plugins": [{"id": 1}]}', encoding="utf-8")
    with start(tmp_path, root) as client:
        assert client.get("/api/registry").status_code == 502
        assert client.get("/api/sources").status_code == 200


def test_without_a_registry_the_listing_says_so_plainly(tmp_path):
    with start(tmp_path, None) as client:
        assert client.get("/api/registry").json() == {"configured": False, "plugins": []}


def test_the_committed_official_registry_matches_what_a_fresh_library_bundles(tmp_path):
    committed = Path(__file__).resolve().parents[3] / "registry"
    with start(tmp_path, committed) as client:
        plugins = listing(client)
    assert sorted(plugins) == EIGHT
    assert {p["state"] for p in plugins.values()} == {"installed"}


def test_a_pending_update_is_approved_from_the_registry_review_bound_to_its_bytes(tmp_path):
    registry = registry_dir(tmp_path, {"oneshelf.hindawi": edited(tmp_path, "oneshelf.hindawi", version="1.1.0",
                                                                  extra_domain="www.hindawi.org")})
    with start(tmp_path, registry) as client:
        first = client.post("/api/registry/review-package", json={"plugin_id": "oneshelf.hindawi"}).json()
        client.post("/api/registry/install", json={"plugin_id": "oneshelf.hindawi", "approved_permissions": [],
                                                   "sha256": first["sha256"]})
        review = client.post("/api/registry/review-package", json={"plugin_id": "oneshelf.hindawi"}).json()
        assert review["state"] == "pending_review"
        assert review["added_permissions"] == ["network:domain:www.hindawi.org"]

        wrong = client.post("/api/registry/install", json={
            "plugin_id": "oneshelf.hindawi", "approved_permissions": review["permissions"], "sha256": "f" * 64})
        assert wrong.status_code == 422
        outcome = client.post("/api/registry/install", json={
            "plugin_id": "oneshelf.hindawi", "approved_permissions": review["permissions"],
            "sha256": review["sha256"]}).json()
        assert outcome["state"] == "active" and outcome["version"] == "1.1.0"
        hindawi = next(s for s in client.get("/api/sources").json()["sources"] if s["id"] == "oneshelf.hindawi")
        assert (hindawi["state"], hindawi["version"], hindawi["channel"]) == ("active", "1.1.0", "registry")
        assert listing(client)["oneshelf.hindawi"]["state"] == "installed"


def test_a_remote_visitor_without_a_passkey_cannot_read_or_install_from_the_registry(tmp_path):
    config = AppConfig.from_env({
        "ONESHELF_DATA_DIR": str(tmp_path / "data"), "ONESHELF_ALLOWED_HOSTS": "testserver",
        "ONESHELF_SESSION_KEY_FILE": str(tmp_path / "keys" / "session.key"),
        "ONESHELF_BUNDLED_PLUGINS_DIR": str(OFFICIAL), "ONESHELF_REGISTRY_URL": registry_dir(tmp_path).as_uri(),
    })
    with TestClient(create_app(config), client=("203.0.113.9", 50000)) as remote:
        assert remote.get("/api/registry").status_code == 401
        assert remote.post("/api/registry/review-package", json={"plugin_id": "oneshelf.tapas"}).status_code == 401
        assert remote.post("/api/registry/install", json={"plugin_id": "oneshelf.tapas"}).status_code == 401


def test_another_site_cannot_make_the_browser_install_from_the_registry(tmp_path):
    with start(tmp_path, registry_dir(tmp_path)) as client:
        client.delete("/api/sources/oneshelf.tapas")
        response = client.post("/api/registry/install", json={"plugin_id": "oneshelf.tapas"},
                               headers={"Origin": "https://evil.example"})
        assert response.status_code == 403
        assert listing(client)["oneshelf.tapas"]["state"] == "available"


# -- the Registry published from OneShelf-Adapters: mixed trust, sources Core has never heard of ------------

def adapters_registry(tmp_path, *, signer_dir=None):
    """A OneShelf-Adapters-style tree built by Core's adapter_repo tooling: the eight Official adapters,
    one Verified Community and one Community adapter that no OneShelf release bundles."""
    from oneshelf.plugins import adapter_repo
    root = tmp_path / "adapters-repo"
    for tier in ("official", "verified-community", "community"):
        (root / "adapters" / tier).mkdir(parents=True)
    for plugin in EIGHT:
        shutil.copytree(OFFICIAL / plugin, root / "adapters" / "official" / plugin)
    for tier, plugin in (("verified-community", "example.verified-books"), ("community", "example.books")):
        target = root / "adapters" / tier / plugin
        shutil.copytree(OFFICIAL / "oneshelf.gutenberg", target)
        manifest = target / "manifest.yaml"
        manifest.write_text(manifest.read_text(encoding="utf-8").replace("id: oneshelf.gutenberg", f"id: {plugin}"),
                            encoding="utf-8")
    out = tmp_path / "published"
    args = ["build-registry", "--root", str(root), "--out", str(out)]
    public = None
    if signer_dir is not None:
        from cryptography.hazmat.primitives import serialization
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
        key = Ed25519PrivateKey.generate()                       # TEST-ONLY, in the test's tmp directory
        signer_dir.mkdir(parents=True)
        (signer_dir / "test-only.pem").write_bytes(key.private_bytes(
            serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))
        args += ["--signing-key", str(signer_dir / "test-only.pem"), "--key-id", "test-only-1"]
        public = adapter_repo.public_line(key, "test-only-1")
    else:
        args += ["--unsigned-preview"]
    assert adapter_repo.main(args) == 0
    return out, public


def start_with_keys(tmp_path, registry, keys):
    config = AppConfig.from_env({
        "ONESHELF_DATA_DIR": str(tmp_path / "data"), "ONESHELF_ALLOWED_HOSTS": "testserver",
        "ONESHELF_SESSION_KEY_FILE": str(tmp_path / "keys" / "session.key"),
        "ONESHELF_BUNDLED_PLUGINS_DIR": str(OFFICIAL), "ONESHELF_REGISTRY_URL": registry.as_uri(),
        "ONESHELF_REGISTRY_TRUSTED_KEYS": keys or "",
    })
    return TestClient(create_app(config), client=("127.0.0.1", 50000))


def test_a_registry_only_source_installs_without_any_change_to_oneshelf(tmp_path):
    registry, _ = adapters_registry(tmp_path)
    with start_with_keys(tmp_path, registry, None) as client:
        books = listing(client)["example.books"]
        assert (books["state"], books["trust_label"], books["effective_trust"]) == ("available", "community", "community")
        review = client.post("/api/registry/review-package", json={"plugin_id": "example.books"}).json()
        assert review["tests_passed"] and review["added_permissions"] == review["permissions"]
        installed = client.post("/api/registry/install", json={
            "plugin_id": "example.books", "approved_permissions": review["permissions"], "sha256": review["sha256"]})
        assert installed.json()["state"] == "active"
        sources = {s["id"]: s for s in client.get("/api/sources").json()["sources"]}
        assert (sources["example.books"]["channel"], sources["example.books"]["trust_label"]) == ("registry", "community")
        assert sorted(p for p, s in sources.items() if s["channel"] == "bundled") == EIGHT   # the bundled set is untouched


def test_trust_follows_the_signature_and_the_installations_keys_never_the_label(tmp_path):
    registry, public = adapters_registry(tmp_path, signer_dir=tmp_path / "signer")
    with start_with_keys(tmp_path / "trusting", registry, public) as client:
        plugins = listing(client)
    assert plugins["oneshelf.tapas"]["effective_trust"] == "official"
    assert plugins["example.verified-books"]["effective_trust"] == "verified_community"
    assert plugins["example.books"]["effective_trust"] == "community"
    with start_with_keys(tmp_path / "not-trusting", registry, None) as client:        # same Registry, no keys
        plugins = listing(client)
    assert {p["effective_trust"] for p in plugins.values()} == {"community"}


def test_an_unsigned_preview_never_reads_as_official(tmp_path):
    registry, _ = adapters_registry(tmp_path)
    _, public = adapters_registry(tmp_path / "other", signer_dir=tmp_path / "other-signer")
    with start_with_keys(tmp_path, registry, public) as client:
        plugins = listing(client)
    assert plugins["oneshelf.tapas"]["trust_label"] == "official" and plugins["oneshelf.tapas"]["signed"] is False
    assert {p["effective_trust"] for p in plugins.values()} == {"community"}
