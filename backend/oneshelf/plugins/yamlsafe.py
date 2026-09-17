"""Restricted YAML loading for plugin packages: safe types only, no anchors/aliases, bounded size."""
from __future__ import annotations

from typing import Any

import yaml
from yaml.constructor import ConstructorError
from yaml.events import AliasEvent

MAX_DEPTH = 32
MAX_NODES = 50_000


class YamlError(ValueError):
    pass


class _RestrictedLoader(yaml.SafeLoader):
    def __init__(self, stream):
        super().__init__(stream)
        self._depth = 0
        self._nodes = 0

    def compose_node(self, parent, index):
        event = self.peek_event()
        if isinstance(event, AliasEvent) or getattr(event, "anchor", None):
            raise YamlError("YAML anchors/aliases are not allowed")
        self._nodes += 1
        if self._nodes > MAX_NODES:
            raise YamlError("YAML document too large")
        self._depth += 1
        if self._depth > MAX_DEPTH:
            raise YamlError("YAML nesting too deep")
        try:
            return super().compose_node(parent, index)
        finally:
            self._depth -= 1

    def construct_mapping(self, node, deep=False):
        keys = set()
        for key_node, _ in node.value:
            key = self.construct_object(key_node, deep=deep)
            if key in keys:
                raise YamlError(f"duplicate key {key!r}")
            keys.add(key)
        return super().construct_mapping(node, deep=deep)


def load_yaml(data: bytes | str) -> Any:
    try:
        return yaml.load(data, Loader=_RestrictedLoader)  # noqa: S506 - restricted SafeLoader subclass
    except YamlError:
        raise
    except (yaml.YAMLError, ConstructorError, ValueError, RecursionError) as exc:
        raise YamlError(f"invalid YAML: {exc}") from exc
