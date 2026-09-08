"""Fetch pages the way the app does — desync, rate limits, browser fallback.

    python scratchpad/probe_via_app.py URL [URL ...] [--out DIR]

Use this rather than `curl` when probing a site: several hosts answer a rapid
bare loop with a challenge page having served the real thing minutes earlier,
so a `curl` failure is not evidence about the site. Each page is saved for
inspection and the path is printed.
"""
import argparse
import asyncio
import hashlib
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app.config import settings
from app.db import Database
from app.desync import DesyncProxy
from app.session import SessionManager
from scratchpad.verify_dl import create_run_settings


async def get_many(urls):
    s, run = create_run_settings(settings, Path(".state/source-program/probe"))
    proxy = DesyncProxy(port=0)
    s._runtime_proxy = await proxy.start()
    db = Database(s.db_path); await db.connect()
    m = SessionManager(s, db)
    out = {}
    try:
        for url in urls:
            try:
                out[url] = await asyncio.wait_for(
                    m.fetch_text_direct(url), timeout=45)
            except Exception as exc:
                try:
                    out[url] = await asyncio.wait_for(
                        m.fetch_html(url), timeout=90)
                except Exception as exc2:
                    out[url] = f"__ERROR__ {type(exc).__name__}: {exc} | browser: {exc2}"
    finally:
        await m.close(); await db.close(); await proxy.stop()
    return out


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("urls", nargs="+")
    parser.add_argument("--out", type=Path, default=Path(".state/probe"),
                        help="where to save each page (default: .state/probe)")
    args = parser.parse_args()

    args.out.mkdir(parents=True, exist_ok=True)
    got = asyncio.run(get_many(args.urls))
    failed = False
    for url, body in got.items():
        if body.startswith("__ERROR__"):
            failed = True
            print(f"{url}\n   {body[:200]}")
            continue
        # Named by a hash of the URL so a re-probe overwrites its own file
        # rather than accumulating; `hash()` is salted per process and would
        # not.
        digest = hashlib.sha256(url.encode()).hexdigest()[:12]
        path = args.out / f"probe_{digest}.html"
        path.write_text(body, encoding="utf-8")
        print(f"{url}\n   {len(body)} bytes -> {path}")
    sys.exit(1 if failed else 0)
