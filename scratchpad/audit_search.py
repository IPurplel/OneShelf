"""WP-2: the R3 gate, run against every configured search site.

    python scratchpad/audit_search.py [--out DIR] [--site HOST ...]

For each site: one query it should be able to answer, and one sentinel it
cannot. A site is search-eligible only when the positive returns hits AND the
sentinel returns **none** — five sites so far have answered an unanswerable
query with a front-page grid, a latest-posts widget or the whole catalogue
newest-first, and nothing structural tells those apart from a real hit.

Runs against isolated storage through the desync proxy, exactly as
verify_dl.py does. Results are checkpointed after every query, so one hanging
site cannot cost the whole batch (the WP-0 connectivity audit already paid for
that lesson).
"""
from __future__ import annotations

import argparse
import asyncio
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
import traceback

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.adapters import resolve as resolve_adapter  # noqa: E402
from app.adapters import select as select_adapter  # noqa: E402
from app.config import settings  # noqa: E402
from app.db import Database  # noqa: E402
from app.desync import DesyncProxy  # noqa: E402
from app.session import SessionManager  # noqa: E402
from scratchpad.verify_dl import create_run_settings  # noqa: E402

#: Nothing indexes this. Any hit it returns is the site ignoring the query.
SENTINEL = "zzqvoneshelfnonexistent987654321"

#: One query per site that the site genuinely holds, chosen per content kind.
#: Arabic sites get an Arabic query: a Latin one on an Arabic-only index
#: proves nothing about whether search works.
POSITIVES = {
    "3asq.online": "hunter",
    "manga-starz.net": "solo",
    "arabtoons.net": "ناروتو",
    "azoramoon.com": "solo",
    "azorafly.com": "solo",
    "8ghrb.com": "رواية",
    "www.noor-book.com": "White Nights",
    "kitaboka.com": "رواية",
    "www.planetebook.com": "Frankenstein",
    # "Agnes Grey" is planetebook's copy, not this site's: the first
    # run of this audit scored bettergutenberg 0 for a book it does not
    # have. A positive query has to name something the site holds.
    "bettergutenberg.org": "Brief Lives",
    "www.gutenberg.org": "Frankenstein",
    "www.royalroad.com": "mother of learning",
    "archiveofourown.org": "Good Omens",
    "www.webtoons.com": "Lore Olympus",
    "mangadex.org": "berserk",
    "mangaread.org": "solo",
    "manhuaplus.com": "martial",
    "rizzfables.com": "leveling",
    "kolnovel.com": "\u0625\u0645\u0628\u0631\u0627\u0637\u0648\u0631",
    "cenele.com": "online",
    "rewayat.club": "\u0631\u0648\u0627\u064a\u0629",
    "riwayatarab.com": "\u0627\u0644\u0634\u064a\u0637\u0627\u0646\u064a",
    "aco.dlib.nyu.edu": "mutanabbi",
}

PER_QUERY_TIMEOUT = 90.0


def host_of(site: str) -> str:
    from urllib.parse import urlsplit
    return urlsplit(site).netloc or site


async def run_query(adapter, site: str, query: str) -> dict:
    row: dict = {"site": site, "host": host_of(site), "query": query,
                 "adapter": adapter.id,
                 "checked": datetime.now(timezone.utc).date().isoformat()}
    try:
        results = await asyncio.wait_for(
            adapter.search(site, query, limit=12), timeout=PER_QUERY_TIMEOUT)
    except asyncio.TimeoutError:
        row["error"] = f"timeout after {PER_QUERY_TIMEOUT}s"
    except Exception as exc:
        row["error"] = f"{type(exc).__name__}: {exc}"
        row["traceback"] = traceback.format_exc(limit=4)
    else:
        row["count"] = len(results)
        row["titles"] = [r.title for r in results[:8]]
        row["urls"] = [r.url for r in results[:8]]
    return row


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=Path("docs/evidence/wp2"))
    parser.add_argument("--site", action="append", dest="sites",
                        help="restrict to these hosts (repeatable)")
    args = parser.parse_args()

    sites = list(settings.search_sites)
    if args.sites:
        wanted = {host_of(s if "//" in s else f"//{s}").lower()
                  for s in args.sites}
        sites = [s for s in sites
                 if host_of(s).lower() in wanted or s.lower() in wanted]
        if not sites:
            print(f"no configured site matched {args.sites}", file=sys.stderr)
            return 2

    args.out.mkdir(parents=True, exist_ok=True)
    report = args.out / "search-audit.json"

    run_settings, run_dir = create_run_settings(
        settings, Path(".state/source-program/wp2-search"))
    proxy = DesyncProxy(port=0)
    run_settings._runtime_proxy = await proxy.start()
    db = Database(run_settings.db_path)
    await db.connect()
    manager = SessionManager(run_settings, db)

    rows: list[dict] = []
    try:
        for site in sites:
            host = host_of(site)
            # The URL-only guess is a filter, not the verdict -- exactly what
            # app.main does. Selecting by URL alone calls every Madara and
            # MangaThemesia site "generic", and GenericAdapter has no search(),
            # so the first run of this audit reported six sites returning
            # nothing when the app itself would have searched them properly.
            url_guess = select_adapter(site).id
            try:
                adapter = await resolve_adapter(site, manager)
            except Exception as exc:
                print(f"{host:26} resolve failed: {exc}", flush=True)
                rows.append({"site": site, "host": host, "kind": "resolve",
                             "error": f"{type(exc).__name__}: {exc}"})
                continue
            if adapter.id != url_guess:
                print(f"{host:26} fingerprint: {url_guess} -> {adapter.id}",
                      flush=True)
            positive = POSITIVES.get(host)
            if positive is None:
                print(f"!! no positive query configured for {host}", flush=True)
                continue
            for query in (positive, SENTINEL):
                row = await run_query(adapter, site, query)
                kind = "positive" if query != SENTINEL else "sentinel"
                row["kind"] = kind
                rows.append(row)
                # Checkpoint every response: an audit must survive the failure
                # it is measuring.
                report.write_text(
                    json.dumps(rows, ensure_ascii=False, indent=2) + "\n",
                    encoding="utf-8")
                summary = row.get("error") or f"{row.get('count')} hits"
                print(f"{host:26} {kind:9} {summary}", flush=True)
    finally:
        await manager.close()
        await db.close()
        await proxy.stop()

    print(f"\nrun directory: {run_dir}")
    print(f"report: {report}")

    # The verdict, printed so it lands in the transcript.
    print("\n== R3 verdict ==")
    by_host: dict[str, dict] = {}
    for row in rows:
        by_host.setdefault(row["host"], {})[row["kind"]] = row
    for host, pair in by_host.items():
        pos, neg = pair.get("positive", {}), pair.get("sentinel", {})
        if "error" in pos or "error" in neg:
            verdict = "UNPROVEN (error)"
        elif neg.get("count"):
            verdict = f"FAILS R3 (sentinel returned {neg['count']})"
        elif not pos.get("count"):
            verdict = "no positive hits"
        else:
            verdict = f"T2 ok ({pos['count']} hits, sentinel 0)"
        print(f"{host:26} {verdict}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
