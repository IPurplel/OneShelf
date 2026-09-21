"""The official Registry is generated, never hand-edited.

`plugins.registry_tool` builds every official adapter with the one canonical builder, checks it the way
an install would, and writes `registry/index.json` + `registry/packages/*.osp`. These pin what that means:
the output is byte-for-byte reproducible, every hash in the index is the hash of the file beside it,
signing uses a key the owner supplies (here a throwaway key made inside the test's tmp directory —
TEST-ONLY, never written anywhere else), and `verify` fails loudly on anything a hand edit or a stale
build would leave behind.
"""
import base64
import hashlib
import json
import shutil
from pathlib import Path

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from oneshelf.plugins.bundled import build_package
from plugins import registry_tool

OFFICIAL = Path(__file__).resolve().parents[3] / "plugins" / "official"
EIGHT = ["oneshelf.3asq", "oneshelf.arxiv", "oneshelf.gutenberg", "oneshelf.hindawi", "oneshelf.mangadex",
         "oneshelf.standard-ebooks", "oneshelf.tapas", "oneshelf.webtoon"]
REPO = Path(__file__).resolve().parents[4]


def make_test_only_key(directory: Path) -> tuple[Path, str]:
    """TEST-ONLY Ed25519 key, created in the test's tmp directory and gone with it."""
    key = Ed25519PrivateKey.generate()
    path = directory / "keys" / "test-only-signing.pem"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                       serialization.NoEncryption()))
    path.chmod(0o600)
    public = key.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    return path, base64.b64encode(public).decode()


def build(out, *args):
    return registry_tool.main(["build", "--sources", str(OFFICIAL), "--out", str(out), *args])


def verify(out, *args):
    return registry_tool.main(["verify", "--registry", str(out), "--sources", str(OFFICIAL), *args])


def index(out):
    return json.loads((out / "index.json").read_text(encoding="utf-8"))


def test_every_official_adapter_is_published_with_its_real_hash(tmp_path):
    assert build(tmp_path / "r") == 0
    data = index(tmp_path / "r")
    assert data["schema"] == "oneshelf.registry/1"
    assert [p["id"] for p in data["plugins"]] == EIGHT                        # sorted, all eight
    for entry in data["plugins"]:
        package = tmp_path / "r" / entry["file"]
        assert entry["file"] == f"packages/{entry['id']}-{entry['version']}.osp"
        assert hashlib.sha256(package.read_bytes()).hexdigest() == entry["sha256"]
        assert (entry["trust_label"], entry["api"]) == ("official", "1.0")
        assert "signature" not in entry


def test_the_registry_package_is_the_bundled_package(tmp_path):
    assert build(tmp_path / "r") == 0
    for plugin in EIGHT:
        bundled = build_package(OFFICIAL / plugin, tmp_path / "b" / f"{plugin}.osp").read_bytes()
        entry = next(p for p in index(tmp_path / "r")["plugins"] if p["id"] == plugin)
        assert (tmp_path / "r" / entry["file"]).read_bytes() == bundled


def test_two_builds_are_byte_for_byte_identical(tmp_path):
    assert build(tmp_path / "a") == 0 and build(tmp_path / "b") == 0
    files = sorted(p.relative_to(tmp_path / "a") for p in (tmp_path / "a").rglob("*") if p.is_file())
    assert files == sorted(p.relative_to(tmp_path / "b") for p in (tmp_path / "b").rglob("*") if p.is_file())
    for name in files:
        assert (tmp_path / "a" / name).read_bytes() == (tmp_path / "b" / name).read_bytes()


def test_a_fresh_build_verifies(tmp_path):
    assert build(tmp_path / "r") == 0
    assert verify(tmp_path / "r") == 0


def test_a_hand_edited_hash_fails_verification(tmp_path, capsys):
    assert build(tmp_path / "r") == 0
    data = index(tmp_path / "r")
    data["plugins"][0]["sha256"] = "0" * 64
    (tmp_path / "r" / "index.json").write_text(json.dumps(data), encoding="utf-8")
    assert verify(tmp_path / "r") != 0
    assert "sha256" in capsys.readouterr().err


def test_a_replaced_package_fails_verification(tmp_path):
    assert build(tmp_path / "r") == 0
    entry = index(tmp_path / "r")["plugins"][0]
    (tmp_path / "r" / entry["file"]).write_bytes(b"PK\x03\x04 not the package")
    assert verify(tmp_path / "r") != 0


def test_a_registry_that_lags_its_sources_fails_verification(tmp_path, capsys):
    assert build(tmp_path / "r") == 0
    sources = tmp_path / "sources"
    shutil.copytree(OFFICIAL, sources)
    manifest = sources / "oneshelf.arxiv" / "manifest.yaml"
    manifest.write_text(manifest.read_text(encoding="utf-8").replace("version: 1.0.0", "version: 1.0.1", 1),
                        encoding="utf-8")
    assert registry_tool.main(["verify", "--registry", str(tmp_path / "r"), "--sources", str(sources)]) != 0
    assert "oneshelf.arxiv" in capsys.readouterr().err


def test_a_stray_package_fails_verification(tmp_path):
    assert build(tmp_path / "r") == 0
    (tmp_path / "r" / "packages" / "oneshelf.extra-9.9.9.osp").write_bytes(b"stray")
    assert verify(tmp_path / "r") != 0


