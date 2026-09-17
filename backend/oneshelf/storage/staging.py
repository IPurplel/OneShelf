"""Per-root staging areas: <root>/.oneshelf/staging/<area-id>/ on the destination filesystem (Master §24.3)."""
from __future__ import annotations

import json
import os
from pathlib import Path

from oneshelf.domain.clock import utcnow_iso
from oneshelf.domain.ids import new_id
from oneshelf.storage.roots import META_DIR, STAGING, StorageRoot, check_availability, staging_dir

STAGING_PREFIX = f"{META_DIR}/{STAGING}/"
AREA_META = "staging.json"


class StagingError(RuntimeError):
    pass


def new_staging_area(
    root: StorageRoot, *, purpose: str, owner_id: str, resumable: bool = False
) -> tuple[Path, str]:
    availability = check_availability(root)
    if not availability.available:
        raise StagingError(f"storage location unavailable ({availability.reason})")
    area_id = new_id()
    area = staging_dir(root.path) / area_id
    area.mkdir(parents=True)
    if os.stat(area).st_dev != os.stat(root.path).st_dev:
        area.rmdir()
        raise StagingError("staging must be on the same filesystem as its storage root")
    (area / AREA_META).write_text(
        json.dumps({"purpose": purpose, "owner_id": owner_id, "resumable": resumable, "created_at": utcnow_iso()}),
        encoding="utf-8",
    )
    return area, f"{STAGING_PREFIX}{area_id}"


def read_area_meta(area: Path) -> dict | None:
    try:
        return json.loads((area / AREA_META).read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return None
