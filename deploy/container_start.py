"""Keep old updaters from concealing pre-release plugin/backup directories."""
import os
from pathlib import Path
import sys


def check_legacy_storage(root: Path) -> None:
    for name in ("plugins", "backups"):
        directory = root / name
        if directory.exists() and (not directory.is_dir() or any(directory.iterdir())):
            raise RuntimeError("legacy plugins/backups would be hidden; see README: Legacy deployment storage")


if __name__ == "__main__":
    try:
        if legacy_root := os.environ.get("ONESHELF_LEGACY_DATA_DIR"):
            check_legacy_storage(Path(legacy_root))
    except (OSError, RuntimeError):
        sys.exit("Cannot start safely: check legacy deployment storage and permissions; see README.")
    os.execvp("python", ["python", "-m", "oneshelf.api.app"])
