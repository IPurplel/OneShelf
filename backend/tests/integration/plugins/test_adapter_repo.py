"""`oneshelf.plugins.adapter_repo`: the checks and Registry build OneShelf-Adapters runs, owned by Core.

The adapter repository pins a Core revision and calls this module, so its contributors are held to exactly
the rules an install applies — nothing is re-implemented there. These build throwaway adapter trees from
copies of the real official adapters and pin: tier structure, identity, the declarative-only payload,
secrets, fixture limits, immutability per id+version, trust derived from the tier (never from a file a
contributor edits), and the signing policy. Keys here are TEST-ONLY, generated in tmp directories.
"""
import asyncio
import base64
import hashlib
import json
import shutil
from pathlib import Path

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from oneshelf.plugins import adapter_repo
from oneshelf.plugins.bundled import build_package
from oneshelf.plugins.manager import PluginManager
from oneshelf.plugins.registry import DirectoryRegistry, parse_index

OFFICIAL = Path(__file__).resolve().parents[3] / "plugins" / "official"
EIGHT = ["oneshelf.3asq", "oneshelf.arxiv", "oneshelf.gutenberg", "oneshelf.hindawi", "oneshelf.mangadex",
         "oneshelf.standard-ebooks", "oneshelf.tapas", "oneshelf.webtoon"]


def derived(source: Path, target: Path, new_id: str, *, version: str | None = None) -> Path:
    """A second adapter made from an official one: same recipes, its own identity."""
    shutil.copytree(source, target)
    manifest = target / "manifest.yaml"
    text = manifest.read_text(encoding="utf-8").replace(f"id: {source.name}", f"id: {new_id}", 1)
    if version:
        text = text.replace("version: 1.0.0", f"version: {version}", 1)
    manifest.write_text(text, encoding="utf-8")
    return target


def make_tree(root: Path, *, official=("oneshelf.gutenberg", "oneshelf.arxiv"), verified=(), community=()) -> Path:
    for tier in ("official", "verified-community", "community"):
        (root / "adapters" / tier).mkdir(parents=True, exist_ok=True)
    for plugin in official:
        shutil.copytree(OFFICIAL / plugin, root / "adapters" / "official" / plugin)
    for plugin in verified:
        derived(OFFICIAL / "oneshelf.gutenberg", root / "adapters" / "verified-community" / plugin, plugin)
    for plugin in community:
        derived(OFFICIAL / "oneshelf.gutenberg", root / "adapters" / "community" / plugin, plugin)
    return root


def key_pair(directory: Path) -> tuple[Path, str]:
    """TEST-ONLY Ed25519 key in a tmp directory."""
    key = Ed25519PrivateKey.generate()
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / "test-only.pem"
    path.write_bytes(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                       serialization.NoEncryption()))
    path.chmod(0o600)
    raw = key.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    return path, base64.b64encode(raw).decode()


def run(*argv) -> int:
    return adapter_repo.main([str(a) for a in argv])


def problems_for(root, *args, capsys) -> str:
    assert run("check-all", "--root", root, *args) != 0
    return capsys.readouterr().err


def community(root: Path, plugin: str = "example.books") -> Path:
    return root / "adapters" / "community" / plugin


# -- structure and identity ---------------------------------------------------------------------------------

def test_a_well_formed_tree_passes(tmp_path):
    root = make_tree(tmp_path / "repo", community=["example.books"])
    assert run("check-all", "--root", root) == 0


def test_all_eight_official_adapters_pass_as_they_are(tmp_path):
    root = make_tree(tmp_path / "repo", official=EIGHT)
    assert run("check-all", "--root", root) == 0


def test_an_unknown_tier_directory_fails(tmp_path, capsys):
    root = make_tree(tmp_path / "repo")
    (root / "adapters" / "trusted").mkdir()
    assert "trusted" in problems_for(root, capsys=capsys)


