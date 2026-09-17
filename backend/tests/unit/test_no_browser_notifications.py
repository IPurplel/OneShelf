"""Master §30, §49 (EX-12): v1 has in-app notifications only — no browser or push notifications."""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
# The Web Notifications API only exists in web code; push tooling is forbidden everywhere.
WEB_ONLY = re.compile(r"new\s+Notification\s*\(|window\.Notification|Notification\.requestPermission|"
                      r"serviceWorker|pushManager|showNotification", re.IGNORECASE)
ANYWHERE = re.compile(r"web-push|pywebpush|firebase|onesignal|apns", re.IGNORECASE)


def test_no_browser_notification_or_push_apis_anywhere():
    offenders = []
    for directory in ("oneshelf", "testsource"):
        for path in (ROOT / directory).rglob("*"):
            if path.suffix not in (".py", ".js", ".ts", ".html", ".yaml", ".sql") or not path.is_file():
                continue
            web_code = path.suffix in (".js", ".ts", ".html")
            for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
                if ANYWHERE.search(line) or (web_code and WEB_ONLY.search(line)):
                    offenders.append(f"{path.relative_to(ROOT)}:{number}: {line.strip()}")
    assert offenders == []


def test_requirements_contain_no_push_dependency():
    text = (ROOT / "requirements.lock").read_text().lower()
    assert "webpush" not in text and "firebase" not in text and "apns" not in text
