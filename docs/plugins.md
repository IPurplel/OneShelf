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
  permissions. A submission bundle can be written to disk; nothing is ever published.
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

## 7. The Official Source Registry

The same eight adapters are also published as a **Registry**: `registry/index.json` and
`registry/packages/<id>-<version>.osp` in this repository, served over HTTPS from
`https://raw.githubusercontent.com/IPurplel/OneShelf/main/registry/index.json` (the default
`ONESHELF_REGISTRY_URL`). Bundled and Registry are two ways a package *arrives*; there is one plugin
architecture, one `PluginManager` pipeline and one lifecycle per plugin id.

**Sources → Official Source Registry** reads the index and sets each entry against the library:

| State | Shown as | Action |
|---|---|---|
| Same version installed | Installed | none |
| Not installed, or removed by you | Not installed | Install |
| Newer in the Registry | Update available: 1.0.0 → 1.1.0 (or *Disabled · Update available*) | Update |
| That newer version already waits for review | Version … is waiting for your review | Review update |
| Installed version is newer than the Registry's | Your installed version … is newer | none — no downgrade |
| Needs a newer plugin API than this OneShelf | Requires a newer OneShelf | none |

Every action opens a **review** first (`POST /api/registry/review-package`): the package is downloaded,
hash-checked against the index, validated, and its packaged tests are run — nothing is installed. The review
shows publisher, version, trust, capabilities, every permission with the ones an update newly asks for
marked **New**, and the test result. The install request carries the reviewed `sha256`; if the Registry's
package changed in between, the install is refused (`the package changed since it was reviewed`).

**Ownership.** Installing or updating from the Registry makes it `channel = registry`, recorded at once —
also while an update waits for review. The bundled bootstrap only ever maintains `channel = bundled`
plugins, so it never reclaims or downgrades one the Registry now owns. A removed source is never
reinstalled automatically, and neither reading the Registry nor updating a disabled source enables it.
New permissions are never approved for you, official or not.

**Trust.** The index's `trust_label` is a claim. A package is *Official* only when its sha256 carries a valid
Ed25519 signature from a key in your local `ONESHELF_REGISTRY_TRUSTED_KEYS`; unsigned or unknown-key
entries install as *Community*, and a bad signature from a trusted key is refused. Keys never come from the
index. **Until the owner's signing key exists the committed Registry is unsigned**, so the Sources screen
labels its entries *Says Official · not verified*, and a source reinstalled from it is recorded as Community.
Bundled sources are unaffected: they come from the image itself.

**If the Registry is unreachable** (offline, rate limited, malformed), the section says so with *Try again*;
installed sources, search, reading and readiness are unaffected. Failures are cached for 60 s and good
listings for 5 min, so nothing is hammered.

**Network.** Only `https://` (or a local `file://` mirror). Core's egress policy allows the index host alone;
every package location must be a plain relative `.osp` path beneath the index's own directory — no other
host, no other repository on the same host, no credentials, query, `..` or encoded tricks — and redirects are
re-checked hop by hop. Index ≤ 5 MB, package ≤ 20 MB.

### Publishing the Registry

The index is generated, never hand-edited:

```bash
cd backend
.venv/bin/python -m plugins.registry_tool build     # builds, validates and packaged-tests all eight
.venv/bin/python -m plugins.registry_tool verify    # rebuilds from source; fails on any difference
```

`build` uses the same deterministic builder as the bundled bootstrap, so Registry and bundled bytes are
identical and a fresh library reads every entry as Installed. `verify` fails on a hand-edited hash, a
replaced or stray package, a failing adapter, a registry that lags its sources, or a signature that does not
verify; `tests/integration/plugins/test_registry_tool.py` runs it against the committed `registry/`.
Bump an adapter's `version`, run `build`, commit `registry/` with the adapter.

### Signing (owner only)

```bash
# Once, on a machine you trust, OUTSIDE the repository. Nothing here is committed or uploaded.
umask 077
mkdir -p ~/.config/oneshelf-registry
openssl genpkey -algorithm ed25519 -out ~/.config/oneshelf-registry/official-2026.pem
# Back this file up offline now (encrypted drive or password manager). It is the only copy.

cd OneShelf/backend
# The PUBLIC half, in the form ONESHELF_REGISTRY_TRUSTED_KEYS expects — this line is safe to publish:
.venv/bin/python -m plugins.registry_tool public-key \
    --signing-key ~/.config/oneshelf-registry/official-2026.pem --key-id official-2026
# Sign the Registry, then prove it verifies against the public key alone:
.venv/bin/python -m plugins.registry_tool build \
    --signing-key ~/.config/oneshelf-registry/official-2026.pem --key-id official-2026
.venv/bin/python -m plugins.registry_tool verify --trusted-keys "official-2026:<PUBLIC-BASE64>" --require-signed
```

Then set that public line as the default `ONESHELF_REGISTRY_TRUSTED_KEYS` in `deploy/compose.yaml` and
`.env.example` (and update `tests/deploy/test_registry_defaults.py`, which pins "no key shipped yet"), and
commit `registry/` with them. `ONESHELF_REGISTRY_SIGNING_KEY_FILE=~/.config/oneshelf-registry/official-2026.pem`
may replace `--signing-key`. The tool refuses a key inside the work tree, and `.gitignore` and
`.dockerignore` exclude `*.pem`, `*.key` and `*.p8`.

**Rotation.** Generate a new key (`official-2027`), trust both
(`official-2026:<old>,official-2027:<new>`), re-sign the Registry with the new key and release; once
installations have updated, remove the old key from the trusted list. A key is never taken from the index.