def test_the_same_id_in_two_tiers_fails(tmp_path, capsys):
    root = make_tree(tmp_path / "repo", community=["oneshelf.gutenberg"])
    assert "more than one tier" in problems_for(root, capsys=capsys)


def test_a_manifest_id_that_differs_from_its_directory_fails(tmp_path, capsys):
    root = make_tree(tmp_path / "repo")
    shutil.copytree(OFFICIAL / "oneshelf.tapas", community(root, "example.not-tapas"))
    assert "example.not-tapas" in problems_for(root, capsys=capsys)


def test_a_directory_name_that_is_not_a_plugin_id_fails(tmp_path, capsys):
    root = make_tree(tmp_path / "repo")
    derived(OFFICIAL / "oneshelf.gutenberg", community(root, "Bad_Name"), "Bad_Name")
    assert "Bad_Name" in problems_for(root, capsys=capsys)


# -- the package itself -------------------------------------------------------------------------------------

def test_an_invalid_manifest_fails(tmp_path, capsys):
    root = make_tree(tmp_path / "repo", community=["example.books"])
    manifest = community(root) / "manifest.yaml"
    manifest.write_text(manifest.read_text(encoding="utf-8").replace("version: 1.0.0", "version: one", 1),
                        encoding="utf-8")
    assert "example.books" in problems_for(root, capsys=capsys)


def test_an_invalid_recipe_fails(tmp_path, capsys):
    root = make_tree(tmp_path / "repo", community=["example.books"])
    recipe = sorted((community(root) / "recipes").glob("*.yaml"))[0]
    recipe.write_text("capability: search\nsteps: [not, a, recipe]\n", encoding="utf-8")
    assert "example.books" in problems_for(root, capsys=capsys)


def test_a_base_url_on_an_undeclared_domain_fails(tmp_path, capsys):
    root = make_tree(tmp_path / "repo", community=["example.books"])
    source = community(root) / "source.yaml"
    text = source.read_text(encoding="utf-8")
    line = next(l for l in text.splitlines() if l.startswith("base_url:"))
    source.write_text(text.replace(line, "base_url: https://undeclared.example.net/"), encoding="utf-8")
    assert "allowlisted" in problems_for(root, capsys=capsys)


@pytest.mark.parametrize("name", ["payload.py", "run.sh", "inject.js", "lib.so", "tool.exe", "mod.wasm"])
def test_executable_or_code_files_fail(tmp_path, capsys, name):
    root = make_tree(tmp_path / "repo", community=["example.books"])
    (community(root) / name).write_text("x", encoding="utf-8")
    assert name in problems_for(root, capsys=capsys)


def test_a_symlink_inside_an_adapter_fails(tmp_path, capsys):
    root = make_tree(tmp_path / "repo", community=["example.books"])
    outside = tmp_path / "secret.txt"
    outside.write_text("not yours", encoding="utf-8")
    (community(root) / "tests" / "fixtures" / "leak.json").symlink_to(outside)
    assert "symlink" in problems_for(root, capsys=capsys)


def test_an_adapter_directory_that_is_a_symlink_fails(tmp_path, capsys):
    root = make_tree(tmp_path / "repo")
    elsewhere = derived(OFFICIAL / "oneshelf.gutenberg", tmp_path / "elsewhere" / "example.books", "example.books")
    community(root).symlink_to(elsewhere, target_is_directory=True)
    assert "symlink" in problems_for(root, capsys=capsys)


def test_the_canonical_builder_refuses_to_follow_a_symlink(tmp_path):
    source = derived(OFFICIAL / "oneshelf.gutenberg", tmp_path / "example.books", "example.books")
    (source / "tests" / "fixtures" / "leak.json").symlink_to(tmp_path / "anything")
    with pytest.raises(ValueError, match="symlink"):
        build_package(source, tmp_path / "out.osp")


