"""WP-5 second pass: separate "blocked here" from "actually gone".

    python scratchpad/triage_pass2.py [--out DIR]

Pass 1 used a plain anonymous client, which measures the site. This pass takes
everything that failed or answered with a body too small to be content and
re-asks through the app's own desync proxy -- the bypass that beats this
network's SNI filtering. A host that answers now was blocked here; a host that
still does not is dead, parked, or challenged.

Also classifies what a 200 actually contained, because a 200 is not content:
this inventory turned up domains for sale, ad-network redirects and Cloudflare
interstitials, all answering 200.
"""
from __future__ import annotations

import argparse
import asyncio
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

#: Below this a response is not a page of content. Measured against this
#: inventory: real sites answered 40 KB-1.1 MB, while parked domains,
#: ad redirects and challenge shells came in at 114-4,800 bytes.
MIN_CONTENT_BYTES = 12_000

#: Hosts that mean the domain is no longer the site it was.
_PARKED_HOSTS = ("hugedomains.com", "sedo.com", "afternic.com", "dan.com",
                 "bodis.com", "parkingcrew.net", "sav.com", "namecheap.com")
#: Redirect/ad networks a repurposed domain lands on.
_AD_HOSTS = ("asdfix.com", "avq.one", "propellerads", "popads", "adsterra")


def verdict_for(status, final_url, html, size) -> str:
    from app.session import is_challenge
    host = urlsplit(final_url).netloc.lower()
    if any(p in host for p in _PARKED_HOSTS):
        return "parked (domain for sale)"
    if any(a in host for a in _AD_HOSTS):
        return "repurposed (redirects into an ad network)"
    if status and status >= 400:
        return f"http {status}"
    try:
        if is_challenge(html):
            return "bot check"
    except Exception:
        pass
    if size < MIN_CONTENT_BYTES:
        return f"shell only ({size} bytes)"
    return "content"


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=Path("docs/evidence/wp5"))
    args = parser.parse_args()

    pass1 = json.load(open(args.out / "triage.json", encoding="utf-8"))

    # Everything that did not clearly return content is worth a second ask.
    retry = [r for r in pass1
             if r.get("step") == "reachability" or r.get("bytes", 0) < MIN_CONTENT_BYTES]
    print(f"{len(retry)} of {len(pass1)} sites need a second look\n")

    from app.config import settings
    from app.db import Database
    from app.desync import DesyncProxy
    from app.session import SessionManager
    from scratchpad.verify_dl import create_run_settings

    s, run = create_run_settings(settings, Path(".state/source-program/wp5"))
    proxy = DesyncProxy(port=0)
    s._runtime_proxy = await proxy.start()
    db = Database(s.db_path)
    await db.connect()
    manager = SessionManager(s, db)

    results = []
    report = args.out / "triage-pass2.json"
    try:
        for row in retry:
            url = row["url"]
            out = {"host": row["host"], "url": url, "group": row["group"],
                   "name": row["name"], "category": row["category"],
                   "pass1": row.get("verdict"), "pass1_bytes": row.get("bytes"),
                   "checked": datetime.now(timezone.utc).date().isoformat()}
            try:
                html = await asyncio.wait_for(
                    manager.fetch_text_direct(url), timeout=45)
            except Exception as exc:
                out.update(verdict="unreachable via desync too",
                           error=f"{type(exc).__name__}: {str(exc)[:110]}")
            else:
                out["bytes"] = len(html)
                out["verdict"] = verdict_for(200, url, html, len(html))
                if out["verdict"] == "content":
                    from app.adapters import select as select_adapter
                    from scratchpad.triage_sites import classify
                    out["adapter"] = select_adapter(url, html).id
                    out["platforms"] = classify(html)
            results.append(out)
            print(f"{out['host']:34} {out['verdict']}", flush=True)
            report.write_text(json.dumps(results, ensure_ascii=False, indent=2)
                              + "\n", encoding="utf-8")
    finally:
        await manager.close()
        await db.close()
        await proxy.stop()

    print(f"\n{len(results)} re-probed -> {report}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
