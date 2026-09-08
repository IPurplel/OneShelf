"""WP-7: cluster novel sites by the markup an adapter would actually use.

    python scratchpad/probe_novels.py [--out DIR]

The triage clustered by *framework* (Next.js, Laravel, WordPress) and that told
us nothing: a framework says how a site is built, not how its chapters are laid
out. This asks the question an adapter cares about — from a real series page,
which selectors hold the chapter list, and from a real chapter, which hold the
prose.

Sites whose answers match can share an adapter. Sites whose answers differ
cannot, however similar their stack.
"""
from __future__ import annotations

import argparse
import asyncio
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

#: One known series page per site, so the probe reads real markup rather than a
#: homepage. Filled in from each site's own listing.
#: the fingerprint.
CHAPTER_LIST = [
    "#chapterlist", "div.eplister", "ul.chapter-list", "div.chapter-list",
    "#chapter-list", "ul.list-chapter", "div.list-chapter", "#list-chapter",
    "ul.main.version-chap", "li.wp-manga-chapter", "div.chapter-item",
    "a.chapter-item", "#tab-chapters", "ul.chapter", "div#chapters",
]
READER = [
    "#chapter-container", "div.chapter-content", "#htmlContent", "div.txt",
    "#chr-content", "div.chr-c", "#content", "div.reading-content",
    "div.entry-content", "#readerarea", "div.epcontent", "article",
    "div.chapter-entity", "div.text-left",
]


async def fetch(client, url: str) -> tuple[int, str, str]:
    try:
        r = await client.get(url, follow_redirects=True, timeout=25)
    except Exception as exc:
        return 0, "", f"{type(exc).__name__}: {str(exc)[:90]}"
    return r.status_code, r.text or "", ""


def hits(html: str, selectors: list[str]) -> dict[str, int]:
    from selectolax.parser import HTMLParser
    tree = HTMLParser(html)
    out = {}
    for sel in selectors:
        try:
            n = len(tree.css(sel))
        except Exception:
            continue
        if n:
            out[sel] = n
    return out


def biggest_text_block(html: str) -> tuple[str, int]:
    """Which container holds the most running text — the reader, usually."""
    from selectolax.parser import HTMLParser
    tree = HTMLParser(html)
    best, best_len = "", 0
    for node in tree.css("div, article, section"):
        ps = node.css("p")
        if len(ps) < 5:
            continue
        length = sum(len((p.text() or "").strip()) for p in ps)
        if length > best_len:
            cls = (node.attributes.get("class") or "").split()
            ident = node.attributes.get("id")
            name = f"#{ident}" if ident else ("." + ".".join(cls[:2]) if cls else node.tag)
            best, best_len = name, length
    return best, best_len


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=Path("docs/evidence/wp7"))
    parser.add_argument("--seeds", type=Path,
                        default=ROOT / "scratchpad/novel_seeds.json")
    args = parser.parse_args()

    seeds = json.loads(args.seeds.read_text(encoding="utf-8"))
    args.out.mkdir(parents=True, exist_ok=True)
    report = args.out / "novel-shapes.json"

    import httpx
    headers = {"User-Agent": ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36"
                              " (KHTML, like Gecko) Chrome/131.0 Safari/537.36"),
               "Accept-Language": "en-US,en;q=0.9,ar;q=0.8"}
    rows = []
    async with httpx.AsyncClient(headers=headers, verify=False) as client:
        for host, urls in seeds.items():
            row = {"host": host, "series_url": urls.get("series"),
                   "chapter_url": urls.get("chapter"),
                   "checked": datetime.now(timezone.utc).date().isoformat()}
            code, html, err = await fetch(client, urls["series"])
            row["series_status"], row["series_bytes"] = code, len(html)
            if err:
                row["series_error"] = err
            else:
                row["chapter_list_selectors"] = hits(html, CHAPTER_LIST)
                row["chapter_links"] = len(re.findall(
                    r'href="[^"]*(?:chapter|chap|ch)[-_/][^"]*"', html, re.I))
            if urls.get("chapter"):
                code, html, err = await fetch(client, urls["chapter"])
                row["chapter_status"], row["chapter_bytes"] = code, len(html)
                if err:
                    row["chapter_error"] = err
                else:
                    row["reader_selectors"] = hits(html, READER)
                    name, size = biggest_text_block(html)
                    row["biggest_text_block"] = name
                    row["biggest_text_chars"] = size
            rows.append(row)
            report.write_text(json.dumps(rows, ensure_ascii=False, indent=2)
                              + "\n", encoding="utf-8")
            print(f"{host:26} list={list((row.get('chapter_list_selectors') or {}))[:2]} "
                  f"reader={row.get('biggest_text_block')} "
                  f"({row.get('biggest_text_chars', 0)} chars)", flush=True)
    print(f"\n{len(rows)} probed -> {report}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
