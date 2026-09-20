"""§49 EX-24, EX-26, EX-27: nothing is solved, stripped or photographed.

A challenge is reported to the person, who decides (§12.1). Protected content stays protected: there is
no decryption of anyone's DRM. And extraction is the declared contract — never a picture of a rendered
page, which is what a source's terms and a reader's eyes both deserve better than.
"""
import importlib.util
import re

from .conftest import BACKEND, code_lines, python_sources

SOLVER_PACKAGES = ["twocaptcha", "python_anticaptcha", "capsolver", "anticaptchaofficial", "deathbycaptcha",
                   "capmonster", "pydub", "speech_recognition"]
SOLVING = re.compile(r"solve_captcha|solve_cloudflare|captcha_solver|recaptcha_token|hcaptcha_token|"
                     r"bypass_(captcha|paywall|drm|challenge)|anti_?captcha", re.IGNORECASE)
DRM = re.compile(r"\b(drm|widevine|adept|adobe_key|decrypt_book|remove_drm|dedrm|lcp_key)\b", re.IGNORECASE)
SCREENSHOT = re.compile(r"\.screenshot\s*\(|screencast|capture_screenshot|element_screenshot|"
                        r"page\.pdf\s*\(", re.IGNORECASE)


def test_no_captcha_solving_toolkit_is_installed():
    assert [n for n in SOLVER_PACKAGES if importlib.util.find_spec(n) is not None] == []


def test_nothing_tries_to_solve_or_bypass_a_challenge():
    offenders = [f"{path.name}:{number}: {line.strip()}"
                 for path, number, line in code_lines(python_sources()) if SOLVING.search(line)]
    assert offenders == []


def test_nothing_touches_drm():
    offenders = [f"{path.name}:{number}: {line.strip()}"
                 for path, number, line in code_lines(python_sources()) if DRM.search(line)]
    assert offenders == []


def test_a_blocked_source_is_reported_rather_than_worked_around():
    """The excluded thing is solving it; what replaces it is saying so, which has to exist (§12.1, §44)."""
    runtime = (BACKEND / "oneshelf" / "plugins" / "runtime.py").read_text(encoding="utf-8")
    assert '_PageFailure("blocked"' in runtime and "class AuthRequired" in runtime


def extraction_sources():
    """Everything that fetches or stores content. Use My Session is deliberately excluded — see below."""
    return [p for p in python_sources() if "sessions/" not in str(p).replace("\\", "/")]


def test_no_page_is_extracted_by_photographing_it():
    offenders = [f"{path.name}:{number}: {line.strip()}"
                 for path, number, line in code_lines(extraction_sources()) if SCREENSHOT.search(line)]
    assert offenders == []


def test_the_only_screencast_is_the_person_logging_in_for_themselves():
    """§13 requires a live view of the isolated login context. That is the one place it may exist."""
    users = {path.relative_to(BACKEND).as_posix() for path, _, line in code_lines(python_sources())
             if re.search(r"screencast", line, re.IGNORECASE)}
    assert users == {"oneshelf/sessions/login.py"}


def test_the_browser_is_not_reachable_from_the_download_or_reader_paths():
    """A browser in the extraction path is how screenshot extraction arrives by accident (§12, §14)."""
    offenders = []
    for directory in ("downloads", "reader"):
        for path, number, line in code_lines(sorted((BACKEND / "oneshelf" / directory).rglob("*.py"))):
            if re.search(r"\b(playwright|BrowserSession|chromium)\b", line):
                offenders.append(f"{path.name}:{number}: {line.strip()}")
    assert offenders == []
