"""The adapter repository's checks and Registry build — owned by Core, run by OneShelf-Adapters.

    python -m oneshelf.plugins.adapter_repo check-all      [--root .] [--baseline PUBLISHED_REGISTRY_DIR]
    python -m oneshelf.plugins.adapter_repo check ID...    [--root .] [--baseline DIR]
    python -m oneshelf.plugins.adapter_repo reproducible   --baseline PUBLISHED_REGISTRY_DIR [--root .]
    python -m oneshelf.plugins.adapter_repo build-registry --out DIR [--signing-key PATH --key-id ID] [--require-signing]
    python -m oneshelf.plugins.adapter_repo verify-registry --registry DIR [--root .] [--require-signed]
    python -m oneshelf.plugins.adapter_repo public-key --signing-key PATH --key-id ID

OneShelf-Adapters pins a Core revision and calls this module, so a contribution is judged by the very rules
an install applies: the canonical builder, `load_package`, the packaged-test runtime and the Registry
parser. Nothing is copied into that repository.

Layout: `adapters/official/`, `adapters/verified-community/`, `adapters/community/`, one directory per
plugin id. **Trust comes from the tier directory**, which only a maintainer-reviewed change can move an
adapter into — never from anything inside an adapter. Signing Official and Verified Community entries is
optional (owner decision, 2026-09-21): an installation trusts those tiers without a signature only from the
Registry it names as first-party (ONESHELF_FIRST_PARTY_REGISTRY_URL); anywhere else only a valid signature
from a locally trusted key does. `--require-signing` enforces signatures. A private key is only ever read
from outside any Git work tree, and only its public half is written anywhere.
"""
from __future__ import annotations

import argparse
import asyncio
import base64
import getpass
import hashlib
import io
import json
import os
import re
import sys
import tempfile
import zipfile
from dataclasses import dataclass
from pathlib import Path

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey

from oneshelf.plugins.bundled import build_package
from oneshelf.plugins.package import ALLOWED_EXTENSIONS, PackageError, _unsafe_entry_name, load_package
from oneshelf.plugins.registry import (INDEX_SCHEMA, DirectoryRegistry, RegistryError, RegistryEntry,
                                       api_supported, parse_index, parse_trusted_keys)
from oneshelf.plugins.runtime import run_packaged_tests

TIERS = {"official": "official", "verified-community": "verified_community", "community": "community"}
SIGNED_TIERS = frozenset({"official", "verified-community"})
SIGNED_LABELS = frozenset(TIERS[t] for t in SIGNED_TIERS)
TRUSTED_KEYS_FILE = Path("registry-trust") / "trusted-keys.txt"
KEY_FILE_ENV = "ONESHELF_REGISTRY_SIGNING_KEY_FILE"

# Fixtures are for parser tests: small, structural, sanitized. Not whole chapters, books or image sets.
MAX_TEXT_FIXTURE_BYTES = 512 * 1024
MAX_BINARY_FIXTURE_BYTES = 128 * 1024
MAX_ADAPTER_BYTES = 4 * 1024 * 1024
BINARY_EXTENSIONS = frozenset({".png", ".jpg", ".jpeg", ".webp"})
TIER_FILES = frozenset({"README.md", ".gitkeep"})
_PLUGIN_ID = re.compile(r"^[a-z0-9]+(?:[.-][a-z0-9]+)*$")
_SECRETS = [
    ("private key", re.compile(rb"-----BEGIN [A-Z ]*PRIVATE KEY-----")),
    ("GitHub token", re.compile(rb"\b(?:gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{40,})")),
    ("AWS access key", re.compile(rb"\bAKIA[0-9A-Z]{16}\b")),
    ("Slack token", re.compile(rb"\bxox[abposr]-[A-Za-z0-9-]{10,}")),
    ("cookie header", re.compile(rb"(?im)^[ \t]*(?:set-)?cookie[ \t]*:[ \t]*[^=\s]+=[^;\s]{12,}")),
    ("bearer token", re.compile(rb"(?i)\bbearer[ \t]+[A-Za-z0-9._~+/-]{20,}")),
    ("JSON Web Token", re.compile(rb"\beyJ[A-Za-z0-9_-]{8,}\.eyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}")),
]


class ToolError(Exception):
    pass


@dataclass(frozen=True)
class Adapter:
    id: str
    tier: str
    path: Path

    @property
    def trust_label(self) -> str:
        return TIERS[self.tier]


