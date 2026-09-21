# Declarative sources and the Adapter Generator

How a `.osp` package is written, what the runtime will and will not do with it, and how the generator
produces and repairs one. Authority: Master §9–12, §41.

## 1. A package is data, not code

An `.osp` is a ZIP with a fixed shape:

```
manifest.yaml          identity, capabilities, the domains it may reach
source.yaml            base URL, URL patterns, rate limits, timeouts
recipes/<capability>.yaml
tests/tests.yaml       cases with fixtures — mandatory
tests/fixtures/…       captured pages the cases run against, offline
```

There is no executable code anywhere in a package, and none is ever run. YAML is parsed with a restricted
loader, regular expressions are RE2 (linear time, bounded), selectors are validated at install time, and
transforms come from a fixed list. A package that tries to smuggle code, an unbounded pattern, a path
payload or an undeclared domain is rejected before it is installed.

## 2. Manifest

```yaml
schema: oneshelf.osp/1
id: oneshelf.example            # lowercase, dotted
name: Example
version: 1.0.0
api: '1.0'
capabilities: [search, work, catalog, reader]     # each needs a recipe
network:
  domains: [api.example.com]                      # the source itself
  cdn_domains: ['*.media.example.com']            # media hosts; wildcards allowed
  allow_http: false
auth:                                             # optional
  login_url: https://example.com/login
  session_domains: [example.com]
  optional_for: [catalog, reader]
defaults:
  language: en
```

Permissions are derived from this, never declared separately: `network:domain:…`, `network:cdn:…`,
`network:http`, `browser:<capability>`, `session:required|optional:<capability>`. The user approves that exact
list at install time, and a version that asks for more must be approved again.

## 3. Recipes

One file per capability. A recipe is a request plus an extraction:

```yaml
capability: search
inputs: [query, offset]          # from: query, page, offset, cursor, listing_key, unit_key, url, language
request:
  url: "{base_url}/search?q={query}&start={offset}"
  headers: {Accept: application/json}
  fetch: http                    # or browser, if the manifest declares it for this capability
  auth: none                     # none | optional | required, matching manifest.auth
response:
  format: json                   # or html (which also parses XML feeds such as Atom and OPDS)
extract:
  values:                        # optional: read once per page, usable by templates
    base: {json: "$.baseUrl"}
  items: {json: "$.data[*]"}     # omit for single-object capabilities such as work
  order: source_listed           # or reverse, when the site lists newest first
  fields:
    listing_key: {json: "$.id", required: true}
    title: {json: "$.attributes.title[*]", required: true}
    cover_url: {template: "{base}/covers/{item}.jpg"}
pagination:
  mode: offset                   # none | page_number | offset | next_link
  start: 0
  step: 20
  max_pages: 5
  stop_when: total_count
  total: {json: "$.total"}
```

Field values come from exactly one of `css`, `xpath`, `json` or `template`, optionally through a transform
pipeline (`trim`, `extract_number`, `normalize_arabic`, `html_decode`, `url_decode`, `base64_decode`,
`normalize_url`, `parse_date`, `replace`, `regex_extract`, `regex_replace`, `split`, `join`).

Two rules exist because real sources need them, and neither widens the security boundary:

- **Templates** compose a value from document-level `values`, the current `item` and the recipe's inputs.
  MangaDex returns a base URL, a hash and bare filenames; the page URLs are built from those three.
  A template whose parts are missing yields nothing rather than half a URL.
- **`{url}` as the whole request** lets a recipe follow a URL the source's own catalogue produced (§8). The
  egress policy still decides whether that URL may be fetched, so an adapter cannot be steered elsewhere.

Field names are fixed per capability (for example `catalog` accepts `unit_key`, `title`, `number`, `volume`,
`unit_type`, `url`, `release_date`), so a recipe cannot invent library concepts.

## 4. Packaged tests are mandatory

`tests/tests.yaml` declares cases with the fixtures they run against:

```yaml
cases:
- capability: search
  inputs: {query: dungeon}
  fixtures:
  - url: https://api.example.com/search?q=dungeon
    file: fixtures/search.json
  expect:
    min_items: 1
    fields_present: [listing_key, title]
    first: {listing_key: '84', title: 'Frankenstein'}
```

