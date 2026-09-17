"""Master §28.1–28.2 / INV-30: LAN trust from the real connection; forwarded headers only via trusted proxies."""
import pytest

from oneshelf.api.access import AccessConfig, classify

LAN = AccessConfig.from_strings(trusted_networks="192.168.1.0/24,fd00::/8", trusted_proxies="")
PROXIED = AccessConfig.from_strings(trusted_networks="192.168.1.0/24", trusted_proxies="10.0.0.2/32")


def h(value):
    return {"x-forwarded-for": value}


def test_loopback_is_trusted_even_without_configuration():
    cfg = AccessConfig.from_strings(trusted_networks="", trusted_proxies="")
    assert classify("127.0.0.1", {}, cfg).kind == "loopback"
    assert classify("::1", {}, cfg).kind == "loopback"


def test_private_address_is_not_lan_unless_configured():
    cfg = AccessConfig.from_strings(trusted_networks="", trusted_proxies="")
    assert classify("192.168.1.20", {}, cfg).kind == "remote"


def test_configured_lan_is_trusted():
    assert classify("192.168.1.20", {}, LAN).kind == "lan"
    assert classify("fd00::5", {}, LAN).kind == "lan"
    assert classify("::ffff:192.168.1.20", {}, LAN).kind == "lan"


@pytest.mark.parametrize("peer", ["203.0.113.7", "8.8.8.8", "not-an-ip", None, "testclient"])
def test_remote_and_unparseable_peers_are_remote(peer):
    assert classify(peer, {}, LAN).kind == "remote"


def test_forged_forwarded_header_from_untrusted_peer_is_ignored():
    result = classify("203.0.113.7", h("127.0.0.1"), LAN)
    assert result.kind == "remote" and result.client_ip == "203.0.113.7"
    result = classify("203.0.113.7", {"x-real-ip": "192.168.1.5", "forwarded": "for=127.0.0.1"}, LAN)
    assert result.kind == "remote"


def test_trusted_proxy_forwarding_remote_client_stays_remote():
    result = classify("10.0.0.2", h("198.51.100.4"), PROXIED)
    assert result.kind == "remote" and result.client_ip == "198.51.100.4"


def test_trusted_proxy_forwarding_lan_client_is_lan():
    assert classify("10.0.0.2", h("192.168.1.30"), PROXIED).kind == "lan"


def test_client_prepended_spoof_through_trusted_proxy_is_ignored():
    # Attacker sends "X-Forwarded-For: 192.168.1.30"; the proxy appends the real client address.
    result = classify("10.0.0.2", h("192.168.1.30, 198.51.100.4"), PROXIED)
    assert result.kind == "remote" and result.client_ip == "198.51.100.4"


def test_trusted_proxy_without_forwarded_header_is_not_lan():
    assert classify("10.0.0.2", {}, PROXIED).kind == "remote"


def test_proxy_address_itself_does_not_grant_lan_trust():
    cfg = AccessConfig.from_strings(trusted_networks="10.0.0.0/8", trusted_proxies="10.0.0.2/32")
    assert classify("10.0.0.2", h("198.51.100.4"), cfg).kind == "remote"


def test_invalid_configuration_is_rejected():
    with pytest.raises(ValueError):
        AccessConfig.from_strings(trusted_networks="192.168.1.0/33", trusted_proxies="")