@dataclass(frozen=True)
class Built:
    adapter: Adapter
    name: str
    version: str
    api: str
    data: bytes

    @property
    def id(self) -> str:
        return self.adapter.id

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self.data).hexdigest()

    @property
    def file(self) -> str:
        return f"packages/{self.id}-{self.version}.osp"


def _vkey(version: str) -> tuple[int, ...]:
    return tuple(int(part) for part in version.split("."))


# -- discovery ------------------------------------------------------------------------------------------------

def discover(root: Path) -> tuple[list[Adapter], list[str]]:
    """Every adapter under `adapters/<tier>/<id>/`, and every structural problem on the way."""
    base = root / "adapters"
    if base.is_symlink() or not base.is_dir():
        return [], ["adapters/: missing (expected adapters/official, adapters/verified-community, adapters/community)"]
    adapters, problems = [], []
    for tier_dir in sorted(base.iterdir()):
        if tier_dir.name in TIER_FILES:
            continue
        if tier_dir.is_symlink() or not tier_dir.is_dir() or tier_dir.name not in TIERS:
            problems.append(f"adapters/{tier_dir.name}: not a trust tier (expected one of {', '.join(TIERS)})")
            continue
        for entry in sorted(tier_dir.iterdir()):
            where = f"adapters/{tier_dir.name}/{entry.name}"
            if entry.name in TIER_FILES:
                continue
            if entry.is_symlink():
                problems.append(f"{where}: is a symlink; adapters must be real directories")
            elif not entry.is_dir():
                problems.append(f"{where}: only adapter directories belong in a tier")
            elif not _PLUGIN_ID.match(entry.name) or len(entry.name) > 64:
                problems.append(f"{where}: directory name must be the plugin id (lowercase, e.g. oneshelf.example)")
            else:
                adapters.append(Adapter(entry.name, tier_dir.name, entry))
    tiers_by_id: dict[str, list[str]] = {}
    for adapter in adapters:
        tiers_by_id.setdefault(adapter.id, []).append(adapter.tier)
    for plugin_id, tiers in sorted(tiers_by_id.items()):
        if len(tiers) > 1:
            problems.append(f"{plugin_id}: appears in more than one tier ({', '.join(tiers)}); one id, one adapter")
    return adapters, problems


# -- one adapter ----------------------------------------------------------------------------------------------

def tree_problems(adapter: Adapter) -> list[str]:
    """What the source directory holds, before anything is built from it."""
    problems, total = [], 0
    for path in sorted(adapter.path.rglob("*")):
        rel = path.relative_to(adapter.path).as_posix()
        where = f"{adapter.id}: {rel}"
        if path.is_symlink():
            problems.append(f"{where}: symlinks are not allowed in adapters")
            continue
        if path.is_dir():
            continue
        if any(part.startswith(".") for part in rel.split("/")):
            problems.append(f"{where}: hidden files (such as .env) are not allowed in adapters")
            continue
        if _unsafe_entry_name(rel):
            problems.append(f"{where}: unsafe file name")
            continue
        suffix = path.suffix.lower()
        if suffix not in ALLOWED_EXTENSIONS:
            problems.append(f"{where}: file type not allowed — adapters are declarative data, not code")
            continue
        size = path.stat().st_size
        limit = MAX_BINARY_FIXTURE_BYTES if suffix in BINARY_EXTENSIONS else MAX_TEXT_FIXTURE_BYTES
        if size > limit:
            problems.append(f"{where}: {size} bytes is over the {limit}-byte limit; keep fixtures minimal")
        total += size
        data = path.read_bytes()
        for label, pattern in _SECRETS:
            if pattern.search(data):
                problems.append(f"{where}: looks like a secret ({label}); never commit credentials or sessions")
                break
    if total > MAX_ADAPTER_BYTES:
        problems.append(f"{adapter.id}: {total} bytes in total is over the {MAX_ADAPTER_BYTES}-byte limit")
    return problems


def _package_problem(adapter: Adapter, exc: Exception) -> str:
    found = re.search(r"unsupported plugin API (\d+\.\d+)", str(exc))
    if found:
        return (f"{adapter.id}: requires a newer OneShelf (plugin API {found.group(1)}); "
                "plugin API changes belong in OneShelf Core")
    return f"{adapter.id}: invalid package: {exc}"


