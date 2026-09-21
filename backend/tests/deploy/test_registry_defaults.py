"""A fresh install knows where the official Registry is; an owner can still point it elsewhere or off.

The default lives in compose as `${VAR-default}` — without the colon — so an existing `.env` that never
mentioned the Registry picks it up, while `ONESHELF_REGISTRY_URL=` (set, empty) switches it off. Only
public keys are ever configured, and none ships until the owner's signing key exists.
"""
import re

import importlib.util

import pytest

from oneshelf.plugins.registry import CachedRegistry, parse_trusted_keys, registry_from_config

from .test_image_contains_bundled_sources import REPO

OFFICIAL_INDEX = "https://raw.githubusercontent.com/IPurplel/OneShelf-Adapters/registry/index.json"
LEGACY_INDEX = "https://raw.githubusercontent.com/IPurplel/OneShelf/main/registry/index.json"


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


def container_start():
    spec = importlib.util.spec_from_file_location("container_start", REPO / "deploy" / "container_start.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_the_default_is_the_oneshelf_adapters_registry_over_https():
    assert container_start().REGISTRY_URL == OFFICIAL_INDEX
    registry = registry_from_config(OFFICIAL_INDEX)                  # constructs only; nothing is contacted
    assert isinstance(registry, CachedRegistry) and registry.location == OFFICIAL_INDEX


def test_the_exact_historical_default_is_read_as_the_new_registry_at_container_start():
    """Existing .env files carry the old default, and update.sh never rewrites .env."""
    environ = {"ONESHELF_REGISTRY_URL": LEGACY_INDEX}
    container_start().alias_registry_url(environ)
    assert environ == {"ONESHELF_REGISTRY_URL": OFFICIAL_INDEX}


@pytest.mark.parametrize("url", [
    LEGACY_INDEX + "?v=1", LEGACY_INDEX + " ", LEGACY_INDEX.replace("/main/", "/release/"),
    LEGACY_INDEX.replace("IPurplel", "someone-else"), LEGACY_INDEX.replace("index.json", "other.json"),
    "https://registry.example.org/oneshelf/index.json", "",
])
def test_any_other_registry_setting_is_left_exactly_as_configured(url):
    environ = {"ONESHELF_REGISTRY_URL": url}
    container_start().alias_registry_url(environ)
    assert environ == {"ONESHELF_REGISTRY_URL": url}


def test_an_unset_registry_setting_stays_unset():
    environ = {}
    container_start().alias_registry_url(environ)
    assert environ == {}


def test_an_empty_registry_url_still_switches_the_registry_off():
    assert registry_from_config("") is None and registry_from_config(None) is None


def test_the_application_itself_carries_no_registry_host():
    source = (REPO / "backend" / "oneshelf" / "plugins" / "registry.py").read_text(encoding="utf-8")
    assert "https://raw.githubusercontent.com" not in source


def test_the_shipped_trusted_keys_value_parses():
    value = next(line.split("=", 1)[1] for line in env_example().splitlines()
                 if line.startswith("ONESHELF_REGISTRY_TRUSTED_KEYS="))
    assert parse_trusted_keys(value) == {}
