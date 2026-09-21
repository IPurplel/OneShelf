# C9 — Verification Report: Generator, Source Suite, Deployment

Recorded: 2026-09-18 · Branch: `c9/generator-sources-deploy` (from `c8/remote-access-first-run` @ `86f4d37`)
Authority: Meta Prompt §C9, §D1–D3 · Companion: `source-capability-ledger.md`

Current handoff status (2026-09-20 workspace date): application work and source adapters are preserved;
Fedora container verification remains open. Historical C9 sections below retain their dated evidence.
Fresh handoff results: backend **989 passed, 1 skipped, 8 deselected**; frontend **196 passed** and
production build passed; deployment subset **58 passed, 1 skipped**. ShellCheck is the skipped tool.
See `../plan/release-handoff.md` for live-source and publication outcomes. This is not a final release PASS.

## 1. Environment and commands

| Item | Value |
|---|---|
| Host | Linux 7.1.10 (Fedora 44), x86-64 |
| Python | 3.14.7 (venv at `backend/.venv`) |
| SQLite | 3.51.2 (FTS5 available) |
| Key dependencies | fastapi 0.141.1 · aiohttp 3.14.3 · scrapling 0.4.15 · webauthn 3.0.0 · playwright 1.63 · google-re2 · cryptography 50.0.1 |
| Commit at recording | `1b9d20b` |
| Container runtime | **none** (`docker`, `podman` absent) — EB-1 |

```sh
cd backend
.venv/bin/pytest                                             # → 954 passed, 1 skipped, 8 deselected (2026-09-21)
ONESHELF_LIVE_SOURCES=1 .venv/bin/pytest tests/live -m live   # → 8 passed (real sources, 2026-09-21)
ONESHELF_DATA_DIR=./var .venv/bin/python -m oneshelf.api.app  # → serves; /api/ready reports ready:true, schema 12
```

The default run is offline and deterministic; current totals are recorded above. Live source checks are a separate,
opt-in suite (`-m live`, `ONESHELF_LIVE_SOURCES=1`), exactly as C9 requires.

## 2. Gate checklist (Meta Prompt §C9)

