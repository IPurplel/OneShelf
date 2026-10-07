-- Text reading units (architecture review C, 2026-09-30): a stored asset may be format 'text', the
-- sanitised HTML container a text source's reader output is downloaded into (Master §27, §34.4 — the
-- source's own form, never converted to EPUB).
--
-- Widening a CHECK constraint means rebuilding the table. As in 0014, this runs inside the migration
-- transaction with foreign keys on: build the parent and both children that reference it, copy, drop the
-- children before the parent so no row is ever orphaned, then rename — which repoints the children's
-- foreign keys at the rebuilt parent. Nothing references imports or download_jobs. Columns, constraints
-- and indexes are otherwise exactly those of 0001 and 0007; imports keeps its own format list, because
-- a text unit is never imported by hand in this version.

CREATE TABLE assets_new (
    id TEXT PRIMARY KEY,
    reading_unit_id TEXT NOT NULL REFERENCES reading_units(id),
    format TEXT NOT NULL CHECK (format IN ('cbz', 'pdf', 'epub', 'text', 'other')),
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
INSERT INTO assets_new (id, reading_unit_id, format, variant, storage_root_id, relative_path, size_bytes, sha256,
                        page_count, integrity, created_at, updated_at)
    SELECT id, reading_unit_id, format, variant, storage_root_id, relative_path, size_bytes, sha256,
           page_count, integrity, created_at, updated_at FROM assets;

CREATE TABLE imports_new (
    id TEXT PRIMARY KEY,
    original_filename TEXT NOT NULL,          -- filename only; no host path persisted
    mode TEXT NOT NULL CHECK (mode IN ('copy', 'move')),
    format TEXT CHECK (format IN ('cbz', 'pdf', 'epub')),
    state TEXT NOT NULL CHECK (state IN ('validating', 'committing', 'completed', 'rejected', 'failed')),
    work_id TEXT REFERENCES works(id),
    asset_id TEXT REFERENCES assets_new(id),
    error TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
INSERT INTO imports_new (id, original_filename, mode, format, state, work_id, asset_id, error, created_at, updated_at)
    SELECT id, original_filename, mode, format, state, work_id, asset_id, error, created_at, updated_at FROM imports;

CREATE TABLE download_jobs_new (
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
    updated_at TEXT NOT NULL,
    method TEXT,
    error_category TEXT,
    next_attempt_at TEXT,
    storage_root_id TEXT REFERENCES storage_roots(id),
    asset_id TEXT REFERENCES assets_new(id),
    checkpoint_json TEXT,
    pending_decision_json TEXT,
    staging_relpath TEXT,
    bytes_done INTEGER NOT NULL DEFAULT 0,
    bytes_total INTEGER,
    started_at TEXT,
    finished_at TEXT
);
INSERT INTO download_jobs_new (id, batch_id, reading_unit_id, state, queue_position, attempts, extraction_contract_json,
                               manifest_json, last_error, created_at, updated_at, method, error_category,
                               next_attempt_at, storage_root_id, asset_id, checkpoint_json, pending_decision_json,
                               staging_relpath, bytes_done, bytes_total, started_at, finished_at)
    SELECT id, batch_id, reading_unit_id, state, queue_position, attempts, extraction_contract_json,
           manifest_json, last_error, created_at, updated_at, method, error_category,
           next_attempt_at, storage_root_id, asset_id, checkpoint_json, pending_decision_json,
           staging_relpath, bytes_done, bytes_total, started_at, finished_at FROM download_jobs;

DROP TABLE download_jobs;
DROP TABLE imports;
DROP TABLE assets;
ALTER TABLE assets_new RENAME TO assets;
ALTER TABLE imports_new RENAME TO imports;
ALTER TABLE download_jobs_new RENAME TO download_jobs;
CREATE INDEX download_jobs_state ON download_jobs (state, queue_position);
CREATE INDEX download_jobs_batch ON download_jobs (batch_id, state);
CREATE INDEX download_jobs_unit ON download_jobs (reading_unit_id, state);
