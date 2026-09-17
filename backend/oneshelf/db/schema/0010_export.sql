-- Export jobs and their per-file state (Master §34.9). Exported files are never tracked as library content.
ALTER TABLE export_jobs ADD COLUMN output TEXT NOT NULL DEFAULT 'folder';
ALTER TABLE export_jobs ADD COLUMN conflict_policy TEXT NOT NULL DEFAULT 'skip_identical';
ALTER TABLE export_jobs ADD COLUMN missing_policy TEXT NOT NULL DEFAULT 'export_downloaded_only';
ALTER TABLE export_jobs ADD COLUMN copied INTEGER NOT NULL DEFAULT 0;
ALTER TABLE export_jobs ADD COLUMN skipped INTEGER NOT NULL DEFAULT 0;
ALTER TABLE export_jobs ADD COLUMN failed INTEGER NOT NULL DEFAULT 0;
ALTER TABLE export_jobs ADD COLUMN finished_at TEXT;

CREATE TABLE export_items (
    job_id TEXT NOT NULL REFERENCES export_jobs(id) ON DELETE CASCADE,
    asset_id TEXT NOT NULL,
    reading_unit_id TEXT NOT NULL,
    source_root_id TEXT NOT NULL,
    source_relative_path TEXT NOT NULL,
    target_path TEXT NOT NULL,
    sha256 TEXT,
    size INTEGER,
    state TEXT NOT NULL CHECK (state IN ('pending', 'copied', 'skipped', 'failed')),
    error TEXT,
    PRIMARY KEY (job_id, asset_id)
);
