# OneShelf — Final Implementation Meta Prompt

## A. Mission, authority, and execution boundary

You are the implementation agent responsible for delivering OneShelf as a complete, tested, self-hosted personal reading library. Act across architecture, backend, frontend, reader engineering, source integration, security, storage, deployment, and QA.

**This document is a planning artifact. Receiving, reading, or generating it does not authorize implementation. Do not modify application code, install dependencies, migrate data, run application jobs, or deploy until the user explicitly asks you to execute. If that authorization is already present in the current session, proceed without asking for it again.** Once authorized, implement and verify the required application; do not stop at a plan, scaffold, mockup, or disconnected demonstration.

The complete Master Specification is embedded verbatim in section F. It is the authoritative product contract. Read it completely before implementation, including every subsection, default, exclusion, state rule, and acceptance invariant. Its 57 numbered sections, 0–56, are mandatory to evaluate; optional/future items retain their stated status. References below such as “Master §26” refer to that embedded text, not this document's lettered sections.

Apply this precedence to OneShelf product and architecture requirements:

1. An explicit subsequent user decision that deliberately changes the approved specification.
2. The attached Master Specification, reproduced in section F.
3. This document's implementation workflow, interpreted consistently with the Master.
4. Existing repository conventions and historical notes, only where compatible.

This precedence concerns project requirements; it does not override the execution environment's permissions or security controls. Never silently simplify, remove, weaken, or expand the product contract. If this workflow appears to conflict with the Master, the Master wins. If an old note contains an additional potentially useful requirement that the Master does not adopt, flag it for review and keep it outside mandatory v1 scope.

The Master's instructions addressed to the prompt-generating model describe the planning stage already completed here. They do not require recursive prompt generation after the user explicitly authorizes implementation. Before authorization, preserve the no-implementation boundary. After authorization, execute the approved product contract.

Treat OneShelf primarily as **“My personal library and reading space.”** The required Reader, discovery, Shelf, Follow, downloads, source management, backups, export, and import must form one coherent application. Sources and languages remain distinct throughout.

## B. Completed source review and reconciliation

This reconciliation was performed on 2026-09-17 before drafting the implementation workflow. It is evidence about the material inspected, not a claim that any current source website or application feature has been live-tested in this task.

### B1. Sources actually inspected

| ID | Source and review scope |
|---|---|
| M | [OneShelf_Master_Spec_v1(2).md](sandbox:/workspace/scratch/b196ffebfda1/upload/OneShelf_Master_Spec_v1(2).md), read completely: 3,803 lines, sections 0–56. SHA-256: `29954d4c34f32725b900a59823afddb31b576127ffbf028ccfa46389b746d3de`. The available original `OneShelf_Master_Spec_v1.md` and `(1)` copy were byte-identical to this attachment. |
| A | [Prior AGENTS.md](sandbox:/workspace/scratch/b196ffebfda1/prior-notes/AGENTS.md), the earlier complete implementation prompt, read completely. The three available earlier prompt copies titled `Pasted markdown.md`, `Pasted markdown(1).md`, and `Pasted markdown(20260908-230403).md` had identical text to it after ignoring terminal newlines. The supplied AGENTS document ends after “For every supported workflow, complete:” and supplies no subsequent text; no missing continuation was invented. |
| R | Local reference checkout of `IPurplel/OneShelf`, inspected revision `eccf0e1818499f88a09750ea121c9402f93c8315`, dated 2026-09-08. Working tree was clean during inspection. This is a historical reference checkout, not proof of the current implementation workspace or current remote HEAD. |
| R1 | [README.md](sandbox:/workspace/scratch/4757a265ed4b/oneshelf-reference/README.md): product claims, configuration, sources, sessions, deployment, and API documentation. |
| R2 | [META_PROMPT.txt](sandbox:/workspace/scratch/4757a265ed4b/oneshelf-reference/META_PROMPT.txt): prior source-coverage program, rules, work packages, matching instructions, and source inventory. |
| R3 | [HANDOFF.md](sandbox:/workspace/scratch/4757a265ed4b/oneshelf-reference/HANDOFF.md): complete historical engineering notes, including dated corrections and later findings. |
| R4 | [CLAUDE_CONTINUATION.md](sandbox:/workspace/scratch/4757a265ed4b/oneshelf-reference/CLAUDE_CONTINUATION.md): previous work status, pagination fix, evidence qualifications, and remaining work. |
| R5 | [docs/development.md](sandbox:/workspace/scratch/4757a265ed4b/oneshelf-reference/docs/development.md), [docs/troubleshooting.md](sandbox:/workspace/scratch/4757a265ed4b/oneshelf-reference/docs/troubleshooting.md), [SOURCES.md](sandbox:/workspace/scratch/4757a265ed4b/oneshelf-reference/SOURCES.md), and [docs/source-inventory.md](sandbox:/workspace/scratch/4757a265ed4b/oneshelf-reference/docs/source-inventory.md): development instructions, storage/backup guidance, source evidence and candidate inventory. |
| R6 | [config.example.yaml](sandbox:/workspace/scratch/4757a265ed4b/oneshelf-reference/config.example.yaml), deployment Compose configuration, dependency manifest, and targeted implementation inspection of `app/adapters/textmatch.py`, `app/models.py`, `app/db.py`, `app/queue.py`, `app/config.py`, and `web/app.js` to verify specific legacy behavior. This was targeted static inspection, not an exhaustive code audit. |
| P | The earlier 2026-09-08 meta-prompt-generation brief and available OneShelf conversation notes: prior role/worktree history, later source-session/plugin decisions, no title stemming, and final architecture-review decisions. Only OneShelf-specific material was used; unrelated retrieved personal context was excluded. |
| V | [oneshelf-library-home.png](sandbox:/workspace/scratch/b196ffebfda1/prior-notes/visuals/manga-downloader/oneshelf-library-home.png) and its available WEBP rendition, both visually inspected. They show the forest-green sidebar, cream canvas, contextual Hero, cover-led wooden shelves, and a top-right profile icon. Product behavior follows the Master when an image differs. |

No standalone `CLAUDE.md` was available in the inspected local checkout or surfaced among the available project files. Historical conversation notes mention `AGENTS.md`/`CLAUDE.md` in `/workspace/OneShelf`, but that active repository was not available here. The live GitHub page could not be retrieved in this environment. Consequently, this document does not claim to have inspected an unavailable local repository, private instructions, or current remote changes. During execution, inspect the actual current repository and all applicable instruction files again before modifying anything.

### B2. Genuine contradictions and their resolutions

Every resolution below is already determined by the Master. Do not ask the user to reconfirm it.

| ID | Conflicting older instruction or reference | Authoritative resolution |
|---|---|---|
| C01 | A §3 lists the built-in Reader as an optional future extension. | Reader is a core v1 subsystem, including Sequential, EPUB, and PDF readers. Master §§26–27, 54, 56. |
| C02 | A §§1, 16 authorize a new independent visual identity and a generic light/dark palette; the earlier generator brief broadly invites redesign. | Preserve the approved forest-green, warm cream, olive, wood-shelf reading-room identity. Refinement of spacing, typography, icons, and responsiveness is allowed within it. Master §§32, 54, 56. |
| C03 | A §§3, 16, 25, 28 and R1 require light/dark/system application themes and theme-persistence gates. | No application-wide multi-theme requirement. Use the approved identity. Required Reader backgrounds and EPUB reading-theme controls remain; they are not an application theme switcher. Master §§26, 32, 56. |
| C04 | A §17 uses Discover, Downloads, Library, Sources, Settings as the primary navigation. | Desktop destinations are Home, Search, My Shelf, Following, Downloads, Sources, Settings; apply the Master's mobile treatment. Master §32. |
| C05 | V visibly includes a top-right profile/avatar control. | Omit the normal profile/avatar. Use Notifications and Needs Attention; Needs Attention is hidden at zero and is a filtered shortcut to unresolved actionable issues. Master §§2.2, 32.2, 44. |
| C06 | R2 rule R5, its T0/T3 ladder and WP-5, R4's closing instruction, and R5's development/source-inventory rules exclude account-gated readable content outright. | Legitimate user-owned source sessions are supported through Use My Session. Authentication is capability-specific; the user logs in personally, Core owns scoped encrypted state, and plugins never receive raw secrets. No access-control bypass. Master §§9–14, 41, 48. This does not add every historically excluded source to the v1 suite. |
| C07 | A §23 and the earlier generator brief permit an implementation with no authentication if documented as LAN-only; R1 describes that old unauthenticated baseline. | Genuine localhost/LAN access remains trusted and unauthenticated by default, while built-in remote access requires passkeys, recovery, session controls, and remote Origin/CSRF protections. Omitting the remote subsystem is not a v1 option. Master §§28–29. |
| C08 | R5's standard extension instructions require writing an executable Python `Adapter` subclass, with arbitrary transform hooks as the normal extension mechanism. | Community packages are declarative non-executable `.osp` files. Core owns HTTP, browser, session, database, filesystem, and path capabilities. Native code is only a rare reviewed official exception. Do not turn legacy Python adapters into unrestricted community plugins. Master §§9–12, 48–49. |
| C09 | R2 WP-3 explicitly requires article-stripped Arabic matching; R6's `textmatch._article_forms()` produces an article-stripped stem for title tokens. | No title stemming, including this automatic affix-stripping carryover. Preserve title words; implement the Master's normalization, aliases, prefix/substring/trigram/fuzzy ranking, and intentional loose `ة ↔ ه` equivalence without reducing title tokens to stems. Master §6.3 and §49; the later no-stemming user decision agrees. |
| C10 | R5 development step 7 and R3/R5 WuxiaBox notes say to key duplicate chapters on chapter number and infer duplicates when list length exceeds the highest number. | Numbers are display/order metadata, never Reading Unit identity. Preserve specials, extras, prologues, decimals, volumes, and source order. Matching remains title-primary with supporting stable source evidence. Repeated numbers alone neither merge units nor prove an incomplete/duplicate catalog. Master §§4–6, 20, 26.13. |
| C11 | R6's shipped configuration sets `stealth: true` and `challenge_click: true`, and R2/R3 contain challenge-solving/fingerprint-avoidance instructions. | No anti-bot stealth or CAPTCHA bypass. Browser retrieval is a controlled resource-discovery method, not an automated challenge solver. Required human action must be reported honestly. Master §§12, 14, 49. |
| C12 | R5 troubleshooting tells users to back up the full configuration volume, including the browser profile. | OneShelf Library/Full Backups exclude source sessions, cookies, tokens, passwords, active remote sessions, recovery code, session master key, and browser profiles. Use the canonical backup contract and a consistent database snapshot. Master §§13, 18, 33. Do not carry the old volume-copy recipe into OneShelf's backup feature. |
| C13 | R6's default `chapter_concurrency: 2` and `image_concurrency: 6` explicitly multiply request capacity; legacy queue limits are job-oriented. | Default HTTP/download concurrency is 4, Browser concurrency is independently 1, coordinated application-wide by the Source Traffic Governor and per-source limits. Old values/topology are not the new defaults. Master §§15–16, 42. |
| C14 | A §7 puts exact alternate-title and author matches ahead of normalized-title matches. | Use the Master's textual relevance tiers: exact title, exact normalized title, exact alias, phrase/prefix, all-token, substring/trigram, fuzzy typo. Small boosts cannot overwhelm strong textual relevance. Master §6.4. Dedicated author-search expansion is review-only, not an excuse to replace this ranking. |
| C15 | A §17 requires recent searches, and R6's `web/app.js` automatically persists them under `md.recentSearches` in `localStorage`. | Search queries/analytics are not persistently collected by default. Retaining in-session navigation state is distinct from persistent query history. Do not carry over automatic persistent recents. Master §7. |

Master §§0, 6.10, 49, and 56 also explicitly supersede matcher telemetry/central collection and browser notifications. Those exclusions are binding even though the inspected older files did not independently establish a current implementation of either feature. Do not invent an additional evidence-backed contradiction or a removal claim for code that was not inspected.

### B3. Historical implementation gaps are not conflicting requirements

The following are implementation context to verify in the actual execution workspace, not reasons to alter the Master:

- R4 records an in-memory queue despite persistent chapter/library records. R6 confirms `_jobs` is an in-memory dictionary in this reference revision. Durable jobs, persistent selections, restart recovery, and commit reconciliation must be implemented or verified in the current workspace.
- R3 and R6 show downloaded-library membership based on `first_download_at`. The required My Shelf permits immediate explicit saving without downloaded files. Keep Shelf membership, assets, Follow, progress, Favorites, Pins, and Completed status separate.
- R6 serializes source cookies as JSON into the legacy database. The new source-session subsystem must encrypt protected state at rest with the key stored separately; legacy storage cannot simply be treated as compliant.
- R4's pagination fix stops raised transport failures, but identifies repeated/empty successful responses and pagination caps as remaining completeness risks. The Master requires the full completeness/trust model, not just exception handling.
- Historical test totals, downloaded artifacts, source availability and counts are dated evidence. They are not fresh completion evidence for this implementation. Missing features in an older checkout are gaps, not contradictions in the approved product.

### B4. Additional old ideas held for review, not silently adopted

These remain outside mandatory v1 scope unless already required by the Master or separately authorized by a subsequent user decision:

- A's preference for FastAPI plus React/TypeScript/Vite, a modular monolith, exact port/layout/startup-script choices, and host-specific deployment instructions. Inspect and retain compatible conventions; the Master fixes SQLite and Docker requirements, not those particular framework selections.
- The older 183-source inventory, “92 verified sources” target, five-reader extraction quota, two-sites-per-platform gate, and earlier 40-Arabic/40-English research request. Master §41 defines the initial integration suite. Historical inventories are candidate research, not extra v1 acceptance quotas.
- A's combined selected-chapter EPUB compilation and generated scanned-page PDF features. The Master requires supported packaging and original-format preservation but does not adopt a general conversion subsystem or those exact additional compilation features. Do not silently require or implement them merely because the older prompt did.
- Dedicated author-search behavior, persistent opt-in search-history UI, Stop All as an extra UI command, redacted diagnostics export, and fixed synthetic benchmark sizes from old notes. The Master already specifies useful metadata indexing, queue controls, diagnostics, and bounded memory; these additional named features/gates require review.
- The legacy generic proxy/desync/attached-browser product controls. Ordinary networking implementation details may be selected as needed, but do not import a new bypass feature, a broad attached-browser capability, or an internal-network exception through old configuration defaults.
- Old named-agent assignments and worktree/merge instructions. They are historical collaboration state, not authorization to launch agents, recover discarded OpenCode work, or merge old branches.
- Earlier palettes and broad “modern media library” ideas do not select another visual identity. Use V in conjunction with the Master, including its explicit corrections.

