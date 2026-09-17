"""Plugin Registry sources (Master §10; ledger A1): a static JSON index, no account, no publishing.

Index format (schema "oneshelf.registry/1"):
  {"schema": "oneshelf.registry/1",
   "plugins": [{"id", "name", "version", "file" | "url", "sha256", "trust_label",
                "signature": {"key_id", "value": base64(ed25519(sha256-hex))}?}]}
Publisher keys are never taken from the index itself; they are configured locally.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol
from urllib.parse import unquote, urljoin, urlsplit

from oneshelf.net.http import HttpClient
from oneshelf.net.policy import EgressPolicy

INDEX_SCHEMA = "oneshelf.registry/1"
_SAFE_FILE = re.compile(r"^[A-Za-z0-9._-]{1,128}\.osp$")


class RegistryError(RuntimeError):
    pass


@dataclass(frozen=True)
class RegistryEntry:
    id: str
    name: str
    version: str
    sha256: str
    trust_label: str
    location: str
    signature_key_id: str | None = None
    signature: str | None = None


def _version_key(version: str) -> tuple[int, ...]:
    return tuple(int(p) for p in version.split("."))


def parse_index(data: bytes) -> list[RegistryEntry]:
    try:
        index = json.loads(data)
    except ValueError as exc:
        raise RegistryError("registry index is not valid JSON") from exc
    if not isinstance(index, dict) or index.get("schema") != INDEX_SCHEMA or not isinstance(index.get("plugins"), list):
        raise RegistryError("unsupported registry index")
    entries = []
    for raw in index["plugins"]:
        try:
            signature = raw.get("signature") or {}
            location = raw.get("file") or raw["url"]
            entries.append(RegistryEntry(
                id=str(raw["id"]), name=str(raw["name"]), version=str(raw["version"]), sha256=str(raw["sha256"]).lower(),
                trust_label=str(raw.get("trust_label", "community")), location=str(location),
                signature_key_id=signature.get("key_id"), signature=signature.get("value"),
            ))
            _version_key(entries[-1].version)
        except (KeyError, TypeError, ValueError, AttributeError) as exc:
            raise RegistryError(f"invalid registry entry: {exc}") from exc
    return entries


class Registry(Protocol):
    location: str

    async def entries(self) -> list[RegistryEntry]: ...

    async def fetch(self, entry: RegistryEntry) -> bytes: ...


def pick(entries: list[RegistryEntry], plugin_id: str, version: str | None) -> RegistryEntry:
    candidates = [e for e in entries if e.id == plugin_id and (version is None or e.version == version)]
    if not candidates:
        raise RegistryError(f"plugin {plugin_id!r} {version or ''} not found in registry")
    return max(candidates, key=lambda e: _version_key(e.version))


class DirectoryRegistry:
    """A registry mirror on local storage (also used for offline mirrors and tests)."""

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)
        self.location = self.root.as_uri()

    async def entries(self) -> list[RegistryEntry]:
        return parse_index((self.root / "index.json").read_bytes())

    async def fetch(self, entry: RegistryEntry) -> bytes:
        if not _SAFE_FILE.match(entry.location):
            raise RegistryError("registry file names must be plain .osp file names")
        return (self.root / entry.location).read_bytes()


class HttpRegistry:
    """A static index served over HTTPS, fetched through the Core policy-enforced client."""

    def __init__(self, index_url: str, client: HttpClient, max_package_bytes: int = 20 * 1024**2) -> None:
        self.location = index_url
        self.client = client
        self.max_package_bytes = max_package_bytes

    async def entries(self) -> list[RegistryEntry]:
        response = await self.client.fetch(self.location, max_bytes=5 * 1024**2)
        if response.status != 200:
            raise RegistryError(f"registry index returned HTTP {response.status}")
        return parse_index(response.body)

    async def fetch(self, entry: RegistryEntry) -> bytes:
        response = await self.client.fetch(urljoin(self.location, entry.location), max_bytes=self.max_package_bytes)
        if response.status != 200:
            raise RegistryError(f"registry package returned HTTP {response.status}")
        return response.body


class ConfiguredHttpRegistry:
    """HTTPS registry configured by the user; each access uses a client allowlisted to that host only."""

    def __init__(self, index_url: str) -> None:
        self.location = index_url
        host = urlsplit(index_url).hostname or ""
        self._policy = EgressPolicy(domains=(host,))

    async def entries(self) -> list[RegistryEntry]:
        async with HttpClient(self._policy) as client:
            return await HttpRegistry(self.location, client).entries()

    async def fetch(self, entry: RegistryEntry) -> bytes:
        async with HttpClient(self._policy) as client:
            return await HttpRegistry(self.location, client).fetch(entry)


def registry_from_config(url: str | None):
    """None (no registry), a local mirror (file://directory) or an HTTPS static index URL."""
    if not url:
        return None
    parts = urlsplit(url)
    if parts.username or parts.password:
        raise RegistryError("registry URLs must not contain credentials")
    if parts.scheme == "file":
        return DirectoryRegistry(unquote(parts.path))
    if parts.scheme == "https" and parts.hostname:
        try:
            return ConfiguredHttpRegistry(url)
        except ValueError as exc:
            raise RegistryError(f"invalid registry host: {exc}") from exc
    raise RegistryError("registry URL must be https:// or a local file:// mirror")


def parse_trusted_keys(value: str | None) -> dict[str, bytes]:
    """"key-id:base64-ed25519-public-key,..." from local configuration (never from a registry index)."""
    import base64

    keys: dict[str, bytes] = {}
    for item in (value or "").split(","):
        if not item.strip():
            continue
        key_id, _, encoded = item.strip().partition(":")
        raw = base64.b64decode(encoded)
        if not key_id or len(raw) != 32:
            raise RegistryError(f"invalid trusted registry key {key_id!r}")
        keys[key_id] = raw
    return keys
