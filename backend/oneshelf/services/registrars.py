"""All commit-journal registrars known to this build (replayed during recovery)."""
from oneshelf.importer import service as importer


def all_registrars() -> dict:
    return {**importer.registrars()}
