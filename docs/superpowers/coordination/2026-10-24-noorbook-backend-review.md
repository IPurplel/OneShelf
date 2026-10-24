## Backend Owner Coordination Decision — Noor Book Reader

**Reviewer:** Claude Code (Lead Backend, Adapter, and Reading Systems Engineer)
**Date:** 2026-10-24
**Branch:** `codex/noorbook-reader` at `8aaff477`
**Worktree:** `C:/Users/Dicev/.codex/worktrees/noorbook-reader/OneShelf` (isolated)
**Documents reviewed:** `docs/superpowers/specs/2026-10-24-noorbook-reader-design.md`, `docs/superpowers/plans/2026-10-24-noorbook-reader.md`

### Verdict: CONDITIONALLY APPROVED

Codex may implement the scoped backend/adapter changes in this isolated worktree under the contract below. The plan is well-structured, correctly identifies three integration gaps, and the proposed scope does not overreach.

---

### Confirmed integration gaps

| Gap | Location | Confirmed |
|---|---|---|
| `_online_descriptors()` ignores `ListResult.complete` | `backend/oneshelf/reader/service.py:251–266` — calls `self.sources.run()`, takes `list(result.entries)`, caches and returns without ever reading `result.complete` | Yes |
| `_validate_image()` rejects SVG | `backend/oneshelf/integrity/validators.py:133–150` — Pillow `Image.open` raises `UnidentifiedImageError` on any SVG content | Yes |
| `BrowserFetcher` is GET-only | `backend/oneshelf/sources/browser_fetcher.py:31` — raises `FetchFailed("browser retrieval supports GET navigation only")` on non-GET | Yes |

---

### Approved scope — files Codex may edit

| File | Allowed change |
|---|---|
| **NEW** `backend/oneshelf/reader/page_image.py` | Safe SVG-to-raster normalization function, under Condition 4 |
| `backend/oneshelf/reader/service.py` | (a) In `_online_descriptors()`: reject and do not cache when `result.complete is False` and entries is nonempty. Raise `CapabilityError("incomplete_result", ...)`. (b) In `_fetch_online_page()`: call the normalization function on response bytes before `_validate_image()` and `cache.put()`, only when content is detected as SVG. Raster pass-through must be unchanged. |
| `backend/oneshelf/integrity/validators.py` | **No changes.** `_validate_image()` continues to validate the *output* of normalization. SVG bytes must never reach `_validate_image()` directly. |
| `backend/oneshelf/api/library.py` | **No changes** to content headers or response contract. |
| `backend/oneshelf/plugins/schema.py` | No changes unless Task 1 proves a new pagination mode is required, which then requires a separate contract addendum. |
| `backend/oneshelf/sources/browser_fetcher.py` | No changes unless Task 1 proves a new browser interaction primitive is required, in which case report `Native Adapter Review Required` and stop. |
| **NEW** `backend/tests/unit/reader/test_page_image.py` | Unit tests for the normalization boundary |
| **Extend** `backend/tests/integration/reader/test_reading.py` | Completeness rejection test, synthetic SVG resource test |
| **Adapter repo** `adapters/community/oneshelf.noorbook/` | Declarative package only, under Condition 5 |

---

### Binding conditions

#### Condition 1 — Task 1 network replay gate is BLOCKING for the adapter

Task 1 (network replay evidence) gates adapter implementation (Task 3) and source-specific integration. No adapter recipe may be written until:

- The actual HTTP request sequence for the Read interaction is captured and documented (methods, URL patterns, required headers, response schema).
- The sequence is replayed through Core transport (`oneshelf.net.http` or `browser_fetcher`) — not just an external browser.
- The declarative feasibility decision is made: can the flow be expressed in the current recipe schema, or is a new primitive needed?
- A second title is tested to confirm the pattern generalizes.

