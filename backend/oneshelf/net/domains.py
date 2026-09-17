"""Domain allowlist rules (Master §11). Rules are exact hostnames or a single leading wildcard label."""
from __future__ import annotations

import ipaddress
import re

_LABEL = re.compile(r"^(?!-)[a-z0-9-]{1,63}(?<!-)$")
_BLOCKED_SUFFIXES = ("localhost", "local", "lan", "internal", "intranet", "home", "corp", "private", "arpa", "onion", "invalid")


class DomainRuleError(ValueError):
    pass


def to_ascii_host(host: str) -> str:
    host = host.strip().rstrip(".").lower()
    try:
        return host.encode("idna").decode("ascii")
    except UnicodeError as exc:
        raise DomainRuleError(f"invalid hostname: {host!r}") from exc


def _is_ip_literal(value: str) -> bool:
    candidate = value.strip("[]")
    try:
        ipaddress.ip_address(candidate)
        return True
    except ValueError:
        return candidate.isdigit()


def normalize_rule(rule: str) -> str:
    """Validate and canonicalize a domain rule; raises DomainRuleError for anything unsafe or ambiguous."""
    if not isinstance(rule, str) or not rule or any(c in rule for c in "/:@[] \t\\?#"):
        raise DomainRuleError(f"domain rule must be a bare hostname: {rule!r}")
    wildcard = rule.startswith("*.")
    base = rule[2:] if wildcard else rule
    if "*" in base or _is_ip_literal(base):
        raise DomainRuleError(f"invalid domain rule: {rule!r}")
    ascii_base = to_ascii_host(base)
    labels = ascii_base.split(".")
    if len(labels) < 2 or any(not _LABEL.match(label) for label in labels) or len(ascii_base) > 253:
        raise DomainRuleError(f"invalid domain rule: {rule!r}")
    if labels[-1].isdigit() or labels[-1] in _BLOCKED_SUFFIXES or ascii_base.endswith(".home.arpa"):
        raise DomainRuleError(f"internal or reserved domain not allowed: {rule!r}")
    return f"*.{ascii_base}" if wildcard else ascii_base


def host_matches(host: str, rule: str) -> bool:
    try:
        host = to_ascii_host(host)
    except DomainRuleError:
        return False
    if rule.startswith("*."):
        return host.endswith(rule[1:]) and host != rule[2:]
    return host == rule


def host_allowed(host: str, rules: list[str] | tuple[str, ...]) -> bool:
    return any(host_matches(host, rule) for rule in rules)