| Gate item | Evidence | Result |
|---|---|---|
| Generator is a real subsystem, not a placeholder | `generator/{discovery,structure,draft,repair,service}.py` plus `api/generator.py`; 25 tests in `tests/integration/generator/` | Pass |
| Pipeline: URL → static discovery → mapping → capabilities → `.osp` draft | `test_discovery.py` (search route from the pasted URL or a form, result shape, work page sampled twice, chapter list, reader images) | Pass |
| Capability states Confirmed / Probable / Unknown / Unsupported | `test_a_javascript_only_page_is_reported_rather_than_guessed`, `test_unsupported_capabilities_are_left_out_rather_than_guessed` | Pass |
| Source and CDN domains separated from ads and analytics | `test_source_and_cdn_domains_are_separated_from_third_parties` — candidates are fetched before becoming permissions; `tracker.example` lands in `rejected_domains` | Pass |
| Declarative `.osp` output with automatic manifest, recipes, safe transforms | `test_the_draft_is_a_valid_package_that_the_runtime_accepts` (strict schema, RE2, transform allowlist) | Pass |
| Sanity beyond "a selector returned something" | `test_generated_adapter.py`: the generated package runs in the real runtime and returns the right titles, listing keys, units **in source order** and page images | Pass |
| Automated tests in the generated package | `test_the_draft_carries_offline_tests_with_captured_fixtures`, `test_the_generated_package_passes_its_own_packaged_tests` | Pass |
| Preview and Recipe Inspector | `test_discovery_preview_shows_recipes_confidence_and_every_fetch` — recipes, confidence, the permissions an install would ask for, and every fetch made | Pass |
| Generate ≠ Install; no auto-publish | `test_generate_writes_a_package_and_does_not_install_it`, `test_a_submission_bundle_is_prepared_locally_and_never_published`; installing is a separate call with its own permission approval | Pass |
| Repair: diff, validate, atomic activation, rollback | `test_repair.py` and `test_repair_diffs_and_validates_before_the_developer_installs`: the site is redesigned, diagnosis reports `catalog` broken (and `reader` honestly unchecked), repair produces 0.1.1 with a selector diff, validation passes, activation is a separate call; an unvalidatable repair is refused and leaves the installed version untouched | Pass |
| Unsupported declarative sites are named, not hacked | `RepairError` wording and `draft.unsupported`; no stealth path exists (`tests/unit/test_no_stealth.py`) | Pass |
| Required initial suite | Eight packages ship (`oneshelf.mangadex`, `oneshelf.gutenberg`, `oneshelf.arxiv`, `oneshelf.standard-ebooks`, `oneshelf.webtoon`) plus the OneShelf Test Source; Tapas, Safahat/Hindawi and 3asq are recorded with dated evidence in the capability ledger | **Partial — see §4** |
| Artefacts verified by opening them | The live suite unzips the Gutenberg and Standard Ebooks EPUBs and checks `META-INF/container.xml`; the arXiv PDF is checked for `%PDF-`; downloads elsewhere are validated by the integrity layer before commit | Pass |
| Offline deterministic vs live integration separated | `-m 'not live'` is the default in `pyproject.toml`; each package carries fixtures captured from the same responses | Pass |
| Docker deployment with separate mounts | `deploy/Dockerfile`, `deploy/compose.yaml`: `/data`, `/plugins`, `/keys`, `/content`, `/backups`, non-root user, healthcheck on `/api/ready` | **Blocked — EB-1** |
| Startup and readiness behaviour | `test_readiness_reports_what_startup_actually_did`; verified by running the module directly | Pass |
| API, event and plugin/generator documentation | `docs/api.md` (107 routes), `docs/plugins.md`, `docs/operations.md` | Pass |
| Migration and recovery instructions | `docs/operations.md` §6–§8, consistent with `db/migrate.py` and `services/startup.py` | Pass |
| No stealth or blanket backup defaults copied into deployment | `tests/unit/test_no_stealth.py`; the compose file starts loopback-only and backup locations are chosen explicitly | Pass |
| Blocked gates documented, not claimed | This section, §4 and the capability ledger | Pass |

## 3. Runtime changes real sources required

Each was written test-first and is covered by its own test:

| Change | Why | Test |
|---|---|---|
| Markup parsing tolerates an XML declaration | arXiv and OPDS are Atom feeds | `tests/unit/plugins/test_runtime_documents.py` |
| A field may be a declarative `template` over document-level `values`, the item and inputs | MangaDex builds page URLs from a base URL, a hash and bare filenames | `tests/unit/plugins/test_templates.py`, `test_templates_compose_resource_urls_from_document_values` |
| `language` is an allowed recipe input, supplied by the core from the track | Multi-language sources (§4 Language Track, §41.3) | `test_a_recipe_may_ask_for_the_tracks_language_but_not_arbitrary_inputs`, `test_capability_inputs.py` |
| A recipe may follow a URL its own catalogue produced, as the whole request | Direct-URL sources (§8); the egress policy still gates the fetch | `test_a_recipe_may_follow_a_url_its_own_catalog_produced` |
| Inputs a recipe does not declare are dropped, not fatal | The core can offer context without breaking older packages | `test_inputs_a_recipe_does_not_declare_are_dropped_rather_than_failing` |


## 3a. The Final Release Gate — what the Fedora host must run

**Not executed in ai-box.** No Docker/Podman executable or runtime socket is available there.
Run the following in Bash on the Fedora host, with Podman, a current Compose provider, Git, curl and
Python 3 installed. Do not run it inside ai-box. Use a fresh disposable checkout: the generated PDF
contains one blank page and no personal content. The commands preserve its volumes at the end.

### 1. Public clean clone and install