They run offline during install (the Tested stage of Staged → Validated → Tested → Active). A package whose
own tests fail is not activated.

## 5. The generator

`POST /api/generator/drafts` with a URL from the site runs: static discovery → site mapping → capabilities →
`.osp` draft. It reports each capability as **Confirmed**, **Probable**, **Unknown** or **Unsupported**, and
says why — a page that builds itself with JavaScript is named as such instead of being guessed at.

- Only hosts that actually served content the adapter needs become permissions; ads and analytics hosts are
  listed as rejected.
- The preview is the Recipe Inspector: the recipes, the confidence, the permissions an install would request,
  and every fetch discovery made.
- **Generate is not Install.** Generate writes a validated `.osp`; installing is a separate call that approves
  permissions. A submission bundle can be written to disk; nothing is ever published. To contribute it,
  copy the bundle's files into `adapters/community/<id>/` in [OneShelf-Adapters](https://github.com/IPurplel/OneShelf-Adapters) and follow its
  CONTRIBUTING.md — generating, installing and publishing stay separate steps.
- **Repair** diagnoses the installed adapter against the live site, re-discovers, shows a selector diff, writes
  a new version and validates it. Activation is another explicit call, and a repair that cannot be validated is
  refused so the working adapter stays in place.

For a site that genuinely cannot be expressed — proprietary encrypted or signed behaviour — the honest answers
are *Unsupported by Declarative Adapter* and *Native Adapter Review Required*. Do not force a hack.

## 6. The shipped suite

`backend/plugins/official/` holds the packages that ship with OneShelf, and
`docs/c9/source-capability-ledger.md` records what each one was actually verified to do, what is missing and
why. `backend/testsource/` is the OneShelf Test Source: a local, deterministic source for failure and recovery
testing (rate limits, 500s, session expiry, corrupt media, interrupted downloads, catalogue collapse), enabled
only when `ONESHELF_DEV_TEST_SOURCE=1`.

### How the shipped suite is installed

Nobody installs these by hand. On a **fresh library**, the first start builds each package in
`backend/plugins/official/` with the same deterministic builder a developer uses, and installs it through
`PluginManager.install_file` — the full pipeline, packaged tests included — as `trust_label = official`,
`channel = bundled`. The result is recorded in `bundled_plugins`, and a marker in `app_meta` records that the
bootstrap has run.

After that:

| Situation | What happens on the next start |
|---|---|
| Nothing changed | Nothing. The package is recognised as already installed; no tests are re-run |
| A newer version ships, same permissions | Installed through the normal update path; the previous version is kept for rollback |
| A newer version asks for more permissions | **Waits for review.** The approved version keeps working; nothing new is approved |
| The person disabled it | Left alone — and not updated, because installing a version would re-enable it |
| The person removed it | Left alone, for good. The plugin row kept after uninstall is the evidence |
| The person reinstalled it by hand | Theirs. It is never updated for them |
| It failed to install | Recorded with its reason and raised in Needs Attention. Retried only when the bundled package changes. The library starts normally (§3.3) |
| An existing library already had official sources | Recorded as skipped. Nothing is added automatically |

Permissions are approved without a review only on that first install, for the adapters exactly as shipped,
because the owner chose that. The permission model is otherwise unchanged for bundled adapters.

To change a shipped adapter, bump its `version` in `manifest.yaml`. The builder is deterministic, so the same
sources are always the same bytes; different content under the same version is refused rather than guessed at.

## 7. OneShelf-Adapters and the Source Registry

