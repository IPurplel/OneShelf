"""Even a pre-release updater must not start an image over concealed legacy storage."""
import importlib.util
from pathlib import Path

import pytest


@pytest.mark.parametrize("name", ["plugins", "backups"])
def test_startup_refuses_hidden_legacy_files_and_preserves_them(tmp_path, name):
    path = Path(__file__).resolve().parents[3] / "deploy/container_start.py"
    spec = importlib.util.spec_from_file_location("container_start", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    legacy = tmp_path / name
    legacy.mkdir()
    sentinel = legacy / "keep"
    sentinel.write_bytes(b"legacy data")
    with pytest.raises(RuntimeError, match="legacy"):
        module.check_legacy_storage(tmp_path)
    assert sentinel.read_bytes() == b"legacy data"


def test_startup_accepts_empty_legacy_mountpoints(tmp_path):
    path = Path(__file__).resolve().parents[3] / "deploy/container_start.py"
    spec = importlib.util.spec_from_file_location("container_start", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    (tmp_path / "plugins").mkdir()
    (tmp_path / "backups").mkdir()
    module.check_legacy_storage(tmp_path)