```bash
set -euo pipefail
RELEASE_DIR=$(mktemp -d "$HOME/oneshelf-release-XXXXXX")
export COMPOSE_PROJECT_NAME="oneshelf-release-$(date +%s)"
export ONESHELF_RUNTIME=podman
mkdir "$RELEASE_DIR/evidence"
export EVIDENCE="$RELEASE_DIR/evidence"
git clone https://github.com/IPurplel/OneShelf.git "$RELEASE_DIR/OneShelf"
cd "$RELEASE_DIR/OneShelf"
git rev-parse HEAD | tee "$EVIDENCE/commit.txt"
git ls-remote origin refs/heads/main | tee "$EVIDENCE/remote-main.txt"
podman --version | tee "$EVIDENCE/runtime.txt"
podman compose version | tee "$EVIDENCE/compose.txt"
getenforce | tee "$EVIDENCE/selinux.txt"
# Port 8420 must be free. For another port set ONESHELF_PORT before installation.
./install.sh 2>&1 | tee "$EVIDENCE/install.txt"
compose() { podman compose --env-file .env -p "$COMPOSE_PROJECT_NAME" -f deploy/compose.yaml "$@"; }
export GATE_URL="http://127.0.0.1:${ONESHELF_PORT:-8420}"
wait_ready() {
  python3 - <<'PY'
import json, os, time, urllib.request
opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
for attempt in range(90):
    try:
        with opener.open(os.environ['GATE_URL'] + '/api/ready', timeout=5) as r:
            ready = json.load(r)
        if ready.get('ready') is True and ready.get('migrations_pending') == 0:
            print(json.dumps(ready)); break
    except (OSError, ValueError):
        pass
    time.sleep(2)
else:
    raise SystemExit('readiness timed out')
PY
}
wait_ready | tee "$EVIDENCE/ready-before.json"
curl -fsS "$GATE_URL/api/health" | tee "$EVIDENCE/health.json"
python3 - <<'PY'
import json, os
from pathlib import Path
health = json.loads((Path(os.environ['EVIDENCE'])/'health.json').read_text())
assert health['status'] == 'ok' and health['access'] == 'loopback', health
PY
curl -fsS "$GATE_URL/" -o "$EVIDENCE/index.html"
# The eight official sources arrive with the install, through the normal plugin pipeline.
compose exec -T oneshelf ls /app/plugins/official | tee "$EVIDENCE/bundled-in-image.txt"
curl -fsS "$GATE_URL/api/sources" | tee "$EVIDENCE/sources-fresh.json"
python3 - <<'PY'
import json, os
from pathlib import Path
p = Path(os.environ['EVIDENCE'])
expected = {"oneshelf.3asq", "oneshelf.arxiv", "oneshelf.gutenberg", "oneshelf.hindawi", "oneshelf.mangadex",
            "oneshelf.standard-ebooks", "oneshelf.tapas", "oneshelf.webtoon"}
assert {n for n in (p/'bundled-in-image.txt').read_text().split() if n.startswith('oneshelf.')} == expected
assert 'UPSTREAM.json' in (p/'bundled-in-image.txt').read_text().split()   # the snapshot's provenance ships with it
sources = {s['id']: s for s in json.loads((p/'sources-fresh.json').read_text())['sources']}
assert set(sources) == expected, sorted(sources)
for s in sources.values():
    assert (s['state'], s['trust_label'], s['channel']) == ('active', 'official', 'bundled'), s
    assert s['capabilities'], s
ready = json.loads((p/'ready-before.json').read_text())
assert ready['bundled_sources']['failed'] == [] and len(ready['bundled_sources']['installed']) == 8, ready
PY
# The Official Source Registry answers from inside the container, and reads the eight as installed.
curl -fsS "$GATE_URL/api/registry" | tee "$EVIDENCE/registry.json"
python3 -c "import json,sys; d=json.load(open(sys.argv[1])); assert d['configured'] and len(d['plugins'])==8 and {p['state'] for p in d['plugins']}=={'installed'}, d" "$EVIDENCE/registry.json"
# No key file anywhere in the application (/app); system CA bundles elsewhere are expected.
compose exec -T oneshelf sh -c 'find / -xdev \( -name "*.pem" -o -name "*.key" -o -name "*.p8" \) -path "/app/*" 2>/dev/null' | tee "$EVIDENCE/keys-in-image.txt"
test ! -s "$EVIDENCE/keys-in-image.txt"
```

