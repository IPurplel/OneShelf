"""Shared ground for the §49 guards: the shipped code, its routes, and its dependencies."""
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parents[3]
REPO = BACKEND.parent
FRONTEND = REPO / "frontend" / "src"


def python_sources() -> list[Path]:
    """Only what ships. The Test Source is a controlled fake and the tests are not the product."""
    return sorted((BACKEND / "oneshelf").rglob("*.py"))


def frontend_sources() -> list[Path]:
    return sorted(p for p in FRONTEND.rglob("*") if p.suffix in {".ts", ".tsx"} and not p.name.endswith(".test.tsx")
                  and not p.name.endswith(".test.ts"))


def code_lines(paths):
    """Source lines with their comments stripped, so a guard cannot be satisfied — or tripped — by prose."""
    for path in paths:
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            bare = line.split("#", 1)[0] if path.suffix == ".py" else line.split("//", 1)[0]
            if "/*" in bare:
                bare = bare.split("/*", 1)[0]
            if bare.strip():
                yield path, number, bare


@pytest.fixture(scope="session")
def routes(tmp_path_factory) -> set[str]:
    from oneshelf.api.app import AppConfig, create_app

    tmp = tmp_path_factory.mktemp("exclusion-guards")
    app = create_app(AppConfig.from_env({"ONESHELF_DATA_DIR": str(tmp),
                                         "ONESHELF_SESSION_KEY_FILE": str(tmp / "session.key")}))
    found: set[str] = set()

    def walk(items):
        for item in items:
            path = getattr(item, "path", None)
            if path:
                found.add(path)
            inner = getattr(item, "original_router", None)
            if inner is not None:
                walk(inner.routes)

    walk(app.routes)
    assert len(found) > 60, "the route walk found almost nothing, so it is proving nothing (I-14)"
    return found


@pytest.fixture(scope="session")
def schema() -> str:
    return "\n".join(p.read_text(encoding="utf-8") for p in sorted((BACKEND / "oneshelf" / "db" / "schema")
                                                                   .glob("*.sql")))
