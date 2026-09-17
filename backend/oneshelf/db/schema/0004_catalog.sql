-- Source-provided unit URL (used by Reader/download descriptors); never identity.
ALTER TABLE reading_units ADD COLUMN url_hint TEXT;

-- Catalog snapshot contents (Master §5.2: current + previous Trusted plus bounded supporting history).
CREATE TABLE snapshot_units (
    snapshot_id TEXT NOT NULL REFERENCES catalog_snapshots(id) ON DELETE CASCADE,
    unit_key TEXT NOT NULL,
    order_index INTEGER NOT NULL,
    raw_title TEXT,
    number TEXT,
    volume TEXT,
    unit_type TEXT NOT NULL DEFAULT 'unknown',
    url TEXT,
    release_date TEXT,
    PRIMARY KEY (snapshot_id, unit_key)
);
CREATE INDEX snapshot_units_order ON snapshot_units (snapshot_id, order_index);
CREATE INDEX catalog_snapshots_track ON catalog_snapshots (track_id, trust, fetched_at);