Adapters are developed in their own repository, **[IPurplel/OneShelf-Adapters](https://github.com/IPurplel/OneShelf-Adapters)**: sources, packaged
tests, contribution guide, review policy, CI, and the published **Source Registry**. OneShelf reads that
Registry over HTTPS — there is no Git checkout, submodule or build step at runtime:

```
adapter source → PR → CI (pinned OneShelf tooling) → maintainer review → merge
  → Registry build (canonical builder, packaged tests) → signing where the tier requires it
  → verification → published on the `registry` branch
  → OneShelf: Sources → Source Registry → review → PluginManager validation, hash, signature,
    permissions → install
```

A merge is governance, not runtime trust: every later layer still applies.

**Default Registry:** `https://raw.githubusercontent.com/IPurplel/OneShelf-Adapters/registry/index.json` (set by Compose and `.env.example`; `ONESHELF_REGISTRY_URL=` switches it off).
Adapter updates reach existing installations through it without a new OneShelf release. The Registry is
read only when the Sources screen is opened — there is no background polling.

**The old default still works.** Before the move, `.env.example` shipped `https://raw.githubusercontent.com/IPurplel/OneShelf/main/registry/index.json`. `update.sh` never rewrites
`.env`, so the container start (`deploy/container_start.py`) reads exactly that value as the new default,
for the process only. Any other value is used as configured. The application itself carries no Registry
host (INV-29), which is why the translation lives in deployment. Running from source, set the new URL
yourself. Core's own `registry/` directory is a frozen, deprecated snapshot kept for older installations.

### Trust tiers

| OneShelf-Adapters tier | Registry label | OneShelf shows it as |
|---|---|---|
| `adapters/official/` | `official` | **Official** — only with a valid signature from a key in `ONESHELF_REGISTRY_TRUSTED_KEYS` |
| `adapters/verified-community/` | `verified_community` | **Verified Community** — same rule |
| `adapters/community/` | `community` | **Community** |

The tier comes from the directory, which only maintainers can change; nothing inside an adapter sets it.
OneShelf believes a label only when the signature verifies against a key the installation trusts: unsigned
or unknown-key claims are Community, and a bad signature from a trusted key is refused. Keys never come from
the Registry. Sources → Source Registry shows each entry's own level, and installed sources show trust and
delivery separately (*Official · Bundled*, *Official · Registry*, *Verified Community · Registry*,
*Community · Registry*, *Local upload*).

**Signing status:** the project signing key does not exist yet, so the Registry is published as an
**unsigned preview** — every entry reads *Says Official · not verified* and installs as Community.
The owner's one-time step is in OneShelf-Adapters' `docs/publishing.md`.

### What Sources → Source Registry does

Unchanged from before the move: each entry is set against the library (Installed, Install, Update,
Review update, Disabled · Update available, installed version newer, Requires a newer OneShelf); every
action opens a review (`POST /api/registry/review-package`) that downloads, hash-checks, validates and
packaged-tests the package without installing it; the install is bound to the reviewed sha256; a
Registry action makes the plugin `channel = registry`, which the bundled bootstrap never reclaims or
downgrades; removed sources are never reinstalled automatically; disabled sources stay disabled; new
permissions always wait for review. Adapters that OneShelf does not bundle install the same way.

### Network

Only `https://` (or a local `file://` mirror). Core's egress policy allows the index host alone, and every
package location must be a plain relative `.osp` path beneath the index's own directory — so the Registry
on `raw.githubusercontent.com` cannot point OneShelf at any other repository on that host. Redirects and DNS
answers are re-checked; index ≤ 5 MB, package ≤ 20 MB. Moving the Registry did not widen any of this.

### The bundled snapshot

`backend/plugins/official/` is a **release snapshot** of the Official adapters listed in its
`UPSTREAM.json` (`bundled`), which also records the OneShelf-Adapters commit it came from. First run installs
from it with no network access at all. It is never edited here:

```bash
cd backend
.venv/bin/python -m plugins.sync_snapshot --from ../../OneShelf-Adapters   # validates, tests, copies, records
git diff                                                                   # review, then commit yourself
```

Only allowlisted Official adapters are copied — Registry-only adapters stay out of the image. Adding one to
`bundled` is a Core release decision.

### Packages are the same bytes everywhere

The canonical builder stores entries uncompressed with fixed header fields, because zlib implementations
compress differently and a deflated package was reproducible on one platform only. OneShelf-Adapters' CI
rebuilds every published version on GitHub's runner and requires the exact published bytes. An
installation that already has a version never reinstalls it because a newer build packs it differently.

### Tooling for the adapter repository

`oneshelf.plugins.adapter_repo` (in the installed package) is what OneShelf-Adapters runs, from a Core
commit it pins: `check`, `check-all`, `reproducible`, `build-registry`, `verify-registry`, `public-key`.
Validation rules live here only.