def build_adapter(adapter: Adapter, work: Path) -> tuple[Built | None, list[str]]:
    """Build with the canonical builder, load as an install would, run the packaged tests."""
    problems = tree_problems(adapter)
    if problems:
        return None, problems
    try:
        path = build_package(adapter.path, work / f"{adapter.id}.osp")
        package = load_package(path)
    except (PackageError, ValueError, OSError) as exc:
        return None, [_package_problem(adapter, exc)]
    if package.id != adapter.id:
        return None, [f"{adapter.id}: manifest id is {package.id!r}; it must match the directory name"]
    if not api_supported(package.manifest.api):
        return None, [_package_problem(adapter, ValueError(f"unsupported plugin API {package.manifest.api}"))]
    report = asyncio.run(run_packaged_tests(package))
    if not report.passed:
        return None, [f"{adapter.id}: packaged tests failed: {'; '.join(report.failures)}"]
    return Built(adapter, package.manifest.name, package.version, package.manifest.api, path.read_bytes()), []


def _package_files(data: bytes) -> dict[str, bytes] | None:
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            return {i.filename: archive.read(i) for i in archive.infolist() if not i.is_dir()}
    except (zipfile.BadZipFile, OSError, ValueError):
        return None


def baseline_problems(built: Built, published: list[RegistryEntry], baseline: Path | None = None) -> list[str]:
    """A published id+version is immutable, and versions only move forward.

    Immutability is about the adapter's files. The same files packed into different container bytes (as
    when the canonical builder stopped compressing, to be reproducible on every platform) are the same
    version; a changed file is not.
    """
    mine = [e for e in published if e.id == built.id]
    problems = []
    same = next((e for e in mine if e.version == built.version), None)
    if same is not None and same.sha256 != built.sha256:
        before = None
        if baseline is not None:
            try:
                before = _package_files(asyncio.run(DirectoryRegistry(baseline).fetch(same)))
            except RegistryError:
                before = None
        if before is None or before != _package_files(built.data):
            problems.append(f"{built.id} {built.version}: content changed but the version did not — bump the "
                            "version (published packages are immutable per id and version)")
    newest = max((e.version for e in mine), key=_vkey, default=None)
    if newest is not None and _vkey(built.version) < _vkey(newest):
        problems.append(f"{built.id}: version {built.version} is a downgrade from published {newest}")
    return problems


def _load_baseline(baseline: Path | None) -> list[RegistryEntry]:
    if baseline is None:
        return []
    try:
        return parse_index((baseline / "index.json").read_bytes())
    except (OSError, RegistryError) as exc:
        raise ToolError(f"--baseline {baseline}: {exc}") from exc


def check(root: Path, ids: list[str] | None, baseline: Path | None) -> tuple[list[Built], list[str]]:
    adapters, problems = discover(root)
    if ids:
        known = {a.id for a in adapters}
        problems += [f"{i}: no such adapter under adapters/" for i in ids if i not in known]
        adapters = [a for a in adapters if a.id in ids]
    published = _load_baseline(baseline)
    built_all = []
    with tempfile.TemporaryDirectory(prefix="oneshelf-adapters-") as work:
        for adapter in adapters:
            built, found = build_adapter(adapter, Path(work))
            problems += found
            if built is not None:
                problems += baseline_problems(built, published, baseline)
                built_all.append(built)
    return sorted(built_all, key=lambda b: b.id), problems


def reproducibility_problems(root: Path, baseline: Path) -> list[str]:
    """Every adapter whose version is already published must rebuild to exactly the published bytes.

    Run on a different platform from the one that published, this is the proof that the canonical builder is
    reproducible everywhere — and the guard that notices if it ever stops being so.
    """
    built, problems = check(root, None, baseline)
    if problems:
        return problems
    published = {(e.id, e.version): e for e in _load_baseline(baseline)}
    for item in built:
        entry = published.get((item.id, item.version))
        if entry is not None and entry.sha256 != item.sha256:
            problems.append(f"{item.id} {item.version}: rebuilding here does not reproduce the published package "
                            f"({item.sha256[:12]} vs {entry.sha256[:12]}); the builder is not reproducible")
    return problems


# -- the Registry ---------------------------------------------------------------------------------------------

