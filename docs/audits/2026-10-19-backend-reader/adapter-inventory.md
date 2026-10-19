# Adapter inventory and test results (2026-10-19)

This inventory comes from the actual sources, not historical counts:

- **Bundled release snapshot:** `backend/plugins/official/` has 8 adapters, pinned to OneShelf-Adapters
  `0aa48e9` (`UPSTREAM.json`), with one local hotfix (MangaDex 1.0.2).
- **Live Source Registry** (`IPurplel/OneShelf-Adapters`, `registry` branch, fetched 2026-10-19): **112**
  packages, 8 official and 104 community; plugin API 1.0 ×92 and 1.2 ×20. Every package downloaded and its
  SHA-256 matched the index.
- **Frozen legacy Registry** in this repository (`registry/`): 8 packages, deprecated and not rebuilt.
- **Installed on production** (`GET /api/sources`, 192.168.8.32): 10 adapters. These are Registry 3asq
  1.0.1, MangaDex 1.0.1, Hindawi 1.0.1, Tapas 1.0.1, WEBTOON 1.0.1, Arabic Collections Online 0.1.1 and
  Pepper&Carrot 0.1.1, plus **bundled** Gutenberg 1.0.0, Standard Ebooks 1.0.0 and arXiv 1.0.0.

## 1. Static validation and packaged tests: all 112 Registry packages

Method: each package went through Core's `load_package` (archive, YAML safety, schema, cross-validation,
domains, permissions) and `run_packaged_tests` (fixture-only, no network) on `origin/main` Core.
Script: `qa-artifacts/be-audit-20261019/registry-sweep/sweep.py`. Output: `sweep-main.json`.

| Result | Count |
|---|---|
| Packages loaded and validated | **112 / 112** |
| Packaged test suites passing | **112 / 112** (530 cases) |
| Index id/version matches the manifest | 112 / 112 |
| Declared capability with no packaged case | 1 (`oneshelf.mangadex` `health`) |
| Declare `browser` retrieval | **0** |
| Declare `auth` (Use My Session) | **0** |
| Offer `search` / `reader` / `downloads` | 39 / 32 / 81 |
| No `defaults.language` declared | 13 |

**Consequence:** no real adapter exercises browser escalation, Use My Session, reconnect, or capability-level
auth. Those §41.3 "difficult web" roles are verified only against the synthetic OneShelf Test Source. 73
adapters (65%) cannot be searched; they are reachable only by URL entry.

The full per-adapter table is in Appendix A.

## 2. Live functional audit of the eight official adapters

Environment: an isolated local instance (`origin/main`, data in `qa-artifacts/be-audit-20261019/local-data`),
using the bundled snapshot. Harness: `qa-artifacts/be-audit-20261019/live/live_adapters.py`, run in three
passes (`live-main.json`, `live-pass2.json`, `live-pass3.json`). Each pass does one query or URL per source,
one catalog refresh, an online reader-page fetch, and **one small-unit download**. The artifact is then
validated by opening it. Downloaded files stay in the ignored data directory. Access restrictions were never
bypassed, and no accounts were used.