Flag additional requirements in a review ledger with their source and disposition. Do not block required v1 work on optional proposals. The older preference to place detailed website investigation instructions last is retained as a formatting convention in section G; the verbatim Master remains intact as the authoritative input rather than being rearranged to fit an old prompt layout.

### B5. Important distinctions that are not contradictions

- A Source Track can require an external source account while OneShelf has no normal username/password account.
- Trusted LAN access to OneShelf does not permit plugins to access arbitrary LAN/internal targets. Inbound UI trust and outbound source network policy are separate boundaries.
- Reader Cache and read-ahead rendering do not imply a permanent download. Auto-download while reading is OFF by default; Follow never automatically downloads new releases.
- “Export never changes library state” permits the explicit, separately disclosed Download Missing Then Export flow: the normal Download Engine commits content first; export then copies it. Export-job bookkeeping does not change Shelf, progress, or source mappings.
- A complete suspicious snapshot can be trusted through the Master's recovery rules. An incomplete snapshot cannot be trusted, even through Trust This Catalog.
- Local operational diagnostics and test evidence are permitted; matcher-decision telemetry and central/shared collection are not.
- Reader backgrounds and EPUB theme settings do not imply global application theme switching. The screenshot's illustrative Hero carousel, sample titles, and progress values do not create new product requirements or authorize fabricated production data.

## C. Execution workflow after explicit authorization

### C0. Inspect and establish the current baseline before edits

1. Identify the actual target repository, branch/worktree, revision, and working-tree changes. Read all applicable `AGENTS.md`, `CLAUDE.md`, nested instructions, README, architecture docs, prior prompts, handoffs, manifests, migrations, tests, deployment configuration, and relevant source files. The reference paths in section B are evidence locations, not instructions to modify that historical checkout.
2. Compare current instructions against the Master and the conflict register. Follow compatible project conventions. Record newly discovered genuine conflicts with source locations and Master resolutions. Do not ask the user to decide conflicts the Master already resolves.
3. Identify existing application state, managed storage roots, caches, credentials, and external mounts without printing secret values. Preserve user changes and data. Do not reset branches, delete volumes, overwrite configuration, or run destructive tests against real content.
4. Verify which features already exist and whether their semantics conform. Use existing code where sound. Do not assume a clean-slate rewrite is required by the old prompt or assume old branches are integrated.
5. Record the baseline with the current project's actual test/build commands and distinguish pre-existing failures from introduced failures. Historical reported pass counts are not this baseline.
6. Create implementation traceability covering every Master section/subsection and all 30 invariants: requirement ID, implementation location, API/UI surface, persistence/state implications, acceptance test/evidence, and status. Statuses must distinguish not started, implemented, verified, and blocked; required work cannot be silently relabeled deferred.
7. Describe the subsystem boundaries, persistent models, state machines, migration strategy, and dependency order before changing persistent state. Make routine engineering choices autonomously, cite current official documentation when choosing or changing dependencies, and preserve project conventions where compatible.

Do not impose a new stack purely because an older prompt preferred it. Do not add cloud services or unrelated subsystems. If a required external capability cannot be verified in the environment, record the concrete blocker and continue independent work.

### C1. Architecture, persistence, and safe local foundation

Master coverage: §§1–4, 17–18, 22–25, 37–39, 48, 52.

Implement the domain boundaries: Work, Source Listing, Source Track, Local Source Track, Reading Unit, format/asset records, user overrides/mappings, catalogs, Shelf membership, Follow, progress/read state, batches/jobs/checkpoints, storage roots, notifications, backup/export/import state, and protected session references. Distinguish raw/display/search text from stable identity.

Use SQLite as the source of truth, with WAL, migrations, bounded write transactions and explicit consistency boundaries. Define recoverable migration paths. Never use a live database file copy as a consistent snapshot mechanism.

Implement stable storage-root IDs with relative paths, safe Unicode naming, per-root staging on the destination filesystem, integrity records, offline-root detection, space guards, and recoverable commit journaling. Define ownership of every persistent record and cleanup class. Metadata updates must not silently rename files. Protect paths from traversal, absolute injection, symlink escape, and plugin control.

Build an initial Local Source Track slice so imported validated CBZ/PDF/EPUB content can be represented independently of network plugins. Design import, scanner, migration, and final commit around the same integrity and root-availability model.

**Gate:** schema migration/recovery tests; same-title/source/language/format collision cases; path/symlink tests; unavailable-root cases; crash injection around final rename and database registration; repeatable reconciliation; no incomplete artifact marked downloaded. Test data must be isolated.

### C2. Approved UI shell and local reading slice

Master coverage: §§2.3, 22–23, 26–27, 29, 31–32, 44–47.

Build the responsive navigation, reusable cards, drawers, forms, index-like Reading Unit lists, library surfaces and operational paper/card surfaces using the approved reference. Preserve its overall composition and material/color language while applying the Master's explicit profile-icon correction and adaptive content semantics.

Implement Home, Search, My Shelf, Following, Downloads, Sources, Settings and the shared Work Details structure with real routes/state appropriate to the existing framework. Keep source/debug machinery progressively disclosed. Empty states must work without fictitious books, statistics, trending scores, or network-only Hero selection.

Implement the local Sequential Reader plus EPUB and PDF viewers as core product flows, including the complete feature sets and defaults in §26. Isolate untrusted documents from the application origin and privileged actions. Implement progress writes, safe lifecycle flushing, and multi-tab conflict handling before relying on Continue Reading. A stale tab must not undo newer progress; explicit Mark Unread and legitimate rereading must still work.

Complete Arabic/English UI, appropriate RTL/LTR layout, mixed-direction text presentation, keyboard/focus behavior, touch gestures, reduced motion and accessibility-critical controls. UI direction and content reading direction are independent.

**Gate:** local reading without source/plugin/network; sequential Long Strip/Single/Double modes and true source order; EPUB logical progress/search/bookmarks/highlights; PDF page/text-layer search/bookmarks/highlights; controls don't hide while a panel is open; source changes never claim exact page equivalence; untrusted HTML/EPUB/PDF cannot execute privileged app actions; responsive Arabic/English visual checks against the reference.

### C3. Declarative source runtime, sessions, and secure network policy

Master coverage: §§9–13, 15, 21, 48.

Build the typed capability contracts and declarative `.osp` schema/runtime. Community packages describe bounded operations and safe transforms; they do not execute code or own host capabilities. Preserve Unknown capability/metadata states. Classification precedence is User override > explicit source classification > plugin default > Unknown.

Implement persistent Registry/local-upload management, full atomic validation/installation/activation, update/disable/uninstall/rollback, compatibility checks, packaged tests, permission-change review, provenance preservation and reinstall flows. Trust labels do not grant broader device access. Registry submission must be explicit; installation must not require an account connection.

Implement Core-owned source-isolated login/session contexts, encrypted session state with a separate key, capability/domain scoping, required browser-storage support, validation/reconnect/disconnect states and actions. Never expose raw session material to plugins, logs, status endpoints, backups, or export metadata. Disconnect deletes the local source session immediately; successful reconnect replaces state atomically and resumes affected work.

Enforce source/CDN allowlists plus redirect/DNS revalidation and private/internal-target blocking in HTTP and browser paths. The OneShelf Test Source exception is explicit and development-only. Build the application-wide Traffic Governor with the full priority order and independent browser capacity. Background browser work cannot starve Reader or direct user work.

**Gate:** malformed/executable plugin rejection; bounded transform/regex tests; installation rollback; new-permission review; same-source session isolation and cross-source/CDN secret-leak tests; reconnect waits; DNS/redirect/browser SSRF cases; priority/fairness tests; uninstall preserves local content and Shelf provenance.

### C4. Catalog trust, local-first discovery, and persistent identity

Master coverage: §§3–8, 31, 38.

Implement complete-catalog snapshots and explicit completeness evidence independently from suspicion. Retain current and previous Trusted Catalogs and bounded supporting history. Evaluate suspicion only for complete candidates. Preserve trusted state on incomplete or suspicious refreshes. Implement two-complete-consecutive-success recovery and advanced Trust This Catalog without allowing incomplete catalogs to pass.

Implement local indexing with SQLite FTS5 or equivalent, immediate local results, progressive live enrichment and per-source progress/retry. Cached/live copies of one source listing update a single record. One slow or failed source cannot clear or block useful results. Discovery Cache is versioned/namespaced by source and plugin version/schema and never cleans authoritative personal state.

Implement exact/normalized/alias/prefix/token/substring/fuzzy ranking as specified, Arabic normalization including loose `ة ↔ ه`, original-text preservation and no stemming. Keep grouping separate from ranking. Soft Groups are presentation-only; Shelf/Follow/Download must resolve a concrete Source Listing/Track. Hard mappings require the specified evidence or explicit user decisions. Implement Merge, Split, Unlink, Never Match and durable user overrides.

Implement supported URL resolution into the same Work/Source Track flow. Preserve original and historical titles/aliases where useful. Never equate checksums or covers with Work identity, or Unknown metadata/quality with negative evidence.

**Gate:** catalog 300→7, incomplete pagination and retry sequences; trusted-only Download Missing/baselines; same-title adaptations and source variants; manual mapping persistence; aliases/title changes; Arabic regressions and no-stemming checks; stale plugin-cache invalidation; local results surviving live failures; soft-group actions binding to concrete tracks; no persistent default search-query collection.

### C5. Downloads, recovery, and online reading

Master coverage: §§14–19, 24–27, 36, 39, 42.

Implement persisted batches and per-Reading-Unit jobs, selections, checkpoints, retry budgets and manifests. Use windowed scheduling rather than loading huge queues or media fully into memory. Document and enforce the state machine, including session/rate-limit waits, verification, packaging, committing and recovering. Pause/resume/cancel/retry/reorder must be valid server-side actions. Successful units survive failures in other units.

Persist and enforce each Extraction Contract. Smart Retry stays within its method before fallback. Preferred + Ask is the default; Strict/Locked and optional user-configured Automatic Fallback retain their exact meanings. Never silently change source, language, required content/output or configured method. A mid-unit method change starts a new complete staged unit and replaces only after validation. Method-specific resume must validate resource compatibility; changed validators must never splice different file versions.

Complete streaming transport, media/document validation, original-byte-preserving packaging, commit journal recovery and orphan cleanup in the specified startup order. Only verified final artifacts become downloaded content. Repair through the same method may fix an individual page without broad fallback. Clearing Download History does not delete content or progress.

Connect online Reader fetching and temporary Reader Cache to the same controlled source transport and identity model. Implement optional auto-download while reading with its OFF default, genuine-engagement threshold, current-only/current-plus-read-ahead modes, bounded five-existing-unit read-ahead and leaving-Work cancellation behavior. Download Entire Work remains explicit.

**Gate:** restart/queue recovery; partial batch success and Retry All Failed; Range/If-Range and changed ETag; interrupted browser manifests; HTML-as-media and corruption; crash at every commit boundary; independent HTTP/browser limits; Reader priority under saturated background work; reading without permanent download; enabled engagement trigger; leaving Work cancels unstarted read-ahead; cache eviction protects the current unit/open nearby pages/permanent files.

### C6. Shelf, Follow, health, attention, and live events

Master coverage: §§5.5–5.6, 20–23, 30–32, 35–36, 43–47.

Complete immediate Shelf saves, local-only Shelf search, Saved/Reading/Completed/Favorites views, separate Pin/Favorite state, clear file deletion choices and durable progress. Completed remains Completed when releases appear.

Implement Follow bound to Work, Language, Preferred Source and Source Track. First Follow establishes a trusted baseline without old-release floods. Compare catalogs, not max chapter numbers or numeric gaps. Metadata changes, reordering and disappearing/reappearing known units do not become fresh releases. Source changes establish a Source Change Baseline and preserve progress. Follow never downloads new releases automatically. Unfollow is immediate with Undo and affects neither Shelf nor files.

Implement capability-level health with passive-first signals, thresholds/hysteresis, trusted recovery, rate-limit/reconnect distinctions, plugin-version diagnosis and explicit low-priority active checks. Do not launch periodic browser health probes or use health to rewrite methods/source/language.

Implement in-app Notifications and Needs Attention as distinct presentations of authoritative subsystem issues, with logical dedupe, groupings, Seen/Unseen independent of reading, required retention and focused actions. Avoid per-page/retry/success noise. Keep Download History, export activity, backup state and diagnostics separate. Add the local event channel and reconnection/fallback refresh behavior.

**Gate:** first-Follow baseline; source change; added irregular units; existing-unit rename/reorder/reappearance; Complete status preservation; independent Shelf/Follow/files/progress operations; notification actions never mark content read; source/root dedupe; bounded history cleanup; no browser notifications; multi-client updates and stale-progress protection.

### C7. Storage management, import, backups, restore, and export

Master coverage: §§18, 24–25, 33–39, 42–43, 47.

Complete multi-root storage management, disk reserve/preflight, offline-root behavior, scanner reconciliation, manual deletion/relocation handling and resumable migration. Never delete old storage automatically. Mount-path-only changes remap and validate without copying all content unnecessarily.

Implement Copy-default import of CBZ/PDF/EPUB, explicit Move, conservative association/Choose Work/Create Local Work, local provenance and integrity records. Do not add prominent Leave in Place or complex storage deduplication.

Implement exactly Library Backup and Full Backup, the versioned/checksummed canonical format, all exclusions, consistent SQLite snapshots, explicit Backup Location and same-physical-disk warning. Schedule Library Backup every seven days and catch up when suitable after downtime. Full Backup is manual by default. Retain the last four verified backups; verify the new backup before rotating any old verified one.

Implement restore preflight, forward migration in staging, rejection of newer schema into an older app, missing-plugin reinstall/skip and explicit review for compatible replacements/new permissions. Replace Current Library creates a lightweight Safety Snapshot. Merge is deterministic: current manual edits/mappings/settings win; missing records may be added; progress never regresses; healthy files are not replaced without reason; verified backup files can repair missing/corrupt local files. Backup encryption is not a new core v1 requirement.

Implement export as a persistent/resumable portable Copy with explicit Work/Language/Source/selection/format contract. Prefer local originals, folder output by default, optional ZIP, checksums, destination preflight and Skip Identical/Replace/Keep Both. For missing selected content, offer exactly the specified choices and disclose permanent library downloads before Download Missing Then Export. No implicit format conversion. History cleanup never deletes exported files. Existing local content exports with the plugin absent.

