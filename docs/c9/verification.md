# C9 — Verification Report: Generator, Source Suite, Deployment

Recorded: 2026-09-18 · Branch: `c9/generator-sources-deploy` (from `c8/remote-access-first-run` @ `86f4d37`)
Authority: Meta Prompt §C9, §D1–D3 · Companion: `source-capability-ledger.md`

Status: **C9 backend gates passed except the ones blocked below.** The Docker image cannot be built or
restarted here, and the C2 frontend does not exist yet, so this is not a claim that the whole application is
complete.

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

The default run is offline and deterministic: 772 tests, no network. Live source checks are a separate,
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

This is the one gate that cannot run in the development container: there is no container runtime in
it, and installing one there would prove nothing about a real machine. Run this on the Fedora host.
Podman is the primary path; Docker behaves the same and the scripts detect either.

Everything below is verbatim. Nothing needs to be adapted.

### 1. A clean checkout, installed the way anyone would

```sh
cd ~                                  # anywhere outside the development checkout
git clone https://github.com/IPurplel/OneShelf.git
cd OneShelf
./install.sh
```

Expected: it finds Podman, finds Compose, creates `.env`, builds, starts, waits, and prints
`OneShelf is running at http://127.0.0.1:8420`. It must exit 0.

### 2. It is actually up

```sh
curl -fsS http://127.0.0.1:8420/api/ready   ; echo
curl -fsS http://127.0.0.1:8420/api/health  ; echo
```

Expected: `ready: true`, `migrations_pending: 0`, a `recovery` block; and `status: ok` with
`access: loopback`. Open <http://127.0.0.1:8420> in a browser — the interface must load, not a 404.

### 3. Put a real library in it

```sh
curl -fsS -X POST http://127.0.0.1:8420/api/storage/roots \
     -H 'Content-Type: application/json' -d '{"name":"Library","path":"/content"}' ; echo
```

Then import a file through the interface (Home → Import), or with the API, and note the work's title.

```sh
curl -fsS http://127.0.0.1:8420/api/shelf | head -c 400 ; echo
SCHEMA_BEFORE=$(curl -fsS http://127.0.0.1:8420/api/ready | grep -o '"schema_version":[0-9]*')
echo "$SCHEMA_BEFORE"
ls deploy/volumes/content
```

### 4. Restart

```sh
podman compose -f deploy/compose.yaml restart
sleep 10
curl -fsS http://127.0.0.1:8420/api/shelf | head -c 400 ; echo
```

Expected: the same work is still there.

### 5. Full recreation — the case that would lose anything written inside the container

```sh
podman compose -f deploy/compose.yaml down
podman compose -f deploy/compose.yaml up -d
sleep 20
curl -fsS http://127.0.0.1:8420/api/ready ; echo
curl -fsS http://127.0.0.1:8420/api/shelf | head -c 400 ; echo
ls deploy/volumes/content
```

Expected: ready again, **the same `schema_version` as before** and `migrations_pending: 0` — a
re-migration here would mean the database was not the same one — the same work on the shelf, and the
file still in `deploy/volumes/content`.

### 6. It runs unprivileged and reports its own health

```sh
podman compose -f deploy/compose.yaml exec oneshelf id
podman inspect --format '{{.State.Health.Status}}' "$(podman compose -f deploy/compose.yaml ps -q oneshelf)"
```

Expected: `uid=10001` (not 0), and `healthy`.

### 7. Update is safe

```sh
./update.sh
curl -fsS http://127.0.0.1:8420/api/shelf | head -c 400 ; echo
```

Expected: it rebuilds, restarts, reports ready and healthy, and the same work is still there. (With
no upstream change it should say so and rebuild what is present.)

### 8. Uninstall keeps the library

```sh
./uninstall.sh
ls deploy/volumes/data deploy/volumes/content
./install.sh
curl -fsS http://127.0.0.1:8420/api/shelf | head -c 400 ; echo
```

Expected: `uninstall.sh` says the library has been kept, the directories still hold the files, and
reinstalling brings the same library back.

### What passing this closes

M2, M2.1 and M56's Docker clause move to `VERIFIED`, and REL-01, REL-02, REL-03 and REL-08 with them.
REL-07 (publishing) and REL-09 (clean-clone against the published repository) follow.

### What would fail it

A non-zero exit from any script; a re-migration or a changed `schema_version` at step 5; an empty
shelf after recreation; a missing file under `deploy/volumes/content`; `id` reporting uid 0; an
unhealthy container; or `uninstall.sh` removing anything at step 8.

## 4. Blocked and partial gates

| ID | Gate | Why | What would clear it |
|---|---|---|---|
| EB-1 | Docker build, restart and recreation against isolated mounts | No container runtime on this host | Run `docker compose up -d --build` on a host with Docker or Podman, then restart and recreate the container and confirm the library survives on the mounts |
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
