"""Site adapters."""

from .base import Adapter, AdapterError
from .generic import GenericAdapter
from .madara import MadaraAdapter
from .registry import ADAPTERS, CONTENT_TYPES, describe, resolve, select

__all__ = [
    "Adapter",
    "AdapterError",
    "GenericAdapter",
    "MadaraAdapter",
    "ADAPTERS",
    "CONTENT_TYPES",
    "describe",
    "resolve",
    "select",
]
