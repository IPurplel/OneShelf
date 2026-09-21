"""Build, sign and verify the official Source Registry (`registry/index.json` + `registry/packages/*.osp`).

    python -m plugins.registry_tool build   [--out ../registry] [--signing-key PATH --key-id ID]
    python -m plugins.registry_tool verify  [--registry ../registry] [--trusted-keys ID:BASE64,...] [--require-signed]
    python -m plugins.registry_tool public-key --signing-key PATH --key-id ID

The index is generated, never hand-edited: every package is built by the same canonical builder the
image uses for its bundled sources, loaded and packaged-tested the way an install would, and hashed from
the bytes written beside it. `verify` rebuilds from the sources and fails on any difference, so a stale
or hand-edited registry cannot pass.

Signing needs the owner's Ed25519 private key, supplied from outside the repository — by path, or by
`ONESHELF_REGISTRY_SIGNING_KEY_FILE` naming a file. The tool never generates, stores or prints a private
key, and refuses one that lives inside the work tree. Only the public half is ever configured
(`ONESHELF_REGISTRY_TRUSTED_KEYS`); `public-key` prints it in that format.
"""
from __future__ import annotations

import argparse
import asyncio
import base64
import getpass
import hashlib
import json
import os
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey

from oneshelf.plugins.bundled import build_package, discover
from oneshelf.plugins.package import PackageError, load_package
from oneshelf.plugins.registry import (INDEX_SCHEMA, DirectoryRegistry, RegistryError, api_supported,
                                       parse_index, parse_trusted_keys)
from oneshelf.plugins.runtime import run_packaged_tests

REPO = Path(__file__).resolve().parents[2]
OFFICIAL_DIR = Path(__file__).resolve().parent / "official"
DEFAULT_REGISTRY = REPO / "registry"
KEY_FILE_ENV = "ONESHELF_REGISTRY_SIGNING_KEY_FILE"
TRUST_LABEL = "official"


class ToolError(Exception):
    pass


@dataclass(frozen=True)
class Built:
    id: str
    name: str
    version: str
    api: str
    data: bytes

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self.data).hexdigest()

    @property
    def file(self) -> str:
        return f"packages/{self.id}-{self.version}.osp"


# -- building ---------------------------------------------------------------------------------------------

def _build_sources(sources: Path) -> list[Built]:
    """Every adapter under `sources`, built, loaded and packaged-tested — or a ToolError naming each failure."""
    directories = discover(sources)
    if not directories:
        raise ToolError(f"no adapters found under {sources}")
    built, problems = [], []
    with tempfile.TemporaryDirectory(prefix="oneshelf-registry-") as work:
        for source in directories:
            path = build_package(source, Path(work) / f"{source.name}.osp")
            try:
                package = load_package(path)
            except PackageError as exc:
                problems.append(f"{source.name}: invalid package: {exc}")
                continue
            if package.id != source.name:
                problems.append(f"{source.name}: directory name does not match manifest id {package.id!r}")
                continue
            report = asyncio.run(run_packaged_tests(package))
            if not report.passed:
                problems.append(f"{source.name}: packaged tests failed: {'; '.join(report.failures)}")
                continue
            built.append(Built(package.id, package.manifest.name, package.version, package.manifest.api,
                               path.read_bytes()))
    if problems:
        raise ToolError("\n".join(problems))
    return sorted(built, key=lambda b: b.id)


def _index(built: list[Built], signer: Ed25519PrivateKey | None, key_id: str | None) -> bytes:
    plugins = []
    for item in built:
        entry = {"id": item.id, "name": item.name, "version": item.version, "api": item.api,
                 "file": item.file, "sha256": item.sha256, "trust_label": TRUST_LABEL}
        if signer is not None:
            # The same message Core verifies: the package's sha256 hex digest. Ed25519 is deterministic,
            # so a signed index is as reproducible as an unsigned one.
            entry["signature"] = {"key_id": key_id,
                                  "value": base64.b64encode(signer.sign(item.sha256.encode())).decode()}
        plugins.append(entry)
    document = {"schema": INDEX_SCHEMA, "plugins": plugins}
    return (json.dumps(document, indent=2, sort_keys=True, ensure_ascii=False) + "\n").encode()


