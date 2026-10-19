"""Open the real OneShelf in Google Chrome and record what a person would see.

    backend/.venv/bin/python scripts/agent/browser_check.py [--url URL] [--path /some/page ...] [--click TEXT]

For each path it loads the page in headless Google Chrome (the installed `google-chrome`, else Playwright's
bundled Chrome for Testing) at desktop and mobile size,
saves a viewport and a full-page screenshot, and records console errors, uncaught page exceptions and failed network
requests. ``--click`` follows a visible link or button with that accessible name on the first page — a
harmless interaction (navigation only; never use it on anything that changes data). Screenshots and a
``report.json`` go to ``qa-artifacts/browser/<timestamp>/`` (git-ignored). Exit status: 0 clean, 1 problems found,
2 the browser or the app could not be reached.

This complements the Playwright MCP server in ``.mcp.json`` / ``.codex/config.toml``:
use the MCP tools to explore and interact, and this to capture repeatable evidence.
See docs/agent-browser-verification.md.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path
from urllib.parse import urljoin

from playwright.sync_api import Error, sync_playwright

ROOT = Path(__file__).resolve().parents[2]
VIEWPORTS = {"desktop": {"width": 1440, "height": 900}, "mobile": {"width": 390, "height": 844}}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--url", default=os.environ.get("ONESHELF_URL", "http://192.168.8.32:8420/"))
    parser.add_argument("--path", action="append", default=[], help="page to open, relative to --url (repeatable)")
    parser.add_argument("--click", help="accessible name of a link/button to follow on the first page; it must be visible at both "
                        "sizes (Sources, Downloads and Settings sit under More on mobile)")
    parser.add_argument("--out", type=Path, default=ROOT / "qa-artifacts" / "browser" / time.strftime("%Y%m%d-%H%M%S"))
    args = parser.parse_args()
    paths = args.path or ["/"]
    args.out.mkdir(parents=True, exist_ok=True)

    report: dict = {"url": args.url, "browser": None, "pages": []}
    with sync_playwright() as p:
        browser = None
        for channel in ("chrome", "chromium"):
            try:
                browser = p.chromium.launch(channel=channel, headless=True)
                break
            except Error as exc:
                print(f"{channel}: did not launch: {str(exc).splitlines()[0]}")
        if browser is None:
            print("BLOCKED: no Chrome could be launched")
            return 2
        report["browser"] = f"Google Chrome {browser.version}"
        print(report["browser"])
        for size, viewport in VIEWPORTS.items():
            context = browser.new_context(viewport=viewport, is_mobile=size == "mobile", has_touch=size == "mobile")
            for index, path in enumerate(paths):
                entry = visit(context, urljoin(args.url, path), size, args.out, args.click if index == 0 else None)
                report["pages"].append(entry)
                problems = len(entry["console_errors"]) + len(entry["page_errors"]) + len(entry["failed_requests"])
                print(f"[{size}] {path}: HTTP {entry['status']} title={entry['title']!r} "
                      f"problems={problems} screenshot={entry['screenshot']}")
                for line in entry["console_errors"] + entry["page_errors"] + entry["failed_requests"]:
                    print(f"    {line}")
                if entry.get("clicked"):
                    print(f"    clicked {args.click!r} -> {entry['clicked']['url']} ({entry['clicked']['screenshot']})")
            context.close()
        browser.close()

    (args.out / "report.json").write_text(json.dumps(report, indent=2, ensure_ascii=False))
    print(f"report: {args.out / 'report.json'}")
    if any(page["status"] is None for page in report["pages"]):
        return 2
    clean = all(not (pg["console_errors"] or pg["page_errors"] or pg["failed_requests"]) for pg in report["pages"])
    return 0 if clean else 1


def visit(context, url: str, size: str, out: Path, click: str | None) -> dict:
    page = context.new_page()
    entry: dict = {"url": url, "viewport": size, "status": None, "title": None,
                   "console_errors": [], "page_errors": [], "failed_requests": []}
    page.on("console", lambda m: m.type == "error" and entry["console_errors"].append(f"console: {m.text}"))
    page.on("pageerror", lambda e: entry["page_errors"].append(f"exception: {e}"))
    page.on("requestfailed", lambda r: entry["failed_requests"].append(f"failed: {r.method} {r.url} {r.failure}"))
    page.on("response", lambda r: r.status >= 400 and entry["failed_requests"].append(f"HTTP {r.status}: {r.request.method} {r.url}"))
    try:
        response = page.goto(url, wait_until="load", timeout=45000)
        settle(page)
    except Error as exc:
        entry["page_errors"].append(f"navigation: {str(exc).splitlines()[0]}")
        page.close()
        return entry
    entry["status"] = response.status if response else None
    entry["title"] = page.title()
    name = url.rstrip("/").rsplit("/", 1)[-1] if url.rstrip("/").count("/") > 2 else "home"
    # The viewport shot is what a person sees; the full-page one shows the rest of the page, but draws
    # fixed elements (sidebar, mobile tab bar) where the viewport ended — that is a capture artifact.
    shot = out / f"{size}-{name}.png"
    page.screenshot(path=str(shot))
    page.screenshot(path=str(out / f"{size}-{name}-full.png"), full_page=True)
    entry["screenshot"] = str(shot)
    entry["horizontal_overflow"] = page.evaluate("document.documentElement.scrollWidth > window.innerWidth")
    if entry["horizontal_overflow"]:
        entry["page_errors"].append("layout: page scrolls horizontally")
    if click:
        target = page.get_by_role("link", name=click).or_(page.get_by_role("button", name=click)).first
        try:
            target.click(timeout=10000)
            settle(page)
            clicked = out / f"{size}-{name}-after-click.png"
            page.screenshot(path=str(clicked))
            entry["clicked"] = {"url": page.url, "screenshot": str(clicked)}
        except Error as exc:
            entry["page_errors"].append(f"click {click!r}: {str(exc).splitlines()[0]}")
    page.close()
    return entry


def settle(page) -> None:
    """Let the SPA render. Live updates can keep the network busy, so idle is waited for briefly, not required."""
    try:
        page.wait_for_load_state("networkidle", timeout=8000)
    except Error:
        pass
    page.wait_for_timeout(1000)


if __name__ == "__main__":
    sys.exit(main())
