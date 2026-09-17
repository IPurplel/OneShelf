-- OneShelf initial domain schema (Master §4, §5, §13, §16–18, §20, §22–24, §30, §33–34, §37).
-- Conventions: TEXT ids from oneshelf.domain.ids; timestamps ISO-8601 UTC text;
-- NULL means UNKNOWN for optional metadata (Master §3.2); display/raw/search text kept separate.

CREATE TABLE storage_roots (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    path TEXT NOT NULL,                      -- configured mount path; never used as content identity
    is_default INTEGER NOT NULL DEFAULT 0 CHECK (is_default IN (0, 1)),
    reserve_override_bytes INTEGER CHECK (reserve_override_bytes IS NULL OR reserve_override_bytes >= 0),
    last_availability TEXT NOT NULL DEFAULT 'unknown'
        CHECK (last_availability IN ('available', 'unavailable', 'unknown')),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE works (
    id TEXT PRIMARY KEY,
    display_title TEXT NOT NULL,
    original_title TEXT,
    content_type TEXT NOT NULL DEFAULT 'unknown'
        CHECK (content_type IN ('manga', 'manhwa', 'manhua', 'comic', 'book', 'novel', 'paper', 'other', 'unknown')),
    content_type_source TEXT NOT NULL DEFAULT 'unknown'
        CHECK (content_type_source IN ('user', 'source', 'plugin_default', 'unknown')),
    creator TEXT,
    description TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE work_aliases (
    id TEXT PRIMARY KEY,
    work_id TEXT NOT NULL REFERENCES works(id) ON DELETE CASCADE,
    title TEXT NOT NULL,
    language TEXT,
    kind TEXT NOT NULL CHECK (kind IN ('alias', 'original', 'source_title', 'historical')),
    created_at TEXT NOT NULL,
    UNIQUE (work_id, title, kind)
);

CREATE TABLE source_listings (
    id TEXT PRIMARY KEY,
    source_id TEXT NOT NULL,
    source_listing_key TEXT NOT NULL,        -- source-provided ID or canonical URL (Master §6.9)
    canonical_url TEXT,
    raw_title TEXT,
    work_id TEXT REFERENCES works(id),
    created_at TEXT NOT NULL,
    last_seen_at TEXT,
    UNIQUE (source_id, source_listing_key)
);

CREATE TABLE source_tracks (
    id TEXT PRIMARY KEY,
    work_id TEXT NOT NULL REFERENCES works(id),
    source_id TEXT NOT NULL,                 -- plugin source id, or 'local' for Local Source Tracks
    language TEXT NOT NULL,                  -- BCP 47 tag; 'und' when unknown
    kind TEXT NOT NULL CHECK (kind IN ('source', 'local')),
    listing_id TEXT REFERENCES source_listings(id),
    availability TEXT NOT NULL DEFAULT 'unknown'
        CHECK (availability IN ('available', 'unavailable', 'unknown')),
    created_at TEXT NOT NULL,
    UNIQUE (work_id, source_id, language),
    CHECK ((kind = 'local') = (source_id = 'local'))
);

CREATE TABLE reading_units (
    id TEXT PRIMARY KEY,
    track_id TEXT NOT NULL REFERENCES source_tracks(id),
    source_unit_key TEXT NOT NULL,           -- stable source evidence (ID/URL) or local identity
    raw_title TEXT,
    display_title TEXT,
    unit_type TEXT NOT NULL DEFAULT 'unknown'
        CHECK (unit_type IN ('chapter', 'special', 'extra', 'prologue', 'epilogue', 'one_shot', 'other', 'unknown')),
    source_number TEXT,                      -- text preserves '3.5'; never identity
    derived_number TEXT,
    user_number TEXT,
    volume TEXT,
    source_order REAL NOT NULL,              -- Source Track reading order
    release_date TEXT,
    availability TEXT NOT NULL DEFAULT 'unknown'
        CHECK (availability IN ('available', 'unavailable', 'unknown')),
    first_seen_at TEXT NOT NULL,
    last_seen_at TEXT,
    missing_since TEXT,
    UNIQUE (track_id, source_unit_key)
);
CREATE INDEX reading_units_order ON reading_units (track_id, source_order);

CREATE TABLE assets (
    id TEXT PRIMARY KEY,
    reading_unit_id TEXT NOT NULL REFERENCES reading_units(id),
    format TEXT NOT NULL CHECK (format IN ('cbz', 'pdf', 'epub', 'other')),
    variant TEXT NOT NULL DEFAULT '',
    storage_root_id TEXT NOT NULL REFERENCES storage_roots(id),
    relative_path TEXT NOT NULL CHECK (
        relative_path <> '' AND relative_path NOT LIKE '/%' AND relative_path NOT LIKE '%\%' ESCAPE '|'
        AND relative_path <> '..' AND relative_path NOT LIKE '../%' AND relative_path NOT LIKE '%/../%'
        AND relative_path NOT LIKE '%/..'
    ),
    size_bytes INTEGER NOT NULL CHECK (size_bytes >= 0),
    sha256 TEXT NOT NULL CHECK (length(sha256) = 64),
    page_count INTEGER,
    integrity TEXT NOT NULL CHECK (integrity IN ('ok', 'corrupt', 'missing_local_file', 'unknown')),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE (storage_root_id, relative_path),
    UNIQUE (reading_unit_id, format, variant)
);

CREATE TABLE work_mappings (
    id TEXT PRIMARY KEY,
    kind TEXT NOT NULL CHECK (kind IN ('merge', 'split', 'unlink', 'never_match')),
    listing_id TEXT REFERENCES source_listings(id),
    work_id TEXT REFERENCES works(id),
    other_work_id TEXT REFERENCES works(id),
    decided_by TEXT NOT NULL CHECK (decided_by IN ('user', 'evidence')),
    created_at TEXT NOT NULL
);

CREATE TABLE user_overrides (
    id TEXT PRIMARY KEY,
    target_kind TEXT NOT NULL CHECK (target_kind IN ('work', 'track', 'reading_unit', 'listing')),
    target_id TEXT NOT NULL,
    field TEXT NOT NULL,
    value_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE (target_kind, target_id, field)
);

CREATE TABLE catalog_snapshots (
    id TEXT PRIMARY KEY,
    track_id TEXT NOT NULL REFERENCES source_tracks(id),
    completeness TEXT NOT NULL CHECK (completeness IN ('fetching', 'incomplete', 'complete')),
    trust TEXT NOT NULL DEFAULT 'none' CHECK (trust IN ('none', 'trusted_current', 'trusted_previous', 'suspicious')),
    unit_count INTEGER,
    evidence_json TEXT,
    plugin_version TEXT,
    fetched_at TEXT NOT NULL,
    CHECK (trust = 'none' OR completeness = 'complete')   -- incomplete snapshots are never trusted (Master §5.1)
);

CREATE TABLE shelf_entries (
    work_id TEXT PRIMARY KEY REFERENCES works(id),
    added_at TEXT NOT NULL,
    is_favorite INTEGER NOT NULL DEFAULT 0 CHECK (is_favorite IN (0, 1)),
    is_pinned INTEGER NOT NULL DEFAULT 0 CHECK (is_pinned IN (0, 1)),
    completed_at TEXT
);

CREATE TABLE follows (
    id TEXT PRIMARY KEY,
    work_id TEXT NOT NULL REFERENCES works(id),
    language TEXT NOT NULL,
    preferred_source_id TEXT NOT NULL,
    track_id TEXT NOT NULL REFERENCES source_tracks(id),
    last_attempted_at TEXT,
    last_successful_at TEXT,
    created_at TEXT NOT NULL,
    UNIQUE (work_id, language)
);

CREATE TABLE reading_state (
    reading_unit_id TEXT PRIMARY KEY REFERENCES reading_units(id),
    read_state TEXT NOT NULL DEFAULT 'unread' CHECK (read_state IN ('unread', 'partial', 'read')),
    locator_json TEXT,
    fraction REAL CHECK (fraction IS NULL OR (fraction >= 0 AND fraction <= 1)),
    revision INTEGER NOT NULL DEFAULT 0,     -- compare-and-set against stale multi-tab writes
    updated_at TEXT NOT NULL
);

CREATE TABLE download_batches (
    id TEXT PRIMARY KEY,
    label TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE download_jobs (
    id TEXT PRIMARY KEY,
    batch_id TEXT NOT NULL REFERENCES download_batches(id),
    reading_unit_id TEXT NOT NULL REFERENCES reading_units(id),
    state TEXT NOT NULL CHECK (state IN (
        'QUEUED', 'PREPARING', 'DOWNLOADING', 'VERIFYING', 'PACKAGING', 'COMMITTING', 'COMPLETED', 'PAUSED',
        'WAITING_FOR_SESSION', 'WAITING_FOR_RATE_LIMIT', 'RETRY_WAIT', 'FAILED', 'CANCELED', 'RECOVERING')),
    queue_position REAL,
    attempts INTEGER NOT NULL DEFAULT 0,
    extraction_contract_json TEXT,
    manifest_json TEXT,
    last_error TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX download_jobs_state ON download_jobs (state, queue_position);

CREATE TABLE commit_journal (
    id TEXT PRIMARY KEY,
    storage_root_id TEXT NOT NULL REFERENCES storage_roots(id),
    staging_relpath TEXT NOT NULL,
    final_relpath TEXT NOT NULL,
    expected_sha256 TEXT NOT NULL CHECK (length(expected_sha256) = 64),
    expected_size INTEGER NOT NULL,
    registration_json TEXT NOT NULL,         -- DB registration intent replayed on recovery
    state TEXT NOT NULL CHECK (state IN ('pending', 'moved', 'verified', 'registered', 'done', 'aborted')),
    error TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX commit_journal_open ON commit_journal (state) WHERE state NOT IN ('done', 'aborted');

CREATE TABLE imports (
    id TEXT PRIMARY KEY,
    original_filename TEXT NOT NULL,          -- filename only; no host path persisted
    mode TEXT NOT NULL CHECK (mode IN ('copy', 'move')),
    format TEXT CHECK (format IN ('cbz', 'pdf', 'epub')),
    state TEXT NOT NULL CHECK (state IN ('validating', 'committing', 'completed', 'rejected', 'failed')),
    work_id TEXT REFERENCES works(id),
    asset_id TEXT REFERENCES assets(id),
    error TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE notifications (
    id TEXT PRIMARY KEY,
    dedupe_key TEXT NOT NULL UNIQUE,
    class TEXT NOT NULL CHECK (class IN ('important', 'informational')),
    state TEXT NOT NULL DEFAULT 'active' CHECK (state IN ('active', 'resolved', 'expired')),
    seen INTEGER NOT NULL DEFAULT 0 CHECK (seen IN (0, 1)),
    count INTEGER NOT NULL DEFAULT 1,
    payload_json TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    resolved_at TEXT
);

CREATE TABLE backup_records (
    id TEXT PRIMARY KEY,
    kind TEXT NOT NULL CHECK (kind IN ('library', 'full')),
    state TEXT NOT NULL CHECK (state IN ('creating', 'verifying', 'verified', 'failed', 'rotated')),
    location TEXT NOT NULL,
    checksum TEXT,
    created_at TEXT NOT NULL,
    verified_at TEXT
);

CREATE TABLE export_jobs (
    id TEXT PRIMARY KEY,
    state TEXT NOT NULL,
    contract_json TEXT NOT NULL,
    destination TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

-- References only: encrypted session material lives in secrets.db with a separately stored key (Master §13).
CREATE TABLE source_session_refs (
    source_id TEXT PRIMARY KEY,
    state TEXT NOT NULL DEFAULT 'not_connected'
        CHECK (state IN ('not_connected', 'checking', 'connected', 'needs_reconnect')),
    secret_ref TEXT,
    updated_at TEXT NOT NULL
);