Open the printed URL and confirm the interface loads. Keep the default loopback binding for this
local gate. A separate LAN test must deliberately configure a trusted subnet; reverse proxies must
be configured as trusted proxies before public exposure. Never add a bridge gateway as a shortcut.

### 2. Register storage and import an actual PDF through the application

```bash
curl -fsS -X POST "$GATE_URL/api/storage/roots" -H 'Content-Type: application/json' \
  -d '{"name":"Release gate","path":"/content"}' | tee "$EVIDENCE/root.json"
compose exec -T oneshelf python -c \
  'import sys; from pypdf import PdfWriter; w=PdfWriter(); w.add_blank_page(width=300,height=400); w.write(sys.stdout.buffer)' \
  > "$EVIDENCE/gate.pdf"
curl -fsS -X POST "$GATE_URL/api/import/uploads?filename=release-gate.pdf" \
  -H 'Content-Type: application/pdf' --data-binary "@$EVIDENCE/gate.pdf" > "$EVIDENCE/upload.json"
python3 - <<'PY' > "$EVIDENCE/import-request.json"
import json, os
from pathlib import Path
upload=json.loads((Path(os.environ['EVIDENCE'])/'upload.json').read_text())
print(json.dumps({'upload_id': upload['upload_id'], 'title': 'OneShelf release gate',
                  'content_type': 'book', 'language': 'en', 'mode': 'copy', 'add_to_shelf': True}))
PY
curl -fsS -X POST "$GATE_URL/api/import" -H 'Content-Type: application/json' \
  --data-binary "@$EVIDENCE/import-request.json" > "$EVIDENCE/import.json"
check_library() {
  curl -fsS "$GATE_URL/api/shelf" > "$EVIDENCE/shelf-current.json"
  python3 - <<'PY'
import json, os
from pathlib import Path
p=Path(os.environ['EVIDENCE'])
work=json.loads((p/'import.json').read_text())['work_id']
shelf=json.loads((p/'shelf-current.json').read_text())
assert any(row['work_id']==work for row in shelf['entries']), 'imported work missing'
PY
  compose exec -T oneshelf python -c \
    'import pathlib,hashlib,json; p=pathlib.Path("/content"); files={str(f.relative_to(p)):hashlib.sha256(f.read_bytes()).hexdigest() for f in p.rglob("*") if f.is_file() and f.name!=".oneshelf-managed"}; assert files; print(json.dumps(files,sort_keys=True))' \
    > "$EVIDENCE/content-current.json"
  cmp "$EVIDENCE/content-before.json" "$EVIDENCE/content-current.json"
}
compose exec -T oneshelf python -c \
  'import pathlib,hashlib,json; p=pathlib.Path("/content"); files={str(f.relative_to(p)):hashlib.sha256(f.read_bytes()).hexdigest() for f in p.rglob("*") if f.is_file() and f.name!=".oneshelf-managed"}; assert files; print(json.dumps(files,sort_keys=True))' \
  > "$EVIDENCE/content-before.json"
check_library
curl -fsS -X POST "$GATE_URL/api/backups" -H 'Content-Type: application/json' \
  -d '{"kind":"library"}' > "$EVIDENCE/backup.json"
test -n "$(find deploy/volumes/backups -maxdepth 1 -name '*.osbackup' -print -quit)"
test -s deploy/volumes/keys/session.key
sha256sum .env > "$EVIDENCE/env-before.sha256"
```

### 3. Restart, then remove and recreate containers

Before restarting, change two sources the way a person would, so the gate proves those choices stand.

