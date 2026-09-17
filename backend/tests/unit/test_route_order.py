"""Literal API paths must be registered before parameterized ones, or they are swallowed."""
import re

from oneshelf.api.app import AppConfig, create_app

PARAM = re.compile(r"\{[^}]+\}")


def routes():
    app = create_app(AppConfig.from_env({"ONESHELF_DATA_DIR": "/tmp/oneshelf-route-check"}))
    return [(r.path, sorted(r.methods)) for r in app.routes if hasattr(r, "methods")]


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