def _write_atomic(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_bytes(data)
    os.replace(temporary, path)


def build(sources: Path, out: Path, signer: Ed25519PrivateKey | None, key_id: str | None) -> list[Built]:
    built = _build_sources(sources)
    for item in built:
        _write_atomic(out / item.file, item.data)
    wanted = {out / item.file for item in built}
    for stale in (out / "packages").glob("*.osp"):
        if stale not in wanted:
            stale.unlink()        # generated output only: a package the index no longer names
    _write_atomic(out / "index.json", _index(built, signer, key_id))
    return built


# -- verifying --------------------------------------------------------------------------------------------

def verify(registry: Path, sources: Path | None, trusted: dict[str, bytes], require_signed: bool) -> list[str]:
    problems: list[str] = []
    try:
        entries = parse_index((registry / "index.json").read_bytes())
    except (OSError, RegistryError) as exc:
        return [f"index.json: {exc}"]
    seen: set[str] = set()
    directory = DirectoryRegistry(registry)
    for entry in entries:
        where = f"{entry.id} {entry.version}"
        if entry.id in seen:
            problems.append(f"{where}: listed more than once")
        seen.add(entry.id)
        try:
            data = asyncio.run(directory.fetch(entry))
        except RegistryError as exc:
            problems.append(f"{where}: {exc}")
            continue
        if hashlib.sha256(data).hexdigest() != entry.sha256:
            problems.append(f"{where}: sha256 in the index is not the hash of {entry.location}")
            continue
        with tempfile.TemporaryDirectory(prefix="oneshelf-verify-") as work:
            path = Path(work) / "package.osp"
            path.write_bytes(data)
            try:
                package = load_package(path)
            except PackageError as exc:
                problems.append(f"{where}: invalid package: {exc}")
                continue
            report = asyncio.run(run_packaged_tests(package))
        if (package.id, package.version) != (entry.id, entry.version):
            problems.append(f"{where}: package is {package.id} {package.version}")
        if entry.api != package.manifest.api or not api_supported(entry.api):
            problems.append(f"{where}: api {entry.api!r} does not match the package ({package.manifest.api})")
        if not report.passed:
            problems.append(f"{where}: packaged tests failed: {'; '.join(report.failures)}")
        problems += _signature_problems(where, entry, trusted, require_signed)
    named = {(registry / e.location).resolve() for e in entries}
    for path in sorted((registry / "packages").glob("*")):
        if path.resolve() not in named:
            problems.append(f"packages/{path.name}: not named by the index")
    if sources is not None:
        problems += _source_problems(entries, sources)
    return problems


def _signature_problems(where, entry, trusted, require_signed) -> list[str]:
    if not entry.signature:
        return [f"{where}: unsigned"] if require_signed else []
    key = trusted.get(entry.signature_key_id)
    if key is None:
        if trusted or require_signed:
            return [f"{where}: signed by {entry.signature_key_id!r}, which is not a trusted key"]
        return []
    try:
        Ed25519PublicKey.from_public_bytes(key).verify(base64.b64decode(entry.signature), entry.sha256.encode())
    except (InvalidSignature, ValueError):
        return [f"{where}: signature does not verify with {entry.signature_key_id!r}"]
    return []


def _source_problems(entries, sources: Path) -> list[str]:
    try:
        built = {b.id: b for b in _build_sources(sources)}
    except ToolError as exc:
        return [str(exc)]
    listed = {e.id: e for e in entries}
    problems = []
    for plugin in sorted(set(built) | set(listed)):
        have, want = listed.get(plugin), built.get(plugin)
        if want is None:
            problems.append(f"{plugin}: in the registry but not in the sources")
        elif have is None:
            problems.append(f"{plugin}: in the sources but not in the registry — rebuild it")
        elif (have.version, have.sha256, have.location, have.api, have.name) != (
                want.version, want.sha256, want.file, want.api, want.name):
            problems.append(f"{plugin}: registry {have.version} ({have.sha256[:12]}) is not what the sources "
                            f"build ({want.version}, {want.sha256[:12]}) — rebuild it")
    return problems


# -- keys -------------------------------------------------------------------------------------------------

def _key_path(argument: str | None) -> Path | None:
    raw = argument or os.environ.get(KEY_FILE_ENV) or None
    if raw is None:
        return None
    path = Path(raw).expanduser().resolve()
    # Checked before the file is opened: a private key inside the work tree is one `git add` from public.
    if path.is_relative_to(REPO):
        raise ToolError(f"the signing key must live outside the repository ({REPO}); move it and retry")
    return path


def _load_key(path: Path) -> Ed25519PrivateKey:
    try:
        data = path.read_bytes()
    except OSError as exc:
        raise ToolError(f"cannot read the signing key: {exc.strerror}") from exc
    if path.stat().st_mode & 0o077:
        print(f"warning: {path} is readable by other users; chmod 600 it", file=sys.stderr)
    try:
        key = serialization.load_pem_private_key(data, password=None)
    except TypeError:
        if not sys.stdin.isatty():
            raise ToolError("the signing key is encrypted; run this interactively to enter its passphrase")
        key = serialization.load_pem_private_key(data, password=getpass.getpass("Signing key passphrase: ").encode())
    except ValueError as exc:
        raise ToolError("the signing key is not a PEM private key") from exc
    if not isinstance(key, Ed25519PrivateKey):
        raise ToolError("the signing key must be an Ed25519 key")
    return key


def _public(key: Ed25519PrivateKey) -> str:
    raw = key.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    return base64.b64encode(raw).decode()


# -- command line -----------------------------------------------------------------------------------------

def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m plugins.registry_tool", description=__doc__.split("\n\n")[0])
    commands = parser.add_subparsers(dest="command", required=True)
    b = commands.add_parser("build", help="build every official adapter into the registry directory")
    b.add_argument("--sources", type=Path, default=OFFICIAL_DIR)
    b.add_argument("--out", type=Path, default=DEFAULT_REGISTRY)
    b.add_argument("--signing-key", help=f"Ed25519 PEM private key outside the repository (or ${KEY_FILE_ENV})")
    b.add_argument("--key-id", help="the id the trusted-keys setting knows this key by")
    v = commands.add_parser("verify", help="check a registry against its packages and sources")
    v.add_argument("--registry", type=Path, default=DEFAULT_REGISTRY)
    v.add_argument("--sources", type=Path, default=OFFICIAL_DIR)
    v.add_argument("--trusted-keys", default=os.environ.get("ONESHELF_REGISTRY_TRUSTED_KEYS", ""))
    v.add_argument("--require-signed", action="store_true")
    p = commands.add_parser("public-key", help="print the public key line for ONESHELF_REGISTRY_TRUSTED_KEYS")
    p.add_argument("--signing-key")
    p.add_argument("--key-id", required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.command == "build":
            path = _key_path(args.signing_key)
            if path is not None and not args.key_id:
                raise ToolError("--key-id is required when signing")
            signer = _load_key(path) if path is not None else None
            built = build(args.sources, args.out, signer, args.key_id if signer else None)
            state = f"signed with {args.key_id}" if signer else "unsigned"
            print(f"built {len(built)} packages into {args.out} ({state})")
            return 0
        if args.command == "verify":
            try:
                trusted = parse_trusted_keys(args.trusted_keys)
            except ValueError as exc:
                raise ToolError(f"--trusted-keys: {exc}") from exc
            problems = verify(args.registry, args.sources, trusted, args.require_signed)
            for problem in problems:
                print(problem, file=sys.stderr)
            if problems:
                return 1
            print(f"{args.registry}: verified")
            return 0
        path = _key_path(args.signing_key)
        if path is None:
            raise ToolError(f"--signing-key (or ${KEY_FILE_ENV}) is required")
        print(f"{args.key_id}:{_public(_load_key(path))}")
        return 0
    except ToolError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