**Gate:** unavailable destination/root; space reserve; resumable root migration; old-data preservation; import uncertainty; backup secret scanning; consistent snapshots; failed verification does not rotate prior backups; version incompatibility; Replace safety snapshot; deterministic merge conflict cases; plugin absence/permission review; export interruptions/conflicts/per-file failures; history cleanup preserving files; explicit missing-content download notice and normal permanent commit pipeline.

### C8. Remote access and first run

Master coverage: §§2, 28–29, 48.

Implement single-user built-in remote passkey authentication on the canonical HTTPS hostname, the fixed internal WebAuthn identity without a product account/profile, recovery code lifecycle, genuine LAN recovery, remote session listing/revocation, secure cookies, and Origin/CSRF protections.

Determine LAN trust from real connections and explicit configuration. Accept forwarded client identity only through configured trusted proxies. A remote reverse proxy must not accidentally grant LAN administrative privileges because its own connection is private. LAN recovery affects only remote Web UI authentication, leaving library state and external source sessions intact.

Implement the short first-run flow with storage, access mode, conditional remote setup and optional sources. Do not force advanced settings before Home. Authentication boundaries needed for earlier phases must already protect those surfaces; this phase completes and verifies the full flow, rather than exposing privileged endpoints until the end.

**Gate:** genuine LAN versus forged forwarded headers; remote proxy cases; passkey authentication and revocation; recovery regeneration invalidating old codes; correct session defaults; no tokens in Web Storage; remote CSRF/Origin rejection; recovery's limited scope; first-run Arabic/English and mobile usability.

### C9. Generator, initial integration suite, and full deployment verification

Master coverage: §§9–16, 40–43, 49–56.

Complete the Scrapling-based developer/community Adapter Generator and repair workflow exactly as Master §12 and final section G require. It is a required subsystem, not a placeholder or an arbitrary-code plugin generator. Generate, Install, and Registry submission remain separate actions.

Use the required initial suite: MangaDex; 3asq/Al-Aasheq; WEBTOON; Tapas; Safahat/Hindawi; Project Gutenberg; arXiv; Standard Ebooks; and the controlled OneShelf Test Source. Start useful vertical slices with the foundation sources while building earlier phases; do not defer all real integration until this phase. Treat 3asq as a public catalog/parser/Reading Unit stress source, not an assumed official/licensed default.

Complete Docker deployment, persistent application/plugin/session-key/content/backup arrangements with their required separation, startup/readiness behavior, API/event documentation, operational guides and migration/recovery instructions. Verify restart and recreation against isolated mounted data. Do not copy old stealth/challenge defaults or blanket backup instructions into the new deployment.

Run the test categories in Master §53 and section D. Record current actual commands, versions, commit, environment and evidence. Separate offline deterministic tests from live source integration and real Docker/browser checks. Verify supported artifacts by opening/parsing/rendering their actual contents, not merely checking filenames, HTTP status or magic bytes.

If a source or environment blocks a required gate, document the exact capability, access conditions, evidence and remaining test. Continue independent work but do not claim that gate passed or the whole application is complete. Do not deploy publicly, publish plugins, merge discarded work, or alter unrelated host installations merely to finish verification.

## D. Acceptance evidence and delivery contract

### D1. Required invariant evidence

All 30 Master §51 invariants remain binding. The following test obligations make them reviewable; they do not replace the detailed tests in §53.

| Master invariant | Minimum evidence required |
|---|---|
| 1 | Incomplete pagination and complete 300→7 suspicious refresh preserve the last Trusted Catalog and trusted-derived state; recovery/trust actions obey completeness. |
| 2 | Search actions, Follow, Reader, retries, fallback, downloads and exports preserve source/language unless the user explicitly changes them. |
| 3 | Soft Group presentation cannot create durable mappings; Shelf/Follow/Download persist concrete listing/track identity. |
| 4 | Source refresh, plugin update and restore merge preserve current manual overrides according to their precedence. |
| 5 | Missing creator/date/volume/classification metadata remains Unknown and is not scored as mismatch. |
| 6 | Unknown quality does not hide, reject or mark otherwise available content unavailable. |
| 7–9 | Ordinary reading makes no permanent download; feature defaults OFF; enabled engagement behaves as specified; Follow new-release events never enqueue automatic downloads. |
| 10 | Exercise Remove from Shelf, Unfollow and Delete Files separately with assertions for files, Shelf, Follow, read state and progress. |
| 11 | Read and export existing local CBZ/PDF/EPUB with source offline, plugin disabled/uninstalled and source session disconnected. |
| 12 | Malicious document HTML/EPUB/SVG/PDF resources cannot reach privileged app actions, auth context or prohibited network targets. |
| 13–15 | Malicious `.osp` code/transform/path payloads are rejected; HTTP and browser redirect/DNS SSRF cases cannot reach private/internal targets. |
| 16–17 | Incomplete/corrupt artifacts stay out of completed local content; crash each commit step and repeat reconciliation without duplicate/lost registration. |
| 18 | Offline root produces Storage Location Unavailable, not mass Missing Local File or cleanup; reconnect safely reconciles. |
| 19 | Inspect Library and Full backup contents and manifests to prove all secret/session/cache/staging exclusions, not only absence of one cookie field. |
| 20–21 | Normal export only copies; missing-content flow requires explicit permanent-download disclosure and then uses the normal validated library commit. |
| 22–23 | Seen/Clear Seen/notification cleanup do not alter reading; clearing download/export history does not remove underlying content or progress. |
| 24 | Irregular ordered units, prologue, Special, Extra and 3.5 navigate by Source Track order. |
| 25 | Manual cross-source change presents Start This Unit/Try Approximate Position; uncertain equivalence does not guess a unit or claim exact page position. |
| 26 | Saturate low-priority browser/download work and demonstrate bounded Reader/direct-action responsiveness under the governor. |
| 27–28 | Work-level search presentation retains selectable provenance without duplicated source cards as separate copies of a matched Work; covers never influence identity. |
| 29 | Review persistent records, diagnostics, network calls and cleanup to verify no matcher-decision collector or central/shared telemetry. |
| 30 | Passkey/session/CSRF/Origin tests plus genuine LAN/trusted-proxy/forged-header cases prove the access boundary. |

### D2. Requirement/default completeness

Use the full embedded specification for exact values. Maintain one implementation source for defaults and verify UI/API/runtime/migration consistency rather than inventing different defaults per layer.

Explicitly verify every default in Master §42, plus defaults specified elsewhere: Preferred + Ask; settings precedence; classification precedence; remember Reader settings per Work ON; reader preloading approximately next 7/previous 4; folder-default export; Copy-default import; Library/Full backup behavior; local/LAN authentication OFF; remote lifetime options; notification grouping/deduplication and cleanup; metadata/format identity behavior.

Test both limits where retention uses “days or count/size, whichever comes first.” Cleanup must preserve authoritative subsystem state, active/open content where specified, permanent files and recoverable jobs. Do not substitute hard-coded numeric chapter assumptions for catalog/order/identity rules.

### D3. Deliverables and completion claims

When implementation is authorized, deliver an integrated runnable backend/frontend with required Reader, declarative plugin runtime and management, generator/repair workflow, source-session handling, catalog/search/mapping services, durable jobs/governor, storage/integrity/recovery, Shelf/Follow/health/notifications, auth, backups/restore, export/import/scanner, events, Docker deployment, migrations, tests, and documentation.

Provide:

- Requirement-to-implementation/test traceability and the updated conflict/review ledger.
- Architecture, persistent-state/state-transition and migration/recovery documentation.
- Current API/auth/event and declarative plugin/generator documentation.
- Deployment/startup/storage/backup/restore/upgrade instructions consistent with actual behavior.
- A dated source-capability evidence ledger that distinguishes verified, unverified, unavailable, action-required and unsupported capabilities without inventing support.
- A final verification report listing actual commands and outcomes, tested workflows, artifact checks, screenshots for UI/RTL/accessibility-critical states, and concrete blocked gates.

Do not claim completion because tests from the old repository passed, a source homepage loaded, a preview listed chapters, or a feature screen exists. Required features must work end to end, exclusions must remain excluded, and tests must run against the delivered implementation. Do not run destructive tests on the user's real library. Preserve existing work and make persistent-state changes reversible/recoverable where practical.

## E. Normative completeness map

This map ensures the implementation workflow reaches the entire Master. It is not a replacement for reading each section.

| Master sections | Responsibility |
|---|---|
| 0, 54–56 | Authority, reconciliation, scope discipline, generation/execution boundary. |
| 1–4 | Vision, platform, languages, foundational rules, domain identity. |
| 5–8 | Catalog trust, matching/search, discovery cache, direct URLs. |
| 9–15 | Declarative plugins, lifecycle, network security, generator, sessions, extraction contracts, traffic governor. |
| 16–19 | Durable downloads, recovery, SQLite durability, reading-triggered download rules. |
| 20–23 | Follow, capability health, Shelf, independent user states/actions. |
| 24–25 | Storage roots, migration, disk guard, staging recovery and cleanup. |
| 26–29 | Both reader families, untrusted content isolation, remote/LAN auth, first run. |
| 30–32 | Notifications, truthful discovery semantics, approved complete UI direction. |
| 33–39 | Backup/restore, export, separate histories, events, import/scanner, packaging. |
| 40–43 | API documentation, complete initial source/test suite, all defaults, bounded diagnostics. |
| 44–48 | Attention controls, progressive disclosure, error/destructive UX, security boundaries. |
| 49–53 | Exact exclusions/non-goals, all acceptance invariants, subsystem boundaries, required testing. |

## F. Authoritative Master Specification — complete verbatim input

Everything between the following markers is the complete supplied Master. Its product requirements take precedence over older material and over any abbreviated description elsewhere in this Meta Prompt. Do not skip it because the preceding workflow is detailed.

<!-- BEGIN AUTHORITATIVE MASTER SPECIFICATION -->
# OneShelf — Master Specification / Authoritative Source of Truth

**Status:** Architecture and product requirements approved through the final architecture review  
**Purpose:** Authoritative source-of-truth to hand to GPT-6 Astra (or another implementation-planning model) before generating the final implementation Meta Prompt  
**Rule of precedence:** This Master Specification overrides older drafts, prompts, notes, screenshots, AGENTS/CLAUDE instructions, and earlier design assumptions wherever they conflict. Later explicit user decisions represented here win.

---

# 0. Instructions to the Model Reading This Specification

Treat this document as the authoritative OneShelf product and architecture specification.

Do **not** redesign, simplify, reinterpret, remove, silently weaken, or add product requirements unless a section explicitly marks something as optional or future work.

Before generating an implementation Meta Prompt:

1. Inspect any available OneShelf repository documentation, AGENTS.md, CLAUDE.md, old prompts/specs, and project notes.
2. Compare them against this Master Specification.
3. Treat this Master Specification as the final authority when conflicts exist.
4. Preserve every hard rule, exclusion, security boundary, default, state transition rule, and UX decision.
5. If an external note introduces a potentially useful requirement not contradicted here, flag it for review rather than silently incorporating it.
6. Do not revive requirements explicitly removed from scope.
7. Do not start implementation merely because the architecture is specified. The requested output from this document is a final implementation Meta Prompt unless the user later explicitly asks to execute.

Important reconciliations with older project notes:
- Earlier notes that treated the built-in Reader as optional are obsolete. The Reader is now a core v1 subsystem.
- Earlier generic UI instructions are superseded by the approved OneShelf visual reference and UI/UX direction defined in this document.
- Older matcher telemetry/central logging concepts are explicitly removed and must not be revived.
- Browser Notifications are explicitly excluded from v1.
- The current visual identity is authoritative; do not infer a multi-theme requirement merely because an older draft mentioned themes.

---

# 1. Product Vision

OneShelf is a **self-hosted, single-user universal reading library, discovery, reader, download, source-management, follow, backup, and export system**.

Its core purpose is to make many heterogeneous reading sources feel like one coherent personal library while **never hiding the fact that sources and languages are distinct**.

Supported content families include:

- Manga
- Manhwa
- Manhua
- Comics
- Books
- Novels / web novels where source adapters support them
- Research papers
- PDF
- EPUB
- CBZ
- Similar readable works that fit the same architecture

OneShelf should feel first and foremost like:

> **“My personal library and reading space.”**

It must **not** feel first and foremost like:

> a scraper dashboard, source-debugging tool, download manager, or generic admin panel.

Technical machinery exists under the surface and is progressively disclosed only when needed.

---

# 2. Deployment and Core Platform Assumptions

## 2.1 Deployment

- Self-hosted web application.
- Docker is a first-class deployment target.
- Persistent application storage is required.
- Advanced users may mount separate library, backup, import/export, or storage locations.
- The application must not assume a cloud backend.
- The application must remain useful without any OneShelf cloud account because there is no OneShelf cloud account in v1.

## 2.2 User model

- v1 is single-user.
- No normal OneShelf username/password account.
- No cloud profile.
- No multi-user roles or permissions system.
- Remote Web UI authentication uses passkeys; LAN access is trusted as defined later.

## 2.3 Languages and direction

The product must support at minimum:

- Arabic
- English
- RTL
- LTR

RTL/LTR applies not only to reading direction, but also to appropriate UI layout, text presentation, and accessibility where relevant.

Arabic title normalization must be supported for search/matching, while preserving original user-facing text.

---

# 3. Foundational Product Rules

These rules apply across subsystems.

## 3.1 Source and language integrity

Never silently:

- switch source
- switch language
- mix source tracks
- mix languages
- substitute one source’s Reading Unit for another without an explicit user action

Fallback may change **extraction method**, but never the Source or Language of the Extraction Contract.

## 3.2 Unknown is a valid state

Missing metadata is not failure.

`UNKNOWN` must not be silently converted into:

- No
- False
- Unavailable
- Unsupported
- Bad quality
- Missing content

Hard rule:

> **Unknown quality ≠ unavailable content.**

## 3.3 Local content independence

Locally stored content remains readable even if:

- the source disappears
- the plugin is disabled
- the plugin is uninstalled
- the internet is unavailable
- the source account/session disconnects
- the source changes its catalog

Content already owned locally must not become unusable because the original source integration is unavailable.

## 3.4 No hidden destructive behavior

OneShelf must not silently:

- delete local content because a source no longer lists it
- interpret offline storage as deletion
- remove Shelf state when Follow changes
- remove Follow state when Shelf changes
- overwrite good files with suspicious data
- trust incomplete source catalogs
- silently replace user overrides

---

# 4. Core Domain Model

## 4.1 Work

A **Work** is OneShelf’s logical representation of a readable title.

Examples:
- Solo Leveling
- Berserk
- a specific book
- a research paper

A Work may aggregate multiple source listings, languages, and formats, while preserving provenance.

