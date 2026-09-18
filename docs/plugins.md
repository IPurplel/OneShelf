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
