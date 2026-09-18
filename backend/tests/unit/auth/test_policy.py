"""Master §28.1–28.2 and ledger A2: trusted networks come from configuration, never from headers."""
import pytest

from oneshelf.api.access import AccessConfig, classify
from oneshelf.auth.policy import AccessPolicy, PolicyError


@pytest.fixture
def policy(db):
    return AccessPolicy(db, base=AccessConfig.from_strings(trusted_networks="", trusted_proxies=""))


def test_only_loopback_is_trusted_before_first_run(policy):
    config = policy.current()
    assert config.trusted_networks == () and config.trusted_proxies == ()
    assert classify("127.0.0.1", {}, config).kind == "loopback"
    assert classify("192.168.1.50", {}, config).kind == "remote"


def test_configured_private_networks_become_lan(db, policy):
    policy.set_trusted_networks(["192.168.1.0/24", "10.0.0.0/8"])
    assert classify("192.168.1.50", {}, policy.current()).kind == "lan"
    assert classify("10.4.4.4", {}, policy.current()).kind == "lan"
    assert classify("203.0.113.7", {}, policy.current()).kind == "remote"
    assert AccessPolicy(db, base=AccessConfig()).current().trusted_networks     # survives a restart


def test_public_ranges_are_refused_as_a_trusted_lan(policy):
    with pytest.raises(PolicyError):
        policy.set_trusted_networks(["0.0.0.0/0"])
    with pytest.raises(PolicyError):
        policy.set_trusted_networks(["8.8.8.0/24"])
    with pytest.raises(PolicyError):
        policy.set_trusted_networks(["not-a-network"])
    assert policy.current().trusted_networks == ()


def test_environment_networks_are_kept_alongside_configured_ones(db):
    policy = AccessPolicy(db, base=AccessConfig.from_strings(trusted_networks="172.18.0.0/16", trusted_proxies=""))
    policy.set_trusted_networks(["192.168.1.0/24"])
    kinds = {str(n) for n in policy.current().trusted_networks}
    assert kinds == {"172.18.0.0/16", "192.168.1.0/24"}


def test_trusted_proxies_are_explicit_and_forwarded_headers_need_them(policy):
    headers = {"x-forwarded-for": "192.168.1.50"}
    policy.set_trusted_networks(["192.168.1.0/24"])
    assert classify("10.9.9.9", headers, policy.current()).kind == "remote"   # not a configured proxy: ignored
    policy.set_trusted_proxies(["10.9.9.9/32"])
    assert classify("10.9.9.9", headers, policy.current()).kind == "lan"


def test_warns_when_every_client_arrives_from_one_gateway_address(policy):
    policy.set_trusted_networks(["192.168.1.0/24"])
    assert policy.gateway_warning() is None
    for _ in range(policy.GATEWAY_SAMPLE):
        policy.note_client("192.168.1.1")
    warning = policy.gateway_warning()
    assert warning["address"] == "192.168.1.1" and "one address" in warning["message"].lower()

    policy.note_client("192.168.1.77")
    assert policy.gateway_warning() is None      # genuinely different devices: no warning
