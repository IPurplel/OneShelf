"""A fresh install knows where the official Registry is; an owner can still point it elsewhere or off.

The default lives in compose as `${VAR-default}` — without the colon — so an existing `.env` that never
mentioned the Registry picks it up, while `ONESHELF_REGISTRY_URL=` (set, empty) switches it off. Only
public keys are ever configured, and none ships until the owner's signing key exists.
"""
import re

from oneshelf.plugins.registry import CachedRegistry, parse_trusted_keys, registry_from_config

from .test_image_contains_bundled_sources import REPO

OFFICIAL_INDEX = "https://raw.githubusercontent.com/IPurplel/OneShelf/main/registry/index.json"


def compose():
    return (REPO / "deploy" / "compose.yaml").read_text(encoding="utf-8")


def env_example():
    return (REPO / ".env.example").read_text(encoding="utf-8")


def test_compose_defaults_to_the_official_registry_but_lets_an_empty_value_switch_it_off():
    assert f'ONESHELF_REGISTRY_URL: "${{ONESHELF_REGISTRY_URL-{OFFICIAL_INDEX}}}"' in compose()


def test_compose_passes_trusted_public_keys_through_and_ships_none():
    assert 'ONESHELF_REGISTRY_TRUSTED_KEYS: "${ONESHELF_REGISTRY_TRUSTED_KEYS-}"' in compose()


def test_env_example_names_the_official_registry_and_no_key():
    text = env_example()
    assert f"ONESHELF_REGISTRY_URL={OFFICIAL_INDEX}" in text.splitlines()
    assert "ONESHELF_REGISTRY_TRUSTED_KEYS=" in text.splitlines()
    assert "SIGNING_KEY" not in re.sub(r"(?m)^#.*$", "", text)       # a signing key is never configured here


def test_the_default_is_the_committed_index_over_https():
    assert (REPO / "registry" / "index.json").is_file()
    registry = registry_from_config(OFFICIAL_INDEX)                  # constructs only; nothing is contacted
    assert isinstance(registry, CachedRegistry) and registry.location == OFFICIAL_INDEX


def test_the_shipped_trusted_keys_value_parses():
    value = next(line.split("=", 1)[1] for line in env_example().splitlines()
                 if line.startswith("ONESHELF_REGISTRY_TRUSTED_KEYS="))
    assert parse_trusted_keys(value) == {}
