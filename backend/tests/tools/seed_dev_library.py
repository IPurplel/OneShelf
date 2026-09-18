"""Seed a development library so the UI can be looked at and screenshotted.

Development only. The titles are OneShelf's own test fixtures, not invented "sample books" shown to a
real user: the product itself never fabricates content (Master §32.3, C2 gate).

    .venv/bin/python -m tests.tools.seed_dev_library http://127.0.0.1:8420
"""
from __future__ import annotations

import json
import sys
import tempfile
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from tests.fixtures.builders import make_cbz, make_pdf  # noqa: E402

WORKS = [
    ("The Irregular Chronicle", "manga", "en", 0.72),
    ("A Very Long Saga", "manhwa", "en", 0.48),
    ("حكاية القمر", "manga", "ar", 0.63),
    ("Paged Archive", "comic", "en", 0.41),
    ("The Manual", "book", "en", None),
    ("Broken Media", "manga", "en", None),
]


def call(base: str, path: str, *, data: bytes | None = None, json_body: dict | None = None, method: str = "GET"):
    body, headers = None, {}
    if json_body is not None:
        body, headers = json.dumps(json_body).encode(), {"Content-Type": "application/json"}
        method = "POST"
    elif data is not None:
        body, headers = data, {"Content-Type": "application/octet-stream"}
        method = "POST"
    request = urllib.request.Request(f"{base}{path}", data=body, headers=headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return json.loads(response.read() or b"null")
    except urllib.error.HTTPError as error:
        print(f"  ! {path}: HTTP {error.code} {error.read()[:200]!r}")
        raise


def main() -> None:
    base = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8420"
    library = Path(tempfile.mkdtemp(prefix="oneshelf-dev-library-"))
    print(f"storage root: {library}")
    call(base, "/api/storage/roots", json_body={"name": "Library", "path": str(library)})

    staging = Path(tempfile.mkdtemp(prefix="oneshelf-dev-import-"))
    for title, content_type, language, fraction in WORKS:
        source = (make_pdf(staging / f"{abs(hash(title))}.pdf", pages=3) if content_type == "book"
                  else make_cbz(staging / f"{abs(hash(title))}.cbz"))
        review = call(base, f"/api/import/uploads?filename={source.name}", data=source.read_bytes())
        imported = call(base, "/api/import", json_body={
            "upload_id": review["upload_id"], "title": title, "content_type": content_type, "language": language,
            "unit_label": "Chapter 1",
        })
        if fraction is not None:
            call(base, f"/api/reader/units/{imported['reading_unit_id']}/progress",
                 json_body={"fraction": fraction, "revision": 0, "locator": {"page": 1}})
        print(f"  seeded {title} ({content_type})")

    home = call(base, "/api/home")
    print(f"home: hero={bool(home['hero'])} continue={len(home['continue_reading'])} "
          f"recent={len(home['recently_added'])}")


if __name__ == "__main__":
    main()
