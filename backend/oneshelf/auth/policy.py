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
        if not (network.is_private or network.is_link_local or network.is_loopback):
            raise PolicyError(f"{network} is a public range; a trusted LAN must be a private network")


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
            self.conn.execute(
                "INSERT INTO settings (scope, scope_id, key, value_json, updated_at) VALUES ('global','',?,?,?)"
                " ON CONFLICT(scope, scope_id, key) DO UPDATE SET value_json = excluded.value_json,"
                " updated_at = excluded.updated_at", (key, json.dumps(values), utcnow_iso()))

    def set_trusted_networks(self, values: list[str]) -> tuple[IPNetwork, ...]:
        networks = _parse(values)
        _require_private(networks)
        self._set(NETWORKS_SETTING, [str(n) for n in networks])
        return networks

    def set_trusted_proxies(self, values: list[str]) -> tuple[IPNetwork, ...]:
        proxies = _parse(values)
        self._set(PROXIES_SETTING, [str(n) for n in proxies])
        return proxies

    def current(self) -> AccessConfig:
        return AccessConfig(
            trusted_networks=tuple(dict.fromkeys(self.base.trusted_networks + _parse(self._get(NETWORKS_SETTING)))),
            trusted_proxies=tuple(dict.fromkeys(self.base.trusted_proxies + _parse(self._get(PROXIES_SETTING)))),
        )

    def describe(self) -> dict:
        config = self.current()
        return {"trusted_networks": [str(n) for n in config.trusted_networks],
                "trusted_proxies": [str(n) for n in config.trusted_proxies],
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
