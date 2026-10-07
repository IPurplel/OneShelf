-- A retried mark creation keeps its operation identity across an uncertain response.
-- Nullable for marks created by older clients and existing libraries.
ALTER TABLE reading_bookmarks ADD COLUMN operation_id TEXT;
ALTER TABLE reading_highlights ADD COLUMN operation_id TEXT;

CREATE UNIQUE INDEX idx_reading_bookmarks_operation ON reading_bookmarks(operation_id)
    WHERE operation_id IS NOT NULL;
CREATE UNIQUE INDEX idx_reading_highlights_operation ON reading_highlights(operation_id)
    WHERE operation_id IS NOT NULL;