def test_an_oversized_fixture_fails(tmp_path, capsys):
    root = make_tree(tmp_path / "repo", community=["example.books"])
    big = community(root) / "tests" / "fixtures" / "huge.json"
    big.write_text('{"x": "' + "a" * (adapter_repo.MAX_TEXT_FIXTURE_BYTES + 1) + '"}', encoding="utf-8")
    assert "huge.json" in problems_for(root, capsys=capsys)


def test_a_large_binary_fixture_fails(tmp_path, capsys):
    root = make_tree(tmp_path / "repo", community=["example.books"])
    image = community(root) / "tests" / "fixtures" / "page.png"
    image.write_bytes(b"\x89PNG" + b"\0" * adapter_repo.MAX_BINARY_FIXTURE_BYTES)
    assert "page.png" in problems_for(root, capsys=capsys)


@pytest.mark.parametrize("content", [
    "-----BEGIN " + "PRIVATE KEY-----\nMC4CAQAwBQYDK2VwBCIEI\n-----END " + "PRIVATE KEY-----",
    "token: ghp_" + "A1b2C3d4E5f6G7h8I9j0K1l2M3n4O5p6Q7r8",
    "Cookie: session_id=abcdef0123456789abcdef0123456789",
    "Authorization: Bearer eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.dozjgNryP4J3jVmNHl0w5N_XgL0n3I9PlFUP0THsR8U",
    "aws_key: AKIA" + "ABCDEFGHIJKLMNOP",
])
def test_likely_secrets_fail(tmp_path, capsys, content):
    root = make_tree(tmp_path / "repo", community=["example.books"])
    (community(root) / "tests" / "fixtures" / "notes.txt").write_text(content, encoding="utf-8")
    assert "secret" in problems_for(root, capsys=capsys)


def test_an_env_file_fails(tmp_path, capsys):
    root = make_tree(tmp_path / "repo", community=["example.books"])
    (community(root) / ".env").write_text("A=1", encoding="utf-8")
    assert ".env" in problems_for(root, capsys=capsys)


def test_an_adapter_whose_packaged_tests_fail_fails(tmp_path, capsys):
    root = make_tree(tmp_path / "repo", community=["example.books"])
    for fixture in (community(root) / "tests" / "fixtures").glob("*.json"):
        fixture.write_text("{}", encoding="utf-8")
    assert "packaged tests failed" in problems_for(root, capsys=capsys)


def test_an_adapter_for_a_newer_plugin_api_fails(tmp_path, capsys):
    root = make_tree(tmp_path / "repo", community=["example.books"])
    manifest = community(root) / "manifest.yaml"
    manifest.write_text(manifest.read_text(encoding="utf-8").replace("api: '1.0'", "api: '1.9'", 1),
                        encoding="utf-8")
    assert "newer OneShelf" in problems_for(root, capsys=capsys)


def test_check_one_adapter_by_id(tmp_path):
    root = make_tree(tmp_path / "repo", community=["example.books"])
    assert run("check", "--root", root, "example.books") == 0
    assert run("check", "--root", root, "example.missing") != 0


# -- immutability against what is already published ---------------------------------------------------------

def published(root: Path, out: Path) -> Path:
    assert run("build-registry", "--root", root, "--out", out, "--unsigned-preview") == 0
    return out


def bump(manifest: Path, old: str, new: str) -> None:
    manifest.write_text(manifest.read_text(encoding="utf-8").replace(f"version: {old}", f"version: {new}", 1),
                        encoding="utf-8")


def test_changed_content_under_the_same_version_fails(tmp_path, capsys):
    root = make_tree(tmp_path / "repo", community=["example.books"])
    baseline = published(root, tmp_path / "published")
    recipe = sorted((community(root) / "recipes").glob("*.yaml"))[0]
    recipe.write_text(recipe.read_text(encoding="utf-8") + "\n# changed\n", encoding="utf-8")
    err = problems_for(root, "--baseline", baseline, capsys=capsys)
    assert "version" in err and "example.books" in err