A Work is not defined merely by title equality.

## 4.2 Source Listing

A **Source Listing** is the concrete listing returned by one source/plugin.

It has source-specific identity and provenance.

## 4.3 Source Track

A **Source Track** represents one Work as exposed by one specific source and language.

Each Source Track has its own:
- catalog
- reading order
- Reading Unit identities
- source metadata
- session requirements
- extraction capabilities
- follow baseline
- availability state

Source Tracks must never be silently blended together.

## 4.4 Reading Unit

A Work is not assumed to be a sequence of integer chapters.

A Reading Unit may be:

- chapter
- special
- extra
- prologue
- epilogue
- one-shot
- other source-defined readable unit

Fields may include:

- internal identity
- raw source title
- display title
- unit type
- optional source-provided number
- optional adapter-derived display number
- optional volume
- source order / reading order
- optional release date
- source
- language
- availability state
- download state
- integrity state
- read state
- exact progress

`UNKNOWN` is valid for absent metadata.

### Numbering precedence

1. Source-provided number
2. Adapter-derived display number
3. UNKNOWN

Derived numbering:
- is presentation/order metadata only
- is never Reading Unit identity
- must not force specials/extras/prologues/epilogues into ordinary numeric chapter semantics
- may be used only when ordering/pattern evidence is reliable
- user correction overrides derived numbering

## 4.5 Volumes

Volumes are optional grouping metadata.

Do not require a physical folder hierarchy based on volumes.

## 4.6 Local Source Track

Imported/local-only content is first-class and represented through a `Local Source Track`.

It must remain readable/exportable without a network source plugin.

---

# 5. Catalog Trust Model

Catalog trust is foundational because Follow, Download Missing, navigation, and missing/deletion inference depend on it.

## 5.1 Complete snapshots only

Only a **complete catalog fetch/snapshot** may become Trusted.

A catalog is incomplete if, for example:

- pagination did not finish
- a required request failed
- the source returned only the first page
- the connection interrupted mid-fetch
- the adapter cannot establish completion

Incomplete catalogs:
- never replace Trusted state
- never trigger mass missing/deletion inference
- are not used as Follow baselines
- are not used by Download Missing

## 5.2 Trusted and Suspicious

Keep:

- current Trusted Catalog
- previous Trusted Catalog
- historical release events
- optionally a small recent snapshot/debug window
- never unbounded catalog history

Example:
- previous Trusted = 300 units
- new complete result = 7 units

If the change is implausible, mark:
`Catalog Suspicious`

Default heuristic signal:
- sudden loss of approximately ≥50%
- and at least 5 Reading Units disappear

This is a heuristic, not the sole validation.

## 5.3 Suspicious recovery

A suspicious new reality may become Trusted after:

- two complete consecutive successful checks showing the same new reality

OR:

- explicit advanced user action: `Trust This Catalog`

## 5.4 Trusted-only dependent operations

The following use only the last Trusted Catalog:

- Download Missing
- Follow baseline comparison
- missing/deletion inference
- catalog-dependent automation
- other destructive or persistent catalog-derived actions

A Suspicious Snapshot must never silently replace those decisions.

## 5.5 Temporarily missing units

If a unit disappears from the current source catalog:

- retain existing local content
- preserve last_seen
- track missing_since if useful
- do not delete local files
- do not treat disappearance alone as proof of permanent deletion

## 5.6 Completion state

Completed Works remain Completed even when new releases appear.

Instead show something like:
`3 releases since completion`

---

# 6. Unified Search and Work Matching

## 6.1 Search model

Search is:
**local-first + progressive live enrichment**

Flow:

1. Search local cache/index immediately.
2. Show results.
3. Query supported live sources.
4. Enrich/merge the same result set progressively.
5. Never clear local results while live sources are still searching.
6. A slow source must not block all results.

Display may show:
`7 / 8 sources searched`

Allow:
`Retry Source`

## 6.2 Search index

Use local SQLite + FTS5 or equivalent.

Index useful fields such as:

- Original title
- Display title
- Normalized title
- Loose normalized title
- Aliases
- Source titles
- Content type
- Languages
- Creator if known
- External IDs if known

## 6.3 Title normalization

Rules:

- preserve original titles
- normalize search keys, not display text
- strong Arabic normalization
- intentionally support `ة ↔ ه` loose equivalence because users may type one for the other
- no title stemming
- no automatic title translation
- no cover/image matching

## 6.4 Ranking

Ranking and grouping are separate.

Approximate text relevance tiers:

1. exact title
2. exact normalized title
3. exact alias
4. phrase/prefix
5. all-token
6. substring/trigram
7. fuzzy typo

Small boosts may come from:

- verified/user mapping
- exact-language alias
- Shelf presence
- multiple agreeing healthy sources

But these boosts must not overpower strong textual relevance.

## 6.5 Type compatibility

Sequential Art family:
- Manga
- Manhwa
- Manhua
- Comic

These are broadly compatible for candidate grouping/matching.

Novel/Book versus sequential art is a meaningful adaptation boundary and usually should not be hard-merged merely because titles match.

## 6.6 Soft Group vs Hard Mapping

**Soft Grouping is presentation-only.**

It must never become permanent identity by itself.

Any Shelf/Follow/Download action must bind to a concrete Source Listing/Source Track.

Hard Mapping requires:
- strong identifiers/evidence
- trusted mapping
- compatible strong evidence
- or explicit user action

User controls:
- Merge
- Split
- Unlink
- Never Match

User decisions persist and win.

## 6.7 Missing metadata

Missing creator/volume/date/etc. is not negative evidence.

`UNKNOWN ≠ mismatch`

## 6.8 Reading Unit identity

Reading Unit matching remains title-primary/simple for resilience across messy sources, while stable supporting evidence may include:

- source ID
- canonical URL
- source order
- aliases
- stable related source evidence

Preserve title aliases/history across source title changes where useful.

## 6.9 Same-source duplicate resolution

Use source listing ID/canonical URL as strong same-source identity where available.

Cached + live versions of the same source item should merge/update, not duplicate.

## 6.10 Matching telemetry

Explicitly removed:
- central matcher telemetry
- cloud matcher dataset
- matcher decision collector
- shared matcher logging

Local operational diagnostics must not recreate this under another name.

---

# 7. Discovery Cache

Default:

- TTL: 7 days
- cap: 250 MB
- LRU cleanup

Hard exclusions from cleanup:

- My Shelf
- Follow
- Downloads
- persistent mappings
- manual user corrections
- other authoritative persistent state

Cache must be namespaced/versioned by:
- source
- plugin version/schema

A plugin update must not make stale parsed cache data look current.

Search queries/analytics are not persistently collected by default.

---

# 8. Direct URL Entry

Recovered from earlier accepted OneShelf project requirements and not contradicted by the final architecture:

OneShelf should support pasting a supported source/work URL as an alternate entry path where the relevant adapter can recognize it.

Expected behavior:

- identify the responsible source plugin
- normalize/resolve the URL
- fetch Work/source-track details
- present a Work preview/resolution flow
- never bypass auth/paywalls/DRM
- use the same matching/mapping rules as search

This is an alternate discovery entry path, not a separate extraction architecture.

---

# 9. Source Adapter / Plugin Architecture

## 9.1 Standard capabilities

Adapters may expose functions such as:

- `search()`
- `getWork()`
- `getChapters()` / Reading Units
- `getPages()`
- `getTrending()`
- `getLatest()`
- `getDownloads()`
- `checkSession()`
- `healthCheck()`

Missing metadata is allowed.

## 9.2 Metadata classification precedence

1. User override
2. explicit source classification
3. plugin default
4. Unknown

Example:
an Arabic-only manga source may declare default language = Arabic.

## 9.3 Declarative community plugins

Community plugins must be **declarative non-executable source packages**, e.g.:

```text
source.osp
├ manifest.yaml
├ source.yaml
├ recipes/
│ search.yaml
│ work.yaml
│ catalog/chapters.yaml
│ reader.yaml
│ latest.yaml
│ trending.yaml
├ tests/
└ icon.webp
```

Do not allow arbitrary:

- `plugin.py`
- JavaScript execution
- shell
- eval
- exec

OneShelf Core owns:

- HTTP
- Scrapling
- browser
- sessions
- downloads
- DB
- filesystem
- path handling
- domain/network enforcement

Plugins describe operations; they do not own host capabilities.

## 9.4 Safe transforms

A bounded safe transform library may include:

- trim
- replace
- split/join
- extract_number
- parse_date
- normalize_url
- normalize_arabic
- HTML decode
- URL decode
- base64 decode
- bounded/safe regex

Resource limits must exist for regex/transforms.

## 9.5 Trust labels

Possible labels:

- Official
- Verified Community
- Community
- Local

These indicate review/trust level, **not broader device access**.

## 9.6 Native adapters

Arbitrary native code adapters are allowed only as rare reviewed official exceptions.

Future WASM may be considered only if genuinely needed.

Not v1 default.

## 9.7 Restricted RPC

Explicitly excluded.

---

# 10. Plugin Installation / Management

Plugins live in persistent storage.

Installation paths:

- Plugin Registry (primary)
- Upload local `.osp`

Install must be atomic:

1. download/copy to temporary area
2. verify hash/signature where applicable
3. validate manifest
4. validate API compatibility
5. validate recipes/domains/capabilities
6. static security checks
7. run packaged tests
8. atomically activate

Management:

- Configure
- Update
- Disable
- Uninstall
- Health
- Rollback

Rules:

- Update requesting new permissions requires explicit approval.
- No auto-publish to Registry.
- Uninstalling a plugin never deletes My Shelf/content.
- Missing plugin on Shelf preserves provenance and offers reinstall.
- Backups store plugin names/versions, never source sessions/passwords.
- Plugin account connection is optional/on-demand.

---

# 11. Plugin Network Security / SSRF

Domain allowlists are mandatory but insufficient.

OneShelf Core must:

- revalidate every redirect
- revalidate DNS resolution
- block unsafe targets by default:
  - loopback
  - private network ranges
  - link-local
  - otherwise unsafe internal-network targets
- apply equivalent network policy to browser requests
- prevent declarative plugins from using OneShelf as an SSRF mechanism into the homelab/LAN

The controlled local `OneShelf Test Source` may use an explicit development-only exception.

---

# 12. Scrapling and Source Discovery / Adapter Generator

## 12.1 Scrapling role

Scrapling is a core developer/community tool for source discovery and adapter generation.

Use:
- static first
- dynamic/browser escalation only if needed
- CSS/XPath
- APIs/XHR
- browser fetching
- adaptive selectors as a resilience layer

Scrapling does **not** own:

- Download Queue
- retry
- My Shelf
- packaging
- source priority
- extraction policy

No stealth/anti-bot bypass.

## 12.2 Generator pipeline

URL
→ static discovery
→ site mapping
→ capabilities
→ optional dynamic/browser discovery
→ XHR/DOM/media
→ confidence
→ `.osp` draft
→ domain/permission review
→ tests
→ developer review/edit
→ validation
→ local install
→ optional explicit Registry submission

## 12.3 Generator features

Must support:

- normal HTTP/static start
- route/pattern mapping
- search discovery
- multiple test queries, including Arabic where relevant
- work page discovery
- Reading Unit discovery preserving raw titles/order/type/number/volume/date
- reader discovery preferring HTML/embedded JSON/API/XHR/media
- browser discovery only if JavaScript is genuinely required
- underlying resource discovery, not screenshots
- capability states:
  - Confirmed
  - Probable
  - Unknown
  - Unsupported
- declarative `.osp` output
- automatic manifest generation
- recipe generation
- safe transforms only
- adaptive selector fallback only after normal selector failure and validation
- required source/CDN domain detection separated from ads/analytics/random domains
- capability-level auth testing
- `/login` existing does not mean the whole source requires authentication
- automated tests
- sanity tests beyond “selector returned something”
- multiple sample Works before high confidence
- preview before Generate
- Recipe Inspector
- Test/Edit/confidence
- Generate != Install
- Repair Existing Adapter
- diff changed selectors/API
- validate before active replacement
- atomic activation + rollback
- community repair/export/submit
- no access to My Shelf/download/progress/unrelated sessions
- Use My Session scoped to current source
- no raw passwords
- no auto-publish

## 12.4 Unsupported declarative sites

For sites requiring weird proprietary encrypted/signed behavior not safely expressible:

- `Unsupported by Declarative Adapter`
- `Native Adapter Review Required`

Do not force hacks.

---

# 13. Use My Session

Some sources need legitimate user-owned authenticated sessions.

Principles:

- user logs in themselves
- OneShelf never stores passwords
- session contexts are isolated per source
- community plugins never receive raw cookies/tokens/session files
- Core owns authenticated requests and domain scoping
- encrypted session state at rest
- encryption key stored separately
- backups exclude:
  - sessions
  - cookies
  - tokens
  - passwords
  - master key

Support where needed:

- cookies
- localStorage
- IndexedDB
- special handling for sessionStorage

States:

- Not Connected
- Connected
- Needs Reconnect
- Checking

Actions:

- Connect Account
- Validate Session
- Reconnect
- Disconnect Account
- optional Log Out & Disconnect if supported

Auth failure:
- pauses affected work
- moves jobs to reconnect/session-wait state
- does not blind-retry endlessly

Reconnect:
- reuse old state where possible
- atomically replace session after successful login
- resume affected work

Normal refreshed cookies may update session.

Disconnect:
- delete local source session immediately

Never log:
- cookies
- auth headers
- tokens

Plugin install must not force auth:
- Connect Account
- Skip

Attach session only to capabilities/domains that need it.

---

# 14. Extraction Policy

Extraction methods:

1. Direct
2. HTML/API
3. Reader Media
4. Browser

Browser should obtain/discover underlying resources, not use screenshots as the normal extraction path.

Every download has an **Extraction Contract**:

- Source
- Language
- Reading Unit/content
- Required output
- Preferred method

Precedence:

1. one-time override
2. source override
3. global default
4. plugin recommendation

Default fallback behavior:
**Preferred + Ask**

Additional modes:
- Strict / Locked
- optional Automatic Fallback with user-defined method order

Rules:

- Smart Retry same method before fallback.
- Fallback never changes source or language.
- Fallback must satisfy the same Extraction Contract.
- Auth/CAPTCHA/rate-limit/whole-source outage must not blindly trigger method fallback.
- Public reader may be an explicit one-time alternative if direct download requires login while the reader content itself is genuinely public.
- No auth bypass if content itself requires login.
- Health informs but does not silently rewrite configured methods.
- Never mix extraction methods within one Reading Unit.
- If switching extraction method after partial content:
  - redownload full unit into temp
  - validate
  - atomic replace
