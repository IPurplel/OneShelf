"""The bundled snapshot is synced from OneShelf-Adapters, never edited on its own.

`plugins.sync_snapshot` copies exactly the allowlisted Official adapters from an adapter-repository
checkout into Core's snapshot directory, after validating and packaged-testing them, and records where they
came from in UPSTREAM.json. These run it against throwaway Git repositories and snapshot directories.
"""
import json
import shutil
import subprocess
from pathlib import Path

from oneshelf.plugins.bundled import build_package
from plugins import sync_snapshot

OFFICIAL = Path(__file__).resolve().parents[3] / "plugins" / "official"
EIGHT = ["oneshelf.3asq", "oneshelf.arxiv", "oneshelf.gutenberg", "oneshelf.hindawi", "oneshelf.mangadex",
         "oneshelf.standard-ebooks", "oneshelf.tapas", "oneshelf.webtoon"]


def git(repo: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True, check=True).stdout.strip()


def commit(root: Path, *, init: bool = False) -> None:
    if init:
        git(root, "init", "-q", "-b", "main")
    git(root, "add", "-A")
    git(root, "-c", "user.name=t", "-c", "user.email=t@example.invalid", "commit", "-q", "-m", "x", "--allow-empty")


def upstream(tmp_path: Path, *, official=tuple(EIGHT), community=()) -> Path:
    root = tmp_path / "adapters-repo"
    for tier in ("official", "verified-community", "community"):
        (root / "adapters" / tier).mkdir(parents=True)
    for plugin in official:
        shutil.copytree(OFFICIAL / plugin, root / "adapters" / "official" / plugin)
    for plugin in community:
        shutil.copytree(OFFICIAL / plugin, root / "adapters" / "community" / plugin)
    commit(root, init=True)
    return root


def snapshot(tmp_path: Path, ids=tuple(EIGHT)) -> Path:
    target = tmp_path / "snapshot"
    target.mkdir()
    for plugin in EIGHT:
        shutil.copytree(OFFICIAL / plugin, target / plugin)
    (target / "UPSTREAM.json").write_text(json.dumps({"repository": "x", "commit": "0" * 40,
                                                      "source_path": "adapters/official",
                                                      "bundled": list(ids)}), encoding="utf-8")
    return target


def run(root, target, *extra) -> int:
    return sync_snapshot.main(["--from", str(root), "--snapshot", str(target), *extra])


def package_bytes(directory: Path, out: Path) -> bytes:
    return build_package(directory, out).read_bytes()


def test_sync_copies_the_eight_and_records_their_provenance(tmp_path):
    root, target = upstream(tmp_path), snapshot(tmp_path)
    assert run(root, target) == 0
    record = json.loads((target / "UPSTREAM.json").read_text(encoding="utf-8"))
    assert record == {"repository": "https://github.com/IPurplel/OneShelf-Adapters",
                      "commit": git(root, "rev-parse", "HEAD"), "source_path": "adapters/official", "bundled": EIGHT}
    assert sorted(p.name for p in target.iterdir() if p.is_dir()) == EIGHT


def test_the_provenance_record_is_deterministic(tmp_path):
    root, target = upstream(tmp_path), snapshot(tmp_path)
    assert run(root, target) == 0
    first = (target / "UPSTREAM.json").read_bytes()
    assert run(root, target) == 0
    assert (target / "UPSTREAM.json").read_bytes() == first


def test_unchanged_upstream_leaves_every_package_byte_identical(tmp_path):
    root, target = upstream(tmp_path), snapshot(tmp_path)
    before = {p: package_bytes(target / p, tmp_path / "a" / f"{p}.osp") for p in EIGHT}
    assert run(root, target) == 0
    assert {p: package_bytes(target / p, tmp_path / "b" / f"{p}.osp") for p in EIGHT} == before


def test_an_upstream_change_is_copied_and_stale_files_inside_it_removed(tmp_path):
    root, target = upstream(tmp_path), snapshot(tmp_path)
    (target / "oneshelf.arxiv" / "tests" / "fixtures" / "stale.json").write_text("{}", encoding="utf-8")
    manifest = root / "adapters" / "official" / "oneshelf.arxiv" / "manifest.yaml"
    manifest.write_text(manifest.read_text(encoding="utf-8").replace("version: 1.0.0", "version: 1.0.1", 1),
                        encoding="utf-8")
    commit(root)
    assert run(root, target) == 0
    assert "version: 1.0.1" in (target / "oneshelf.arxiv" / "manifest.yaml").read_text(encoding="utf-8")
    assert not (target / "oneshelf.arxiv" / "tests" / "fixtures" / "stale.json").exists()