def _write_atomic(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_bytes(data)
    os.replace(temporary, path)


def index_bytes(built: list[Built], signer: Ed25519PrivateKey | None, key_id: str | None) -> bytes:
    plugins = []
    for item in sorted(built, key=lambda b: b.id):
        entry = {"id": item.id, "name": item.name, "version": item.version, "api": item.api,
                 "file": item.file, "sha256": item.sha256, "trust_label": item.adapter.trust_label}
        if signer is not None and item.adapter.tier in SIGNED_TIERS:
            # Core verifies exactly this: an Ed25519 signature over the package's sha256 hex digest.
            entry["signature"] = {"key_id": key_id,
                                  "value": base64.b64encode(signer.sign(item.sha256.encode())).decode()}
        plugins.append(entry)
    return (json.dumps({"schema": INDEX_SCHEMA, "plugins": plugins}, indent=2, sort_keys=True,
                       ensure_ascii=False) + "\n").encode()


def build_registry(root: Path, out: Path, signer: Ed25519PrivateKey | None, key_id: str | None, *,
                   require_signing: bool = False, baseline: Path | None = None) -> list[Built]:
    """Signatures are optional (owner decision, 2026-09-21): the first-party Registry's tiers are trusted
    by installations that name it as first-party. `require_signing` restores the stricter policy."""
    built, problems = check(root, None, baseline)
    if problems:
        raise ToolError("\n".join(problems))
    needs_key = sorted(b.id for b in built if b.adapter.tier in SIGNED_TIERS)
    if needs_key and signer is None and require_signing:
        raise ToolError(f"{len(needs_key)} Official/Verified Community adapters need the project signing key "
                        f"(--signing-key PATH --key-id ID): {', '.join(needs_key)}")
    for item in built:
        _write_atomic(out / item.file, item.data)
    wanted = {out / item.file for item in built}
    for stale in (out / "packages").glob("*.osp"):
        if stale not in wanted:
            stale.unlink()            # generated output only: a package the index no longer names
    _write_atomic(out / "index.json", index_bytes(built, signer, key_id))
    return built


def signature_problems(where: str, entry: RegistryEntry, trusted: dict[str, bytes], require_signed: bool) -> list[str]:
    """The same judgement Core makes: only a trusted key's valid signature makes a signed label true."""
    if entry.trust_label not in SIGNED_LABELS:
        return []
    if not entry.signature:
        return [f"{where}: {entry.trust_label} entry is unsigned"] if require_signed else []
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


def verify_registry(registry: Path, root: Path | None, trusted: dict[str, bytes], require_signed: bool) -> list[str]:
    try:
        entries = parse_index((registry / "index.json").read_bytes())
    except (OSError, RegistryError) as exc:
        return [f"index.json: {exc}"]
    problems, seen = [], set()
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
        problems += signature_problems(where, entry, trusted, require_signed)
    named = {(registry / e.location).resolve() for e in entries}
    for path in sorted((registry / "packages").glob("*")):
        if path.resolve() not in named:
            problems.append(f"packages/{path.name}: not named by the index")
    if root is not None:
        problems += _source_problems(entries, root)
    return problems


def _source_problems(entries: list[RegistryEntry], root: Path) -> list[str]:
    built, problems = check(root, None, None)
    if problems:
        return problems
    want = {b.id: b for b in built}
    have = {e.id: e for e in entries}
    for plugin in sorted(set(want) | set(have)):
        entry, item = have.get(plugin), want.get(plugin)
        if item is None:
            problems.append(f"{plugin}: in the registry but not under adapters/")
        elif entry is None:
            problems.append(f"{plugin}: under adapters/ but not in the registry — rebuild it")
        elif entry.trust_label != item.adapter.trust_label:
            problems.append(f"{plugin}: registry says {entry.trust_label!r} but its tier is {item.adapter.tier!r}")
        elif (entry.version, entry.sha256, entry.location, entry.api, entry.name) != (
                item.version, item.sha256, item.file, item.api, item.name):
            problems.append(f"{plugin}: registry {entry.version} ({entry.sha256[:12]}) is not what the sources "
                            f"build ({item.version}, {item.sha256[:12]}) — rebuild it")
    return problems


# -- keys -----------------------------------------------------------------------------------------------------

def trusted_keys(root: Path | None, extra: str) -> dict[str, bytes]:
    """Public keys only: the repository's committed trusted-keys file plus anything given explicitly."""
    lines = []
    if root is not None and (root / TRUSTED_KEYS_FILE).is_file():
        lines = [l.strip() for l in (root / TRUSTED_KEYS_FILE).read_text(encoding="utf-8").splitlines()]
    value = ",".join([l for l in lines if l and not l.startswith("#")] + ([extra] if extra else []))
    try:
        return parse_trusted_keys(value)
    except ValueError as exc:
        raise ToolError(f"trusted keys: {exc}") from exc


def _inside_work_tree(path: Path) -> Path | None:
    for parent in [path, *path.parents]:
        if (parent / ".git").exists():
            return parent
    return None


def key_path(argument: str | None, *, forbidden: list[Path]) -> Path | None:
    raw = argument or os.environ.get(KEY_FILE_ENV) or None
    if raw is None:
        return None
    path = Path(raw).expanduser().resolve()
    # Decided before the file is opened: a private key inside a repository is one `git add` from public.
    for root in forbidden:
        if path.is_relative_to(root.resolve()):
            raise ToolError(f"the signing key must live outside the repository ({root}); move it and retry")
    tree = _inside_work_tree(path.parent)
    if tree is not None:
        raise ToolError(f"the signing key must live outside any Git work tree ({tree}); move it and retry")
    return path


def load_key(path: Path) -> Ed25519PrivateKey:
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


def public_line(key: Ed25519PrivateKey, key_id: str) -> str:
    raw = key.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    return f"{key_id}:{base64.b64encode(raw).decode()}"


# -- command line ---------------------------------------------------------------------------------------------

def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m oneshelf.plugins.adapter_repo",
                                     description="Check adapters and build the OneShelf Source Registry.")
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("check", "check-all"):
        c = commands.add_parser(name)
        c.add_argument("--root", type=Path, default=Path("."))
        c.add_argument("--baseline", type=Path, help="the published Registry (index.json + packages/) to compare with")
        if name == "check":
            c.add_argument("ids", nargs="+")
    r = commands.add_parser("reproducible")
    r.add_argument("--root", type=Path, default=Path("."))
    r.add_argument("--baseline", type=Path, required=True)
    b = commands.add_parser("build-registry")
    b.add_argument("--root", type=Path, default=Path("."))
    b.add_argument("--out", type=Path, required=True)
    b.add_argument("--baseline", type=Path)
    b.add_argument("--signing-key", help=f"Ed25519 PEM key outside any repository (or ${KEY_FILE_ENV})")
    b.add_argument("--key-id")
    b.add_argument("--require-signing", action="store_true",
                   help="refuse to publish Official/Verified Community entries without a signature")
    b.add_argument("--unsigned-preview", action="store_true", help="accepted for compatibility; unsigned is the default")
    v = commands.add_parser("verify-registry")
    v.add_argument("--registry", type=Path, required=True)
    v.add_argument("--root", type=Path, help="also check the Registry is exactly what these adapters build")
    v.add_argument("--trusted-keys", default="", help="extra public keys, key-id:base64,...")
    v.add_argument("--require-signed", action="store_true")
    p = commands.add_parser("public-key")
    p.add_argument("--signing-key")
    p.add_argument("--key-id", required=True)
    return parser