If Core transport cannot reach the source (the design notes prior connection failures), that is a Task 1 finding, not something to work around by broadening egress or bypassing challenges. **Task 1 has not passed. Do not claim Noor Book source support before this gate clears.**

#### Condition 2 — SVG normalization may proceed independently of Task 1

The safe SVG-to-raster normalization boundary (`page_image.py`) and the completeness enforcement in `_online_descriptors()` are **general Core improvements** that benefit any future source returning SVG content. They do not depend on Noor Book network replay evidence. Codex may implement and test Task 2 (page normalization + completeness check) using synthetic fixtures before Task 1 completes. However:

- This does not constitute Noor Book reader support. A passing `test_page_image.py` with synthetic SVGs proves the normalization contract, not that the Noor Book source is reachable or its pages render faithfully.
- If Task 1 ultimately fails (Core cannot reach the source, or the flow is not declaratively expressible), the SVG normalization and completeness enforcement are still valid Core changes and may be merged on their own merit. The adapter is not.
- End-to-end Noor Book reading verification (Task 4) still requires both Task 1 and Task 2 to pass.

#### Condition 3 — Completeness enforcement contract

In `service.py:_online_descriptors()`, after line 255 (`result = await self.sources.run(...)`):

- If `result.complete is False` and `len(list(result.entries)) > 0`: do NOT cache descriptors, do NOT add to `self._descriptors`. Raise `CapabilityError("incomplete_result", f"the source returned {len(entries)} entries but could not confirm completeness ({result.evidence.stop_reason})")`.
- If `result.complete is False` and entries is empty: the existing empty-entries handler already raises — no change needed.
- If `result.complete is True`: proceed as current (cache and return).
- **Regression requirement:** Existing tests with complete sources must continue to pass. The runtime sets `complete=True` for `pagination.mode == "none"` (`runtime.py:500–502`), so single-page reader recipes are unaffected.

Required test: a reader result with 100 entries, `complete=False`, `evidence.stop_reason="page_failed"` must produce a clear error, no cached descriptors, and no partial page list served to the frontend.

#### Condition 4 — SVG normalization safety requirements

The new `page_image.py` must satisfy ALL of the following:

1. **Input detection:** Only process content that begins with `<?xml` or `<svg` (after stripping BOM and leading whitespace). All other content passes through unchanged to `_validate_image()`.
2. **Reject active content before rendering:** Before invoking any renderer, parse the SVG with `defusedxml` and reject if ANY of the following are present: `<script>`, `<foreignObject>`, `<iframe>`, `<embed>`, `<object>`, `on*` event handler attributes, `<set>`, `<animate>` with attribute names outside an approved geometric/presentation set, `xlink:href` or `href` pointing outside the document (`#` fragment-only references are permitted), `xml:base`, XML external entities, processing instructions, `<!DOCTYPE` with SYSTEM or PUBLIC identifiers.
3. **Reject external references:** No `url()` in style attributes or `<style>` elements may reference an external resource. No `<image>`, `<use>`, `<feImage>`, or `<pattern>` `href`/`xlink:href` may point outside the document.
4. **Bounded execution:** The renderer must have explicit memory limit (≤256 MB), pixel output limit (≤16384×16384), and wall-clock timeout (≤10 seconds). If any limit is exceeded, return an error rather than a partial image.
5. **Renderer selection:** The chosen library must be a maintained, widely-used SVG rasterizer (e.g., `cairosvg`, `resvg` via Python bindings, `librsvg`). Pin the exact version in requirements. Do not use a headless browser for rendering.
6. **Output:** PNG bytes. The output is then validated by the existing `_validate_image()` — that function is the integrity gate, not the normalization itself.
7. **No network access:** The renderer must be configured (or the SVG pre-processed) so that no external network requests are made during rendering. This is defense-in-depth on top of the pre-render rejection in point 3.
8. **Test fixtures:** Synthetic SVG fixtures committed to version control. At minimum: valid SVG with embedded JPEG + vector overlays + clipping, SVG with `<script>`, SVG with external `xlink:href`, SVG with `<foreignObject>`, SVG with XML external entities, oversized SVG dimensions, empty/malformed SVG. Each rejection case must produce a clear, distinct error message.