- Resume is method-specific.
- Plugin updates must not silently change configured method.
- Download History may record initial/final method and fallback reason locally.

---

# 15. Global Source Traffic Governor

One global Source Traffic Governor coordinates:

- Reader
- interactive Search / Work open
- manual user actions
- downloads
- read-ahead
- Follow
- Health

Priority:

1. Reader fetch
2. interactive Search / Work open
3. manual user actions / downloads
4. read-ahead
5. background Follow
6. Health

Browser jobs follow the same priority.

Low-priority browser work must never block Reader/direct user work.

Respect:
- per-source concurrency
- global concurrency
- rate limits
- Retry-After
- backoff
- fairness

---

# 16. Download Engine

Architecture:

persistent SQLite queue/state machine
+ Scheduler
+ Workers
+ Source Traffic Governor
+ staging
+ integrity verification
+ packaging
+ atomic-ish commit
+ recovery
+ history

Possible detailed states:

- QUEUED
- PREPARING
- DOWNLOADING
- VERIFYING
- PACKAGING
- COMMITTING
- COMPLETED
- PAUSED
- WAITING_FOR_SESSION
- WAITING_FOR_RATE_LIMIT
- RETRY_WAIT
- FAILED
- CANCELED
- RECOVERING

Normal UI should group these into understandable states rather than expose raw engine jargon everywhere.

## 16.1 Batch jobs

Large selections split into per-Reading-Unit jobs under a logical batch.

One failed unit ≠ entire batch failed.

Allow:
- Completed
- Completed with Issues
- Retry All Failed

Queue must be persistent and windowed; do not load gigantic queues wholly into RAM.

Controls:
- pause
- resume
- cancel
- retry
- reorder

## 16.2 Concurrency defaults

- normal HTTP/download concurrency: 4
- Browser concurrency: 1
- Browser limit independent from normal HTTP workers
- advanced user may raise limits

## 16.3 Retry

Default:
- initial attempt
- up to 3 retries where appropriate
- exponential backoff + jitter

Special rules:
- 429 → honor Retry-After
- auth failure → WAITING_FOR_SESSION
- 404 → do not blind-repeat
- 5xx/timeouts/resets → retryable

## 16.4 Resume

Image chapters:
- skip already-valid pages
- download missing/invalid pages

Direct files:
- HTTP Range when supported
- ETag / Last-Modified / If-Range
- never splice incompatible old/new versions

Browser:
- rediscover manifest
- resume only if compatible
- otherwise restart temporary full unit

Persist per-job manifest.

## 16.5 Integrity

Sequential images:
- exists
- non-zero
- decodable
- sensible dimensions
- not HTML error page
- expected page coverage where known

Books:
- content type / magic
- openable
- valid archive/container

No partial files in My Shelf.

One failed page may be repaired using the same method before broader fallback.

## 16.6 Cancel

Setting may choose:
- delete partial
- keep partial

## 16.7 History

Clearing Download History:
- does not delete content
- does not reset progress

No cloud telemetry.

---

# 17. Crash-Safe Commit / Recovery

SQLite + filesystem cannot be assumed to be one atomic transaction.

Use an idempotent **Commit Journal / reconciliation mechanism** around final content commits.

Pipeline concept:

validated staging artifact
→ commit journal entry
→ final filesystem move/rename
→ verify final artifact
→ DB transaction
→ mark commit complete

On startup reconcile cases such as:

- final file exists but DB registration did not finish
- DB says complete but final file commit did not finish
- stale commit journal entry
- interrupted packaging

Recovery must be safe to repeat.

Startup ordering:

1. recover jobs / commits
2. reconcile
3. only then clean proven-orphan staging

---

# 18. SQLite / Data Durability

SQLite is the source of truth.

Use:

- WAL mode
- schema migrations
- short/serialized write transactions as appropriate
- explicit consistency boundaries

Database backups must use a consistent SQLite snapshot/backup mechanism.

Do not blindly copy a live DB file while it is being modified.

---

# 19. Auto-Download While Reading

Hard rule:

> Reading ≠ Downloading.

Default:
**OFF**

Options when enabled:
- Current Unit Only
- Current + Read Ahead

Read Ahead default:
next 5 existing Reading Units

`Download Entire Work` remains a separate explicit action.

Engagement trigger when feature is enabled:
- approximately 12% progress
- plus evidence of genuine reading interaction
- not merely opening the unit

Flow:

open online reader
→ temporary Reader Cache
→ genuine engagement reaches threshold
→ permanent download current unit begins
→ optional bounded next units queued

Priority:
current reader fetch
> manual downloads
> read-ahead auto-downloads
> background Follow/Health

If user leaves the Work:
- current-unit job may finish
- already-started next unit may finish
- not-yet-started read-ahead jobs are removed/canceled

No source/language auto-switch.

---

# 20. Follow and New Release Detection

Follow binds to:

- Work
- Language
- Preferred Source
- Source Track

Never auto-switch source/language.

Other same-language sources being ahead may be shown informationally:

- View Alternatives
- Change Preferred Source

Follow and My Shelf are independent.

Unfollow:
- immediate
- Undo
- no destructive content deletion

Detection:
compare current Trusted Catalog versus Follow baseline.

Do not use:
- max chapter number
- assumed numeric gaps

Anything genuinely added after baseline = new.

First Follow:
- creates baseline
- does not flood the user with all old units

New ≠ auto-download.

Automatic new-release downloads are explicitly excluded.

### New vs Newly Available

Internal events may distinguish:

- NEW_RELEASE
- NEWLY_AVAILABLE

UI may group as “New” but details should remain precise where useful.

### Existing metadata updates

If the same recognized Reading Unit changes title/metadata:
- update metadata
- do not create a new release

Reordering alone ≠ new.

Temporarily disappeared then returned:
- not new

Duplicate notifications suppressed.

Unseen/Seen notification state is separate from Unread/Read reading state.

### Preferred Source change

Changing Preferred Source:
- fetch new source catalog
- create Source Change Baseline
- do not report its entire existing catalog as new
- preserve reading progress

### Follow schedule

Default:
- approximately every 12 hours
- with jitter/randomization

Actions:
- Check Now
- Check All Now

Adapter/plugin update actions remain separate:
- Update Now
- Update All

Group checks by source to avoid bursts.

Prefer API/HTML.
Use browser only if declared necessary.

Track:
- Last Attempted
- Last Successful

UI emphasizes Last Successful.

---

# 21. Source Health

Health is capability-level.

Capabilities may include:

- Search
- Work Details
- Catalog
- Reader
- Download
- Authentication

Overall user-facing states:

- Healthy
- Degraded
- Unavailable
- Rate Limited
- Reconnect Required
- Catalog Suspicious

Internal error categories may include:

- Timeout
- 5xx
- Parser Failure
- Selector Missing
- Auth Failure
- Rate Limit
- Unexpected Response
- Catalog Validation Failure

Rules:

- Rate Limited is not “Broken”.
- Reconnect Required is distinct from unavailable.
- One failure does not degrade the whole source immediately.
- Use repeated thresholds + hysteresis.
- Recovery should require trusted success to avoid flapping.
- One content 404 ≠ source failure.
- Repeated parser/selector failures are a strong adapter-update signal.
- Record plugin version with diagnosis.
- Passive signals are primary.
- Active checks only when needed/explicit.
- Do not periodically spin up browser solely for health.
- Active checks use the Traffic Governor at low priority.
- Health describes; it does not silently change source/language/extraction.

UI location:
Settings → Sources

Search only shows concise source progress/count information, not a health dashboard.

---

# 22. My Shelf

My Shelf is a personal library, not a download folder.

Adding to Shelf:
- persists immediately
- does not require downloaded files

Core views/filters:

- All
- Saved
- Reading
- Completed
- Favorites

Pin remains separate from Favorite.

Pinned items may appear prominently at top.

Removing from Shelf:
if files/progress exist, confirm:
- Keep Files
- Delete Files

Unfollow is separate.

Completed:
- remains Completed when new releases appear
- show “N releases since completion”
- optional delete/keep files when marking Completed, but keep metadata/status/progress if files are deleted

Reader progress stored in SQLite.

Shelf search:
- local only
- same local index/ranking philosophy
- no live requests

Formats:

Sequential art:
- CBZ typically one Reading Unit per CBZ
- preserve original images
- no unnecessary recompression

Books:
- PDF / EPUB / original supported formats
- multiple formats may coexist

Per-unit local record:
- source
- path
- integrity
- page count
- download state
- read state
- progress

Import:
- CBZ
- PDF
- EPUB

If association is confident:
- associate automatically

If uncertain:
- Choose Work
- Create Local Work

No aggressive merge.

---

# 23. Shelf / Follow / Files Independence

Hard cross-system rules:

- Remove from Shelf does not automatically Unfollow.
- Unfollow does not remove Shelf entries.
- Unfollow does not delete local files.
- Delete Files does not remove Follow state.
- Delete Files does not remove reading progress metadata unless the user explicitly requests that separately.

---

# 24. Storage Model

## 24.1 Roots

Default Docker deployment may use one persistent volume.

Advanced:
multiple Storage Locations from the start.

Each root has:
- stable root ID
- configured path/mount
- availability state
- free space
- default/non-default state

DB stores:
`storage_root_id + relative_path`

Never use absolute host paths as identity.

## 24.2 Layout

Stable high-level families:

- Sequential Art
- Books
- Other

Exact type stored in DB.

Human-readable hierarchy:
Work
→ Language
→ Source
→ Files

Use short stable OneShelf IDs in names where needed for collisions/recovery.

Preserve Arabic/Unicode filenames.

Source filenames are untrusted.

Core owns safe filename/path generation.

Plugins never decide filesystem paths.

Do not automatically rename/move files when metadata changes.

Future explicit `Reorganize` may do that.

## 24.3 Per-root staging

Every Storage Root has:

`<root>/.oneshelf/staging/`

on the same filesystem.

Reasons:
- atomic-ish rename/commit
- avoid cross-filesystem copies during finalization
- recovery
- detect unavailable destination before download

Partials stay in staging only.

Scanner/reader ignores staging.

## 24.4 Path Safety

Block:

- `../`
- absolute path injection
- symlink escape
- malicious filenames
- plugin-supplied paths

Delete Files only within managed roots.

## 24.5 Disk Space Guard

Per root default reserve:

- 5% of disk size
- capped at 5 GB

Warning:
around 2× reserve.

At reserve:
- pause new automatic/background writes
- never auto-delete library content

Large operations also perform expected-size preflight.

## 24.6 Storage unavailable

Offline/unavailable root state:

`Storage Location Unavailable`

Do not:
- generate mass Missing Local File
- destructive cleanup
- destructive integrity repair

Resume reconciliation only when root is available again.

## 24.7 Manual filesystem changes

Manual file deletion:
- mark Missing Local File
- do not remove Work/Follow/progress

Manual relocation:
- recover using IDs where possible
- otherwise use import/reconciliation flow

## 24.8 Migration

Persistent/resumable flow:

preflight
→ pause affected writes
→ stream copy
→ checksum verify
→ switch root mapping
→ reconcile
→ offer keep/delete old copy

Never delete old storage automatically.

Reads from old root may continue during migration where practical.

Docker mount path change without physical data move:
- update root mapping
- validate/scan
- do not perform unnecessary content migration

---

# 25. Staging Cleanup

After successful jobs:
- cleanup leftovers within ~24 hours

Resumable failed-job partials:
- may be kept ~7 days

Startup:
1. recover jobs
2. recover commits
3. reconcile
4. clean only proven-orphan staging

Never cleanup before recovery.

---

# 26. Reader Architecture

Two reader families:

1. Sequential Reader
2. Book Reader

The Reader is a core v1 subsystem.

## 26.1 Reader principles

Content first.

Three conceptual layers:

1. Content
2. Reading Controls
3. Advanced / Recovery

Do not turn Reader into a dashboard.

## 26.2 Reader shell

Auto-hiding:
- top bar
- bottom progress/navigation

Top bar:
- Back
- Work title
- current Reading Unit
- TOC
- compact download state/action
- More menu

More:
- Mark Read
- Mark Unread
- Change Source
- Reader Settings
- Repair
- Work Details
- advanced details

Back:
- returns to correct navigation context
- flushes progress safely

## 26.3 Distraction-Free

Modes:

### Smart
- controls appear predictably on interaction
- auto-hide after ~3 seconds idle

### Hidden by Default / Minimal
- top/bottom bars start hidden
- remain hidden unless explicitly summoned
- navigation can happen primarily through keyboard, mouse zones, touch gestures

Controls must not auto-hide while:
- menu open
- drawer open
- settings panel open

An Always Visible mode may be added later if useful, but is not required.

## 26.4 Sequential modes

Required:

- Long Strip
- Single Page
- Double Page

Reading directions:
- LTR
- RTL
- Vertical where appropriate

## 26.5 Mouse / keyboard / touch

Desktop Single/Double:
- edge zones previous/next
- center zone show controls
- respect reading direction

Keyboard:
- previous/next
- Space / Shift+Space
- fullscreen
- TOC
- download current
- zoom
- reset fit
- Esc for controls/panels

Shortcut remapping may be deferred.

Touch:
- center tap controls
- horizontal swipe page navigation when relevant
- vertical natural scroll for Long Strip
- pinch zoom
- double-tap zoom

## 26.6 Long Strip

- bounded nearby render window
- do not hold entire huge chapter decoded in memory
- percentage progress
- optional page detail
- restore approximate relative scroll position

## 26.7 Single Page

- centered
- Fit Smart/Width/Height/Original

## 26.8 Double Page

Support:

- LTR pairing
- RTL pairing
- first page as single cover
- manual Shift Pairing correction
- sensible wide/spread page handling
- no AI crop requirement
- no destructive cropping

## 26.9 Auto Fit

Options:

- Smart
- Width
- Height
- Original

Smart should be stable rather than oscillate visibly every page.

## 26.10 Zoom

Desktop:
- keyboard
- Ctrl+wheel

Touch:
- pinch
- double tap

While zoomed:
- drag pans
- avoid accidental page advance

## 26.11 Progress

Bottom UI is minimal.

Progress models:

- Manga/PDF: page-based
- Long Strip: position-based
- EPUB: logical/percentage

Clicking progress may open scrubber.

## 26.12 TOC

Drawer/sheet, not a separate full page.

Desktop:
- side drawer

Tablet:
- side sheet

Mobile:
- full-height/bottom sheet

Shows Reading Units and states.

Light filters:
- All
- Unread
- Downloaded
- New

Current unit highlighted subtly.

## 26.13 End-of-unit

Use Source Track order, never `chapter + 1`.

