"""The 3asq package's own boundaries (Master §12.1, §41.4).

Its earlier domain (3asq.org) no longer resolves and the source moved to 3asq.online. What matters here
is that the move changed configuration and nothing else: the identity a Source Track is keyed on is the
plugin id, which carries no domain at all, and the egress policy is no looser than any other source's.
"""
import pathlib
import tempfile

import pytest

from oneshelf.net.policy import DisallowedTarget, EgressPolicy
from oneshelf.plugins.package import load_package
from plugins.build import build_package, official_packages


@pytest.fixture(scope="module")
def package():
    source = next(p for p in official_packages() if p.name == "oneshelf.3asq")
    return load_package(build_package(source, pathlib.Path(tempfile.mkdtemp()) / "3asq.osp"))


def test_the_source_id_carries_no_domain_so_a_move_never_forks_identity(package):
    """Source Tracks are keyed on this id; if it held a domain, 3asq.org and 3asq.online would be two
    different sources and every existing mapping would be orphaned by the move."""
    assert package.id == "oneshelf.3asq"
    assert "online" not in package.id and "org" not in package.id and "." not in package.id.split(".", 1)[1]


def test_the_canonical_domain_is_the_one_that_answers(package):
    assert package.source.base_url == "https://3asq.online"
    assert package.manifest.network.domains == ["3asq.online"]
    assert package.manifest.network.cdn_domains == []
    assert package.manifest.network.allow_http is False          # https only


def test_it_asks_for_one_permission_and_no_more(package):
    assert set(package.permissions) == {"network:domain:3asq.online"}
    assert package.manifest.auth is None                          # nothing here is behind a login
    assert package.manifest.browser.capabilities == []            # and nothing needs a browser


def policy_for(package):
    network = package.manifest.network
    return EgressPolicy(domains=tuple(network.domains), cdn_domains=tuple(network.cdn_domains),
                        allow_http=network.allow_http)


@pytest.mark.parametrize("url", [
    "http://3asq.online/manga/one-piece/",        # the old scheme is not allowed back in
    "https://3asq.org/manga/one-piece/",          # nor the old domain
    "https://evil.test/manga/one-piece/",
    "https://3asq.online.evil.test/",             # a suffix that only looks like the domain
    "https://127.0.0.1/",
    "https://192.168.1.10/",
    "file:///etc/passwd",
])
def test_the_policy_refuses_everything_that_is_not_this_source(package, url):
    with pytest.raises((DisallowedTarget, ValueError)):
        policy_for(package).check_url(url)


def test_the_policy_allows_the_source_itself(package):
    assert policy_for(package).check_url("https://3asq.online/manga/one-piece/") is not None
