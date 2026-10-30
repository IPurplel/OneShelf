"""A fresh install can reach ECH sources (Noor Book) without editing .env; an owner can still choose another
resolver or none.

Like the Registry, the default lives in compose as `${VAR-default}` — without the colon — so an existing
`.env` that never mentioned it picks it up, while `ONESHELF_ECH_DOH_URL=` (set, empty) contacts no resolver.
The application itself carries no resolver host (INV-29).
"""
from .test_registry_defaults import compose, env_example
from .test_image_contains_bundled_sources import REPO

DEFAULT_DOH = "https://cloudflare-dns.com/dns-query"


def test_compose_defaults_to_cloudflare_doh_but_lets_an_empty_value_switch_it_off():
    assert f'ONESHELF_ECH_DOH_URL: "${{ONESHELF_ECH_DOH_URL-{DEFAULT_DOH}}}"' in compose()


def test_env_example_names_the_same_resolver():
    assert f"ONESHELF_ECH_DOH_URL={DEFAULT_DOH}" in env_example().splitlines()


def test_the_application_itself_carries_no_resolver_host():
    source = (REPO / "backend" / "oneshelf" / "net" / "curl_ech.py").read_text(encoding="utf-8")
    assert "cloudflare-dns.com" not in source and "dns.google" not in source
