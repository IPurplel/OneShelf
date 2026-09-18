-- Bookmarks and Highlights (Master §26.22). A reader's own marks are library state, not browser state:
-- they belong to the Reading Unit, survive a cleared browser, reach every device that reaches the
-- library, and travel in a Library Backup. v1 keeps exactly these two — no notes, no drawing (§49).
CREATE TABLE reading_bookmarks (
    id TEXT PRIMARY KEY,
    reading_unit_id TEXT NOT NULL REFERENCES reading_units(id) ON DELETE CASCADE,
    locator_json TEXT NOT NULL,
    locator_key TEXT NOT NULL,          -- the same place is never bookmarked twice
    label TEXT,
    created_at TEXT NOT NULL,
    UNIQUE (reading_unit_id, locator_key)
);

CREATE INDEX idx_reading_bookmarks_unit ON reading_bookmarks(reading_unit_id, created_at);

CREATE TABLE reading_highlights (
    id TEXT PRIMARY KEY,
    reading_unit_id TEXT NOT NULL REFERENCES reading_units(id) ON DELETE CASCADE,
    locator_json TEXT NOT NULL,
    text TEXT NOT NULL,
    colour TEXT NOT NULL DEFAULT 'yellow',
    created_at TEXT NOT NULL
);

CREATE INDEX idx_reading_highlights_unit ON reading_highlights(reading_unit_id, created_at);
