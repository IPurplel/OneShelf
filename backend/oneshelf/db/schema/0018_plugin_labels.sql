-- Persist parsed adapter labels for Registry display and scoped search.
-- Existing rows are marked for one-time backfill from their stored package at startup.
ALTER TABLE plugins ADD COLUMN category TEXT;
ALTER TABLE plugins ADD COLUMN languages_json TEXT NOT NULL DEFAULT '[]';
ALTER TABLE plugins ADD COLUMN metadata_ready INTEGER NOT NULL DEFAULT 0 CHECK (metadata_ready IN (0, 1));
