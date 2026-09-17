"""Master §24.1, §24.5, §24.6, §24.8: storage roots, availability, disk guard, mount remap."""
import json

import pytest

from oneshelf.storage.roots import (
    GiB,
    RootError,
    SpaceState,
    check_availability,
    get_root,
    list_roots,
    preflight,
    register_root,
    remap_root,
    reserve_bytes,
    set_default_root,
    space_status,
)


def test_register_root_writes_marker_and_staging(db, tmp_path):
    path = tmp_path / "lib"
    path.mkdir()
    root = register_root(db, "Library", path)
    marker = json.loads((path / ".oneshelf" / "root.json").read_text())
    assert marker["root_id"] == root.id
    assert (path / ".oneshelf" / "staging").is_dir()
    assert root.is_default  # first root becomes default
    assert get_root(db, root.id).path == str(path)


def test_register_rejects_missing_nested_and_foreign_roots(db, tmp_path):
    with pytest.raises(RootError):
        register_root(db, "Missing", tmp_path / "nope")
    (tmp_path / "lib" / "inner").mkdir(parents=True)
    register_root(db, "Library", tmp_path / "lib")
    with pytest.raises(RootError):
        register_root(db, "Nested", tmp_path / "lib" / "inner")
    with pytest.raises(RootError):
        register_root(db, "Parent", tmp_path)
    with pytest.raises(RootError):
        register_root(db, "Again", tmp_path / "lib")


def test_single_default_root(db, tmp_path):
    for name in ("a", "b"):
        (tmp_path / name).mkdir()
    a = register_root(db, "A", tmp_path / "a")
    b = register_root(db, "B", tmp_path / "b")
    assert not b.is_default
    set_default_root(db, b.id)
    defaults = [r.id for r in list_roots(db) if r.is_default]
    assert defaults == [b.id]
    assert a.id != b.id


def test_available_root(db, tmp_path):
    (tmp_path / "lib").mkdir()
    root = register_root(db, "Library", tmp_path / "lib")
    status = check_availability(root)
    assert status.available and status.reason is None


def test_unmounted_root_is_unavailable_not_deleted(db, tmp_path):
    (tmp_path / "lib").mkdir()
    root = register_root(db, "Library", tmp_path / "lib")
    # An unmounted mount point typically shows up as an empty directory without our marker.
    (tmp_path / "lib" / ".oneshelf" / "root.json").unlink()
    status = check_availability(root)
    assert not status.available and status.reason == "marker_missing"


def test_missing_path_and_foreign_marker_are_unavailable(db, tmp_path):
    (tmp_path / "lib").mkdir()
    (tmp_path / "other").mkdir()
    root = register_root(db, "Library", tmp_path / "lib")
    other = register_root(db, "Other", tmp_path / "other")
    (tmp_path / "lib" / ".oneshelf" / "root.json").write_text(json.dumps({"root_id": other.id}))
    assert check_availability(root).reason == "marker_mismatch"
    (tmp_path / "lib" / ".oneshelf" / "root.json").unlink()
    (tmp_path / "lib" / ".oneshelf" / "staging").rmdir()
    (tmp_path / "lib" / ".oneshelf").rmdir()
    (tmp_path / "lib").rmdir()
    assert check_availability(root).reason == "path_missing"


def test_reserve_is_five_percent_capped_at_five_gib():
    assert reserve_bytes(total=10 * GiB) == int(0.5 * GiB)
    assert reserve_bytes(total=1000 * GiB) == 5 * GiB
    assert reserve_bytes(total=1000 * GiB, override=GiB) == GiB


def test_space_states():
    total = 20 * GiB  # reserve = 1 GiB, warning at 2 GiB
    assert space_status(total=total, free=10 * GiB).state is SpaceState.OK
    assert space_status(total=total, free=2 * GiB).state is SpaceState.LOW
    assert space_status(total=total, free=GiB).state is SpaceState.AT_RESERVE
    assert space_status(total=total, free=GiB // 2).state is SpaceState.AT_RESERVE


def test_preflight_keeps_reserve_free():
    total, free = 20 * GiB, 3 * GiB
    assert preflight(total=total, free=free, expected_bytes=GiB).allowed
    decision = preflight(total=total, free=free, expected_bytes=int(2.5 * GiB))
    assert not decision.allowed and decision.reason == "would_breach_reserve"


def test_remap_root_to_new_mount_path_without_copy(db, tmp_path):
    (tmp_path / "old").mkdir()
    root = register_root(db, "Library", tmp_path / "old")
    (tmp_path / "old").rename(tmp_path / "new")  # same data, new mount path
    remapped = remap_root(db, root.id, tmp_path / "new")
    assert remapped.path == str(tmp_path / "new")
    assert check_availability(remapped).available


def test_remap_refuses_path_that_is_not_this_root(db, tmp_path):
    (tmp_path / "old").mkdir()
    (tmp_path / "empty").mkdir()
    root = register_root(db, "Library", tmp_path / "old")
    with pytest.raises(RootError):
        remap_root(db, root.id, tmp_path / "empty")
    assert get_root(db, root.id).path == str(tmp_path / "old")
