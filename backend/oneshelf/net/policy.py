"""Outbound egress policy for source traffic (Master §11, §48; INV-15).

Every hop is checked: scheme, credentials, IP-literal hosts, ports, domain allowlist; every DNS answer
is checked and rejected entirely if any address is not public. Inbound LAN trust never widens this.
"""
from __future__ import annotations

import ipaddress
from dataclasses import dataclass
from urllib.parse import urlsplit

from oneshelf.net.domains import host_allowed, normalize_rule, to_ascii_host, DomainRuleError

TEST_SOURCE_ID = "oneshelf.test-source"
_NAT64 = ipaddress.ip_network("64:ff9b::/96")
_NAT64_LOCAL = ipaddress.ip_network("64:ff9b:1::/48")


class DisallowedTarget(ValueError):
    """URL rejected before any network activity."""


class BlockedDestination(RuntimeError):
    """DNS answer contained a non-public address (or no usable address)."""


class PolicyConfigError(ValueError):
    pass


def is_public_address(value: str) -> bool:
    try:
        ip = ipaddress.ip_address(value)
    except ValueError:
        return False
    if isinstance(ip, ipaddress.IPv6Address):
        if ip.ipv4_mapped is not None:
            return is_public_address(str(ip.ipv4_mapped))
        if ip.sixtofour is not None:
            return is_public_address(str(ip.sixtofour))
        if ip.teredo is not None or ip in _NAT64_LOCAL:
            return False
        if ip in _NAT64:
            return is_public_address(str(ipaddress.IPv4Address(int(ip) & 0xFFFFFFFF)))
    return bool(
        ip.is_global and not (ip.is_multicast or ip.is_reserved or ip.is_unspecified or ip.is_loopback
                              or ip.is_link_local or ip.is_private)
    )


@dataclass(frozen=True)
class Target:
    url: str
    scheme: str
    host: str
    port: int


@dataclass(frozen=True)
class EgressPolicy:
    domains: tuple[str, ...]
    cdn_domains: tuple[str, ...] = ()
    allow_http: bool = False
    dev_loopback_exception: bool = False
    allowed_ports: tuple[int, ...] = ()

    def __post_init__(self) -> None:
        if not self.domains:
            raise PolicyConfigError("an egress policy needs at least one allowlisted domain")
        try:
            for rule in (*self.domains, *self.cdn_domains):
                if normalize_rule(rule) != rule:
                    raise PolicyConfigError(f"domain rule is not canonical: {rule!r}")
        except DomainRuleError as exc:
            raise PolicyConfigError(str(exc)) from exc

    @property
    def rules(self) -> tuple[str, ...]:
        return (*self.domains, *self.cdn_domains)

    def check_url(self, url: str) -> Target:
        try:
            parts = urlsplit(url)
            port = parts.port
        except ValueError as exc:
            raise DisallowedTarget(f"malformed URL: {url!r}") from exc
        schemes = {"https", "http"} if self.allow_http else {"https"}
        if parts.scheme not in schemes:
            raise DisallowedTarget(f"scheme not allowed: {parts.scheme!r}")
        if parts.username is not None or parts.password is not None:
            raise DisallowedTarget("credentials in URLs are not allowed")
        host = parts.hostname
        if not host:
            raise DisallowedTarget("URL has no host")
        candidate = host.strip("[]")
        try:
            ipaddress.ip_address(candidate)
            raise DisallowedTarget("IP-literal hosts are not allowed")
        except ValueError:
            pass
        if candidate.isdigit():
            raise DisallowedTarget("numeric hosts are not allowed")
        try:
            ascii_host = to_ascii_host(candidate)
        except DomainRuleError as exc:
            raise DisallowedTarget(str(exc)) from exc
        if not host_allowed(ascii_host, self.rules):
            raise DisallowedTarget(f"domain not allowlisted: {ascii_host}")
        default_port = 443 if parts.scheme == "https" else 80
        port = port or default_port
        if port != default_port and port not in self.allowed_ports and not self.dev_loopback_exception:
            raise DisallowedTarget(f"port not allowed: {port}")
        return Target(url=url, scheme=parts.scheme, host=ascii_host, port=port)

    def check_resolved(self, host: str, addresses: list[str]) -> None:
        if not addresses:
            raise BlockedDestination(f"no addresses for {host}")
        if all(is_public_address(a) for a in addresses):
            return
        if self.dev_loopback_exception and all(ipaddress.ip_address(a).is_loopback for a in addresses):
            return
        raise BlockedDestination(f"{host} resolves to a non-public address")


def policy_for_plugin(
    plugin_id: str,
    *,
    domains: list[str],
    cdn_domains: list[str],
    allow_http: bool,
    dev_test_source_enabled: bool,
) -> EgressPolicy:
    """The loopback exception exists only for the OneShelf Test Source and only when explicitly enabled."""
    return EgressPolicy(
        domains=tuple(domains),
        cdn_domains=tuple(cdn_domains),
        allow_http=allow_http,
        dev_loopback_exception=dev_test_source_enabled and plugin_id == TEST_SOURCE_ID,
    )
