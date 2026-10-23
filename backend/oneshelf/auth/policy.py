"""Trusted-network policy (Master §28.1–28.2; ledger A2).

Trust is configuration plus the real peer address — never a client-supplied header. Configured networks
are stored in settings so First Run and Settings can change them without a restart, and are merged with
anything the deployment set in the environment.

Because NAT and rootless port forwarding can make every remote client look like one private address, the
policy watches how many distinct addresses actually appear and warns when they all collapse into one.
"""
from __future__ import annotations

import ipaddress
import json
import logging
import sqlite3
from collections import Counter

from oneshelf.api.access import AccessConfig, IPNetwork
from oneshelf.db.connection import transaction
from oneshelf.domain.clock import utcnow_iso

NETWORKS_SETTING = "access.trusted_networks"
PROXIES_SETTING = "access.trusted_proxies"

GATEWAY_WARNING = (
    "Every device reaching OneShelf so far has arrived from one address ({address}). That usually means a "
    "router or proxy is forwarding traffic, so anyone behind it would count as a trusted LAN device. Narrow "
    "your trusted networks, or configure that address as a trusted proxy."
)


logger = logging.getLogger(__name__)

# The widest prefix a trusted proxy may name (I-91). A proxy is a few known machines, never a whole range.
MIN_PROXY_PREFIX = {4: 8, 6: 32}
# Where a proxy in front of OneShelf can actually live. Python's `is_private` also counts documentation and
# benchmarking ranges, which are not anyone's network, so proxies use this explicit list instead.
PROXY_RANGES = tuple(ipaddress.ip_network(n) for n in (
    "10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16", "100.64.0.0/10", "127.0.0.0/8", "169.254.0.0/16",
    "::1/128", "fc00::/7", "fe80::/10"))


class PolicyError(RuntimeError):
    pass


def _parse(values: list[str]) -> tuple[IPNetwork, ...]:
    networks = []
    for value in values:
        try:
            networks.append(ipaddress.ip_network(str(value).strip(), strict=True))
        except ValueError as exc:
            raise PolicyError(f"{value!r} is not a network in CIDR form, for example 192.168.1.0/24") from exc
    return tuple(networks)


def _require_private(networks: tuple[IPNetwork, ...]) -> None:
    for network in networks:
        if not _private_or_local(network):
            raise PolicyError(f"{network} is a public range; a trusted LAN must be a private network")


def _private_or_local(network: IPNetwork) -> bool:
    return network.is_private or network.is_link_local or network.is_loopback


def _proxy_problem(network: IPNetwork) -> str | None:
    """Why a network cannot be a trusted proxy, or None (Master §28.2, I-91).

    Forwarded client addresses are believed only from a trusted proxy, so a proxy range that reaches the
    internet would let anyone there claim to be a LAN device.
    """
    if not any(network.version == r.version and network.subnet_of(r) for r in PROXY_RANGES):
        return f"{network} is not a private address; a trusted proxy must be inside your network"
    if network.prefixlen < MIN_PROXY_PREFIX[network.version]:
        return f"{network} is too wide for a proxy; name the proxy's own address, for example 192.168.1.5/32"
    return None


def _require_safe_proxies(proxies: tuple[IPNetwork, ...]) -> None:
    for proxy in proxies:
        problem = _proxy_problem(proxy)
        if problem:
            raise PolicyError(problem)


class AccessPolicy:
    GATEWAY_SAMPLE = 20

    def __init__(self, conn: sqlite3.Connection, *, base: AccessConfig | None = None) -> None:
        self.conn = conn
        self.base = base or AccessConfig()
        self._clients: Counter[str] = Counter()

    # -- storage ------------------------------------------------------------------------------------

    def _get(self, key: str) -> list[str]:
        row = self.conn.execute("SELECT value_json FROM settings WHERE scope = 'global' AND scope_id = ''"
                                " AND key = ?", (key,)).fetchone()
        return json.loads(row[0]) if row is not None else []

    def _set(self, key: str, values: list[str]) -> None:
        with transaction(self.conn):
            self._write(key, values)

    def _write(self, key: str, values: list[str]) -> None:
        self.conn.execute(
            "INSERT INTO settings (scope, scope_id, key, value_json, updated_at) VALUES ('global','',?,?,?)"
            " ON CONFLICT(scope, scope_id, key) DO UPDATE SET value_json = excluded.value_json,"
            " updated_at = excluded.updated_at", (key, json.dumps(values), utcnow_iso()))

    def update(self, *, trusted_networks: list[str] | None = None,
               trusted_proxies: list[str] | None = None) -> None:
        networks = _parse(trusted_networks) if trusted_networks is not None else None
        if networks is not None:
            _require_private(networks)
        proxies = _parse(trusted_proxies) if trusted_proxies is not None else None
        if proxies is not None:
            _require_safe_proxies(proxies)
        with transaction(self.conn):
            if networks is not None:
                self._write(NETWORKS_SETTING, [str(network) for network in networks])
            if proxies is not None:
                self._write(PROXIES_SETTING, [str(proxy) for proxy in proxies])

    def set_trusted_networks(self, values: list[str]) -> tuple[IPNetwork, ...]:
        networks = _parse(values)
        _require_private(networks)
        self._set(NETWORKS_SETTING, [str(n) for n in networks])
        return networks

    def set_trusted_proxies(self, values: list[str]) -> tuple[IPNetwork, ...]:
        proxies = _parse(values)
        _require_safe_proxies(proxies)
        self._set(PROXIES_SETTING, [str(n) for n in proxies])
        return proxies

    def _stored_proxies(self) -> tuple[tuple[IPNetwork, ...], tuple[IPNetwork, ...]]:
        """Stored proxies split into honoured and ignored ones.

        An older build accepted any range; such an entry is kept in settings and reported so the person can
        see and fix it, but it is never honoured (I-91). Deployment configuration is the operator's own.
        """
        stored = _parse(self._get(PROXIES_SETTING))
        ignored = tuple(p for p in stored if _proxy_problem(p))
        if ignored and not getattr(self, "_reported_ignored", False):
            self._reported_ignored = True
            logger.warning("ignoring %d unsafe trusted proxy setting(s): %s", len(ignored),
                           ", ".join(str(p) for p in ignored))
        return tuple(p for p in stored if p not in ignored), ignored

    def current(self) -> AccessConfig:
        honoured, _ignored = self._stored_proxies()
        return AccessConfig(
            trusted_networks=tuple(dict.fromkeys(self.base.trusted_networks + _parse(self._get(NETWORKS_SETTING)))),
            trusted_proxies=tuple(dict.fromkeys(self.base.trusted_proxies + honoured)),
        )

    def describe(self) -> dict:
        config = self.current()
        _honoured, ignored = self._stored_proxies()
        return {"trusted_networks": [str(n) for n in config.trusted_networks],
                "trusted_proxies": [str(n) for n in config.trusted_proxies],
                "ignored_proxies": [str(n) for n in ignored],
                "gateway_warning": self.gateway_warning()}

    # -- gateway detection --------------------------------------------------------------------------

    def note_client(self, client_ip: str | None) -> None:
        if client_ip:
            self._clients[client_ip] += 1

    def gateway_warning(self) -> dict | None:
        if len(self._clients) != 1:
            return None
        address, count = next(iter(self._clients.items()))
        if count < self.GATEWAY_SAMPLE:
            return None
        return {"address": address, "message": GATEWAY_WARNING.format(address=address)}
