"""Ledger K1 / Master §12.1, §49: no anti-bot stealth, fingerprint spoofing or challenge solving."""
import importlib.util
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
FORBIDDEN_DISTRIBUTIONS = ["patchright", "browserforge", "camoufox", "undetected_chromedriver",
                           "playwright_stealth", "cloudscraper"]
FORBIDDEN_CODE = re.compile(
    r"StealthyFetcher|StealthySession|DynamicFetcher|DynamicSession|scrapling\.fetchers|solve_cloudflare|"
    r"hide_canvas|block_webrtc|google_search\s*=|stealth", re.IGNORECASE)
# curl_cffi is allowed for one reason: its BoringSSL build can send Encrypted Client Hello, which Python's
# ssl module cannot. Its fingerprint-shaping options are what K1 forbids, so they may appear nowhere.
ECH_TRANSPORT = Path("oneshelf") / "net" / "curl_ech.py"
FINGERPRINT_OPTIONS = re.compile(r"impersonate|\bja3\b|akamai|extra_fp", re.IGNORECASE)


def _code_lines():
    for directory in ("oneshelf", "testsource"):
        for path in (ROOT / directory).rglob("*.py"):
            for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
                yield path.relative_to(ROOT), number, line


def test_stealth_packages_are_not_installed():
    assert [name for name in FORBIDDEN_DISTRIBUTIONS if importlib.util.find_spec(name) is not None] == []


def test_oneshelf_code_never_uses_scrapling_fetchers_or_stealth_features():
    offenders = [f"{path}:{number}: {line.strip()}" for path, number, line in _code_lines()
                 if FORBIDDEN_CODE.search(line) and "no stealth" not in line.lower() and "never" not in line.lower()]
    assert offenders == []


def test_curl_cffi_is_only_the_ech_transport():
    offenders = [f"{path}:{number}: {line.strip()}" for path, number, line in _code_lines()
                 if re.search(r"\bcurl_cffi\b", line) and re.match(r"\s*(from|import)\s", line)
                 and path != ECH_TRANSPORT]
    assert offenders == []


def test_no_code_shapes_a_tls_or_http_fingerprint():
    offenders = [f"{path}:{number}: {line.strip()}" for path, number, line in _code_lines()
                 if FINGERPRINT_OPTIONS.search(line)]
    assert offenders == []


def test_scrapling_is_declared_without_fetchers_extra():
    pyproject = (ROOT / "pyproject.toml").read_text()
    assert re.search(r'"scrapling>=[^"\[]+"', pyproject) and "scrapling[" not in pyproject
