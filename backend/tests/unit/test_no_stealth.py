"""Ledger K1 / Master §12.1, §49: no anti-bot stealth, fingerprint spoofing or challenge solving."""
import importlib.util
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
# curl_cffi is the explicitly reviewed Noor ECH exception; its imports stay in net/ech.py.
FORBIDDEN_DISTRIBUTIONS = ["patchright", "browserforge", "camoufox", "undetected_chromedriver",
                           "playwright_stealth", "cloudscraper"]
FORBIDDEN_CODE = re.compile(
    r"StealthyFetcher|StealthySession|DynamicFetcher|DynamicSession|scrapling\.fetchers|solve_cloudflare|"
    r"hide_canvas|block_webrtc|google_search\s*=|stealth", re.IGNORECASE)


def test_stealth_packages_are_not_installed():
    assert [name for name in FORBIDDEN_DISTRIBUTIONS if importlib.util.find_spec(name) is not None] == []


def test_oneshelf_code_never_uses_scrapling_fetchers_or_stealth_features():
    offenders = []
    for directory in ("oneshelf", "testsource"):
        for path in (ROOT / directory).rglob("*.py"):
            for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
                if FORBIDDEN_CODE.search(line) and "no stealth" not in line.lower() and "never" not in line.lower():
                    offenders.append(f"{path.relative_to(ROOT)}:{number}: {line.strip()}")
    assert offenders == []


def test_scrapling_is_declared_without_fetchers_extra():
    pyproject = (ROOT / "pyproject.toml").read_text()
    assert re.search(r'"scrapling>=[^"\[]+"', pyproject) and "scrapling[" not in pyproject


def test_curl_is_confined_to_the_reviewed_core_ech_transport():
    import ast
    consumers = []
    for path in (ROOT / "oneshelf").rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            modules = ([node.module or ""] if isinstance(node, ast.ImportFrom) else
                       [alias.name for alias in node.names] if isinstance(node, ast.Import) else [])
            if any(name.split(".")[0] == "curl_cffi" for name in modules):
                consumers.append(path.relative_to(ROOT / "oneshelf").as_posix())
    assert set(consumers) == {"net/ech.py"}