Card:
- completed state
- next actual Reading Unit
- Back to Work

Next may be:
- Special
- Extra
- etc.

## 26.14 Auto Read

Default threshold:
97%

Always allow:
- Mark as Read
- Mark as Unread

Manual status change does not eject the user.

## 26.15 Continue Reading

Same-source:
- restore exact progress where possible

Long Strip:
- approximate scroll position

## 26.16 Source indicator / switching

Subtle indicator:
`Arabic · Source A`

Source switching:
- manual only
- same-language alternatives may be shown
- cross-source warning: page layouts may differ
- options:
  - Start This Unit
  - Try Approximate Position
- never pretend exact page equivalence across sources
- if equivalent unit cannot be confidently found:
  - state that
  - open target Source Track
  - do not guess

## 26.17 Reader settings precedence

Current Session
> Work Preference
> Content-Type Default
> Global

Remember per-work:
ON by default

Normal settings:
- Mode
- Direction
- Fit
- Background
- Page Gap
- Double Page

Advanced:
- Preload
- input behavior
- auto-read threshold
- Read Ahead

Background:
- Black
- Dark Gray
- White

## 26.18 Preloading

Single/Double:
roughly next 7 + previous 4

Long Strip:
bounded nearby window

Do not expose unless advanced.

## 26.19 Download state in Reader

Compact:
- not downloaded
- progress
- downloaded

Auto-download status remains quiet.

`Download Entire Work` is a larger Work-page/More action, not a page-navigation control.

## 26.20 Reader Cache

Temporary Reader Cache ≠ permanent download.

Normal Reader should not show noisy “Cached” badges.

Details may distinguish:
- Online / temporarily cached
- Downloaded

Cache identity includes:
- source
- Reading Unit identity
- resource identity/validator

Never key only by title/display chapter number.

## 26.21 Error recovery

Page load failure:
- Retry
- Repair
- Skip

Corrupt local page:
- Repair from Source
- Skip

Never silently delete.

If source unavailable:
- local content remains readable
- cached online pages remain usable where possible
- no automatic source switch

Reconnect:
- inline Reconnect
- resume same Reading Unit

Rate Limit:
- calm temporary state
- automatic retry when appropriate

Offline:
- clearly distinguish Downloaded versus Online-only units

## 26.22 Book Reader

### EPUB

Features:
- font family
- font size
- line height
- margins
- theme
- TOC
- search
- bookmarks
- highlights
- logical progress

TOC drawer may include tabs:
- TOC
- Bookmarks
- Highlights

No fake fixed page count requirement.

### PDF

Features:
- page navigation
- zoom
- fit width/page
- text search if text layer exists
- bookmarks
- highlights
- progress
- optional thumbnail/page/TOC/bookmark sidebar

No full notes/drawing/annotation system in v1.

Only:
- Bookmarks
- Highlights

Sequential page bookmarks are not required in v1.

## 26.23 Multi-tab progress

Multiple open tabs must not regress progress via stale writes.

Progress writes:
- debounced
- force flush on:
  - unit change
  - tab hidden
  - reader exit
  - browser lifecycle event

## 26.24 Loading

Use layout-preserving placeholders/skeletons rather than disruptive blank spinners.

Minimal one-time guidance may say:
“Tap/click center to show controls.”

---

# 27. Untrusted Reader Content Isolation

Security hard rule:

Never inject raw source HTML, EPUB HTML, or other untrusted document content directly into the OneShelf application origin/DOM.

Use:

- sanitization
- sandboxing where applicable
- strong CSP
- script blocking
- isolated document/PDF viewer context
- safe handling of SVG/HTML/embedded resources

Untrusted document content must not:
- access OneShelf auth/session context
- call privileged application actions
- escape allowed network policy

---

# 28. Web UI Authentication

## 28.1 Local/LAN

Single-user.

No OneShelf account.

Localhost:
- auth OFF by default

LAN:
- auth OFF by default
- any device genuinely inside the trusted LAN is considered fully trusted

LAN trust includes administrative actions such as:
- reset remote passkeys
- revoke remote sessions

BUT only when genuine LAN origin is established.

## 28.2 LAN trust boundary

LAN origin is derived from:
- actual network connection
- explicit server/trusted network configuration

Never trust arbitrary client-supplied headers.

`X-Forwarded-For` or similar:
- trusted only when received from explicitly configured Trusted Proxies

Traffic via a remote reverse proxy does not automatically gain LAN trust.

## 28.3 Remote access

Remote/Internet:
- Passkey-only built-in authentication

Advanced remote approaches may include:
- Tailscale/VPN
- trusted reverse proxy/auth
- homelab setups

Use a stable canonical HTTPS hostname for WebAuthn/passkeys.

LAN IP access remains separate and unauthenticated.

## 28.4 Internal WebAuthn identity

Passkeys may use a single fixed internal user identity.

This is an implementation detail only.

Do not expose it as a normal account/profile concept.

## 28.5 Recovery

First passkey setup includes Recovery Code.

Recovery Code:
- not used for normal login
- stored only as verifier/hash
- regeneration invalidates the old code
- may authorize registering a new passkey after passkey loss

Also support LAN Recovery.

LAN Recovery:
- genuine trusted LAN may reset remote passkeys
- revoke remote UI sessions
- allow new passkey registration
- no extra proof required under the trusted-LAN model

Confirmation must explicitly state that it affects only remote Web UI auth.

Must NOT affect:
- library
- Shelf
- progress
- downloads
- plugins
- source sessions
- content

## 28.6 Sessions

Remote session management:
- session label/ID
- current indicator
- created
- last active
- expiration
- Revoke
- Revoke All Other Sessions

Avoid invasive fingerprinting.

Default lifetime:
30 days

Configurable:
- shorter
- 90 days
- 1 year
- until manually revoked

Cookies:
- HttpOnly
- Secure on HTTPS
- SameSite
- no session tokens in Web Storage

Sensitive remote operations may require passkey re-auth.

## 28.7 Remote state-changing API security

Use:
- Origin validation
- CSRF protection
- secure session cookies

Reverse proxy auth:
- advanced
- only trust configured proxy
- never trust forwarded identity headers globally

---

# 29. First Run

Keep onboarding short.

Possible flow:

1. Welcome
2. Storage Location
3. Access Mode:
   - Local
   - LAN
   - Remote
4. If Remote:
   - canonical HTTPS hostname
   - first passkey
   - Recovery Code
5. Optional source setup
6. Finish

Do not force advanced configuration before the user reaches Home.

---

# 30. Notifications

v1 uses **In-App Notifications only**.

No Browser Notifications in v1.

## 30.1 Important notification classes

Important:
- New Releases
- Download Failed
- Reconnect Required
- Low Storage
- Catalog Suspicious

Informational:
- Plugin Update Available
- Source Recovered
- Backup/Import completion where useful

Background/diagnostic events should not notify:
- temporary timeout
- retry succeeded
- health probe succeeded
- cache operation
- individual page repair success

Notification Center is not a log viewer.

## 30.2 New Releases grouping

Per Work:
group releases.

Example:
`3 new releases`

If numeric and safe:
`Ch. 209–211`

If mixed:
- Chapter 209
- Special
- Extra Story

Across multiple Works:
group into concise summary where appropriate.

## 30.3 Seen vs Read

Notification:
- Seen / Unseen

Reading:
- Read / Unread / Partial

Completely independent.

Use:
`Mark All as Seen`

Not:
`Mark All as Read`

Provide:
`Clear Seen`

Clearing/seeing notifications must not change Reading state.

## 30.4 Download notifications

Avoid per-item success spam.

Use:
- grouped batch success when useful
- final failure notifications

Smart Retry:
- silent
- notify only after retries exhausted / user action needed

## 30.5 Reconnect

Deduplicate per Source.

One source needing reconnect should not create 20 notifications for 20 Works.

## 30.6 Rate Limit

Normally:
- status-only/silent

If prolonged and materially blocking:
- one concise in-app notice may be shown

## 30.7 Low Storage

Deduplicate per Storage Root.

Do not repeat continuously.

Notify again only:
- after recovery then recurrence
- or if severity escalates

## 30.8 Catalog Suspicious

In-app warning.

Must state:
OneShelf kept the last trusted catalog.

## 30.9 Plugin updates

Informational.

Update requiring new permissions:
- explicit review
- never silent auto-update

## 30.10 Source Recovered

Optional/silent by default.

## 30.11 Backup / Import

Backup Failure:
important

Backup Success:
silent by default

Large Import:
may notify when review is needed.

## 30.12 Actions

Prefer one or two focused actions maximum.

Examples:
- View Releases
- Retry
- Reconnect
- Manage Storage
- Review Update

## 30.13 Deduplication

Mandatory logical dedupe keys, e.g.:

- `source-auth:<source>`
- `storage-low:<root>`
- `catalog-suspicious:<source>`
- `new-release:<work>`

Repeated same problem updates existing notification/count.

## 30.14 Persistent vs Transient

Support both.

Persistent:
- stays while action required

Transient:
- may expire

Resolved notification:
- may remain in active center for ~1 hour
- then disappear

## 30.15 Cleanup

Important hard rule: bounded history.

Default:
- 30 days
- or 500 entries
- whichever comes first

Underlying subsystem state remains authoritative after notification cleanup.

---

# 31. Home Discovery Semantics

## 31.1 Trending

Show only when one or more adapters provide trusted `getTrending()` or equivalent source data.

Do not invent a fake global popularity score.

Aggregate into Works without pretending that ranking is globally authoritative.

If no supporting source data:
hide section.

## 31.2 Latest Releases

`Latest Releases` is a discovery feed from `getLatest()`/equivalent.

It is distinct from:
`New Releases` in Following.

## 31.3 Recently Added

Means:
**recently added to My Shelf**

Local/library state.

Not “latest content on the internet”.

## 31.4 Hero selection

Hero is contextual but stable.

Do not perform a network request just to choose Hero.

Approximate priority:

1. Continue Reading
2. relevant pinned or new-release Work
3. cached discovery fallback

---

# 32. UI/UX Visual Direction

The approved visual reference is authoritative.

The target feeling:

**personal library + classic reading room + modern web application**

Visual character:

- deep forest-green left sidebar
- warm ivory/cream main canvas
- muted olive accents
- warm natural wood
- restrained shadows
- literary serif headings
- clean UI typography for controls/metadata
- calm
- premium
- mature
- natural
- not childish
- not corporate
- not futuristic
- not neon
- not generic SaaS
- not Netflix/Plex imitation

## 32.1 Desktop navigation

Fixed dark forest-green left sidebar.

Primary destinations:

- Home
- Search
- My Shelf
- Following
- Downloads
- Sources
- Settings

Notifications/Needs Attention live top-right rather than as oversized primary nav destinations.

OneShelf logo at top-left.

Subtle botanical/leaf motif may appear sparingly.

## 32.2 Header controls

No normal profile/avatar.

Use:
- Notifications icon
- Needs Attention icon + count

Needs Attention:
- hidden when count = 0
- appears only for unresolved actionable issues:
  - Reconnect Required
  - Low Storage
  - Download Failed
  - Catalog Suspicious
- click opens concise grouped actionable popover/drawer

Notifications:
general in-app inbox.

Do not duplicate entries unnecessarily:
Needs Attention is a filtered shortcut over unresolved actionable problems.

## 32.3 Home

Home should visually stay very close to the approved reference.

Hierarchy:

- welcome heading
- short subtitle
- large Hero
- Continue Reading
- Trending if available
- Latest Releases if available
- Recently Added
- other library sections only when useful

Home is adaptive:
empty/irrelevant sections disappear.

Do not turn Home into a technical dashboard.

## 32.4 Hero

Large rounded banner.

May include:
- cover
- Work title
- type
- brief description
- Continue Reading
- wide atmospheric artwork

Hero is context-aware per prior rules.

## 32.5 Wooden shelves

Core identity motif.

Use prominently in:
- Home
- My Shelf
- selected Discover/Collection areas

Rule:

Library content
→ bookshelf language

System/management content
→ warm paper/card language

Do not put wooden shelves everywhere.

Avoid shelves in:
- Settings
- Downloads
- Sources
- Backup operational flows

Wood should feel premium and subtle, not cartoon skeuomorphism.

## 32.6 Work cards

Reusable:
- Compact
- Standard
- Detailed

All represent one logical Work.

Cover remains dominant.

Availability can be concise:
`Arabic · 2 sources`
`English · 1 source`

Do not show every internal state on cards.

## 32.7 Search UI

Same visual identity, lighter operational treatment.

- warm canvas
- serif page title
- large search field
- elegant filter chips
- Grid/List option
- cover-focused results
- no mandatory shelves for every result

## 32.8 Work Details

Smaller Hero-like header.

Include:
- cover
- title
- original title if useful
- type
- creator if known
- description

Primary actions:
- Continue / Read
- Add to Shelf
- Follow
- Favorite
- Pin

Small number of tabs:
- Read
- Details
- Sources

Reading Unit list should look like an elegant index rather than a technical table.

## 32.9 My Shelf

Strongest extension of bookshelf motif after Home.

Possible sections:
- Pinned
- Reading
- Completed
- Favorites

Provide:
- Shelf search
- Sort
- Filter
- Grid/List

## 32.10 Following

Reading journal/update inbox visual treatment.

Use warm paper-like rows/cards.

Prioritize:
- New Releases
- Needs Attention
- Up to Date

No charts.

## 32.11 Downloads

Operational screen:
- no shelves
- warm paper panels
- muted olive progress
- forest-green controls
- batch cards/rows
- expandable per-unit details

Do not become an analytics dashboard.

## 32.12 Sources

Elegant administrative list, loosely inspired by library catalog cards.

Main page:
- source
- type/language
- status
- last successful check
- Configure/More

Advanced technical details hidden.

## 32.13 Notifications

Warm paper-like right drawer/panel.

Actions:
- Mark All as Seen
- Clear Seen
- View All

## 32.14 Settings

Readable document/paper aesthetic.

Desktop:
- settings categories left
- current panel right

Categories:

- General
- Reader
- Downloads
- Storage
- Sources
- Notifications
- Backup
- Remote Access
- Advanced
- Developer

Progressive disclosure.

## 32.15 Backup/Restore

Archival/preservation feeling.

Restore is a multi-step workflow, not a casual destructive modal.

## 32.16 Export

Clean wizard:

Content
→ Format
→ Destination
→ Review

Selected Works may show small covers.

## 32.17 First Run

Warm welcome:
`Welcome to OneShelf`
`Your stories, one library.`

Subtle botanical accents acceptable.

## 32.18 Reader visual exception

Reader strips away most decorative identity.

