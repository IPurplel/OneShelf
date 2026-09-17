-- Scoped settings (Master §14 precedence, §42 defaults live in code and are overridden here).
CREATE TABLE settings (
    scope TEXT NOT NULL CHECK (scope IN ('global', 'source', 'work', 'content_type')),
    scope_id TEXT NOT NULL DEFAULT '',
    key TEXT NOT NULL,
    value_json TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (scope, scope_id, key)
);

-- Download engine state (Master §16). Jobs carry their own Extraction Contract and resume manifest.
ALTER TABLE download_jobs ADD COLUMN method TEXT;
ALTER TABLE download_jobs ADD COLUMN error_category TEXT;
ALTER TABLE download_jobs ADD COLUMN next_attempt_at TEXT;
ALTER TABLE download_jobs ADD COLUMN storage_root_id TEXT REFERENCES storage_roots(id);
ALTER TABLE download_jobs ADD COLUMN asset_id TEXT REFERENCES assets(id);
ALTER TABLE download_jobs ADD COLUMN checkpoint_json TEXT;
ALTER TABLE download_jobs ADD COLUMN pending_decision_json TEXT;
ALTER TABLE download_jobs ADD COLUMN staging_relpath TEXT;
ALTER TABLE download_jobs ADD COLUMN bytes_done INTEGER NOT NULL DEFAULT 0;
ALTER TABLE download_jobs ADD COLUMN bytes_total INTEGER;
ALTER TABLE download_jobs ADD COLUMN started_at TEXT;
ALTER TABLE download_jobs ADD COLUMN finished_at TEXT;
CREATE INDEX download_jobs_batch ON download_jobs (batch_id, state);
CREATE INDEX download_jobs_unit ON download_jobs (reading_unit_id, state);

ALTER TABLE download_batches ADD COLUMN selection_json TEXT;
ALTER TABLE download_batches ADD COLUMN paused INTEGER NOT NULL DEFAULT 0 CHECK (paused IN (0, 1));

-- Download History is separate from content and progress: clearing it deletes neither (Master §16.7, INV-23).
CREATE TABLE download_history (
    id TEXT PRIMARY KEY,
    reading_unit_id TEXT,
    work_id TEXT,
    source_id TEXT,
    language TEXT,
    outcome TEXT NOT NULL CHECK (outcome IN ('completed', 'failed', 'canceled')),
    initial_method TEXT,
    final_method TEXT,
    fallback_reason TEXT,
    error_category TEXT,
    bytes INTEGER,
    started_at TEXT,
    finished_at TEXT NOT NULL
);
CREATE INDEX download_history_time ON download_history (finished_at);