#### Condition 5 — Adapter package constraints

The `.osp` adapter package in `adapters/community/oneshelf.noorbook/`:

1. **Declarative only.** If the Noor Book read flow cannot be expressed in the current recipe schema (`request`/`response`/`extract`/`pagination`), report `Native Adapter Review Required` and do not implement a workaround. Do not embed JavaScript, Playwright scripts, or imperative browser automation in a recipe.
2. **Network:** Declare only domains proven necessary for the reader flow. Exclude advertising, analytics, and social media domains.
3. **Capabilities:** Declare only `reader` (and `work` if metadata extraction is proven). Do not declare `search`, `downloads`, `catalog`, `latest`, or `trending` without separate evidence and contract.
4. **Identity:** A source listing produces one book Reading Unit. Page groups are not chapters or separate Works. Source page labels are preserved. Expiring URL tokens are never part of unit identity.
5. **Completeness:** The reader recipe's pagination must produce `complete=True` only when all page groups have been fetched and all page slots are populated. A recipe that returns 100 entries from the first group alone must not report `complete=True`.
6. **Fixtures:** Sanitized synthetic HTML fixtures (no live session tokens) with test cases covering: both page groups, lazy/empty slots, first page, last page (111), failed second group, wrong-title response, preview/restricted state.

#### Condition 6 — Public API preserved

The reader page route (`library.py:325–361`) continues to serve `application/octet-stream` with the existing content isolation headers:

```python
"Content-Security-Policy": "sandbox; default-src 'none'; img-src data: blob:; style-src 'unsafe-inline'"
"X-Content-Type-Options": "nosniff"
"Cache-Control": "no-store"
"Cross-Origin-Resource-Policy": "same-origin"
```

No changes to these headers. No new content type served through this route. The frontend image reader receives raster bytes as it does today.

#### Condition 7 — No production changes

No changes to the primary worktree at `G:/work/OneShelf`. No deployment, rebuild, or restart of the production server at `192.168.8.32`. No publishing of the adapter to a registry. The full Task 4 verification cycle (commit → push → user-managed deployment → browser QA) applies before any production use.

#### Condition 8 — What is explicitly NOT approved

- Changes to `validators.py:_validate_image()` to accept SVG directly.
- Weakening content isolation headers in `library.py` for any reason.
- New browser interaction primitives (click, select, form submission in `BrowserFetcher`) without a separate written contract.
- New pagination modes in `schema.py` without a separate contract addendum.
- Serving raw SVG bytes to the frontend through any route.
- Bypassing site challenges, broadening egress beyond declared source/CDN domains, or scraping without demonstrating the source's intended read access pattern.
- Any `complete=True` claim from an adapter recipe that has not fetched all page groups.
- Incomplete descriptor results entering the Reader Cache or being returned as a page list.

---

### Explicit ruling: SVG normalization vs. Task 1 failure

**If Core transport cannot reach the Noor Book source and network replay evidence cannot be collected:**

- **Task 2 (SVG normalization + completeness enforcement) may still be implemented and merged.** These are general Core safety improvements. The completeness check closes a real gap that affects all sources. The SVG normalizer enables any future source that serves SVG content. Neither depends on Noor Book specifically.
- **Task 3 (adapter package) is BLOCKED.** Without replay evidence, there is no proven request contract to encode in a recipe. Do not guess request bodies or invent an adapter from browser observation alone.
- **Task 4 (end-to-end Noor Book verification) is BLOCKED.** No source to verify against.
- **The branch may still produce value** by delivering the two Core improvements. Whether to merge them to `main` without the adapter is a user decision, not an ownership question.

---

### Cross-boundary coordination status