No:
- shelves around pages
- decorative plants
- heavy cream frames

Use:
- Black
- Dark Gray
- White

Controls inherit OneShelf icon/typography quality.

## 32.19 Drawers/dialogs

Warm paper-like surfaces.

Avoid heavy glassmorphism.

Destructive dialogs explain:
- exactly what will happen
- what will remain untouched

## 32.20 Motion

Subtle:
- cover hover lift 2–4px
- soft drawer slide
- Hero crossfade

No:
- bounce
- elastic overshoot
- flashy transitions
- excessive parallax

Support reduced motion.

## 32.21 Mobile

Do not merely shrink desktop.

Suggested bottom navigation:

- Home
- Search
- Shelf
- Following
- More

More:
- Downloads
- Sources
- Notifications
- Settings

Reader is touch-first.

---

# 33. Backup / Restore

Exactly two main backup types.

## 33.1 Library Backup

Includes state/metadata such as:

- Shelf
- Works
- Follow
- reading progress
- Completed
- Favorites
- Pins
- manual edits/overrides
- mappings
- plugin requirements/versions
- small covers
- settings
- relevant history
- import metadata

Does NOT include downloaded reading files.

## 33.2 Full Backup

Everything in Library Backup
+
selected downloaded content

User may choose which Works/content to include to control size.

## 33.3 Hard exclusions

Never include:

- passwords
- cookies
- source sessions
- auth tokens
- active remote UI sessions
- recovery code
- session master key
- browser profiles
- staging
- partial downloads
- rebuildable caches

## 33.4 Format

Canonical OneShelf backup format, e.g.:

`.osbackup`

Contains:
- manifest
- schema/version
- checksums
- content inventory
- plugin requirements

## 33.5 Version compatibility

Old backup → newer OneShelf:
- may migrate forward in staging
- original backup remains unchanged

Newer backup/schema → older OneShelf:
- block restore
- require update first
- never silently discard unknown/newer fields

## 33.6 Preflight

Before restore:
- archive/checksum validation
- manifest
- compatibility
- space
- plugin requirements
- permission changes
- summary/issues

Missing plugin:
- does not block content restore
- offer reinstall/skip

Exact plugin unavailable:
- compatible newer may be used only with explicit review

New permissions:
- require approval

## 33.7 Restore modes

- Replace Current Library
- Merge With Current Library

Before Replace:
- create lightweight Safety Snapshot

Merge deterministic rules:
- current manual edits/mappings/settings win
- missing backup data may be added
- progress never regresses
- healthy local file is not replaced without reason
- verified-good backup file may replace corrupt/missing local file

## 33.8 Automatic backups

Default:
Library Backup every 7 days

If app was offline:
run at next suitable opportunity after startup

Full Backup:
manual by default

Verified retention:
keep last 4 verified backups

Rotation:
- create new
- verify new
- only then remove oldest according to retention
- never delete prior verified backup first

## 33.9 Backup location

Explicit `Backup Location`.

Default may be application persistent storage for convenience.

UI must warn:

> A backup on the same physical disk does not protect against disk failure.

Allow external mounts / alternate locations.

## 33.10 Encryption

Built-in backup encryption is not a core/default v1 requirement.

Secrets are excluded.

Users may use encrypted storage/tools externally.

---

# 34. Export System

Export ≠ Backup.

Export:
one-way safe portable copy outside OneShelf.

Never modify:
- library
- DB state
- progress
- source mapping
- original managed content

## 34.1 Scope

Support:

- Current Reading Unit
- Selected Units
- Range
- Entire Work
- Selected Works

Export contract:
- Work
- Language
- Source
- selected Reading Units
- selected formats

Never silently mix source/language.

## 34.2 Existing local content

Prefer local files as-is.

Copy:
- CBZ
- PDF
- EPUB
- other supported originals

No unnecessary recompression/rebuild.

## 34.3 Missing selected content

Ask explicitly:

- Export Downloaded Content Only
- Download Missing Then Export
- Cancel

If `Download Missing Then Export`:
UI must state:

> This will also permanently download these items into your OneShelf library.

Then:
normal Download Engine
→ integrity
→ permanent library commit
→ export

No hidden temporary download behavior.

## 34.4 Formats

Sequential Art:
CBZ default

Books/Research:
original PDF / EPUB / supported original

No conversion subsystem in v1.

No:
- CBZ → PDF
- EPUB → PDF
- PDF → EPUB

unless later added as a dedicated feature.

## 34.5 Multiple files

Default:
folder

Optional:
ZIP

Do not make giant ZIP default.

Avoid wasteful recompression of already-compressed formats.

## 34.6 Metadata

Preserve:
ComicInfo.xml inside CBZ where appropriate.

May include:
`oneshelf-export.json`

Portable metadata may include:
- title
- aliases
- language
- source
- Reading Units
- formats
- export date

Never include:
- secrets
- sessions
- tokens
- cookies
- internal absolute paths

Export metadata may improve future re-import confidence but must not be required for files to remain usable.

## 34.7 Naming

Export layout may be cleaner than managed internal layout.

OneShelf IDs need not appear by default.

Optional advanced inclusion may exist later.

## 34.8 Destination and conflicts

User selects explicit destination.

Preflight:
- online
- writable
- enough space
- conflicts

Never silently overwrite.

Conflict options:
- Skip Identical
- Replace
- Keep Both

Checksum-identical files may be skipped.

## 34.9 Jobs

Persistent/resumable.

Support huge exports.

Stream data.

Do not load entire export into RAM.

Destination-local staging where useful.

Verify copied files via checksums.

One failed file does not fail whole export.

Allow:
Retry Failed

Export is always Copy, never Move.

## 34.10 Local-only / missing plugin

Local Source Track exports normally.

Missing plugin does not block export of existing local files.

## 34.11 Export activity cleanup

Recent export activity only.

Default:
- 30 days
- or 100 jobs
- whichever comes first

Cleaning export history never deletes exported files.

---

# 35. Notifications / Export / Backup UX Separation

- Notifications = user attention/events
- Download History = job history
- Export recent activity = short-lived operation history
- Backup history = backup verification/restore state
- Diagnostics = operational troubleshooting

Do not collapse these into one generic log.

---

# 36. Multi-Client Live Updates

Core should provide an internal real-time event channel for UI updates such as:

- downloads
- notifications
- progress
- source/job state

Use:
- SSE
- WebSocket
- or equivalent

Fallback refresh/polling where needed.

No cloud service required.

---

# 37. Import

Supported:
- CBZ
- PDF
- EPUB

Default:
Copy

Move:
explicit option

Leave in Place:
advanced/future, not prominent v1 default

Import may:
- confidently associate
- ask Choose Existing Work
- create Local Work

Never aggressively merge uncertain content.

Drag & drop may be supported in UI.

---

# 38. Library Scanner

Scans managed storage and reconciles DB/storage.

Rules:

Manual delete:
- Missing Local File
- keep Work/Follow/progress

Offline root:
- Storage Location Unavailable
- no mass missing

Missing plugin:
- local files remain readable

Use OneShelf-specific IDs/metadata to aid recovery/import.

Per asset:
- checksum
- size
- path
- integrity

Checksums are never Work-matching evidence.

No complex storage dedup in v1.

---

# 39. ComicInfo / Packaging

Sequential art CBZ may include ComicInfo.xml where appropriate.

Preserve original images.

Do not recompress unnecessarily.

Packaging happens only after integrity verification.

---

# 40. API / Documentation

Recovered from earlier accepted project requirements and compatible with the final architecture:

The finished implementation should include clear API documentation for supported internal/public-facing application APIs as appropriate for maintainability and integration.

This does **not** imply a cloud API or public multi-tenant service.

Documentation should cover:
- core endpoint groups
- auth expectations
- events/realtime channel
- source/plugin-related APIs where relevant
- download/job state interfaces

Do not expose secrets/internal privileged implementation details unnecessarily.

---

# 41. Initial Test Source Suite

## 41.1 Real integration sources

1. MangaDex
2. 3asq / Al-Aasheq
3. WEBTOON
4. Tapas
5. Safahat / Hindawi
6. Project Gutenberg
7. arXiv
8. Standard Ebooks

## 41.2 Controlled local test source

Add:
`OneShelf Test Source`

Purpose:
deterministic failure/recovery testing.

## 41.3 Roles

Foundation:
- Project Gutenberg
- Safahat/Hindawi
- arXiv

Test:
- search
- metadata
- direct downloads
- PDF/EPUB
- Book Reader
- research papers
- Arabic metadata
- storage
- integrity

Sequential:
- MangaDex
- 3asq

Test:
- Work
- Source Track
- Language Track
- Reading Units
- irregular numbering
- specials/one-shots
- reader images
- CBZ packaging
- Download Missing
- Follow

Difficult web:
- WEBTOON
- Tapas

Test:
- dynamic/mixed pages
- partial web availability
- browser escalation
- optional login
- Use My Session
- reconnect
- capability-level auth

Format stress:
- Standard Ebooks

Test:
- one Work
- multiple formats
- format selection
- avoid creating duplicate Works per format

## 41.4 Correctness vs stress

Stronger correctness/reference-style:
- MangaDex
- Project Gutenberg
- Safahat/Hindawi
- arXiv

Real-world stress:
- 3asq
- WEBTOON
- Tapas

3asq:
use for public catalog/parser/Reading Unit structure testing.
Do not assume it is an official/licensed default source.

## 41.5 Local deterministic cases

Simulate:

- irregular unit order
- irregular numbers
- Special
- Prologue
- chapter 3.5
- catalog 300 → 7
- HTTP 429 + Retry-After
- HTTP 500
- session expiry
- HTML returned instead of image/media
- corrupted/invalid media
- interrupted download
- changed ETag/version validator
- redirect to unapproved domain
- malformed metadata
- incomplete pagination
- other recovery edge cases

Principle:

real sources = integration testing  
local test source = deterministic failure testing

---

# 42. Default Values

Approved defaults:

## Backup
- Library Backup: every 7 days
- Full Backup: manual
- retain last 4 verified backups

## Discovery Cache
- TTL: 7 days
- cap: 250 MB
- LRU

## Reader Cache
- TTL: 7 days
- cap: 5 GB
- LRU
- never evict current Reading Unit / currently open nearby pages / permanent downloads

## Auto-download
- OFF by default
- when enabled: trigger at ~12% + genuine reader interaction

## Read Ahead
- next 5 existing Reading Units

## Auto Mark Read
- 97%

## Reader Smart Controls
- auto-hide ~3 seconds

## Download concurrency
- HTTP/download: 4
- Browser: 1

## Follow
- ~12 hours + jitter

## Notifications
- resolved active item disappears after ~1 hour
- history 30 days or 500 entries

## Export activity
- 30 days or 100 jobs

## Diagnostics
- 7 days or 100 MB

## Retry
- initial attempt + up to 3 retries where appropriate

## Remote UI session
- 30 days

## Storage reserve
- 5% of root
- capped at 5 GB
- warning around 2× reserve

## Catalog suspicious heuristic
- roughly ≥50% sudden loss
- and at least 5 units
- only on complete snapshots
- never sole source of truth

## Staging
- successful leftovers cleanup ~24h
- resumable failed partials ~7 days

Source-specific:
- timeout
- rate limit
- page-size specifics
remain plugin/source-specific where appropriate.

---

# 43. Local Diagnostics

Keep only necessary operational diagnostics:

- parser/network failures
- job failures
- health operational data
- bounded troubleshooting details

Default retention:
- 7 days
- or 100 MB
- rotating

Never store:
- passwords
- cookies
- tokens
- auth headers
- sensitive full response bodies

Never recreate matcher-decision telemetry.

---

# 44. Home / UI Notification Interaction

Top-right:
- Needs Attention icon + count
- Notifications bell + count

Needs Attention:
- secondary to Hero
- hidden when zero
- actionable unresolved issues only

Click:
concise grouped popover/drawer with:
- Reconnect
- Manage Storage
- Retry
- View Source

Notifications:
general inbox.

---

# 45. UI Progressive Disclosure

General rule:

Normal UI:
what normal users need to complete the task.

Advanced UI:
technical knobs, diagnostics, engine details.

Examples:

Downloads normal:
- location
- concurrency
- auto-download while reading
- Read Ahead

Advanced:
- HTTP workers
- Browser concurrency
- retry behavior
- extraction behavior
- diagnostics

Reader normal:
- Mode
- Direction
- Fit
- Background
- Page Gap
- Double Page

Advanced:
- Preload
- input behavior
- threshold
- Read Ahead

Sources normal:
- status
- capabilities
- account/session
- update
- configure

Advanced:
- manifest
- domains
- diagnostics
- recipes
- plugin version internals

---

# 46. Error UX

User-facing errors should answer:

1. What happened?
2. What did OneShelf do safely?
3. What can the user do?

Example:

`Source catalog looks unusual.`  
`OneShelf kept the last trusted catalog.`  
`[Retry] [View Source]`

Avoid exposing raw engine errors unless in expandable technical details.

---

# 47. Destructive Action UX

Do not use “Are you sure?” alone.

Explicitly state:

- what will be removed
- what will remain
- whether files/progress/Follow/Shelf are affected

Examples:
- Remove from Shelf
- Delete Files
- Replace Current Library on restore
- Reset Remote Passkeys
- Uninstall Source Plugin

---

# 48. Security Summary

Hard security boundaries:

- declarative community plugins
- Core-owned network/filesystem/session capabilities
- domain allowlists
- redirect/DNS revalidation
- SSRF blocking
- genuine LAN trust only
- trusted proxy configuration required
- Origin/CSRF protection remote
- secure cookies
- no auth tokens in Web Storage
- untrusted document isolation
- path traversal/symlink escape blocking
- no plugin filesystem control
- no raw session exposure
- no secrets in logs/backups/export metadata

---

# 49. Explicit v1 Exclusions

Do not add these back into scope:

- cloud OneShelf account
- multi-user
- arbitrary executable community plugin code
- restricted-RPC plugin design
- matcher telemetry / central collector / shared decision dataset
- automatic source switching
- automatic cross-language fallback
- automatic translation
- title stemming
- cover/image matching
- AI matching requirement
- browser notifications
- automatic new-release downloads
- complex storage deduplication
- full note/drawing/annotation system
- social feed
- comments/reviews
- followers
- chat
- ads
- subscriptions/payments
- gaming/achievement systems
- anti-bot stealth/bypass
- CAPTCHA bypass
- paywall bypass
- DRM bypass
- screenshot-based normal extraction
- hidden destructive cleanup
- implicit format conversion subsystem
- uncontrolled plugin access to LAN/internal services

---