```bash
curl -fsS -X POST "$GATE_URL/api/sources/oneshelf.webtoon/disable" >/dev/null
curl -fsS -X DELETE "$GATE_URL/api/sources/oneshelf.tapas" >/dev/null
check_sources() {
  curl -fsS "$GATE_URL/api/sources" | python3 -c '
import json, sys
s = {x["id"]: x["state"] for x in json.load(sys.stdin)["sources"]}
assert s["oneshelf.webtoon"] == "disabled", s
assert s["oneshelf.tapas"] == "uninstalled", s
assert sum(v == "active" for v in s.values()) == 6, s
assert len(s) == 8, s
print("sources as the person left them:", s)'
}
check_sources
compose restart
wait_ready | tee "$EVIDENCE/ready-restart.json"
check_library
check_sources | tee "$EVIDENCE/sources-restart.txt"
compose down
compose up -d
wait_ready | tee "$EVIDENCE/ready-recreated.json"
check_library
check_sources | tee "$EVIDENCE/sources-recreated.txt"
python3 - <<'PY'
import json, os
from pathlib import Path
p=Path(os.environ['EVIDENCE'])
before=json.loads((p/'ready-before.json').read_text())
after=json.loads((p/'ready-recreated.json').read_text())
assert after['schema_version']==before['schema_version']
assert after['migrations_pending']==0 and after['ready'] is True
PY
compose exec -T oneshelf python -c \
  'import sqlite3; c=sqlite3.connect("/data/oneshelf.db"); assert c.execute("PRAGMA integrity_check").fetchone()[0]=="ok"; assert not c.execute("PRAGMA foreign_key_check").fetchall(); print(c.execute("SELECT version,name FROM schema_migrations ORDER BY version").fetchall())' \
  | tee "$EVIDENCE/schema.txt"
compose exec -T oneshelf id | tee "$EVIDENCE/container-user.txt"
test "$(compose exec -T oneshelf id -u | tr -d '\r')" = 10001
CONTAINER_ID=$(compose ps -q oneshelf)
for attempt in $(seq 1 30); do
  HEALTH=$(podman inspect --format '{{.State.Health.Status}}' "$CONTAINER_ID")
  [ "$HEALTH" != healthy ] || break
  sleep 2
done
printf '%s\n' "$HEALTH" | tee "$EVIDENCE/container-health.txt"
test "$HEALTH" = healthy
podman inspect --format '{{range .Mounts}}{{println .Destination}}{{end}}' "$CONTAINER_ID" \
  | tee "$EVIDENCE/mounts.txt"
# Expected: /data /data/plugins /data/backups /keys /content, plus read-only /legacy-data.
```

### 4. Update and nondestructive uninstall/reinstall

```bash
./update.sh 2>&1 | tee "$EVIDENCE/update.txt"
wait_ready | tee "$EVIDENCE/ready-update.json"
check_library
check_sources | tee "$EVIDENCE/sources-update.txt"
sha256sum -c "$EVIDENCE/env-before.sha256"
./uninstall.sh 2>&1 | tee "$EVIDENCE/uninstall.txt"
test -d deploy/volumes/data && test -d deploy/volumes/content
./install.sh 2>&1 | tee "$EVIDENCE/reinstall.txt"
wait_ready | tee "$EVIDENCE/ready-reinstalled.json"
check_library
sha256sum -c "$EVIDENCE/env-before.sha256"
./uninstall.sh
printf 'Host gate completed; retained library and evidence: %s\n' "$RELEASE_DIR"
```

The commands fail on a script error, missing imported work, changed content hash, invalid schema,
root execution, unhealthy container or configuration change. Retain the evidence outside the clone;
do not publish private logs or substitute this procedure for actual execution. A stable schema alone
is not persistence proof; the imported work and content hashes carry that assertion.

Passing this gate supplies evidence for M2/M2.1/M56, REL-01/02/03/08/09 and REL-11 — including that
the eight official sources arrive with a fresh install, and that a disabled or removed one stays that
way across restart, full recreation and `./update.sh`. Those rows remain open until
the evidence is reviewed. GitHub publication (REL-07) is independently authorized by the latest user
instruction and does not close any deployment requirement.

## 4. Blocked and partial gates

