"""The production image actually carries the official adapters, and knows where they are.

No container runtime exists where this suite runs, so the image cannot be built here. What can be
proved is everything the build is made of: which files Docker would send in the build context (with
the real `.dockerignore`, evaluated the way Docker evaluates it), where the Dockerfile puts them, and
what the image tells the application. The Fedora host gate then confirms it inside a real container
(docs/c9/verification.md §3a).
"""
import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
OFFICIAL = REPO / "backend" / "plugins" / "official"
EIGHT = ["oneshelf.3asq", "oneshelf.arxiv", "oneshelf.gutenberg", "oneshelf.hindawi", "oneshelf.mangadex",
         "oneshelf.standard-ebooks", "oneshelf.tapas", "oneshelf.webtoon"]


def _pattern_to_regex(pattern: str) -> re.Pattern:
    out, i = [], 0
    while i < len(pattern):
        if pattern.startswith("**/", i):
            out.append("(?:.*/)?"); i += 3
        elif pattern.startswith("**", i):
            out.append(".*"); i += 2
        elif pattern[i] == "*":
            out.append("[^/]*"); i += 1
        elif pattern[i] == "?":
            out.append("[^/]"); i += 1
        else:
            out.append(re.escape(pattern[i])); i += 1
    return re.compile("^" + "".join(out) + "$")


def dockerignore_rules():
    rules = []
    for raw in (REPO / ".dockerignore").read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        negate = line.startswith("!")
        pattern = line[1:] if negate else line
        pattern = pattern.strip("/")
        rules.append((negate, _pattern_to_regex(pattern)))
    return rules


def excluded(relpath: str, rules) -> bool:
    """Docker's rule: the last pattern that matches the path, or any directory above it, decides."""
    parts = relpath.split("/")
    candidates = ["/".join(parts[:n]) for n in range(1, len(parts) + 1)]
    verdict = False
    for negate, regex in rules:
        if any(regex.match(c) for c in candidates):
            verdict = not negate
    return verdict


def test_the_matcher_agrees_with_docker_on_the_cases_that_matter():
    """A matcher that is wrong in the safe direction would prove nothing, so it is checked first."""
    rules = [(False, _pattern_to_regex("backend/tests")), (False, _pattern_to_regex("**/*.db")),
             (False, _pattern_to_regex(".env.*")), (True, _pattern_to_regex(".env.example"))]
    assert excluded("backend/tests/unit/test_x.py", rules)            # a directory excludes its contents
    assert not excluded("backend/plugins/official/x/tests/tests.yaml", rules)   # not another tests/
    assert excluded("deep/down/library.db", rules)
    assert excluded(".env.local", rules) and not excluded(".env.example", rules)


def test_every_official_adapter_file_is_sent_to_the_build():
    rules = dockerignore_rules()
    files = [p.relative_to(REPO).as_posix() for p in OFFICIAL.rglob("*") if p.is_file()]
    assert files, "no official adapter files found at all"
    dropped = [f for f in files if excluded(f, rules)]
    assert dropped == [], f"the build context would silently drop: {dropped[:5]}"
    for plugin in EIGHT:
        assert any(f.startswith(f"backend/plugins/official/{plugin}/manifest.yaml") for f in files)


def test_the_dockerfile_puts_them_where_the_image_says_they_are():
    dockerfile = (REPO / "deploy" / "Dockerfile").read_text(encoding="utf-8")
    assert re.search(r"^COPY backend/ /app/$", dockerfile, re.MULTILINE), "backend/ is no longer copied to /app/"
    env = re.search(r"ONESHELF_BUNDLED_PLUGINS_DIR=(\S+)", dockerfile)
    assert env is not None, "the image does not tell the application where its bundled adapters are"
    assert env.group(1) == "/app/plugins/official"          # = backend/plugins/official under COPY backend/ /app/


def test_compose_does_not_switch_the_bootstrap_off():
    compose = (REPO / "deploy" / "compose.yaml").read_text(encoding="utf-8")
    assert "ONESHELF_BUNDLED_PLUGINS_DIR" not in compose, \
        "compose overrides the image's bundled directory; a fresh install would come up with no sources"


def test_the_builder_the_image_uses_is_part_of_the_installed_package():
    """The image installs `oneshelf` with pip; a builder living outside it would not exist at runtime."""
    pyproject = (REPO / "backend" / "pyproject.toml").read_text(encoding="utf-8")
    assert 'include = ["oneshelf*"]' in pyproject
    assert (REPO / "backend" / "oneshelf" / "plugins" / "bundled.py").is_file()
    app = (REPO / "backend" / "oneshelf" / "api" / "app.py").read_text(encoding="utf-8")
    assert "from oneshelf.plugins.bundled import sync_bundled" in app
    assert "import plugins.build" not in app and "from plugins" not in app