# 50. Non-Goals That Must Not Delay v1

Do not let optional future ideas delay the required application.

Examples:
- advanced multi-user
- cloud sync
- generalized annotation suite
- AI recommendation engine
- arbitrary automation marketplace
- WASM plugin runtime
- advanced format conversion
- storage deduplication
- browser/system push notifications

---

# 51. Acceptance Invariants

The implementation must preserve these invariants:

1. A Suspicious or incomplete catalog can never erase trusted state.
2. Source/language never switch silently.
3. A Soft Group never becomes permanent identity merely because titles look similar.
4. User overrides never get silently overwritten by source refresh.
5. Unknown metadata never becomes negative evidence.
6. Unknown quality never blocks content merely because quality is unknown.
7. Reading never implies permanent download unless user enabled auto-download.
8. Auto-download is OFF by default.
9. Follow never auto-downloads new releases.
10. Remove from Shelf, Unfollow, and Delete Files remain independent actions.
11. Local content remains readable without source/plugin/network.
12. Reader content cannot execute privileged OneShelf actions.
13. Community plugins cannot execute arbitrary code.
14. Plugins cannot access arbitrary filesystem paths.
15. Plugins cannot SSRF into trusted LAN/internal services.
16. Incomplete downloads never appear as completed My Shelf content.
17. A crash during commit must be recoverable idempotently.
18. Offline storage is not treated as mass deletion.
19. Backup never contains source sessions/passwords/tokens.
20. Export never silently modifies the library.
21. Download Missing Then Export requires explicit notice that it permanently downloads to the library first.
22. Notifications never alter Reading state.
23. Clearing history never deletes underlying content/state.
24. Reader navigation follows Source Track order, not numeric chapter assumptions.
25. Cross-source progress transfer is approximate/manual, not fake exact-page equivalence.
26. Browser background work cannot starve Reader/direct user work.
27. Search results represent Works, not duplicated source cards.
28. Cover images are presentation only, never identity evidence.
29. Matching diagnostics never become telemetry/central collection.
30. Remote access uses secure passkey/session/CSRF boundaries while genuine LAN remains fully trusted per configuration.

---

# 52. Implementation Structure Expectations

The implementation should preserve clear subsystem boundaries.

At minimum, architecture should separate responsibilities such as:

- API layer
- application services
- source adapters/plugins
- HTTP retrieval
- browser retrieval
- source sessions
- search/indexing
- matching/mapping
- catalogs/trust
- metadata/provenance
- Download Scheduler/Workers
- Traffic Governor
- packaging/integrity
- SQLite/data access
- storage roots
- Reader/cache
- Follow
- Source Health
- Notifications
- Backup/Restore
- Export
- Import/Library Scanner
- events/realtime updates
- authentication/security
- diagnostics/logging
- frontend
- tests

Source-specific extraction logic must not contaminate generic queue/download/storage logic.

Keep units/components small enough to understand and test independently.

---

# 53. Testing Expectations

Testing must include:

- unit tests
- integration tests
- deterministic local source failures
- source adapter contract tests
- migration tests
- crash/recovery tests
- queue persistence/restart recovery
- storage offline/reconnect
- catalog incomplete/suspicious/trust transitions
- session reconnect flows
- rate limits
- download resume/validators
- corrupt media repair
- path safety
- SSRF attempts
- untrusted EPUB/HTML isolation
- remote CSRF/origin checks
- backup compatibility
- restore merge rules
- export resume/conflicts
- Arabic normalization
- RTL/LTR UI
- matching manual overrides
- multi-tab progress non-regression
- event/realtime updates
- accessibility-critical interactions

Do not run destructive tests against the user’s real library data.

Use isolated test data and the OneShelf Test Source.

---

# 54. Final State of Product Design

The product architecture is considered sufficiently specified for a final implementation Meta Prompt.

No major subsystem remains intentionally undefined.

The remaining visual work may refine high-fidelity screens, spacing, typography sizing, icons, and responsive detail, but must remain inside the approved visual language and product behaviors.

Do not treat those visual refinements as permission to change architecture or feature semantics.

---

# 55. Final Instructions for GPT-6 Astra

When asked to produce the final OneShelf implementation Meta Prompt:

1. Use this Master Specification as the single authoritative product source.
2. Inspect repository/project instructions and old OneShelf docs for implementation context.
3. Cross-check them against this spec.
4. List any true contradiction before generating the prompt.
5. Do not silently reintroduce removed features.
6. Do not silently omit hard rules because the final prompt becomes long.
7. Prefer explicit implementation phases and acceptance criteria over vague prose.
8. Preserve all data-safety, source-integrity, session, SSRF, crash-recovery, and catalog-trust rules.
9. Preserve the exact v1 exclusions.
10. Preserve the visual direction and the approved UI reference rather than replacing it with a generic dashboard.
11. The final Meta Prompt should be suitable for a coding agent such as Codex/Claude and should tell the agent to inspect the existing repository before modifying anything.
12. Require implementation to follow existing project conventions where they do not conflict with this spec.
13. Require tests before claiming completion.
14. Require no destructive operations against existing user data.
15. Require all migrations and persistent-state changes to be reversible/recoverable where practical.
16. Do not implement until the user explicitly asks to execute; generating the Meta Prompt is a planning artifact, not execution authorization.

---

# 56. Memory / Prior-Context Reconciliation Notes

The following useful requirements were recovered from older OneShelf project context and retained because they are compatible with the final architecture:

- self-hosted Docker deployment
- Arabic + English support
- RTL/LTR support
- persistent jobs and restart recovery
- application-wide concurrency control
- stable source/work/Reading Unit identities
- atomic validation/commit patterns
- direct supported URL entry
- real-time UI progress/events
- API documentation
- avoid loading huge scanned/visual works fully decoded into RAM
- keep display text, matching text, and identity concepts distinct

The following older ideas are superseded and must **not** override this spec:

- “Reader is optional/future” → superseded; Reader is core v1.
- generic UI redesign away from the chosen visual reference → superseded by the approved library/wood-shelf visual direction.
- matcher telemetry/logging concepts → explicitly removed.
- browser notifications → explicitly excluded from v1.
- generic multi-theme assumptions → current approved visual identity is authoritative unless the user later explicitly requests theme switching.


<!-- END AUTHORITATIVE MASTER SPECIFICATION -->

## G. WEBSITE ACCESS, SOURCE DISCOVERY & DOWNLOAD EXTRACTION

This final execution section operationalizes Master §§9–16 and 41. It does not extend the approved source list, broaden access entitlements, weaken the declarative plugin boundary, or change Extraction Contracts. Apply the same policy to manual investigations, generator probes, adapter tests, runtime requests, browser subrequests, and repair workflows.

### G1. Investigate the actual source before implementing recipes

Identify the source, canonical domain and approved aliases, intended content family, languages, stable listing/Reading Unit evidence, real reading order, available formats, and capability-specific access conditions. Keep public catalog access, public previews, full readable content, downloadable content, and authenticated capabilities distinct.

Start with normal HTTP/static discovery through controlled Core infrastructure and Scrapling. Inspect the actual HTML, structured data, exposed APIs and source-provided resources. Use CSS/XPath and validated safe transforms. Dynamic/browser escalation is justified only when the required capability genuinely needs it; one dynamic search page does not make all operations browser-dependent.

Check official/documented APIs, server-rendered content, embedded JSON/hydration data, manifests, and the reader's own XHR/DOM/media as appropriate to what the source actually serves. These are investigation candidates, not a sequence of mandatory extra requests against every site. Do not guess URLs/selectors and report them as verified. Do not execute scraped script text with eval/exec or insert executable hooks into community packages.

Browser-assisted investigation must discover underlying resources and actual content order. Screenshots are not the normal extraction path. Do not use stealth, CAPTCHA solving, paywall bypass, DRM bypass, or repeated challenge attempts as a fallback strategy. When a legitimate user session is needed, use only the current source's Core-owned Use My Session flow. The user logs in; no passwords are stored or supplied to plugins.

### G2. Generate declarative packages with reviewed permissions

Implement the full pipeline:

URL → static discovery → route/site mapping → capabilities → optional dynamic discovery → XHR/DOM/media evidence → confidence → `.osp` draft → domain/permission review → tests → developer review/edit → validation → local install → optional explicit Registry submission.

Generate the manifest and source/recipe definitions, including search, Work, catalog/Reading Units, reader, latest and trending where supported. Preserve missing values as Unknown. Report capability confidence as Confirmed, Probable, Unknown or Unsupported; a selector returning something is insufficient for high confidence.

Test several representative Works and multiple search queries, including Arabic when relevant. Verify positive and genuine empty queries so latest-post widgets, whole catalogs and unrelated recommendations cannot masquerade as search results. Verify URL-only support independently from search. A missing capability does not invalidate a separately verified capability.

Discover necessary source and CDN domains separately from ads, analytics and unrelated domains. Apply allowlists, redirect/DNS checks and private-target restrictions in every transport. A plugin cannot nominate arbitrary LAN/browser endpoints or filesystem locations. Safe transforms, including regex, must be bounded. Trust labels never loosen these limits.

Provide Preview before Generate, a Recipe Inspector, Test/Edit/confidence controls, Repair Existing Adapter, diffs of changed selectors/APIs, validation before replacement, atomic activation and rollback, and explicit community export/submission. Generate is not Install. Install is not Registry publication. New permissions require user review. The generator cannot access My Shelf, downloads, progress or unrelated sessions.

Use adaptive selectors only after normal selector failure and validate the recovered result before accepting it. If the required behavior cannot safely be expressed declaratively, return Unsupported by Declarative Adapter / Native Adapter Review Required. Do not smuggle arbitrary code, proprietary signing hacks, or a restricted-RPC architecture into `.osp` to make a site appear supported.

### G3. Establish complete catalogs and stable content descriptors

Resolve all required pagination using actual completion evidence. Preserve raw unit titles, unit type, source-provided numbering, reliably derived display numbering, optional volume/date, stable supporting identity, language and source order. Respect source-defined Specials, Extras, Prologues, Epilogues, one-shots and decimal labels.

A request error, safety cap, repeated page, unexpected empty response, login page or incomplete dynamic list is not proof of completion. Return explicit incomplete state when completion cannot be established; do not publish partial data as Trusted or infer removed/missing units from it. Compare counts only when their source and meaning are known. Do not infer missing chapters from numeric gaps or duplicates from repeated numbers alone.

Deduplicate using the Master's title-primary Reading Unit matching with stable supporting source evidence. Same-source listing IDs/canonical URLs are strong listing identity; title aliases/history may support source title changes. Display numbering is never identity. Different formats of one book do not become separate Works or invented numbered chapters merely to fit old queue APIs.

Locate the actual complete file, prose or image resources within the declared capability and Extraction Contract. Preserve original images/files where supported. Determine resource sequence from the source, never request completion order. Reject unrelated covers, ads, tracking assets, transparent spacers, placeholders, login/error HTML, and incomplete visible-only lazy-loaded subsets. Validate dimensions together with content/provenance; do not turn a historical fixed pixel threshold into a universal quality or availability rule.

Prefer a source-provided complete supported original when consistent with the user's selected contract. Do not silently change a configured method just because another method is cheaper. Reader-generated content is only packaged into approved supported outputs; do not add the older combined-EPUB or scanned-PDF feature requirements or a conversion subsystem without review.

### G4. Hand execution to shared Core services

Recipes return typed metadata and content/resource descriptors, not private download loops, DB writes, host paths or raw credentials. Core controls HTTP/browser retrieval, source sessions, rate limits, retries, governor scheduling, temporary work, integrity, packaging, final commit and history.

Keep legitimate request context scoped to the current source/capability/domain. Revalidate redirects and resolution before credentials or resources can cross boundaries. Never blindly forward auth headers, cookies or source tokens to a CDN or redirect target. Browser-backed requests obey the same network policy.

For expiring resource URLs, refresh through the adapter's declared capability and compare stable identity/order/validators under a bounded policy. Do not assume every 403/404/reset is an expired session. Distinguish auth failure, CAPTCHA/action-required, rate limiting, source outage, transport failure and parser changes so they do not trigger inappropriate method fallback.

Apply Smart Retry within the current method. Honor Retry-After and bounded backoff. Auth failure waits for reconnect. Preferred + Ask, Strict/Locked and any enabled user-defined Automatic Fallback use the exact Master semantics. All fallback preserves source, language, Reading Unit/content and required output. Never mix methods within a single unit; switch through a complete fresh staged artifact, validation and safe replacement.

When a direct download requires login but the same reader content is genuinely public, offer the Master's explicit one-time alternative. This is not permission to bypass authentication for protected content or silently substitute a preview for a complete Work.

### G5. Verify through the application and record honest capability evidence

For each required integration, verify the supported workflow through the application's actual services and normal queue with isolated data. Capture representative real fixtures with URL, date, plugin version, access conditions and sanitization notes; never include secrets. Synthetic fault fixtures belong to the controlled OneShelf Test Source and security/recovery tests, and do not prove a real site works.

Test the roles assigned in Master §41: foundation PDF/EPUB/Arabic/research flows; sequential tracks, languages, irregular units and CBZ; difficult dynamic/mixed/auth/reconnect behavior; and Standard Ebooks format variants without duplicate Works. Test public 3asq catalog/parser structure without claiming it is an official/licensed default. Report unavailable external capabilities honestly instead of bypassing controls or dropping the required test from the matrix.

The controlled source must reproduce irregular order/numbers, Special, Prologue, chapter 3.5, complete 300→7 catalog loss, incomplete pagination, HTTP 429 with Retry-After, HTTP 500, session expiry, HTML-as-media, corruption, interruption, changed ETag/version validators, unapproved redirects, malformed metadata and other required recovery/security cases. Its local-network exception must not be enabled for ordinary plugins or production by accident.

For downloadable workflows, verify actual artifact contents, expected coverage when known, source order, checksum and readable container structure. Open/decode CBZ pages, inspect EPUB through its declared container/manifest/spine, and parse/render PDF content. A real-looking file with missing pages or empty prose is not a verified complete download. A homepage, HTTP 200, DOM match, successful search or preview is not download verification.

Record the implementation revision, plugin version, exact source/capability, tested Work and language, access/session conditions, catalog completeness, output format, artifact size/checksum/content counts, validation results and timestamp. Keep evidence local and secret-free. This engineering evidence must not become runtime matcher-decision telemetry or shared collection.

Complete the applicable cycle for each claimed source capability: investigate → establish access and identity → generate/review declarative recipes → test capability contracts → validate complete catalog/content descriptors → perform the actual supported Reader/download workflow → inspect resulting content → record verified behavior or the precise blocker.
