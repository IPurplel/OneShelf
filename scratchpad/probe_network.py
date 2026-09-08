"""What does a page actually fetch? Capture its network instead of guessing.

    python scratchpad/probe_network.py URL [--wait-ms 3000]

The first step of adding a source: when a page is a JavaScript shell with no
title, no author and no file in its HTML, this shows where the content really
comes from. It is how Arabic Collections Online was solved -- its book page is
6.5 KB of shell, and one capture found the IIIF manifest holding the whole
record, including the book as a single PDF.

Prints requests grouped by kind, then the rendered `<img>` sources, and filters
out analytics so the list is readable.
"""
from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

#: Noise every page makes, which would otherwise bury the one useful request.
NOISE = ("google-analytics.com", "googletagmanager.com", "doubleclick.net",
         "quantserve.com", "facebook.net", "/cdn-cgi/", "hotjar", "sentry")


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("url")
    parser.add_argument("--wait-ms", type=int, default=3000,
                        help="settle time after the network goes idle")
    parser.add_argument("--all", action="store_true",
                        help="keep analytics and other noise")
    args = parser.parse_args()

    from patchright.async_api import async_playwright

    seen: list[tuple[str, str, str]] = []
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)
        # ignore_https_errors is set deliberately: some institutional hosts
        # serve a chain this container cannot verify, and that is not what is
        # being investigated here.
        context = await browser.new_context(ignore_https_errors=True)
        page = await context.new_page()
        page.on("request", lambda r: seen.append((r.resource_type, r.method, r.url)))
        await page.goto(args.url, wait_until="networkidle", timeout=60_000)
        await page.wait_for_timeout(args.wait_ms)

        keep = [row for row in seen
                if args.all or not any(n in row[2] for n in NOISE)]
        print(f"{len(seen)} requests ({len(keep)} after filtering noise)\n")
        for kind in ("document", "xhr", "fetch", "script", "image"):
            rows = [(m, u) for k, m, u in keep if k == kind]
            if not rows:
                continue
            print(f"== {kind} ({len(rows)})")
            for method, url in rows[:12]:
                print(f"    {method} {url[:150]}")

        images = await page.eval_on_selector_all(
            "img", "els => els.map(e => e.src).slice(0, 6)")
        if images:
            print("\nrendered <img> srcs:")
            for src in images:
                print("   ", src[:150])
        await browser.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