| Requirement | Status |
|---|---|
| Written contract before cross-boundary code (AGENTS.md) | This document |
| Backend owner review | Complete |
| Frontend contract | Existing image reader API preserved; no frontend contract change needed. Codex may implement Task 4 frontend verification. |
| Deployment | User-managed only |

**Ownership coordination per AGENTS.md is satisfied for the scope above.** Codex may proceed with Task 1 investigation and Task 2 implementation (independently) in this isolated worktree. Task 3 is gated on Task 1 evidence. Task 4 is gated on both.

## Approved embedded-raster addendum

**Confirmed with one clarification.**

The addendum is approved. Embedded `data:image/jpeg;base64` and `data:image/png;base64` on `<image>` elements are permitted under these exact constraints:

1. Only `data:image/jpeg;base64,` and `data:image/png;base64,` prefixes. No other MIME types, no `data:image/svg+xml`, no `data:text/*`, no bare `data:` without explicit type.
2. The base64 payload is strict-decoded (`validate=True` / reject non-alphabet characters). Decode failure rejects the entire SVG.
3. The decoded bytes are validated through Pillow (`Image.open` + `verify` + `load`) and the decoded pixel count is checked against the per-embed bound before rendering proceeds. A single embedded image exceeding the bound rejects the SVG.
4. Nested SVG references via data URI (`data:image/svg+xml`) are rejected unconditionally — this is the critical line between "embedded raster" and "recursive SVG."
5. CSS `url(data:...)` remains rejected regardless of MIME type. Only `href`/`xlink:href` on `<image>` elements are in scope for this allowance.

The proposed API and parameters are approved:

- `async normalize_page_image(data: bytes) -> bytes` in `backend/oneshelf/reader/page_image.py`
- Raster pass-through (non-SVG input returned unchanged)
- `defusedxml` allowlist pre-parse, `resvg_py==0.5.0` pinned
- PNG output validated by existing `_validate_image()`
- ≤256 MiB memory, ≤8 seconds wall time, ≤8M output pixels
- Linux production: OS-level memory/CPU limits on the worker process; unsupported platforms fail closed for SVG input (raster pass-through still works)
- Dependency file changes (`pyproject.toml`, `requirements.lock`) are within approved scope

The original Condition 4.3 wording ("No `<image>` ... `href`/`xlink:href` may point outside the document") was intended to prohibit external network fetches, not embedded inline data. This addendum resolves that ambiguity without weakening the security boundary. The required test fixture (valid SVG with embedded JPEG + vector overlays) is now consistent with the allowlist.

No other conditions are modified.

Good. I've reviewed the coordination document, the full `page_image.py` implementation, the test suite, and the telemetry endpoint guard. Here is my written addendum decision.

---

## Style Conversion and Overflow Addendum — Backend Owner Decision

**Reviewer:** Claude Code (Lead Backend, Adapter, and Reading Systems Engineer)
**Date:** 2026-10-24
**Applies to:** Coordination document `docs/superpowers/coordination/2026-10-24-noorbook-backend-review.md`
**Status:** APPROVED with one clarification

### Addendum A — `overflow` presentation attribute

**Approved.** Add `overflow` to `_ATTRS`. Validate its value to exactly `visible` or `hidden` before passing to the renderer. Reject `scroll`, `auto`, `inherit`, or any other value. This is a standard SVG presentation attribute with no security implications at these two values.

### Addendum B — Inline `style` declaration conversion

**Approved.** The style attribute is currently rejected entirely (`"unsupported SVG attribute"`). The proposed conversion is the correct approach: decompose the style declaration into presentation attributes the allowlist already validates, then discard the `style` attribute so no CSS reaches the renderer.

Binding constraints on the implementation:

