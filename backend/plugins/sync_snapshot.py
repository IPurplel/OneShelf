"""Sync Core's bundled snapshot from an OneShelf-Adapters checkout.

    python -m plugins.sync_snapshot --from ../../OneShelf-Adapters

OneShelf-Adapters is where adapters are developed. Core keeps a *release snapshot* of the Official
adapters listed in `plugins/official/UPSTREAM.json` ("bundled") so a fresh installation has sources even
with no network — first run never contacts GitHub. That list is the Core release decision: adapters
published only to the Registry are never copied here.

The tool validates and packaged-tests each allowlisted adapter with the canonical builder before
touching anything, replaces only those adapter directories inside the snapshot, removes adapter
directories that are no longer allowlisted, verifies the copied bytes build to the same packages, and
records the upstream commit. It never touches a library, installed plugins, or Git: review the diff and
commit it yourself.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from oneshelf.plugins.adapter_repo import build_adapter, discover
from oneshelf.plugins.bundled import build_package

SNAPSHOT = Path(__file__).resolve().parent / "official"
UPSTREAM = "UPSTREAM.json"
REPOSITORY = "https://github.com/IPurplel/OneShelf-Adapters"
SOURCE_PATH = "adapters/official"


class SyncError(Exception):
    pass


def _git(root: Path, *args: str) -> str:
    result = subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True)
    if result.returncode != 0:
        raise SyncError(f"{root} is not a Git checkout of OneShelf-Adapters ({result.stderr.strip() or 'git failed'})")
    return result.stdout.strip()


def _allowlist(snapshot: Path) -> list[str]:
    try:
        record = json.loads((snapshot / UPSTREAM).read_text(encoding="utf-8"))
        bundled = record["bundled"]
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise SyncError(f"{snapshot / UPSTREAM} is missing or unreadable; it holds the bundled allowlist") from exc
    if not isinstance(bundled, list) or not bundled or not all(isinstance(i, str) for i in bundled):
        raise SyncError(f"{UPSTREAM}: 'bundled' must be a non-empty list of plugin ids")
    if len(set(bundled)) != len(bundled):
        raise SyncError(f"{UPSTREAM}: 'bundled' lists an id twice")
    return sorted(bundled)


def sync(root: Path, snapshot: Path, *, allow_dirty: bool = False) -> dict:
    root, snapshot = root.resolve(), snapshot.resolve()
    ids = _allowlist(snapshot)
    commit = _git(root, "rev-parse", "HEAD")
    if not allow_dirty and _git(root, "status", "--porcelain", "--", "adapters"):
        raise SyncError(f"{root} has uncommitted changes under adapters/; the snapshot must name a real commit")
    adapters, problems = discover(root)
    by_id = {a.id: a for a in adapters}
    for plugin in ids:
        adapter = by_id.get(plugin)
        if adapter is None:
            problems.append(f"{plugin}: allowlisted for bundling but not found upstream")
        elif adapter.tier != "official":
            problems.append(f"{plugin}: bundled adapters must be Official; it is in adapters/{adapter.tier}/")
        elif not adapter.path.resolve().is_relative_to(root):
            problems.append(f"{plugin}: resolves outside the adapter repository")
    if problems:
        raise SyncError("\n".join(problems))

    with tempfile.TemporaryDirectory(prefix="oneshelf-sync-") as work:
        work = Path(work)
        built = {}
        for plugin in ids:
            item, found = build_adapter(by_id[plugin], work)
            if found:
                problems += found
            else:
                built[plugin] = item
        if problems:
            raise SyncError("\n".join(problems))

        # Everything is valid: now, and only now, replace the snapshot's adapter directories.
        for plugin in ids:
            staged = snapshot / f".sync-{plugin}"
            if staged.exists():
                shutil.rmtree(staged)
            shutil.copytree(by_id[plugin].path, staged, symlinks=True)
            current = snapshot / plugin
            retired = snapshot / f".retired-{plugin}"
            if current.exists():
                os.replace(current, retired)
            os.replace(staged, current)
            if retired.exists():
                shutil.rmtree(retired)
        for entry in sorted(snapshot.iterdir()):
            if entry.is_dir() and not entry.is_symlink() and (entry / "manifest.yaml").exists() and entry.name not in ids:
                shutil.rmtree(entry)            # an adapter directory that is no longer bundled

        for plugin in ids:
            copied = build_package(snapshot / plugin, work / f"check-{plugin}.osp").read_bytes()
            if copied != built[plugin].data:
                raise SyncError(f"{plugin}: the copied snapshot does not build to the upstream package")

    record = {"repository": REPOSITORY, "commit": commit, "source_path": SOURCE_PATH, "bundled": ids}
    (snapshot / UPSTREAM).write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
    return record


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m plugins.sync_snapshot", description=__doc__.split("\n\n")[0])
    parser.add_argument("--from", dest="root", type=Path, required=True, help="an OneShelf-Adapters checkout")
    parser.add_argument("--snapshot", type=Path, default=SNAPSHOT)
    parser.add_argument("--allow-dirty", action="store_true", help="accept uncommitted upstream changes (testing only)")
    args = parser.parse_args(argv)
    try:
        record = sync(args.root, args.snapshot, allow_dirty=args.allow_dirty)
    except SyncError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    print(f"synced {len(record['bundled'])} adapters from {record['repository']}@{record['commit'][:12]}")
    print("Review the changes with git diff, then commit them.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
