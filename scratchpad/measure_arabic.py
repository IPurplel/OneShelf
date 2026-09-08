"""WP-3: what Arabic spelling variation actually costs, measured per site.

    python scratchpad/measure_arabic.py [--out DIR] [--site HOST ...]

For each query, every site is asked with the query **as typed** and then with
each alternative spelling ``textmatch.query_variants`` proposes. Two numbers
matter per site: how many hits the raw query earned, and how many the variants
add that the raw query never saw. The second number is the whole case for
sending anything but the raw string -- if it is zero, the expansion is cost
without benefit and should not ship.

Counts are post-gate: what the user would actually have been shown.
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

from app.adapters import resolve as resolve_adapter  # noqa: E402
from app.adapters.textmatch import clean_query, query_variants  # noqa: E402
from app.config import settings  # noqa: E402
from app.db import Database  # noqa: E402
from app.desync import DesyncProxy  # noqa: E402
from app.session import SessionManager  # noqa: E402
from scratchpad.verify_dl import create_run_settings  # noqa: E402

#: Arabic-serving sites among the configured ones. A Latin-only index cannot
#: say anything about Arabic normalisation either way.
ARABIC_SITES = [
    "https://3asq.online",
    "https://arabtoons.net",
    "https://8ghrb.com",
    "https://kitaboka.com",
    "https://www.noor-book.com",
]

#: One query per variation class named in the work package. Each is a real
#: string a reader could type, not a constructed test vector.
QUERIES = [
    ("alef forms (hamza written)", "الأمير"),
    ("alef forms (hamza omitted)", "الامير"),
    ("teh marbuta", "رواية"),
    ("teh marbuta spelled as heh", "روايه"),
    ("alef maqsura", "ليلى"),
    ("alef maqsura spelled as yeh", "ليلي"),
    ("harakat present", "رِوايَة"),
    ("tatweel", "روايـــة"),
    ("arabic-indic digits", "الجزء ٢"),
    ("persian keheh and farsi yeh", "کتاب"),
    ("definite article present", "الغريب"),
    ("copy-paste carrying RLM", "‏الغريب‎"),
]

PER_QUERY_TIMEOUT = 60.0


async def ask(adapter, site: str, query: str) -> tuple[int, list[str], str]:
    try:
        found = await asyncio.wait_for(
            adapter.search(site, query, limit=12), timeout=PER_QUERY_TIMEOUT)
    except asyncio.TimeoutError:
        return -1, [], "timeout"
    except Exception as exc:
        return -1, [], f"{type(exc).__name__}: {exc}"
    return len(found), [r.url for r in found], ""


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=Path("docs/evidence/wp3"))
    parser.add_argument("--site", action="append", dest="sites")
    args = parser.parse_args()

    sites = args.sites or ARABIC_SITES
    args.out.mkdir(parents=True, exist_ok=True)
    report = args.out / "arabic-search.json"

    run_settings, run_dir = create_run_settings(
        settings, Path(".state/source-program/wp3-arabic"))
    proxy = DesyncProxy(port=0)
    run_settings._runtime_proxy = await proxy.start()
    db = Database(run_settings.db_path)
    await db.connect()
    manager = SessionManager(run_settings, db)

    rows: list[dict] = []
    try:
        for site in sites:
            host = urlsplit(site).netloc or site
            try:
                adapter = await resolve_adapter(site, manager)
            except Exception as exc:
                print(f"{host}: resolve failed: {exc}", flush=True)
                continue
            print(f"\n=== {host} ({adapter.id})", flush=True)
            for label, query in QUERIES:
                variants = query_variants(query)
                raw_count, raw_urls, raw_err = await ask(adapter, site, variants[0])
                added: dict[str, list[str]] = {}
                seen = set(raw_urls)
                for variant in variants[1:]:
                    count, urls, err = await ask(adapter, site, variant)
                    fresh = [u for u in urls if u not in seen]
                    seen.update(urls)
                    added[variant] = fresh
                    if err:
                        added[variant] = [f"ERROR {err}"]
                gained = sum(len(v) for v in added.values()
                             if not (v and str(v[0]).startswith("ERROR")))
                row = {
                    "site": site, "host": host, "adapter": adapter.id,
                    "label": label, "query": query,
                    "sent": clean_query(query), "variants": variants[1:],
                    "raw_hits": raw_count, "raw_error": raw_err,
                    "variant_new_hits": gained,
                    "variant_detail": {k: v[:5] for k, v in added.items()},
                    "checked": datetime.now(timezone.utc).date().isoformat(),
                }
                rows.append(row)
                report.write_text(
                    json.dumps(rows, ensure_ascii=False, indent=2) + "\n",
                    encoding="utf-8")
                note = raw_err or f"raw {raw_count:>3}  +{gained} from variants"
                print(f"  {label:32} {query!r:20} {note}", flush=True)
    finally:
        await manager.close()
        await db.close()
        await proxy.stop()

    print(f"\nrun directory: {run_dir}\nreport: {report}")

    print("\n== before/after, per site ==")
    print(f"{'site':22} {'raw hits':>9} {'after variants':>15}")
    by_host: dict[str, list[dict]] = {}
    for row in rows:
        by_host.setdefault(row["host"], []).append(row)
    for host, group in by_host.items():
        raw = sum(r["raw_hits"] for r in group if r["raw_hits"] > 0)
        gain = sum(r["variant_new_hits"] for r in group)
        print(f"{host:22} {raw:>9} {raw + gain:>15}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