def test_a_version_bump_with_changed_content_passes(tmp_path):
    root = make_tree(tmp_path / "repo", community=["example.books"])
    baseline = published(root, tmp_path / "published")
    recipe = sorted((community(root) / "recipes").glob("*.yaml"))[0]
    recipe.write_text(recipe.read_text(encoding="utf-8") + "\n# changed\n", encoding="utf-8")
    bump(community(root) / "manifest.yaml", "1.0.0", "1.0.1")
    assert run("check-all", "--root", root, "--baseline", baseline) == 0


def test_a_version_downgrade_fails(tmp_path, capsys):
    root = make_tree(tmp_path / "repo", community=["example.books"])
    bump(community(root) / "manifest.yaml", "1.0.0", "1.2.0")
    baseline = published(root, tmp_path / "published")
    bump(community(root) / "manifest.yaml", "1.2.0", "1.1.0")
    assert "downgrade" in problems_for(root, "--baseline", baseline, capsys=capsys)


def test_repackaging_the_same_files_under_the_same_version_passes(tmp_path, monkeypatch):
    """Immutability is about the adapter's files, not the zip container around them."""
    import zipfile

    def deflated(source_dir, destination):
        destination = Path(destination)
        destination.parent.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(destination, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            for path in sorted(p for p in Path(source_dir).rglob("*") if p.is_file()):
                archive.write(path, path.relative_to(source_dir).as_posix())
        return destination

    root = make_tree(tmp_path / "repo", community=["example.books"])
    monkeypatch.setattr(adapter_repo, "build_package", deflated)
    baseline = published(root, tmp_path / "published")
    monkeypatch.undo()
    assert run("check-all", "--root", root, "--baseline", baseline) == 0


def test_rebuilding_a_published_version_reproduces_its_bytes(tmp_path):
    root = make_tree(tmp_path / "repo", community=["example.books"])
    baseline = published(root, tmp_path / "published")
    assert run("reproducible", "--root", root, "--baseline", baseline) == 0


def test_a_build_that_does_not_reproduce_published_bytes_fails(tmp_path, monkeypatch, capsys):
    import zipfile

    def deflated(source_dir, destination):
        destination = Path(destination)
        destination.parent.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(destination, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            for path in sorted(p for p in Path(source_dir).rglob("*") if p.is_file()):
                archive.write(path, path.relative_to(source_dir).as_posix())
        return destination

    root = make_tree(tmp_path / "repo", community=["example.books"])
    monkeypatch.setattr(adapter_repo, "build_package", deflated)
    baseline = published(root, tmp_path / "published")
    monkeypatch.undo()
    assert run("reproducible", "--root", root, "--baseline", baseline) != 0
    assert "reproduce" in capsys.readouterr().err


def test_versions_not_yet_published_are_not_compared(tmp_path):
    root = make_tree(tmp_path / "repo", community=["example.books"])
    baseline = published(root, tmp_path / "published")
    bump(community(root) / "manifest.yaml", "1.0.0", "1.0.1")
    recipe = sorted((community(root) / "recipes").glob("*.yaml"))[0]
    recipe.write_text(recipe.read_text(encoding="utf-8") + "\n# changed\n", encoding="utf-8")
    assert run("reproducible", "--root", root, "--baseline", baseline) == 0


def test_the_canonical_builder_is_the_same_on_every_platform(tmp_path):
    """No compression (zlib implementations differ), and every header field fixed."""
    import zipfile
    path = build_package(OFFICIAL / "oneshelf.gutenberg", tmp_path / "g.osp")
    with zipfile.ZipFile(path) as archive:
        infos = archive.infolist()
    assert infos and [i.filename for i in infos] == sorted(i.filename for i in infos)
    for info in infos:
        assert info.compress_type == zipfile.ZIP_STORED
        assert info.create_system == 3 and info.external_attr == 0o100644 << 16
        assert info.date_time == (2026, 1, 1, 0, 0, 0) and info.extra == b"" and info.comment == b""


# -- the Registry: trust from the tier, signatures where the tier needs them ----------------------------------

def test_trust_labels_come_from_the_tier(tmp_path):
    root = make_tree(tmp_path / "repo", verified=["example.verified"], community=["example.books"])
    key, _ = key_pair(tmp_path / "keys")
    out = tmp_path / "reg"
    assert run("build-registry", "--root", root, "--out", out, "--signing-key", key, "--key-id", "k1") == 0
    entries = {e.id: e for e in parse_index((out / "index.json").read_bytes())}
    assert entries["oneshelf.gutenberg"].trust_label == "official" and entries["oneshelf.gutenberg"].signature
    assert entries["example.verified"].trust_label == "verified_community" and entries["example.verified"].signature
    assert entries["example.books"].trust_label == "community" and entries["example.books"].signature is None


def test_signatures_are_optional_by_default(tmp_path):
    """Owner decision, 2026-09-21: the first-party Registry's tiers are its trust; signing is extra evidence."""
    root = make_tree(tmp_path / "repo", verified=["example.verified"])
    assert run("build-registry", "--root", root, "--out", tmp_path / "reg") == 0
    entries = {e.id: e for e in parse_index((tmp_path / "reg" / "index.json").read_bytes())}
    assert entries["oneshelf.gutenberg"].trust_label == "official" and entries["oneshelf.gutenberg"].signature is None
    assert entries["example.verified"].trust_label == "verified_community"


def test_official_publication_without_a_key_fails_when_signing_is_required(tmp_path, capsys):
    root = make_tree(tmp_path / "repo")
    assert run("build-registry", "--root", root, "--out", tmp_path / "reg", "--require-signing") != 0
    assert "signing key" in capsys.readouterr().err
    assert not (tmp_path / "reg" / "index.json").exists()


def test_verified_community_publication_without_a_key_fails_when_signing_is_required(tmp_path):
    root = make_tree(tmp_path / "repo", official=(), verified=["example.verified"])
    assert run("build-registry", "--root", root, "--out", tmp_path / "reg", "--require-signing") != 0


def test_a_community_only_registry_needs_no_key(tmp_path):
    root = make_tree(tmp_path / "repo", official=(), community=["example.books"])
    assert run("build-registry", "--root", root, "--out", tmp_path / "reg") == 0
    assert run("verify-registry", "--registry", tmp_path / "reg", "--root", root, "--require-signed") == 0


def test_an_unsigned_preview_verifies_but_not_as_signed(tmp_path):
    root = make_tree(tmp_path / "repo", community=["example.books"])
    out = published(root, tmp_path / "reg")
    assert run("verify-registry", "--registry", out, "--root", root) == 0
    assert run("verify-registry", "--registry", out, "--root", root, "--require-signed") != 0


def test_a_signed_registry_verifies_against_the_trusted_keys_file(tmp_path):
    root = make_tree(tmp_path / "repo", verified=["example.verified"], community=["example.books"])
    key, public = key_pair(tmp_path / "keys")
    (root / "registry-trust").mkdir()
    (root / "registry-trust" / "trusted-keys.txt").write_text(f"# public keys\nk1:{public}\n", encoding="utf-8")
    out = tmp_path / "reg"
    assert run("build-registry", "--root", root, "--out", out, "--signing-key", key, "--key-id", "k1") == 0
    assert run("verify-registry", "--registry", out, "--root", root, "--require-signed") == 0
    _, other = key_pair(tmp_path / "other")
    (root / "registry-trust" / "trusted-keys.txt").write_text(f"k1:{other}\n", encoding="utf-8")
    assert run("verify-registry", "--registry", out, "--root", root, "--require-signed") != 0


def test_a_community_entry_claiming_official_fails_verification(tmp_path, capsys):
    root = make_tree(tmp_path / "repo", official=(), community=["example.books"])
    out = tmp_path / "reg"
    assert run("build-registry", "--root", root, "--out", out) == 0
    index = json.loads((out / "index.json").read_text(encoding="utf-8"))
    index["plugins"][0]["trust_label"] = "official"
    (out / "index.json").write_text(json.dumps(index), encoding="utf-8")
    assert run("verify-registry", "--registry", out, "--root", root) != 0
    assert "tier" in capsys.readouterr().err


def test_registry_build_is_deterministic_and_leaves_nothing_stale(tmp_path):
    root = make_tree(tmp_path / "repo", community=["example.books"])
    a, b = published(root, tmp_path / "a"), tmp_path / "b"
    (b / "packages").mkdir(parents=True)
    (b / "packages" / "example.gone-0.1.0.osp").write_bytes(b"old")
    published(root, b)
    assert sorted(p.name for p in (b / "packages").iterdir()) == sorted(p.name for p in (a / "packages").iterdir())
    for path in a.rglob("*"):
        if path.is_file():
            assert path.read_bytes() == (b / path.relative_to(a)).read_bytes()
    index = json.loads((a / "index.json").read_text(encoding="utf-8"))
    assert [p["id"] for p in index["plugins"]] == sorted(p["id"] for p in index["plugins"])
    for entry in index["plugins"]:
        assert hashlib.sha256((a / entry["file"]).read_bytes()).hexdigest() == entry["sha256"]
        assert entry["api"] == "1.0"


def test_registry_packages_are_the_bundled_bytes(tmp_path):
    root = make_tree(tmp_path / "repo", official=EIGHT)
    out = published(root, tmp_path / "reg")
    for entry in json.loads((out / "index.json").read_text(encoding="utf-8"))["plugins"]:
        bundled = build_package(OFFICIAL / entry["id"], tmp_path / "b" / f"{entry['id']}.osp").read_bytes()
        assert (out / entry["file"]).read_bytes() == bundled


def test_a_signing_key_inside_the_adapter_repository_is_refused(tmp_path, capsys):
    root = make_tree(tmp_path / "repo")
    assert run("build-registry", "--root", root, "--out", tmp_path / "reg",
               "--signing-key", root / "never-created.pem", "--key-id", "k") != 0
    assert "outside" in capsys.readouterr().err


# -- the contract: what this publishes, Core consumes with the rules it already has --------------------------

def test_core_installs_published_entries_with_trust_from_the_signature_alone(tmp_path, db):
    root = make_tree(tmp_path / "repo", official=("oneshelf.arxiv",), community=["example.books"])
    key, public = key_pair(tmp_path / "keys")
    out = tmp_path / "reg"
    assert run("build-registry", "--root", root, "--out", out, "--signing-key", key, "--key-id", "k1") == 0
    manager = PluginManager(db, store_dir=tmp_path / "store", trusted_keys={"k1": base64.b64decode(public)})
    registry = DirectoryRegistry(out)
    for plugin in ("oneshelf.arxiv", "example.books"):
        review = asyncio.run(manager.review_from_registry(registry, plugin))
        asyncio.run(manager.install_from_registry(registry, plugin, approved_permissions=list(review.permissions),
                                                  expected_sha256=review.sha256))
    assert manager.get("oneshelf.arxiv").trust_label == "official"
    assert manager.get("example.books").trust_label == "community"


def test_without_the_trusted_key_core_treats_an_official_entry_as_community(tmp_path, db):
    root = make_tree(tmp_path / "repo", official=("oneshelf.arxiv",))
    key, _ = key_pair(tmp_path / "keys")
    out = tmp_path / "reg"
    assert run("build-registry", "--root", root, "--out", out, "--signing-key", key, "--key-id", "k1") == 0
    manager = PluginManager(db, store_dir=tmp_path / "store")               # no trusted keys
    review = asyncio.run(manager.review_from_registry(DirectoryRegistry(out), "oneshelf.arxiv"))
    assert review.effective_trust == "community"
