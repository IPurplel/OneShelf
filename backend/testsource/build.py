"""Build the Test Source .osp from testsource/package (deterministic ordering and timestamps)."""
from __future__ import annotations

import zipfile
from pathlib import Path

import yaml

PACKAGE_DIR = Path(__file__).parent / "package"
# The same source as a text source (plugin API 1.2): these files replace the package's own.
TEXT_OVERLAY_DIR = Path(__file__).parent / "text_overlay"
# Browse feeds for Discover (`latest`, `trending`): their recipes and fixture are added, and the manifest and
# packaged tests are extended rather than copied, so the base package stays the one source of truth.
DISCOVER_OVERLAY_DIR = Path(__file__).parent / "discover_overlay"
DISCOVER_CAPABILITIES = ("latest", "trending")
DISCOVER_SORTS = {"latest": "latest", "trending": "popular"}


def _files(directory: Path) -> dict[str, bytes]:
    return {p.relative_to(directory).as_posix(): p.read_bytes() for p in directory.rglob("*") if p.is_file()}


def _with_discover(files: dict[str, bytes]) -> dict[str, bytes]:
    manifest = yaml.safe_load(files["manifest.yaml"])
    manifest["capabilities"] = [*manifest["capabilities"], *DISCOVER_CAPABILITIES]
    tests = yaml.safe_load(files["tests/tests.yaml"])
    for capability in DISCOVER_CAPABILITIES:
        tests["cases"].append({
            "capability": capability, "inputs": {"page": 1},
            "fixtures": [{"url": f"http://testsource.example/browse?sort={DISCOVER_SORTS[capability]}&page=1",
                          "file": "fixtures/browse.html"}],
            "expect": {"min_items": 2, "fields_present": ["listing_key", "title"],
                       "first": {"listing_key": "irregular"}},
        })
    return files | _files(DISCOVER_OVERLAY_DIR) | {
        "manifest.yaml": yaml.safe_dump(manifest, sort_keys=False, allow_unicode=True).encode(),
        "tests/tests.yaml": yaml.safe_dump(tests, sort_keys=False, allow_unicode=True).encode(),
    }


def build_package(destination: str | Path, *, text: bool = False, discover: bool = False) -> Path:
    destination = Path(destination)
    files = _files(PACKAGE_DIR) | (_files(TEXT_OVERLAY_DIR) if text else {})
    if discover:
        files = _with_discover(files)
    with zipfile.ZipFile(destination, "w", compression=zipfile.ZIP_DEFLATED) as z:
        for name in sorted(files):
            info = zipfile.ZipInfo(name, date_time=(2026, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            z.writestr(info, files[name])
    return destination