def test_a_missing_allowlisted_adapter_fails_and_changes_nothing(tmp_path, capsys):
    root = upstream(tmp_path, official=[p for p in EIGHT if p != "oneshelf.tapas"])
    target = snapshot(tmp_path)
    before = (target / "UPSTREAM.json").read_bytes()
    assert run(root, target) != 0
    assert "oneshelf.tapas" in capsys.readouterr().err
    assert (target / "UPSTREAM.json").read_bytes() == before and (target / "oneshelf.tapas").is_dir()


def test_a_bundled_adapter_must_be_official_upstream(tmp_path, capsys):
    root = upstream(tmp_path, official=[p for p in EIGHT if p != "oneshelf.tapas"], community=["oneshelf.tapas"])
    assert run(root, snapshot(tmp_path)) != 0
    assert "oneshelf.tapas" in capsys.readouterr().err


def test_a_duplicate_id_upstream_fails(tmp_path, capsys):
    root = upstream(tmp_path, community=["oneshelf.arxiv"])
    assert run(root, snapshot(tmp_path)) != 0
    assert "more than one tier" in capsys.readouterr().err


def test_registry_only_adapters_are_not_bundled(tmp_path):
    root = upstream(tmp_path)
    shutil.copytree(OFFICIAL / "oneshelf.gutenberg", root / "adapters" / "community" / "example.books")
    manifest = root / "adapters" / "community" / "example.books" / "manifest.yaml"
    manifest.write_text(manifest.read_text(encoding="utf-8").replace("id: oneshelf.gutenberg", "id: example.books"),
                        encoding="utf-8")
    commit(root)
    target = snapshot(tmp_path)
    assert run(root, target) == 0
    assert not (target / "example.books").exists()


def test_an_adapter_no_longer_allowlisted_is_removed_from_the_snapshot(tmp_path):
    root, target = upstream(tmp_path), snapshot(tmp_path, ids=[p for p in EIGHT if p != "oneshelf.webtoon"])
    (target / "README.md").write_text("kept", encoding="utf-8")
    assert run(root, target) == 0
    assert not (target / "oneshelf.webtoon").exists()
    assert (target / "README.md").read_text(encoding="utf-8") == "kept"         # not an adapter: untouched


def test_a_symlink_that_escapes_the_adapter_fails(tmp_path, capsys):
    root = upstream(tmp_path)
    (root / "adapters" / "official" / "oneshelf.arxiv" / "tests" / "fixtures" / "leak.json").symlink_to("/etc/hostname")
    commit(root)
    target = snapshot(tmp_path)
    assert run(root, target) != 0
    assert "symlink" in capsys.readouterr().err
    assert not (target / "oneshelf.arxiv" / "tests" / "fixtures" / "leak.json").exists()


def test_an_adapter_whose_packaged_tests_fail_is_not_synced(tmp_path, capsys):
    root = upstream(tmp_path)
    fixtures = root / "adapters" / "official" / "oneshelf.gutenberg" / "tests" / "fixtures"
    for fixture in fixtures.glob("*.json"):
        fixture.write_text("{}", encoding="utf-8")
    commit(root)
    target = snapshot(tmp_path)
    assert run(root, target) != 0
    assert "packaged tests failed" in capsys.readouterr().err
    assert (target / "oneshelf.gutenberg" / "tests" / "fixtures" / "search.json").read_text(encoding="utf-8") != "{}"


def test_uncommitted_upstream_changes_are_refused(tmp_path, capsys):
    root = upstream(tmp_path)
    (root / "adapters" / "official" / "oneshelf.arxiv" / "manifest.yaml").write_text("dirty", encoding="utf-8")
    assert run(root, snapshot(tmp_path)) != 0
    assert "uncommitted" in capsys.readouterr().err


def test_a_directory_that_is_not_an_adapter_repository_is_refused(tmp_path):
    (tmp_path / "nothing").mkdir()
    assert run(tmp_path / "nothing", snapshot(tmp_path)) != 0


def test_a_snapshot_without_its_allowlist_is_refused(tmp_path, capsys):
    target = snapshot(tmp_path)
    (target / "UPSTREAM.json").unlink()
    assert run(upstream(tmp_path), target) != 0
    assert "UPSTREAM.json" in capsys.readouterr().err


# -- the committed snapshot ---------------------------------------------------------------------------------

def test_the_committed_snapshot_names_its_upstream_and_bundles_exactly_the_eight():
    record = json.loads((OFFICIAL / "UPSTREAM.json").read_text(encoding="utf-8"))
    assert record["repository"] == "https://github.com/IPurplel/OneShelf-Adapters"
    assert len(record["commit"]) == 40 and set(record["commit"]) <= set("0123456789abcdef")
    assert record["source_path"] == "adapters/official"
    assert record["bundled"] == EIGHT
    assert sorted(p.name for p in OFFICIAL.iterdir() if p.is_dir() and (p / "manifest.yaml").exists()) == EIGHT


def test_provenance_is_never_inside_an_adapter():
    assert not any((OFFICIAL / plugin / "UPSTREAM.json").exists() for plugin in EIGHT)