def test_a_rebuild_removes_packages_the_index_no_longer_names(tmp_path):
    (tmp_path / "r" / "packages").mkdir(parents=True)
    old = tmp_path / "r" / "packages" / "oneshelf.arxiv-0.9.0.osp"
    old.write_bytes(b"old")
    assert build(tmp_path / "r") == 0
    assert not old.exists() and verify(tmp_path / "r") == 0


def test_an_adapter_whose_packaged_tests_fail_is_not_published(tmp_path, capsys):
    sources = tmp_path / "sources"
    shutil.copytree(OFFICIAL, sources)
    fixtures = sorted((sources / "oneshelf.gutenberg" / "tests" / "fixtures").glob("*.json"))
    assert fixtures
    for fixture in fixtures:
        fixture.write_bytes(b"{}")
    assert registry_tool.main(["build", "--sources", str(sources), "--out", str(tmp_path / "r")]) != 0
    assert "oneshelf.gutenberg" in capsys.readouterr().err
    assert not (tmp_path / "r" / "index.json").exists()


def test_a_directory_whose_manifest_id_differs_is_refused(tmp_path, capsys):
    sources = tmp_path / "sources"
    shutil.copytree(OFFICIAL / "oneshelf.tapas", sources / "oneshelf.not-tapas")
    assert registry_tool.main(["build", "--sources", str(sources), "--out", str(tmp_path / "r")]) != 0
    assert "oneshelf.not-tapas" in capsys.readouterr().err


# -- signing: an externally supplied key, never one the tool keeps ------------------------------------------

def test_signing_with_a_supplied_key_verifies_against_its_public_key(tmp_path):
    key, public = make_test_only_key(tmp_path)
    assert build(tmp_path / "r", "--signing-key", str(key), "--key-id", "test-only-1") == 0
    for entry in index(tmp_path / "r")["plugins"]:
        assert entry["signature"]["key_id"] == "test-only-1" and entry["signature"]["value"]
    assert verify(tmp_path / "r", "--trusted-keys", f"test-only-1:{public}", "--require-signed") == 0


def test_signed_builds_are_deterministic_too(tmp_path):
    key, _ = make_test_only_key(tmp_path)
    assert build(tmp_path / "a", "--signing-key", str(key), "--key-id", "k") == 0
    assert build(tmp_path / "b", "--signing-key", str(key), "--key-id", "k") == 0
    assert (tmp_path / "a" / "index.json").read_bytes() == (tmp_path / "b" / "index.json").read_bytes()


def test_the_key_may_come_from_an_environment_variable_naming_a_file(tmp_path, monkeypatch):
    key, public = make_test_only_key(tmp_path)
    monkeypatch.setenv("ONESHELF_REGISTRY_SIGNING_KEY_FILE", str(key))
    assert build(tmp_path / "r", "--key-id", "env-1") == 0
    assert verify(tmp_path / "r", "--trusted-keys", f"env-1:{public}", "--require-signed") == 0


def test_a_signature_from_another_key_fails_verification(tmp_path):
    key, _ = make_test_only_key(tmp_path)
    _, other = make_test_only_key(tmp_path / "other")
    assert build(tmp_path / "r", "--signing-key", str(key), "--key-id", "k") == 0
    assert verify(tmp_path / "r", "--trusted-keys", f"k:{other}") != 0


def test_require_signed_refuses_an_unsigned_registry(tmp_path):
    _, public = make_test_only_key(tmp_path)
    assert build(tmp_path / "r") == 0
    assert verify(tmp_path / "r", "--trusted-keys", f"k:{public}", "--require-signed") != 0


def test_a_signing_key_inside_the_repository_is_refused_before_it_is_read(tmp_path, capsys):
    """A key inside the work tree is one `git add .` from being published, so its path alone is refused."""
    inside = REPO / "backend" / "never-created-test-only-key.pem"
    assert not inside.exists()
    assert build(tmp_path / "r", "--signing-key", str(inside), "--key-id", "k") != 0
    assert "outside the repository" in capsys.readouterr().err


def test_a_key_id_is_required_to_sign(tmp_path):
    key, _ = make_test_only_key(tmp_path)
    assert build(tmp_path / "r", "--signing-key", str(key)) != 0


def test_the_public_key_command_prints_only_the_public_half(tmp_path, capsys):
    key, public = make_test_only_key(tmp_path)
    assert registry_tool.main(["public-key", "--signing-key", str(key), "--key-id", "owner-2026"]) == 0
    out = capsys.readouterr().out.strip()
    assert out == f"owner-2026:{public}"
    assert "PRIVATE" not in out


# -- the committed registry ---------------------------------------------------------------------------------

def test_the_committed_registry_is_exactly_what_the_sources_build():
    committed = REPO / "registry"
    assert (committed / "index.json").is_file(), "run: python -m plugins.registry_tool build"
    assert verify(committed) == 0


@pytest.mark.parametrize("pattern", ["*.pem", "*.key", "*signing*"])
def test_no_private_key_is_in_the_registry(pattern):
    assert list((REPO / "registry").rglob(pattern)) == []
