# C4 — Verification Report: Catalog Trust, Local-First Discovery, Persistent Identity

Recorded: 2026-09-17 · Branch: `c4/catalog-search` (from `c3/source-runtime` @ `5bbd2b9`) · Authority: Meta Prompt §C4
Status: **C4 gate passed** for the backend described below. Search/Home/Work screens are C2; Download Missing is C5; Follow baselines, Completed status and notifications are C6.

## Commands and results

```sh
cd backend
.venv/bin/pytest          # → 526 passed (C1 158 + C3 279 + C4 89), no warnings
```

No new runtime dependencies: C4 uses SQLite FTS5, the C3 source runtime and the existing governor.

## Gate checklist (Meta Prompt §C4)

| Gate item | Evidence | Result |
|---|---|---|
| Catalog 300→7, incomplete pagination and retry sequences | `tests/integration/catalog/test_trust.py` (first trusted catalog; incomplete refresh preserves trusted; bounded incomplete history; 300→7 suspicious; two agreeing checks recover; a different second candidate does not; return to the trusted reality clears candidates; heuristic boundaries 300→297, 6→2, 10→5; growth/reordering; metadata-only change; reappearing unit) · `tests/integration/test_discovery_api.py` (live Test Source: 300 → collapse → suspicious → explicit trust; `fail_page_3` → incomplete, trusted count unchanged, trusting an incomplete snapshot refused) | Pass |
| Trusted-only Download Missing / baselines | `CatalogTrust.trusted_catalog()` is the only accessor for catalog-dependent decisions; suspicious and incomplete snapshots are stored separately and never returned by it (`test_trust.py`, `GET /api/tracks/{id}/catalog`). Consumed by C5/C6. | Pass (consumers carried forward) |
| Same-title adaptations and source variants | `test_mapping_and_grouping.py::test_adaptations_are_not_grouped`, `test_results_represent_works_not_duplicated_source_cards`, `test_covers_never_create_identity` | Pass |
| Manual mapping persistence | merge / split / unlink / never-match tests, `test_evidence_never_overrides_a_user_mapping`, API mapping actions | Pass |
| Aliases / title changes | `test_source_title_changes_keep_the_previous_title_as_history` (old title still finds the Work), merge keeps the other Work's title as history | Pass |
| Arabic regressions and no-stemming | `tests/unit/search/test_ranking.py` (loose ة↔ه only at the loose level, diacritics/tatweel/alef forms, Arabic-Indic digits, articles never stripped) · `test_index.py` (normalized and loose local search) | Pass |
| Stale plugin-cache invalidation | `tests/unit/search/test_cache.py` (namespace per source+plugin version, TTL, LRU cap, clear) · API: second search is `cached`, `refresh=true` bypasses, a new plugin version re-fetches | Pass |
| Local results surviving live failures | `test_search_service.py` (failing source keeps others and local results; rate-limited source reported retryable; slow source does not block; retry returns its results) | Pass |
| Soft-group actions binding to concrete tracks | `test_soft_grouping_presents_one_work_without_writing_anything` (no rows written) and `test_actions_bind_to_the_concrete_listing_and_track` / `POST /api/listings/bind` (listing + track persisted with source and language) | Pass |
| No persistent default search-query collection | cache stores hashed keys only (`test_query_text_is_not_stored`), search writes nothing to the library DB (`test_search_writes_nothing_durable_about_the_query`), no query-history table or endpoint | Pass |

## What C4 delivers (backend)

| Area | Modules |
|---|---|
| Catalog trust, snapshots, unit materialization | `catalog/trust.py`, migration `0004_catalog.sql` |
| Search keys, tiers, local FTS index | `search/normalize.py`, `search/ranking.py`, `search/index.py`, migration `0005_search.sql` |
| Soft grouping and concrete listing binding | `search/grouping.py`, migration `0006_listing_mapping.sql` |
| Merge / Split / Unlink / Never Match | `search/mapping.py` |
| Discovery Cache | `search/cache.py` (own `cache.db`) |
| Local-first search with progressive enrichment | `search/service.py` |
| Direct URL entry | `search/url_resolve.py` |
| Home discovery semantics | `discovery/home.py` |
| API | `api/discovery.py`: `GET /api/search` (SSE), `POST /api/search/retry`, `POST /api/resolve-url`, `GET /api/home`, `POST /api/listings/bind`, `GET|POST /api/tracks/{id}/catalog[/refresh|/trust]`, `POST /api/mappings/{merge,split,unlink,never-match}` |

## Known limitations / carried forward (not gate failures)

- **Download Missing and Follow baselines** consume `trusted_catalog()` in C5/C6; C4 only guarantees what may be trusted.
- **Completed status and "N releases since completion"** (§5.6) belong to C6 together with release events.
- **Hero "relevant new-release Work"** (§31.4 second priority) needs Follow data (C6); C4 uses Continue Reading → pinned → cached discovery.
- **Trending aggregation across sources** groups listings but does not rank popularity, by design (§31.1: no invented global score).
- **Search UI**, Work Details and the Sources screens are C2.
- **Live real-world sources** (§41.1) still unverified from this environment (EB-3); the C4 gate uses the controlled Test Source.