def _report(problems: list[str], ok: str) -> int:
    for problem in problems:
        print(problem, file=sys.stderr)
    if problems:
        print(f"{len(problems)} problem(s)", file=sys.stderr)
        return 1
    print(ok)
    return 0


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.command in ("check", "check-all"):
            built, problems = check(args.root, getattr(args, "ids", None), args.baseline)
            return _report(problems, f"{len(built)} adapter(s) passed")
        if args.command == "reproducible":
            return _report(reproducibility_problems(args.root, args.baseline),
                           "every published version rebuilds to its published bytes")
        if args.command == "build-registry":
            path = key_path(args.signing_key, forbidden=[args.root, args.out])
            if path is not None and not args.key_id:
                raise ToolError("--key-id is required when signing")
            signer = load_key(path) if path is not None else None
            built = build_registry(args.root, args.out, signer, args.key_id, require_signing=args.require_signing,
                                   baseline=args.baseline)
            signed = sum(1 for b in built if b.adapter.tier in SIGNED_TIERS) if signer else 0
            print(f"built {len(built)} packages into {args.out} ({signed} signed with {args.key_id or '-'})")
            return 0
        if args.command == "verify-registry":
            trusted = trusted_keys(args.root, args.trusted_keys)
            problems = verify_registry(args.registry, args.root, trusted, args.require_signed)
            return _report(problems, f"{args.registry}: verified")
        path = key_path(args.signing_key, forbidden=[])
        if path is None:
            raise ToolError(f"--signing-key (or ${KEY_FILE_ENV}) is required")
        print(public_line(load_key(path), args.key_id))
        return 0
    except ToolError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
