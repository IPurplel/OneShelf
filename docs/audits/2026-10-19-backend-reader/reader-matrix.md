# Reader format and workflow matrix (2026-10-19)

The scope is the backend side of the Reader: serving, identity, progress, cache, isolation and failure
handling. Rendering, gestures, modes and panels are frontend (Codex) and are marked *FE* where the evidence
is the frontend suite rather than this audit.

Evidence keys:

- **T**: an automated test that passed in today's baseline run (1,485 passed and 8 browser tests passed).
  The file is named.
- **L**: exercised today on the isolated local instance (`qa-artifacts/be-audit-20261019/reader-checks.log`,
  `live/*.json`).
- **P**: exercised on production 192.168.8.32 (`browser-live/`).
- **Probe**: an audit reproduction.

## Formats × operations

| Operation | CBZ (local) | Sequential online (image reader) | PDF (local) | EPUB (local) | Text unit (container / online) |
|---|---|---|---|---|---|
| Open / list pages | **PASS** L: 20 pages, `origin=local` | **PASS** L: MangaDex, WEBTOON, Tapas, 3asq. P: Berserk renders | **PASS** L: `/file` 200 `application/pdf` | **PASS** L: `/file` 200 `application/epub+zip` | **PASS** T: `test_text_units.py`, `test_runtime_text_units.py` |
| Page bounds | **PASS** L: page 21 → 404 | **PASS** T | n/a | n/a | n/a |
| Untrusted-content isolation (§27, INV-12) | **PASS** L: `sandbox; default-src 'none'; img-src data: blob:`, `nosniff` | **PASS** L (same headers), image bytes validated before caching | **PASS** L: `sandbox; default-src 'none'`, `nosniff` | **PASS** L (same). T: sanitiser tests | **PASS** T: `test_text_sanitise.py` (nh3 allowlist, sanitised twice) |
| Byte ranges / streaming | n/a | n/a | **FAIL** L: `Range: bytes=0-99` → 200 with the whole file, read into RAM (BE-011) | **FAIL** (same, BE-011) | n/a |
| Progress write / read-back | **PASS** L: revision 0→1 | **PASS** T | **PASS** T | **PASS** T | **PASS** T |
| Stale-tab protection (§26.23) | **PASS** L: stale revision → 409 `STALE_PROGRESS` | **PASS** T | **PASS** T | **PASS** T | **PASS** T |
| Auto-read 97% / Mark Unread (§26.14) | **PASS** L: 0.98 → `read`, mark-unread → `unread` | **PASS** T | **PASS** T | **PASS** T | **PASS** T |
| Bookmarks / highlights (§26.22) | n/a (not required) | n/a | **PASS** T: `test_marks.py` | **PASS** T: `test_marks.py` | **PASS** T |
| Readable with the plugin disabled (INV-11) | **PASS** L: page served `origin=local` | **FAIL** L: wrong 409 `DOWNLOAD_REQUIRED`, cached pages unreachable (BE-017) | **PASS** T: `test_disconnect.py` | **PASS** T | **PASS** T |
| Download-only source online (§26.19) | n/a | n/a | **PASS** L: 409 `DOWNLOAD_REQUIRED` (arXiv, SE, Hindawi) | **PASS** L | n/a |
| Broken / missing / partial file (§26.21) | **PASS** T: I-83, I-90, `test_audit_regressions.py`. Repair **FAIL** (BE-008, BE-009) | **PASS with gap** L: invalid media refused. Upstream status hidden (BE-017) | **PASS** T: missing → 404 `FILE_NOT_AVAILABLE` | **PASS** T | **PASS** T |
| Reader Cache identity / eviction (§26.20, §42) | n/a | **PASS** T: `test_cache_eviction_protects_the_current_unit_and_permanent_files`. Descriptor cache unbounded (BE-017) | n/a | n/a | n/a |
| Reader priority under load (§15, INV-26) | — | **PASS** T: `test_reader_stays_responsive_while_downloads_saturate_the_governor`, `test_visible_page_overtakes_queued_preloads_on_a_slow_source`. **FAIL** L for synchronous jobs: 1.06 s stall during a backup (BE-006) | — | — | — |
| Download from the Reader (§26.19) | n/a | **FAIL** L: image units on `unknown` Works fail (BE-003) | — | — | **PASS** T |

## Workflows

| Workflow | Status | Evidence |
|---|---|---|
| Reading never downloads (INV-7) and auto-download is OFF by default (INV-8) | PASS | T: `test_reading.py` (no assets after reading). L: no jobs created by online reads |
| Auto-download at the engagement threshold, read-ahead 5, leaving the Work cancels unstarted jobs (§19) | PASS (T) | `test_reading.py`, `test_defaults_reach_every_layer.py` |
| Continue Reading / resume position (§26.15) | PASS (T, ledger BV-01) | `test_progress_can_be_read_back…`, frontend reader tests (FE) |
| Next unit by Source Track order, never `+1` (INV-24) | PASS (T) | Irregular, Special, Prologue and 3.5 fixtures in `test_test_source_pipeline.py`, `test_reading.py` |
| Source switching never claims exact page equivalence (INV-25, §26.16) | PASS (T) | `unit/reader/test_alternatives.py` |
| Switching tracks without corruption | PARTIAL | T for the alternatives API. L: duplicate same-listing tracks arise (BE-004), so progress can split across twins |
| RTL / LTR / vertical reading direction | NOT TESTED (backend) | Direction is chosen in the frontend. The backend supplies the language, but BE-002 stores Arabic sources as `und`, so the RTL default cannot be derived for 3asq or Hindawi |
| Offline: local readable, online clearly distinguished (§26.21) | PARTIAL | Local ✓ (L). Online-cached pages not usable once the source is disabled (BE-017) |
| Expiring CDN URLs (G4) | NOT CONFIRMED | MangaDex@Home URLs still valid 37 min after the descriptors were fetched (README §3) |
| Reader modes (Long Strip / Single / Double), fit, zoom, gestures, TOC, distraction-free (§26.2–26.12) | FE, not re-tested | Frontend suite and ledger rows WP-R1…R5. The Berserk Long Strip renders live (P) |
