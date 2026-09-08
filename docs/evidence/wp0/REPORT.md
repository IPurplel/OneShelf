# WP-0 — Baseline and instrumentation report

Completed 2026-09-07 UTC. This implements the approved WP-0 plan; WP-1 through
WP-9 remain subsequent work packages.

## Result

- **1 source verified this run:** Project Gutenberg. Frankenstein EPUB,
  **474161 bytes, 32 spine items, 239 rendered pages**; a prose page was visually
  inspected. The real queue downloaded one complete EPUB3 file anonymously.
- **17 other configured URLs: T1.** All 18 configured hosts returned HTTP 200
  through the configured local desync proxy. No new T0 or TB classification is
  supported by these measurements. Reader/search access was not tested for the
  other 17 hosts.
- **691 baseline tests; 704 final tests.** All checks passed.

See [SOURCES.md](../../../SOURCES.md) for one row per configured source and the
approved TU tier. Historical T4 observations were not converted into retained
current evidence without an artifact.

## Artifact and provenance

Source: https://www.gutenberg.org/ebooks/84

Absolute retained path:
`/workspace/manga downloader/.state/verification/run-arxyf3k8/downloads/Frankenstein; or, the modern prometheus/Frankenstein; or, the modern prometheus.epub`

SHA-256: `2c29669a2cc1a726d6264178a2e8e86529208fd61ef92ca627b1612b2d98b2bd`.
A byte-identical copy is included at
[tests/fixtures/books/gutenberg_frankenstein.epub](../../../tests/fixtures/books/gutenberg_frankenstein.epub).
This fixture was captured from the real download, not handwritten. Its spine
contains front matter as well as prose; 32 is not a claim of 32 literary chapters.
239 is a layout-dependent PyMuPDF 1.26.4 page count.

The exact command was:

```bash
PYTHONIOENCODING=utf-8 MD_CONFIG_FILE=/dev/null MD_DESYNC_ENABLED=false MD_HEADLESS=true \
  .venv-linux/bin/python scratchpad/verify_dl.py https://www.gutenberg.org/ebooks/84 --format epub --timeout 180
```

[Download transcript](download-transcript.txt) · [Queue and verifier JSON](download.json)

The first real run wrote its file but failed reporting due to a wrong `by_id`
import; it remains labelled failed in its isolated run. After correcting the
import, a new queue run produced the passing artifact above.

## Changes by file

- `scratchpad/verify_dl.py`: unique run directory; isolated settings, database,
  browser profile and output; no directory deletion or attached browser;
  retained success/failure evidence; bounded asynchronous download phase;
  format selection; SHA-256, bytes and counts; image decoding, PDF rendering,
  and EPUB container/spine/render inspection. Non-openable formats cannot pass
  on signatures alone.
- `scratchpad/audit_connectivity.py`: ephemeral isolated HTTP server; real
  connectivity API calls for every configured URL; supplemental same-route GETs
  for redirects and fingerprints; independent endpoint error records;
  per-run atomic evidence checkpoints that survive failures and reruns.
- `tests/test_verify_download.py` and `tests/test_connectivity_audit.py`:
  13 added regression cases for false-positive documents, truncated pages,
  missing/empty EPUB content, count mismatches, environment/storage isolation,
  failed/timed-out runs, and failed audit requests. Real queue success was also
  checked live rather than represented by a stubbed endpoint.
- `requirements-dev.txt`: pinned PyMuPDF 1.26.4 for audit rendering only.
- `.gitignore`: include the two reusable scratchpad tools while leaving other
  scratch work ignored. The Windows `.venv` was preserved; `.venv-linux` is local.
- `SOURCES.md`, `docs/development.md`, `HANDOFF.md`, and this evidence directory:
  current tiers, reproducible commands, limitations, and debugging findings.

## Connectivity evidence

Command: `PYTHONIOENCODING=utf-8 .venv-linux/bin/python scratchpad/audit_connectivity.py`.
The effective local config enables HTTP desync and disables browser desync.
Storage and proxy listener ports were isolated. Four hosts were probed at once.

[Endpoint responses and redirect evidence](connectivity.json) ·
[Actual HTTP transcript](connectivity-transcript.txt).
The original per-run report is also retained below `.state/connectivity` at the
absolute path recorded in the JSON. The repository snapshot is a copy.

Observed redirects include manga-starz.net → starzmanga.com and azoramoon.com →
azorafly.com. Noor and 3asq.online answered through this HTTP route; this does
not prove browser reachability or that desync was necessary. The separate
3asq.org host was not among the configured URLs tested by WP-0.

## Validation output

The environment initially lacked pytest, pyflakes and YAML in system Python;
those import failures were reported before setting up the isolated development
environment. Full subsequent output is retained in [baseline.txt](baseline.txt)
and [final-checks.txt](final-checks.txt).

Baseline:

```text
$ python -m pytest -q
........................................................................ [ 10%]
........................................................................ [ 20%]
........................................................................ [ 31%]
........................................................................ [ 41%]
........................................................................ [ 52%]
........................................................................ [ 62%]
........................................................................ [ 72%]
........................................................................ [ 83%]
........................................................................ [ 93%]
...........................................                              [100%]
691 passed in 36.58s

exit: 0
$ python -m pyflakes app tests

exit: 0
$ bash -n startup.sh

exit: 0
```

Final (with `.venv-linux/bin` first on PATH and UTF-8 output):

```text
$ python -m pytest -q
........................................................................ [ 10%]
........................................................................ [ 20%]
........................................................................ [ 30%]
........................................................................ [ 40%]
........................................................................ [ 51%]
........................................................................ [ 61%]
........................................................................ [ 71%]
........................................................................ [ 81%]
........................................................................ [ 92%]
........................................................                 [100%]
704 passed in 36.67s

exit: 0
$ python -m pyflakes app tests

exit: 0
$ bash -n startup.sh

exit: 0
$ python -m pyflakes scratchpad/verify_dl.py scratchpad/audit_connectivity.py

exit: 0
$ git diff --check

exit: 0
```

The initial verifier regression run reproduced two false positives and the
missing isolation helper (3 failed, 1 passed). All 13 new cases pass after the
changes. Code review identified audit failure propagation and overwritten
reports; both were corrected and covered by regression tests.

## Remaining work, ranked

1. WP-1: measure Noor's current browser/reader route and complete-book throttle;
   exercise existing `desync_browser` behavior before proposing a replacement.
   Test 3asq.org separately from 3asq.online.
2. WP-2: obtain artifacts for every existing adapter, validate positive/negative
   searches, and reconcile configured sources and README claims.
3. WP-3/WP-4: establish the Arabic query measurements and implement search
   recovery with its real-browser transcript. Neither was changed or measured
   in WP-0.
4. WP-5 onward: reconcile the full candidate inventory and triage before adding
   platforms or reader extraction paths.

No account credentials, login flow or paid-content unlock was used. The
verification checks prove structural readability and recorded counts, not
semantic identity of every page or permission to redistribute every source.
