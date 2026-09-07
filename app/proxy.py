"""Proxy configuration.

Both halves of the session must egress through the same path: the browser that
solves the bot check and the HTTP client that downloads images. A clearance
cookie is bound to the IP that earned it, so if the two disagree about their
route, every image request is rejected.

Supports HTTP(S) and SOCKS4/5. For SOCKS5 the hostname is sent to the proxy
rather than resolved locally, so the DNS lookup and the TLS handshake — including
the plaintext hostname in the ClientHello — both happen beyond the local network.
That is what makes this work against SNI-based filtering.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from urllib.parse import unquote, urlparse

log = logging.getLogger(__name__)

SCHEMES = {"http", "https", "socks4", "socks5", "socks5h"}

# Chromium understands socks5:// but not the socks5h:// spelling, even though
# it already performs remote resolution for SOCKS5.
_BROWSER_SCHEME = {"socks5h": "socks5"}


class ProxyError(ValueError):
    """Raised when a proxy URL cannot be understood."""


@dataclass(frozen=True, slots=True)
class ProxyConfig:
    scheme: str
    host: str
    port: int
    username: str | None = None
    password: str | None = None

    @property
    def is_socks(self) -> bool:
        return self.scheme.startswith("socks")

    @property
    def server(self) -> str:
        """Scheme://host:port with no credentials."""
        return f"{self.scheme}://{self.host}:{self.port}"

    def for_browser(self) -> dict[str, str]:
        """Playwright's ``proxy=`` argument.

        Credentials are passed separately rather than embedded in the URL,
        which is what Playwright expects.
        """
        scheme = _BROWSER_SCHEME.get(self.scheme, self.scheme)
        config = {"server": f"{scheme}://{self.host}:{self.port}"}
        if self.username:
            config["username"] = self.username
            config["password"] = self.password or ""
        return config

    def for_httpx(self) -> str:
        """A proxy URL httpx accepts, credentials inline."""
        scheme = _BROWSER_SCHEME.get(self.scheme, self.scheme)
        if self.username:
            from urllib.parse import quote

            auth = quote(self.username, safe="")
            if self.password:
                auth += f":{quote(self.password, safe='')}"
            return f"{scheme}://{auth}@{self.host}:{self.port}"
        return f"{scheme}://{self.host}:{self.port}"

    def describe(self) -> str:
        """Safe for logs and the UI — never leaks the password."""
        auth = f"{self.username}:***@" if self.username else ""
        return f"{self.scheme}://{auth}{self.host}:{self.port}"


def parse_proxy(raw: str | None) -> ProxyConfig | None:
    """Parse a proxy URL. Returns ``None`` when unset, raises when malformed.

    A bare ``host:port`` is treated as HTTP, matching how most tools behave.
    """
    if raw is None:
        return None
    raw = raw.strip()
    if not raw:
        return None

    if "://" not in raw:
        raw = f"http://{raw}"

    try:
        parsed = urlparse(raw)
        scheme = parsed.scheme.lower()
        hostname = parsed.hostname
        # urlparse validates the port lazily on attribute access and raises its
        # own ValueError for a non-numeric or out-of-range value. Convert it so
        # callers only ever have to handle ProxyError.
        raw_port = parsed.port
    except ValueError as exc:
        raise ProxyError(f"Malformed proxy URL {raw!r}: {exc}") from exc

    if scheme not in SCHEMES:
        raise ProxyError(
            f"Unsupported proxy scheme {parsed.scheme!r}. "
            f"Use one of: {', '.join(sorted(SCHEMES))}"
        )
    if not hostname:
        raise ProxyError(f"No host in proxy URL {raw!r}")

    port = raw_port
    if port is None:
        # Sensible defaults so "socks5://127.0.0.1" is not a hard error.
        port = 1080 if scheme.startswith("socks") else 8080
    if not 1 <= port <= 65535:
        raise ProxyError(f"Port {port} out of range in proxy URL")

    return ProxyConfig(
        scheme=scheme,
        host=hostname,
        port=port,
        username=unquote(parsed.username) if parsed.username else None,
        password=unquote(parsed.password) if parsed.password else None,
    )
