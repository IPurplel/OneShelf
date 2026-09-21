"""Plugin Registry sources (Master §10; ledger A1): a static JSON index, no account, no publishing.

Index format (schema "oneshelf.registry/1"):
  {"schema": "oneshelf.registry/1",
   "plugins": [{"id", "name", "version", "file" | "url", "sha256", "trust_label", "api"?,
                "signature": {"key_id", "value": base64(ed25519(sha256-hex))}?}]}

The index is untrusted input. Publisher keys are never taken from it — they are configured locally — and
a trust label in it is only a claim, which a signature from a locally trusted key has to back. It also
decides nothing about what Core may fetch: a package location must stay beneath the index's own
directory, on the same host, with no credentials, queries or encodings that could smuggle a path out.
"""
from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Protocol
from urllib.parse import unquote, urlsplit, urlunsplit

from oneshelf.net.http import HttpClient
from oneshelf.net.policy import EgressPolicy

INDEX_SCHEMA = "oneshelf.registry/1"
MAX_INDEX_BYTES = 5 * 1024**2
MAX_PACKAGE_BYTES = 20 * 1024**2
_SEGMENT = re.compile(r"^[A-Za-z0-9._-]{1,128}$")
_PLUGIN_ID = re.compile(r"^[a-z0-9]+(?:[.-][a-z0-9]+)*$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_VERSION = re.compile(r"^\d+\.\d+\.\d+$")
_API = re.compile(r"^\d+\.\d+$")
MAX_LOCATION = 256
MAX_DEPTH = 4


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
    # The plugin API the package targets, so an index can say "needs a newer OneShelf" without the
    # package being downloaded. A hint only: the package's own manifest is still what is enforced.
    api: str | None = None


def _version_key(version: str) -> tuple[int, ...]:
    return tuple(int(p) for p in version.split("."))


def parse_index(data: bytes) -> list[RegistryEntry]:
    if len(data) > MAX_INDEX_BYTES:
        raise RegistryError("registry index is too large")
    try:
        index = json.loads(data)
    except ValueError as exc:
        raise RegistryError("registry index is not valid JSON") from exc
    if not isinstance(index, dict) or index.get("schema") != INDEX_SCHEMA or not isinstance(index.get("plugins"), list):
        raise RegistryError("unsupported registry index")
    entries = []
    for raw in index["plugins"]:
        try:
            if not isinstance(raw, dict):
                raise TypeError("entry is not an object")
            signature = raw.get("signature") or {}
            if not isinstance(signature, dict):
                raise TypeError("signature is not an object")
            location = raw.get("file") or raw["url"]
            entry = RegistryEntry(
                id=str(raw["id"]), name=str(raw["name"]), version=str(raw["version"]), sha256=str(raw["sha256"]).lower(),
                trust_label=str(raw.get("trust_label", "community")), location=str(location),
                signature_key_id=signature.get("key_id"), signature=signature.get("value"),
                api=str(raw["api"]) if raw.get("api") is not None else None,
            )
            if not _PLUGIN_ID.match(entry.id) or len(entry.id) > 64:
                raise ValueError(f"invalid plugin id {entry.id!r}")
            if not _VERSION.match(entry.version):
                raise ValueError(f"invalid version {entry.version!r}")
            if not _SHA256.match(entry.sha256):
                raise ValueError("sha256 must be 64 hex characters")
            if entry.api is not None and not _API.match(entry.api):
                raise ValueError(f"invalid api {entry.api!r}")
            if not entry.location or len(entry.location) > 2048:
                raise ValueError("missing or overlong package location")
            entries.append(entry)
        except (KeyError, TypeError, ValueError, AttributeError) as exc:
            raise RegistryError(f"invalid registry entry: {exc}") from exc
    return entries


def api_supported(api: str | None) -> bool:
    """Whether this OneShelf can load a package targeting `api` (unknown means: let the manifest decide)."""
    from oneshelf.plugins.schema import API_MAJOR, API_MINOR

    if api is None:
        return True
    major, minor = (int(p) for p in api.split("."))
    return major == API_MAJOR and minor <= API_MINOR


# -- where a package may come from ------------------------------------------------------------------------

def _segments(relative: str) -> list[str]:
    """A relative package path, or nothing: plain segments, no traversal, ending in `.osp`."""
    if (not relative or len(relative) > MAX_LOCATION or "\\" in relative or relative.startswith("/")
            or any(c in relative for c in "?#%") or any(c.isspace() for c in relative)):
        raise RegistryError("registry package locations must be plain relative .osp paths")
    parts = relative.split("/")
    if len(parts) > MAX_DEPTH or any(p in ("", ".", "..") or not _SEGMENT.match(p) for p in parts):
        raise RegistryError("registry package locations must be plain relative .osp paths")
    if not parts[-1].endswith(".osp"):
        raise RegistryError("registry packages must be .osp files")
    return parts


def resolve_package_url(index_url: str, location: str) -> str:
    """The package URL for `location`, only if it lies beneath the index's own directory.

    A host allowlist alone is not enough: raw.githubusercontent.com serves every repository, so an
    index could otherwise point Core at a package from anyone's. Relative locations are joined onto the
    index directory; absolute ones must already be there, over HTTPS, on the same host and port.
    """
    index = urlsplit(index_url)
    base = index.path.rsplit("/", 1)[0] + "/"
    if "://" in location or location.startswith("//"):
        target = urlsplit(location)
        # The index's own scheme and nothing else: an https registry can never be walked down to http.
        if (target.scheme != index.scheme or target.username or target.password or target.query or target.fragment
                or target.hostname != index.hostname or target.port != index.port or not target.path.startswith(base)):
            raise RegistryError("registry packages must be served from beneath the registry index")
        relative = target.path[len(base):]
    else:
        relative = location
    parts = _segments(relative)
    return urlunsplit((index.scheme, index.netloc, base + "/".join(parts), "", ""))


# -- registries -----------------------------------------------------------------------------------------------

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

    def __init__(self, root: str | Path, *, max_package_bytes: int = MAX_PACKAGE_BYTES) -> None:
        self.root = Path(root)
        self.location = self.root.as_uri()
        self.max_package_bytes = max_package_bytes

    async def entries(self) -> list[RegistryEntry]:
        index = self.root / "index.json"
        try:
            if index.stat().st_size > MAX_INDEX_BYTES:
                raise RegistryError("registry index is too large")
            return parse_index(index.read_bytes())
        except OSError as exc:
            raise RegistryError(f"registry index is unreadable: {exc.strerror}") from exc

    async def fetch(self, entry: RegistryEntry) -> bytes:
        if "://" in entry.location or entry.location.startswith("//"):
            raise RegistryError("a local registry serves only files beneath its own directory")
        path = self.root.joinpath(*_segments(entry.location))
        root = self.root.resolve()
        try:
            resolved = path.resolve(strict=True)
        except OSError as exc:
            raise RegistryError("registry package is missing") from exc
        if not resolved.is_relative_to(root):
            raise RegistryError("registry package resolves outside the registry")
        if resolved.stat().st_size > self.max_package_bytes:
            raise RegistryError("registry package is too large")
        return resolved.read_bytes()


class HttpRegistry:
    """A static index served over HTTPS, fetched through the Core policy-enforced client."""

    def __init__(self, index_url: str, client: HttpClient, max_package_bytes: int = MAX_PACKAGE_BYTES) -> None:
        self.location = index_url
        self.client = client
        self.max_package_bytes = max_package_bytes

    async def entries(self) -> list[RegistryEntry]:
        response = await self.client.fetch(self.location, max_bytes=MAX_INDEX_BYTES)
        if response.status != 200:
            raise RegistryError(f"registry index returned HTTP {response.status}")
        return parse_index(response.body)

    async def fetch(self, entry: RegistryEntry) -> bytes:
        url = resolve_package_url(self.location, entry.location)
        response = await self.client.fetch(url, max_bytes=self.max_package_bytes)
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
        return await self._guard(lambda client: HttpRegistry(self.location, client).entries())

    async def fetch(self, entry: RegistryEntry) -> bytes:
        return await self._guard(lambda client: HttpRegistry(self.location, client).fetch(entry))

    async def _guard(self, call):
        """Every way the network can refuse becomes one error the callers already handle."""
        try:
            async with HttpClient(self._policy) as client:
                return await call(client)
        except RegistryError:
            raise
        except Exception as exc:                       # policy refusal, DNS, TLS, timeout, too large
            name = type(exc).__name__
            if name == "ResponseTooLarge":
                raise RegistryError("registry response is too large") from exc
            raise RegistryError(f"registry unavailable ({name})") from exc


class CachedRegistry:
    """Remembers the index for a while, and remembers a failure for a shorter while.

    The Sources screen asks for the Registry every time it opens. Without this, an offline Registry
    would be asked again on every visit, and a slow one would make the screen wait each time.
    Packages are never cached: each is fetched when it is reviewed or installed and checked by hash.
    """

    def __init__(self, inner, *, ttl: float = 300, failure_ttl: float = 60,
                 clock: Callable[[], float] = time.monotonic) -> None:
        self.inner = inner
        self.location = inner.location
        self.ttl, self.failure_ttl, self.clock = ttl, failure_ttl, clock
        self._entries: list[RegistryEntry] | None = None
        self._failure: str | None = None
        self._at = 0.0

    async def entries(self) -> list[RegistryEntry]:
        now = self.clock()
        if self._entries is not None and now - self._at < self.ttl:
            return self._entries
        if self._failure is not None and now - self._at < self.failure_ttl:
            raise RegistryError(self._failure)
        try:
            self._entries, self._failure = await self.inner.entries(), None
        except RegistryError as exc:
            self._entries, self._failure = None, str(exc)
            self._at = now
            raise
        self._at = now
        return self._entries

    def invalidate(self) -> None:
        self._entries, self._failure, self._at = None, None, 0.0

    async def fetch(self, entry: RegistryEntry) -> bytes:
        return await self.inner.fetch(entry)


class UnavailableRegistry:
    """A configured registry Core refuses to use. The Sources page reports it; nothing else stops."""

    def __init__(self, location: str, reason: str) -> None:
        self.location, self.reason = location, reason

    async def entries(self) -> list[RegistryEntry]:
        raise RegistryError(self.reason)

    async def fetch(self, entry: RegistryEntry) -> bytes:
        raise RegistryError(self.reason)

    def invalidate(self) -> None:
        pass


def registry_from_config(url: str | None):
    """None (no registry), a local mirror (file://directory) or an HTTPS static index URL."""
    if not url:
        return None
    parts = urlsplit(url)
    if parts.username or parts.password:
        raise RegistryError("registry URLs must not contain credentials")
    if parts.scheme == "file":
        return CachedRegistry(DirectoryRegistry(unquote(parts.path)))
    if parts.scheme == "https" and parts.hostname:
        try:
            return CachedRegistry(ConfiguredHttpRegistry(url))
        except ValueError as exc:
            raise RegistryError(f"invalid registry host: {exc}") from exc
    raise RegistryError("registry URL must be https:// or a local file:// mirror")


def parse_trusted_keys(value: str | None) -> dict[str, bytes]:
    """"key-id:base64-ed25519-public-key,..." from local configuration (never from a registry index).

    More than one key may be listed, which is how a signing key is rotated: trust old and new together,
    re-sign the registry with the new one, then remove the old.
    """
    import base64

    keys: dict[str, bytes] = {}
    for item in (value or "").split(","):
        if not item.strip():
            continue
        key_id, _, encoded = item.strip().partition(":")
        try:
            raw = base64.b64decode(encoded, validate=True)
        except ValueError as exc:
            raise RegistryError(f"invalid trusted registry key {key_id!r}") from exc
        if not key_id or len(raw) != 32:
            raise RegistryError(f"invalid trusted registry key {key_id!r}")
        keys[key_id] = raw
    return keys
