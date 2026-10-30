"""Container start: keep old updaters from concealing pre-release plugin/backup directories, read the
historical default Registry URL as the current one, and trust the bundled LAN proxy for itself."""
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


def trust_lan_proxy(environ) -> None:
    """The bundled LAN proxy connects from its own loopback address; only it may name the real visitor.

    It is added to whatever proxies the owner configured, never in place of them. Requests made on this
    machine directly (the healthcheck, a browser on the server) still come from 127.0.0.1 and keep their trust.
    """
    address = environ.get("ONESHELF_LAN_PROXY_ADDRESS", "").strip()
    if not address:
        return
    network = f"{address}/32"
    proxies = [part.strip() for part in environ.get("ONESHELF_TRUSTED_PROXIES", "").split(",") if part.strip()]
    if network not in proxies:
        environ["ONESHELF_TRUSTED_PROXIES"] = ",".join([*proxies, network])


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
    trust_lan_proxy(os.environ)
    os.execvp("python", ["python", "-m", "oneshelf.api.app"])
