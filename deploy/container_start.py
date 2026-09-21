"""Container start: keep old updaters from concealing pre-release plugin/backup directories, and read the
historical default Registry URL as the current one."""
import os
from pathlib import Path
import sys

# .env.example shipped this default before the Source Registry moved to OneShelf-Adapters, and update.sh
# never rewrites an owner's .env. This exact value — nothing merely like it — is read as the new default,
# for this process only. The application itself carries no Registry host (INV-29); deployment does.
LEGACY_REGISTRY_URL = "https://raw.githubusercontent.com/IPurplel/OneShelf/main/registry/index.json"
REGISTRY_URL = "https://raw.githubusercontent.com/IPurplel/OneShelf-Adapters/registry/index.json"


def alias_registry_url(environ) -> None:
    if environ.get("ONESHELF_REGISTRY_URL") == LEGACY_REGISTRY_URL:
        environ["ONESHELF_REGISTRY_URL"] = REGISTRY_URL


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
    alias_registry_url(os.environ)
    os.execvp("python", ["python", "-m", "oneshelf.api.app"])
