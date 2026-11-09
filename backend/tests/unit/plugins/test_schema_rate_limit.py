"""An adapter's declared request rate, and the burst it may declare for its site (plugin API 1.4)."""
import copy

import pytest

from oneshelf.plugins.package import PackageError, load_package
from tests.fixtures.osp import MANIFEST, SOURCE, build_osp


def package(tmp_path, *, api, rate_limit):
    manifest = {**copy.deepcopy(MANIFEST), "api": api}
    source = {**copy.deepcopy(SOURCE), "rate_limit": rate_limit}
    return load_package(build_osp(tmp_path / "p.osp", manifest=manifest, source=source))


def test_without_a_burst_a_source_keeps_a_full_gap_before_every_request(tmp_path):
    assert package(tmp_path, api="1.0", rate_limit={"requests_per_minute": 20}).source.rate_limit.burst == 1


def test_a_declared_burst_is_read_and_needs_api_14(tmp_path):
    limits = {"requests_per_minute": 20, "concurrency": 1, "burst": 4}
    assert package(tmp_path, api="1.4", rate_limit=limits).source.rate_limit.burst == 4
    with pytest.raises(PackageError, match="burst needs api '1.4'"):
        package(tmp_path, api="1.3", rate_limit=limits)


@pytest.mark.parametrize("burst", [0, 5])
def test_a_burst_is_bounded(tmp_path, burst):
    with pytest.raises(PackageError):
        package(tmp_path, api="1.4", rate_limit={"requests_per_minute": 20, "burst": burst})