| ID | Gate | Why | What would clear it |
|---|---|---|---|
| EB-1 | Docker build, restart and recreation against isolated mounts | No container runtime on this host | Execute §3a above on the Fedora host and retain the generated evidence |
| ~~EB-2~~ | ~~C2 visual checks~~ | **Cleared 2026-09-18**: the reference was supplied, the UI was corrected against it, and C2's checks ran — see `docs/c2/verification.md` | — |
| ~~§41 suite~~ | ~~3asq / Al-Aasheq~~ | **Cleared 2026-09-21**: `3asq.org` was a dead domain, not an unreachable host — the source moved to `3asq.online`. The adapter ships and is verified live, so **all eight §41 sources are done** and M41.1 is `VERIFIED`. | — |
| ~~§53~~ | ~~Full UI, accessibility and RTL test categories~~ | **Cleared 2026-09-18**: all twenty-six categories audited against the suite in `docs/c9/test-categories.md`; one gap (queue restart recovery) was filled | — |
| ~~INV-29~~ | ~~Telemetry audit of records, diagnostics, network calls and cleanup~~ | **Cleared 2026-09-18**: audited and now held by `tests/unit/test_no_matcher_telemetry.py`; see `docs/c9/test-categories.md` | — |

None of these are worked around, and none are claimed as passing.

## 5. What C9 delivers

| Area | Modules |
|---|---|
| Discovery and structural analysis | `generator/discovery.py`, `generator/structure.py` |
| Draft `.osp` emission with captured fixtures | `generator/draft.py` |
| Diagnosis, repair, versioned replacement | `generator/repair.py` |
| Generator sessions and HTTP surface | `generator/service.py`, `api/generator.py`, migration `0012_generator.sql` |
| Official source packages | `plugins/official/*`, `plugins/build.py` |
| Live source integration suite | `tests/live/test_source_suite.py` (opt-in) |
| Deployment | `deploy/Dockerfile`, `deploy/compose.yaml`, `GET /api/ready` |
| Documentation | `docs/api.md`, `docs/plugins.md`, `docs/operations.md`, `docs/c9/source-capability-ledger.md` |

## 6. Open items for review (ledger §14)

| ID | Item |
|---|---|
| D-C9-01 | The declarative `template` field and document-level `values` extend the `.osp` schema within `api: '1.0'`; older readers would not understand a package that uses them. |
| D-C9-05 | WEBTOON ships without search (robots) and without a reader (JavaScript viewer) rather than not shipping at all. |
| D-C9-06 | Generated adapters are installed through the generator's own endpoint, which only accepts packages from its work directory. |

## 6. Real-browser verification: opening search results, and covers (2026-09-21)

Both defects were found by running the real UI. Reproduced first on `475c145`: a real search for
"frankenstein" gave 50 results, **0 links** (every card an inert `<span>`), clicking changed nothing, and **0 covers**
(no cover field anywhere in the API response).

After the fix — the real application from a fresh library with the bundled official sources, Chromium, real network:

| Step | Result |
|---|---|
| Search "frankenstein" | 50 cards: 50 buttons, 0 inert; 5 real covers loaded through `/api/covers`, the rest placeholders (MangaDex offers none in search) |
| Activate a grouped Gutenberg result with the keyboard | chooser listed each edition by source, language and its own title |
| Choose one | Work page: title, 1 unit, cover loaded |
| Add to shelf → My Shelf; Home | cover on the Shelf card; 4 covers on Home |
| Search "yotsuba" (MangaDex) | placeholders, cards still open (see I-51 for MangaDex languages) |
| Search "one piece" → a 3asq result | Work "One Piece", 567 units, cover loaded |
| Open the first unit | Reader: 4 page images loaded |
| Arabic UI, search "ون بيس" | `dir=rtl`, 12 cards, 8 covers, 0 inert |

Screenshots: `screenshots-search-covers.png`, `screenshots-work-cover.png`, `screenshots-shelf-cover.png`,
`screenshots-work-from-search-3asq.png`, `screenshots-reader-from-search.png`, `screenshots-search-covers-ar.png`.
The first run of this check failed on a real Gutenberg timeout (I-49); it was fixed and the check re-run.