| Adapter (bundled) | Search | Work / URL | Catalog | Online reader | Download (1 unit) | Language / type stored | Status |
|---|---|---|---|---|---|---|---|
| MangaDex 1.0.2 | ✓ 151 hits, 25 languages, `complete` | ✓ | ✓ complete, `total_reached` | ✓ page bytes, sandbox CSP | ✗ when type unknown (416, BE-003). ✓ 20-page CBZ, 79 MB, valid, when type supplied | language ✓ (from source), type `unknown` | **FAIL** (BE-002/003) |
| 3asq 1.0.0 | ✓ Arabic query, 12 hits | ✓ | ✓ 570 / 275 / 111 units, `single_response` | ✓ One Piece pages. ✗ many older chapters: source 404 HTML | ✗ 416 (BE-003). Naruto ch. 1: images 404 upstream | **`und` / `unknown`** (manifest says `ar` / `manga`) | **FAIL** (BE-002/003). Content loss upstream |
| WEBTOON 1.0.0 | — (URL only) | ✓ URL resolve | ✓ 652 and 1,040 units, 23+ pages, `empty_page` | ✓ | ✗ 403 when type unknown (BE-003). ✓ 5-page CBZ when type supplied | `en` / `unknown` | **FAIL** (BE-003) |
| Tapas 1.0.0 | — (URL only) | ✓ URL resolve | ✓ 721 units, 38 pages | ✓ | ✗ `media_invalid` (BE-003) | `en` / `unknown` | **FAIL** (BE-003) |
| Hindawi / Safahat 1.0.0 | ✓ Arabic queries. ✗ Latin queries `blocked` (http redirect) | ✓ | ✓ one-shot | n/a (download-only, 409 `DOWNLOAD_REQUIRED` ✓) | ✓ EPUB, 2.06 MB, valid | **`und` / `unknown`** (manifest `ar` / `book`) | **FAIL** (BE-002, BE-014) |
| Project Gutenberg 1.0.0 | ✗ transport timeout on every query. Health `unavailable` | not reached | not reached | n/a | not reached | — | **FAIL** (BE-014). Registry 2.0.1 is URL-only |
| arXiv 1.0.0 | ✓ 46 hits (`complete: false`, page cap) | ✓ | ✓ | n/a (409 ✓) | ✓ PDF, 4 pages, 194 KB, valid | `und` / `unknown` (manifest `en`) | **FAIL** (BE-002), core flow works |
| Standard Ebooks 1.0.0 | ✓ (`Frankenstein`; `The Yellow Wallpaper` has 0 hits, a genuine empty result) | ✓ URL | ✓ | n/a (409 ✓) | ✓ EPUB, 686 KB, valid. ✗ no format choice (BE-013) | `und` vs `en` → **duplicate tracks** (BE-004) | **FAIL** (BE-004, BE-013) |

### The project's own live suite

`ONESHELF_LIVE_SOURCES=1 pytest tests/live` (log `pytest-live.log`): **6 passed, 1 skipped, 1 failed**
(MangaDex ✓, Gutenberg skipped on transport timeout, arXiv ✓, Standard Ebooks ✓, WEBTOON ✗, Tapas ✓,
Hindawi ✓, 3asq ✓). The WEBTOON failure is BE-019: a socket leaked by the Gutenberg timeout, raised as an
unraisable `ResourceWarning`. It is not a WEBTOON assertion failure. That suite binds content types
explicitly, which is why it passes where the product flow fails (BE-003). Test and product paths diverge.

### Per-adapter assessment against the audit checklist

| Check | MangaDex | 3asq | WEBTOON | Tapas | Hindawi | Gutenberg | arXiv | Std Ebooks |
|---|---|---|---|---|---|---|---|---|
| Manifest and schema valid | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| Install / update / disable / remove | ✓ suite¹ | ✓ suite | ✓ suite | ✓ suite | ✓ suite | ✓ suite | ✓ suite | ✓ suite |
| Capability declarations match recipes | ✓ (health untested) | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| Search and result parsing | ✓ | ✓ | n/a | n/a | partial | ✗ | ✓ | ✓ |
| Details, metadata, identifiers | ✓ | ✓ | ✓ | ✓ | ✓ | — | ✓ | ✓ |
| Units, ordering, pagination | ✓ | ✓, but numbering "0A–0D → 0", types unknown | ✓ season-aware (I-21/22) | ✓ | ✓ | — | ✓ | ✓ |
| Language integrity | ✓ | ✗ `und` | ✓ `en` | ✓ `en` | ✗ `und` | — | ✗ `und` | ✗ `und` / `en` split |
| Download and content validation | ✗ / ✓² | ✗ | ✗ / ✓² | ✗ | ✓ | — | ✓ | ✓ (first format only) |
| Reader vs download-only behaviour | ✓ online | ✓ online | ✓ online | ✓ online | ✓ 409 | — | ✓ 409 | ✓ 409 |
| Errors, rate limits, network failures | Test Source suite ✓ (429, 500, session expiry, HTML-as-image, interrupted, redirect-out) | upstream 404s reported as invalid media (BE-017) | — | — | Latin query → `blocked` failure (BE-014) | timeout → health `unavailable`, socket leak (BE-019) | — | — |
| Fixture coverage and regression tests | packaged ✓ | packaged ✓ + `test_3asq_package.py` | packaged ✓ | packaged ✓ | packaged ✓ | packaged ✓ | packaged ✓ | packaged ✓ |

¹ `tests/integration/plugins/test_lifecycle.py`, `test_registry_lifecycle.py` and `test_bundled_sources.py`
all passed in the baseline run. They exercise install, update, permission review, disable, uninstall and
rollback against packaged and Test Source packages. They are not repeated live per adapter.
² ✗ through the product flow (type `unknown`), ✓ when the type is supplied.