1. **Allowed properties (exhaustive):** `fill`, `fill-opacity`, `stroke`, `stroke-opacity`, `stroke-width`, `fill-rule`. No other property name is accepted.
2. **Pre-parse rejection.** Before splitting declarations, reject the entire `style` value if it contains any of: `@`, `\`, `/*`, `*/`, `!`, `(`, `)`, or non-ASCII characters. This closes CSS escapes, comments, functions (including `url()`), `!important`, and encoded injection vectors with a single fast check.
3. **Declaration parsing.** Split on `;`, strip whitespace, skip empty segments. Each segment must match `property:value` with exactly one `:`. Reject if a property name appears more than once in the same `style` value.
4. **Value validation per type:**
   - **Paint** (`fill`, `stroke`): accept only `none`, `transparent`, `currentColor`, `#` followed by exactly 3 or 6 hex digits (`[0-9a-fA-F]`), or a bare alphabetic name matching `[a-zA-Z]+`. No `url()`, no `rgb()`, no `var()`.
   - **Opacity** (`fill-opacity`, `stroke-opacity`): accept only a decimal matching `0|1|0?\.\d+|1\.0*` in the range [0.0, 1.0].
   - **Width** (`stroke-width`): accept only a positive decimal matching `(\d+(\.\d*)?|\.\d+)` with parsed value > 0. No units (the SVG user-space unit is implicit).
   - **Fill-rule** (`fill-rule`): accept only `nonzero` or `evenodd`.
5. **Precedence.** If the element already carries a presentation attribute for the same property, the `style` value wins (CSS specificity). Overwrite the existing attribute with the validated style value.
6. **Removal.** After conversion, delete the `style` attribute from the element. The serialized SVG passed to `resvg_py` must contain zero `style` attributes.
7. **Scope.** `url()` in style values is unconditionally rejected (per pre-parse check and the fact that `(` is blocked). This means `style="fill:url(#grad)"` is rejected even though the equivalent presentation attribute `fill="url(#grad)"` is accepted via `_LOCAL_PAINT`. This is intentional — it avoids needing a CSS `url()` parser in the style path. If real-world SVGs need `url()` in style for local references, that is a separate future addendum.

**One clarification:** `currentColor` is safe because the `color` property is not in the allowed set, so it always resolves to the initial value (renderer-default black). This is acceptable and faithful enough for reader pages. Do not add `color` to the allowed property list to "fix" this — that opens inheritance chains.

**Test changes:** The existing parametrized rejection case `('<rect style="fill:blue"/>', 'unsupported SVG attribute')` must be moved from `test_svg_rejects_active_or_external_content` to a new acceptance test that verifies the element renders with the converted `fill` attribute. Add rejection tests for: `style="fill:url(http://evil.example)"`, `style="fill:blue; fill:red"` (duplicate), `style="display:none"` (unsupported property), `style="fill:blue !important"`, `style="fill:expression(alert(1))"`.

### Addendum C — Telemetry endpoint guard exemption

**Approved.** In `test_no_module_carries_a_hardcoded_endpoint`, exempt exactly these three string literals:

```
http://www.w3.org/2000/svg
http://www.w3.org/1999/xlink
http://www.w3.org/XML/1998/namespace
```

These are W3C XML namespace identifiers — opaque string constants used for element and attribute qualification, never fetched as network destinations. The exemption must match the **full URL string**, not the host `www.w3.org`. Implementation: collect the full `match.group(0)` and skip if it is in a frozen set of these three exact values. No other URL on `www.w3.org` or any other host is exempted. No production code endpoint is exempted.

### Summary of what is NOT changed

- Conditions 1–8 of the original coordination document remain in full force.
- The embedded-raster addendum remains in full force. CSS `url(data:...)` remains rejected.
- `_validate_image()` is still never modified and still receives only raster bytes.
- Content isolation headers in `library.py` are unchanged.
- No new elements or namespace-qualified attributes are added to `_TAGS` or `_ATTRS` beyond `overflow`.

---

Codex may proceed with implementation of Addenda A, B, and C in the isolated worktree.
