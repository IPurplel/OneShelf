"""WP-5: mechanical triage of the supplied source inventory.

    python scratchpad/triage_sites.py [--out DIR] [--limit N] [--group ar|en]
        [--only HOST ...] [--concurrency 8]

For every supplied URL, in the order the work package requires, stopping at the
first verdict that applies:

  1. AUTH        -- does reaching readable content need an account? Flagged
                    heuristically here and confirmed by hand; a login wall and
                    a working reader look identical to a fetcher, so this step
                    proposes, it does not decide.
  2. REACHABLE   -- does it answer from this network at all, and where does it
                    redirect to?
  3. FINGERPRINT -- does an existing adapter already claim the fetched DOM?
                    A hit here is zero-code coverage (WP-6).
  4. PLATFORM    -- if not, which platform is it? The cluster count is the
                    priority order for WP-7.
  5. DEAD        -- status code and date.

This records evidence, never a tier. A tier needs an artifact (T4) or a named
blocking reason (TB), and neither is decided by a HEAD request.
"""
from __future__ import annotations

import argparse
import asyncio
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import sys
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

INVENTORY = ROOT / "docs/source-inventory.md"

#: Platform signatures, checked against the fetched DOM. Each is a marker that
#: names the engine rather than the site, so it clusters hosts the way WP-7
#: needs. Ordered: the first match wins, so specific beats generic.
PLATFORMS = [
    ("madara",         ("wp-manga", "manga-chapters-holder", "listing-chapters_wrap")),
    ("mangathemesia",  ("eplister", "readerarea", "ts_reader", "bixbox")),
    ("teamx",          ("teamx", "team-x", "olympustaff")),
    ("vcomics/astro",  ("astro-island", "/_vcomics/")),
    ("blogger",        ('content="blogger"', "blogger.googleusercontent.com",
                        "www.blogger.com/static")),
    ("madara-lite",    ("wp-manga-chapter",)),
    ("wordpress",      ("/wp-content/", "/wp-includes/")),
    ("next.js",        ("__NEXT_DATA__", "/_next/static")),
    ("nuxt",           ("__NUXT__", "/_nuxt/")),
    ("laravel",        ("csrf-token", "laravel_session")),
    ("mediawiki",      ("mw-content-text", "/w/load.php")),
    ("drupal",         ("/sites/default/files", "drupal-settings-json")),
]

#: Words that suggest reaching content needs an account. Deliberately treated
#: as a *flag for review*, never a verdict: "sign in" also appears in the
#: header of a site whose reader is wide open.
_AUTH_HINTS = (
    "sign in", "signin", "log in", "login", "register", "subscribe",
    "subscription", "create an account", "my account", "sign up",
    "تسجيل الدخول", "اشترك", "إنشاء حساب", "تسجيل",
)
#: Stronger: these normally appear only when content itself is gated.
_GATE_HINTS = (
    "members only", "subscribers only", "premium", "paywall", "unlock",
    "buy now", "add to cart", "purchase", "free trial", "coins",
    "للمشتركين", "اشتراك مدفوع",
)

TIMEOUT = 25.0


def inventory() -> list[dict]:
    text = INVENTORY.read_text(encoding="utf-8")
    rows, group = [], None
    for line in text.splitlines():
        if line.startswith("## Arabic"):
            group = "ar"
        elif line.startswith("## English"):
            group = "en"
        if not line.startswith("| ") or group is None:
            continue
        parts = [c.strip() for c in line.strip("|").split("|")]
        if len(parts) != 3 or not parts[1].startswith("http"):
            continue
        rows.append({"group": group, "name": parts[0], "url": parts[1],
                     "category": parts[2]})
    return rows


def classify(html: str) -> list[str]:
    from app.adapters.registry import fingerprint_html
    markup = fingerprint_html(html) or ""
    lowered = markup.lower()
    return [name for name, markers in PLATFORMS
            if any(m.lower() in lowered for m in markers)]


def adapter_for(url: str, html: str | None):
    from app.adapters import select as select_adapter
    return select_adapter(url, html).id


def auth_flags(html: str) -> dict:
    from app.adapters.books import _visible_text
    try:
        text = _visible_text(html).lower()
    except Exception:
        text = re.sub(r"<[^>]+>", " ", html).lower()
    return {
        "account_words": sorted({w for w in _AUTH_HINTS if w in text}),
        "gate_words": sorted({w for w in _GATE_HINTS if w in text}),
    }


async def probe(client, row: dict) -> dict:
    url = row["url"]
    out = dict(row, host=urlsplit(url).netloc,
               checked=datetime.now(timezone.utc).date().isoformat())
    try:
        r = await client.get(url, follow_redirects=True, timeout=TIMEOUT)
    except Exception as exc:
        out.update(step="reachability", verdict="unreachable",
                   error=f"{type(exc).__name__}: {str(exc)[:120]}")
        return out

    html = r.text or ""
    out.update(status=r.status_code, final_url=str(r.url),
               redirected=str(r.url).rstrip("/") != url.rstrip("/"),
               bytes=len(r.content))

    if r.status_code >= 400:
        out.update(step="reachability", verdict=f"http {r.status_code}")
        return out

    out["platforms"] = classify(html)
    out["adapter"] = adapter_for(str(r.url), html)
    out["adapter_by_url"] = adapter_for(str(r.url), None)
    out.update(auth_flags(html))

    if out["adapter"] != "generic":
        out.update(step="fingerprint", verdict=f"claimed by {out['adapter']}")
    elif out["platforms"]:
        out.update(step="platform", verdict="+".join(out["platforms"]))
    else:
        out.update(step="platform", verdict="unrecognised")
    return out


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=Path("docs/evidence/wp5"))
    parser.add_argument("--limit", type=int)
    parser.add_argument("--group", choices=["ar", "en"])
    parser.add_argument("--only", action="append", dest="only")
    parser.add_argument("--concurrency", type=int, default=8)
    args = parser.parse_args()

    rows = inventory()
    if args.group:
        rows = [r for r in rows if r["group"] == args.group]
    if args.only:
        want = {o.lower() for o in args.only}
        rows = [r for r in rows if urlsplit(r["url"]).netloc.lower() in want]
    if args.limit:
        rows = rows[:args.limit]

    args.out.mkdir(parents=True, exist_ok=True)
    report = args.out / "triage.json"

    import httpx
    # A plain anonymous client, no proxy: this measures the sites, and mixing in
    # the desync bypass would make "reachable" mean two different things in one
    # table. Hosts that fail here are re-probed through the proxy afterwards.
    headers = {"User-Agent": ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36"
                              " (KHTML, like Gecko) Chrome/131.0 Safari/537.36"),
               "Accept-Language": "en-US,en;q=0.9,ar;q=0.8"}
    results: list[dict] = []
    semaphore = asyncio.Semaphore(args.concurrency)

    async with httpx.AsyncClient(headers=headers, verify=False,
                                 follow_redirects=True) as client:
        async def one(row):
            async with semaphore:
                out = await probe(client, row)
                results.append(out)
                mark = out.get("verdict", "?")
                print(f"{out['host']:34} {str(out.get('status','-')):>4}  {mark}",
                      flush=True)
                report.write_text(
                    json.dumps(results, ensure_ascii=False, indent=2) + "\n",
                    encoding="utf-8")
        await asyncio.gather(*(one(r) for r in rows))

    print(f"\n{len(results)} probed -> {report}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
