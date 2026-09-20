"""§49 EX-01, EX-02: no OneShelf account, and no second user to keep anything apart from.

OneShelf is one person's library on their own machine. There is no sign-up, no tenant, and nothing in
the schema that would let one user's rows be hidden from another's — which is the point: a multi-user
model cannot be bolted on later without this failing first.
"""
import re

from .conftest import code_lines, frontend_sources, python_sources

ACCOUNT_ROUTE = re.compile(r"/(account|accounts|signup|sign-up|register-account|users|tenants?|organisations?|"
                           r"subscriptions?|billing)(/|$)")
# The remote-access session is this device's own; a *user* column would mean rows belong to someone.
# Declared in a CREATE TABLE or added later by an ALTER — both are the same claim about ownership.
OWNERSHIP_COLUMN = re.compile(r"(^\s*|ADD COLUMN\s+)(user_id|owner_id|account_id|tenant_id|member_id)\b",
                              re.MULTILINE | re.IGNORECASE)


def test_no_route_offers_an_account_or_another_user(routes):
    assert [path for path in routes if ACCOUNT_ROUTE.search(path)] == []


def test_the_schema_never_says_which_user_a_row_belongs_to(schema):
    assert OWNERSHIP_COLUMN.findall(schema) == []


def test_nothing_signs_in_to_a_oneshelf_service(routes):
    """Signing in is to a *source*, or to this machine with a passkey — never to OneShelf's own cloud."""
    remote = {path for path in routes if path.startswith("/api/auth/")}
    assert remote and all("passkey" in path or path.split("/")[-1] in
                          {"sign-in", "sign-out", "state", "sessions", "revoke-others", "networks", "hostname",
                           "lan-recovery", "regenerate", "options", "{session_id}", "{credential_id}"}
                          for path in remote)


def test_no_code_reaches_a_oneshelf_account_service():
    offenders = [f"{path.name}:{number}" for path, number, line in code_lines(python_sources() + frontend_sources())
                 if re.search(r"oneshelf\.(cloud|app|io)|api\.oneshelf|accounts?\.oneshelf", line, re.IGNORECASE)]
    assert offenders == []
