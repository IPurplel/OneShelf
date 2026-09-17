"""Minimal, bounded JSON path subset: $ . .name ['name'] [n] [*]  (no recursion, no filters)."""
from __future__ import annotations

import re
from typing import Any

MAX_LENGTH = 256
_TOKEN = re.compile(r"""\.(?P<name>[^\W\d][\w-]*)|\[(?:(?P<index>-?\d+)|(?P<star>\*)|'(?P<sq>[^']*)'|"(?P<dq>[^"]*)")\]""")
_WILDCARD = object()


class JsonPathError(ValueError):
    pass


def parse(path: str) -> list:
    if not isinstance(path, str) or len(path) > MAX_LENGTH or not path.startswith("$"):
        raise JsonPathError(f"invalid json path: {path!r}")
    steps, pos = [], 1
    while pos < len(path):
        match = _TOKEN.match(path, pos)
        if not match:
            raise JsonPathError(f"unsupported json path syntax at {pos}: {path!r}")
        if match.group("name") is not None:
            steps.append(match.group("name"))
        elif match.group("index") is not None:
            steps.append(int(match.group("index")))
        elif match.group("star"):
            steps.append(_WILDCARD)
        else:
            steps.append(match.group("sq") if match.group("sq") is not None else match.group("dq"))
        pos = match.end()
    return steps


def evaluate(path: str | list, document: Any) -> list:
    steps = parse(path) if isinstance(path, str) else path
    current = [document]
    for step in steps:
        nxt = []
        for node in current:
            if step is _WILDCARD:
                if isinstance(node, list):
                    nxt.extend(node)
                elif isinstance(node, dict):
                    nxt.extend(node.values())
            elif isinstance(step, int):
                if isinstance(node, list) and -len(node) <= step < len(node):
                    nxt.append(node[step])
            elif isinstance(node, dict) and step in node:
                nxt.append(node[step])
        current = nxt
    return current
