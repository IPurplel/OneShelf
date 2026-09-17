"""Ordered schema migrations shipped with this build (files named NNNN_name.sql)."""
from importlib import resources

from oneshelf.db.migrate import Migration


def _load() -> tuple[Migration, ...]:
    files = sorted(
        (f for f in resources.files(__package__).iterdir() if f.name.endswith(".sql")),
        key=lambda f: f.name,
    )
    migrations = []
    for f in files:
        version, _, name = f.name.removesuffix(".sql").partition("_")
        migrations.append(Migration(int(version), name, f.read_text(encoding="utf-8")))
    return tuple(migrations)


MIGRATIONS = _load()
