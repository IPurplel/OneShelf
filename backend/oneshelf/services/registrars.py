"""All commit-journal registrars known to this build (replayed during recovery)."""
from oneshelf.downloads import engine as downloads
from oneshelf.importer import service as importer


def all_registrars() -> dict:
    return {**importer.registrars(), **downloads.registrars()}
