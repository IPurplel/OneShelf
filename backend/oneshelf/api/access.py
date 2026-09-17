"""Inbound access classification (Master §28.1–28.2, §48; ledger A2, K4).

Trust is derived from the real peer address and explicit configuration. Forwarded-for headers are
honoured only when the peer is an explicitly configured trusted proxy, using the right-most address
that is not itself a trusted proxy (a client cannot prepend its way into LAN trust).
"""
from __future__ import annotations

import ipaddress
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Literal

IPNetwork = ipaddress.IPv4Network | ipaddress.IPv6Network
IPAddress = ipaddress.IPv4Address | ipaddress.IPv6Address
AccessKind = Literal["loopback", "lan", "remote"]


@dataclass(frozen=True)
class AccessConfig:
    trusted_networks: tuple[IPNetwork, ...] = ()
    trusted_proxies: tuple[IPNetwork, ...] = ()

    @staticmethod
    def _parse(value: str) -> tuple[IPNetwork, ...]:
        return tuple(ipaddress.ip_network(part.strip(), strict=True) for part in value.split(",") if part.strip())

    @classmethod
    def from_strings(cls, *, trusted_networks: str, trusted_proxies: str) -> AccessConfig:
        return cls(cls._parse(trusted_networks), cls._parse(trusted_proxies))


@dataclass(frozen=True)
class AccessClass:
    kind: AccessKind
    client_ip: str | None


def _ip(value: str | None) -> IPAddress | None:
    if not value:
        return None
    try:
        addr = ipaddress.ip_address(value.strip())
    except ValueError:
        return None
    if isinstance(addr, ipaddress.IPv6Address) and addr.ipv4_mapped is not None:
        return addr.ipv4_mapped
    return addr


def _in(addr: IPAddress, networks: tuple[IPNetwork, ...]) -> bool:
    return any(addr.version == net.version and addr in net for net in networks)


def classify(peer: str | None, headers: Mapping[str, str], config: AccessConfig) -> AccessClass:
    peer_ip = _ip(peer)
    if peer_ip is None:
        return AccessClass("remote", None)

    client = peer_ip
    if _in(peer_ip, config.trusted_proxies):
        forwarded = [part.strip() for part in headers.get("x-forwarded-for", "").split(",") if part.strip()]
        client = None
        for entry in reversed(forwarded):
            addr = _ip(entry)
            if addr is None:
                break
            if _in(addr, config.trusted_proxies):
                continue
            client = addr
            break
        if client is None:
            return AccessClass("remote", str(peer_ip))

    if client.is_loopback:
        return AccessClass("loopback", str(client))
    if _in(client, config.trusted_networks):
        return AccessClass("lan", str(client))
    return AccessClass("remote", str(client))