## 3. Bundled vs Registry drift

| Adapter | Bundled | Registry | Production |
|---|---|---|---|
| 3asq | 1.0.0 | 1.0.1 | 1.0.1 (registry) |
| arXiv | 1.0.0 | 1.0.1 | 1.0.0 (bundled) |
| Gutenberg | 1.0.0 (search broken live) | 2.0.1 (URL-only, `www.gutenberg.org`) | 1.0.0 (bundled) |
| Hindawi | 1.0.0 | 1.0.1 | 1.0.1 (registry) |
| MangaDex | **1.0.2 local hotfix** | 1.0.1 | 1.0.1 (registry) |
| Standard Ebooks | 1.0.0 | 1.1.1 | 1.0.0 (bundled) |
| Tapas | 1.0.0 | 1.0.1 | 1.0.1 (registry) |
| WEBTOON | 1.0.0 | 1.0.1 | 1.0.1 (registry) |

## Appendix A — all 112 Registry packages

| Adapter | Version | Trust | API | Capabilities | Packaged cases | Untested caps | Defaults (lang/type) |
|---|---|---|---|---|---|---|---|
| `oneshelf.3asq` | 1.0.1 | official | 1.0 | catalog, latest, reader, search, work | 5 ✓ | — | ar / manga |
| `oneshelf.arxiv` | 1.0.1 | official | 1.0 | catalog, downloads, search, work | 4 ✓ | — | en / — |
| `oneshelf.gutenberg` | 2.0.1 | official | 1.0 | catalog, downloads, work | 3 ✓ | — | en / book |
| `oneshelf.hindawi` | 1.0.1 | official | 1.0 | catalog, downloads, search, work | 4 ✓ | — | ar / book |
| `oneshelf.mangadex` | 1.0.1 | official | 1.0 | catalog, health, reader, search, work | 4 ✓ | health | en / — |
| `oneshelf.standard-ebooks` | 1.1.1 | official | 1.0 | catalog, downloads, search, work | 5 ✓ | — | en / — |
| `oneshelf.tapas` | 1.0.1 | official | 1.0 | catalog, reader, work | 3 ✓ | — | en / comic |
| `oneshelf.webtoon` | 1.0.1 | official | 1.0 | catalog, reader, work | 3 ✓ | — | en / — |
| `oneshelf.acomics` | 0.1.1 | community | 1.0 | catalog, reader, search, work | 9 ✓ | — | ru / comic |
| `oneshelf.amherst-college-press` | 0.1.1 | community | 1.0 | catalog, downloads, search, work | 6 ✓ | — | en / book |
| `oneshelf.anno` | 0.1.1 | community | 1.0 | catalog, reader, work | 5 ✓ | — | de / other |
| `oneshelf.anu-press` | 0.1.1 | community | 1.0 | catalog, downloads, search, work | 4 ✓ | — | en / book |
| `oneshelf.arabic-collections-online` | 0.1.1 | community | 1.0 | catalog, downloads, search, work | 5 ✓ | — | ar / book |
| `oneshelf.athabasca-university-press` | 0.1.1 | community | 1.0 | catalog, downloads, search, work | 6 ✓ | — | en / book |
| `oneshelf.authorama` | 0.1.0 | community | 1.2 | catalog, reader, work | 7 ✓ | — | en / book |
| `oneshelf.babylon-jubh` | 0.1.0 | community | 1.0 | catalog, downloads, work | 6 ✓ | — | ar / paper |
| `oneshelf.baghdad-aladab` | 0.1.0 | community | 1.0 | catalog, downloads, work | 4 ✓ | — | ar / paper |
| `oneshelf.baghdad-jrashc` | 0.1.0 | community | 1.0 | catalog, downloads, work | 5 ✓ | — | ar / paper |
| `oneshelf.bccampus-open-textbooks` | 0.1.1 | community | 1.0 | catalog, downloads, work | 5 ✓ | — | en / book |
| `oneshelf.bokselskap` | 0.1.1 | community | 1.2 | catalog, reader, search, work | 4 ✓ | — | no / book |
| `oneshelf.books-by-habiba` | 0.1.1 | community | 1.0 | catalog, downloads, search, work | 4 ✓ | — | arz / book |
| `oneshelf.brogo` | 0.1.1 | community | 1.2 | catalog, reader, work | 3 ✓ | — | en / comic |
| `oneshelf.chitanka` | 0.1.1 | community | 1.2 | catalog, reader, search, work | 6 ✓ | — | bg / book |
| `oneshelf.comic-book-plus` | 0.1.1 | community | 1.0 | catalog, reader, work | 3 ✓ | — | — / comic |
| `oneshelf.comloc-vault` | 0.1.0 | community | 1.0 | catalog, reader, work | 5 ✓ | — | en / comic |
| `oneshelf.cyberleninka` | 0.1.1 | community | 1.2 | catalog, reader, work | 5 ✓ | — | ru / paper |
| `oneshelf.digital-bodleian` | 0.1.1 | community | 1.0 | catalog, reader, search, work | 4 ✓ | — | — / — |
| `oneshelf.diyala-djhr` | 0.1.0 | community | 1.0 | catalog, downloads, work | 4 ✓ | — | ar / paper |
| `oneshelf.ebible` | 0.1.1 | community | 1.0 | catalog, downloads, work | 7 ✓ | — | — / book |
| `oneshelf.elejandria` | 0.1.1 | community | 1.2 | catalog, downloads, work | 3 ✓ | — | es / book |
| `oneshelf.elmergib-ejhs` | 0.1.0 | community | 1.0 | catalog, downloads, work | 4 ✓ | — | ar / paper |
| `oneshelf.english-storybooks-arabic` | 0.1.1 | community | 1.0 | catalog, downloads, search, work | 5 ✓ | — | ar / book |
| `oneshelf.englishliteratureebooks` | 0.1.0 | community | 1.0 | catalog, downloads, work | 6 ✓ | — | en / book |
| `oneshelf.erudit` | 0.1.1 | community | 1.2 | catalog, reader, work | 4 ✓ | — | fr / paper |
| `oneshelf.fao-knowledge` | 0.1.1 | community | 1.2 | catalog, downloads, work | 5 ✓ | — | en / paper |
| `oneshelf.folger-shakespeare` | 0.1.1 | community | 1.0 | catalog, downloads, work | 3 ✓ | — | en / book |
| `oneshelf.framabook` | 0.1.0 | community | 1.0 | catalog, downloads, work | 9 ✓ | — | fr / book |
| `oneshelf.fsu-arabic-short-stories` | 0.1.1 | community | 1.0 | catalog, downloads, search, work | 4 ✓ | — | ar / book |
| `oneshelf.gallica` | 0.1.1 | community | 1.0 | catalog, reader, work | 4 ✓ | — | — / — |
| `oneshelf.ganjoor` | 0.1.1 | community | 1.2 | catalog, reader, search, work | 5 ✓ | — | fa / book |
| `oneshelf.govinfo` | 0.1.1 | community | 1.0 | catalog, downloads, work | 5 ✓ | — | en / book |
| `oneshelf.ibn-almuqaffa-ut` | 0.1.1 | community | 1.0 | catalog, downloads, work | 3 ✓ | — | ar / paper |
| `oneshelf.imist-chariaa` | 0.1.1 | community | 1.0 | catalog, downloads, work | 4 ✓ | — | ar / paper |
| `oneshelf.imist-dafatir-barlamania` | 0.1.1 | community | 1.0 | catalog, downloads, work | 4 ✓ | — | ar / paper |
| `oneshelf.imist-didase` | 0.1.1 | community | 1.0 | catalog, downloads, work | 4 ✓ | — | ar / paper |
| `oneshelf.imist-insaf` | 0.1.1 | community | 1.0 | catalog, downloads, work | 4 ✓ | — | ar / paper |
| `oneshelf.imist-joussour` | 0.1.1 | community | 1.0 | catalog, downloads, work | 4 ✓ | — | ar / paper |
| `oneshelf.imist-lixus` | 0.1.1 | community | 1.0 | catalog, downloads, work | 4 ✓ | — | ar / paper |
| `oneshelf.imist-prometheus` | 0.1.1 | community | 1.0 | catalog, downloads, work | 4 ✓ | — | ar / paper |
| `oneshelf.imist-tribunejuridique` | 0.1.1 | community | 1.0 | catalog, downloads, work | 4 ✓ | — | ar / paper |
| `oneshelf.intechopen` | 0.1.1 | community | 1.0 | catalog, downloads, work | 4 ✓ | — | en / book |
| `oneshelf.jalit-ut` | 0.1.1 | community | 1.0 | catalog, downloads, work | 3 ✓ | — | ar / paper |
| `oneshelf.jall-ferdowsi` | 0.1.1 | community | 1.0 | catalog, downloads, work | 3 ✓ | — | ar / paper |
| `oneshelf.kufa-arts` | 0.1.0 | community | 1.0 | catalog, downloads, work | 5 ✓ | — | ar / paper |
| `oneshelf.kufa-ewjh` | 0.1.0 | community | 1.0 | catalog, downloads, work | 4 ✓ | — | ar / paper |
| `oneshelf.kufa-fqhj` | 0.1.0 | community | 1.0 | catalog, downloads, work | 5 ✓ | — | ar / paper |
| `oneshelf.kufa-jall` | 0.1.0 | community | 1.0 | catalog, downloads, work | 4 ✓ | — | ar / paper |
| `oneshelf.kufa-kjlps` | 0.1.0 | community | 1.0 | catalog, downloads, work | 4 ✓ | — | ar / paper |
| `oneshelf.kufa-ksc` | 0.1.0 | community | 1.0 | catalog, downloads, work | 4 ✓ | — | ar / paper |
| `oneshelf.lasem-semnan` | 0.1.1 | community | 1.0 | catalog, downloads, work | 3 ✓ | — | ar / paper |
| `oneshelf.latakia-humlitr` | 0.1.0 | community | 1.0 | catalog, downloads, work | 4 ✓ | — | ar / paper |
| `oneshelf.lever-press` | 0.1.1 | community | 1.0 | catalog, downloads, search, work | 6 ✓ | — | en / book |
| `oneshelf.libretexts` | 0.1.1 | community | 1.0 | catalog, downloads, work | 4 ✓ | — | — / book |
| `oneshelf.litteraturbanken` | 0.1.1 | community | 1.0 | catalog, downloads, search, work | 6 ✓ | — | sv / book |
| `oneshelf.manchester-arabic-manuscripts` | 0.1.1 | community | 1.0 | catalog, reader, search, work | 4 ✓ | — | ar / — |
| `oneshelf.mdz-arabic-manuscripts` | 0.1.1 | community | 1.0 | catalog, reader, search, work | 6 ✓ | — | ar / — |
| `oneshelf.megamouse-books` | 0.1.0 | community | 1.0 | catalog, downloads, work | 5 ✓ | — | en / book |
| `oneshelf.mek` | 0.1.1 | community | 1.2 | catalog, downloads, search, work | 6 ✓ | — | hu / book |
| `oneshelf.meson-press` | 0.1.1 | community | 1.0 | catalog, downloads, work | 6 ✓ | — | — / book |
| `oneshelf.misurata-arts` | 0.1.0 | community | 1.0 | catalog, downloads, work | 4 ✓ | — | ar / paper |
| `oneshelf.mosul-berj` | 0.1.0 | community | 1.0 | catalog, downloads, work | 5 ✓ | — | ar / paper |
| `oneshelf.mosul-jeh` | 0.1.0 | community | 1.0 | catalog, downloads, work | 4 ✓ | — | ar / paper |
| `oneshelf.msila-japl` | 0.1.0 | community | 1.0 | catalog, downloads, work | 4 ✓ | — | ar / paper |
| `oneshelf.msila-olda` | 0.1.0 | community | 1.0 | catalog, downloads, work | 4 ✓ | — | ar / paper |
| `oneshelf.nasa-ntrs` | 0.1.1 | community | 1.0 | catalog, downloads, search, work | 6 ✓ | — | en / paper |
| `oneshelf.nijl-kokusho` | 0.1.1 | community | 1.0 | catalog, reader, search, work | 9 ✓ | — | ja / book |
| `oneshelf.oapen` | 0.1.1 | community | 1.0 | catalog, downloads, search, work | 4 ✓ | — | — / book |
| `oneshelf.openedition-books` | 0.1.1 | community | 1.2 | catalog, reader, work | 6 ✓ | — | — / book |
| `oneshelf.openstax` | 0.1.1 | community | 1.0 | catalog, downloads, search, work | 6 ✓ | — | — / book |
| `oneshelf.peppercarrot` | 0.1.1 | community | 1.0 | catalog, reader, work | 3 ✓ | — | — / comic |
| `oneshelf.peter-watts` | 0.1.0 | community | 1.0 | catalog, downloads, work | 5 ✓ | — | en / book |
| `oneshelf.rall-ui` | 0.1.1 | community | 1.0 | catalog, downloads, work | 3 ✓ | — | ar / paper |
| `oneshelf.rctall-atu` | 0.1.1 | community | 1.0 | catalog, downloads, work | 3 ✓ | — | fa / paper |
| `oneshelf.rpo` | 0.1.1 | community | 1.2 | catalog, reader, search, work | 6 ✓ | — | en / book |
| `oneshelf.runeberg` | 0.1.1 | community | 1.2 | catalog, reader, work | 9 ✓ | — | — / book |
| `oneshelf.sandra-and-woo` | 0.1.1 | community | 1.0 | catalog, reader, work | 4 ✓ | — | en / comic |
| `oneshelf.sefaria` | 0.1.1 | community | 1.2 | catalog, reader, search, work | 6 ✓ | — | he / book |
| `oneshelf.sefaria-english` | 0.1.1 | community | 1.2 | catalog, reader, search, work | 6 ✓ | — | en / book |
| `oneshelf.sharia-qu` | 0.1.1 | community | 1.0 | catalog, downloads, work | 4 ✓ | — | ar / paper |
| `oneshelf.siyavula` | 0.1.1 | community | 1.0 | catalog, downloads, work | 4 ✓ | — | en / book |
| `oneshelf.storybooks-canada-arabic` | 0.1.1 | community | 1.0 | catalog, downloads, search, work | 5 ✓ | — | ar / book |
| `oneshelf.tajseer-qu` | 0.1.1 | community | 1.0 | catalog, downloads, work | 4 ✓ | — | ar / paper |
| `oneshelf.textgrid-digitale-bibliothek` | 0.1.1 | community | 1.2 | catalog, reader, search, work | 6 ✓ | — | de / book |
| `oneshelf.thamar-arts` | 0.1.0 | community | 1.0 | catalog, downloads, work | 4 ✓ | — | ar / paper |
| `oneshelf.thamar-edu` | 0.1.0 | community | 1.0 | catalog, downloads, work | 4 ✓ | — | ar / paper |
| `oneshelf.tikrit-jtuh` | 0.1.0 | community | 1.0 | catalog, downloads, work | 4 ✓ | — | ar / paper |
| `oneshelf.tripoli-delalat` | 0.1.0 | community | 1.0 | catalog, downloads, work | 4 ✓ | — | ar / paper |
| `oneshelf.tuwhera-open-books` | 0.1.1 | community | 1.0 | catalog, downloads, search, work | 6 ✓ | — | en / book |
| `oneshelf.ucl-press` | 0.1.1 | community | 1.0 | catalog, downloads, work | 5 ✓ | — | en / book |
| `oneshelf.university-of-michigan-press` | 0.1.1 | community | 1.0 | catalog, downloads, search, work | 6 ✓ | — | en / book |
| `oneshelf.wasit-lark` | 0.1.0 | community | 1.0 | catalog, downloads, work | 4 ✓ | — | ar / paper |
| `oneshelf.wellcome-collection` | 0.1.1 | community | 1.0 | catalog, downloads, reader, search, work | 8 ✓ | — | — / — |
| `oneshelf.who-iris` | 0.1.1 | community | 1.2 | catalog, downloads, work | 5 ✓ | — | en / paper |
| `oneshelf.wikimedia-commons` | 0.1.1 | community | 1.0 | catalog, downloads, search, work | 5 ✓ | — | — / — |
| `oneshelf.wikisource-ar` | 0.1.1 | community | 1.2 | catalog, reader, search, work | 4 ✓ | — | ar / book |
| `oneshelf.wikisource-en` | 0.1.1 | community | 1.2 | catalog, reader, search, work | 4 ✓ | — | en / book |
| `oneshelf.wipo-publications-ar` | 0.1.1 | community | 1.0 | catalog, downloads, search, work | 6 ✓ | — | ar / book |
| `oneshelf.wolne-lektury` | 0.1.1 | community | 1.0 | catalog, downloads, search, work | 6 ✓ | — | pl / book |
| `oneshelf.world-bank-okr` | 0.1.1 | community | 1.2 | catalog, downloads, work | 5 ✓ | — | en / paper |
| `oneshelf.xkcd` | 0.1.1 | community | 1.0 | catalog, reader, work | 5 ✓ | — | en / comic |
| `oneshelf.yarmouk-jjes` | 0.1.0 | community | 1.0 | catalog, downloads, work | 5 ✓ | — | ar / paper |
| `oneshelf.zawia-uzfaj` | 0.1.0 | community | 1.0 | catalog, downloads, work | 4 ✓ | — | ar / paper |
