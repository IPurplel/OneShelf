"""Master §28.6: session tokens live in HttpOnly cookies and never in Web Storage."""
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
WEB_SUFFIXES = {".js", ".jsx", ".ts", ".tsx", ".html", ".svelte", ".vue"}
SKIP = {"node_modules", ".venv", "dist", "build", ".git", "__pycache__"}

# Storing anything token-like in localStorage/sessionStorage, or reading the session cookie from script.
PATTERNS = [
    re.compile(r"(local|session)Storage\s*(\.\s*setItem\s*\(|\[)\s*[\"'`][^\"'`]*"
               r"(token|session|auth|credential)", re.IGNORECASE),
    re.compile(r"document\.cookie\s*=", re.IGNORECASE),
    re.compile(r"oneshelf_remote", re.IGNORECASE),
]


def web_files():
    """The repository's own files: local scratch folders (saved third-party pages, say) are not OneShelf code."""
    listed = subprocess.run(["git", "-C", str(ROOT), "ls-files", "-z"], capture_output=True, check=True).stdout
    for name in listed.decode("utf-8").split("\0"):
        path = ROOT / name
        if name and path.suffix.lower() in WEB_SUFFIXES and not SKIP & set(path.parts) and path.is_file():
            yield path


def violations(paths) -> list[str]:
    found = []
    for path in paths:
        text = path.read_text(encoding="utf-8", errors="ignore")
        for pattern in PATTERNS:
            if pattern.search(text):
                found.append(f"{path}: {pattern.pattern}")
    return found


def test_no_web_code_stores_session_tokens_outside_the_cookie():
    assert violations(web_files()) == []


def test_the_guard_detects_a_planted_violation(tmp_path):
    planted = tmp_path / "app.ts"
    planted.write_text("localStorage.setItem('oneshelf.authToken', token)\n")
    assert violations([planted])
