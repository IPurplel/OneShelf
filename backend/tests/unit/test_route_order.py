"""Literal API paths must be registered before parameterized ones, or they are swallowed."""
import re

from oneshelf.api.app import AppConfig, create_app

PARAM = re.compile(r"\{[^}]+\}")


def routes():
    """Every route the application really serves.

    Included routers are nested objects here, not flattened into `app.routes`, so a filter of
    `hasattr(r, "methods")` sees three routes out of a hundred and this guard passes while covering
    almost nothing (I-14). Walk the tree instead.
    """
    app = create_app(AppConfig.from_env({"ONESHELF_DATA_DIR": "/tmp/oneshelf-route-check"}))
    found: list[tuple[str, list[str]]] = []

    def walk(entries) -> None:
        for entry in entries:
            if getattr(entry, "methods", None) and getattr(entry, "path", None):
                found.append((entry.path, sorted(entry.methods)))
            # An included router is a wrapper here; its real routes hang off `original_router`.
            original = getattr(entry, "original_router", None)
            nested = getattr(original, "routes", None) if original is not None else getattr(entry, "routes", None)
            if nested:
                walk(nested)

    walk(app.routes)
    return found


def test_the_guard_sees_the_whole_api_not_a_handful_of_routes():
    """The blind spot this guard had once: if it only sees a few routes, it proves nothing (I-14)."""
    paths = {path for path, _ in routes()}
    assert len(paths) > 60, f"only {len(paths)} routes visible — the walk is missing routers again"
    assert "/api/downloads/{batch_id}" in paths and "/api/works/{work_id}" in paths


def test_no_literal_route_is_shadowed_by_an_earlier_parameterized_route():
    seen: list[tuple[str, list[str]]] = []
    shadowed = []
    for path, methods in routes():
        literal_segments = path.strip("/").split("/")
        for earlier, earlier_methods in seen:
            earlier_segments = earlier.strip("/").split("/")
            if len(earlier_segments) != len(literal_segments) or not set(methods) & set(earlier_methods):
                continue
            matches = all(PARAM.fullmatch(e) or e == l for e, l in zip(earlier_segments, literal_segments))
            if matches and any(PARAM.fullmatch(e) and not PARAM.fullmatch(l)
                               for e, l in zip(earlier_segments, literal_segments)):
                shadowed.append(f"{methods} {path} is shadowed by {earlier_methods} {earlier}")
        seen.append((path, methods))
    assert shadowed == []
