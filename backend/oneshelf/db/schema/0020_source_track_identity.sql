-- Each concrete source listing and reading language owns a track. Keep local tracks grouped by Work/language.
-- The migration runner disables foreign keys only during this transactional table rebuild and checks them
-- before commit. Old links whose listing has moved or been unlinked become unavailable archives.
CREATE TABLE source_tracks_new (
    id TEXT PRIMARY KEY,
    work_id TEXT NOT NULL REFERENCES works(id),
    source_id TEXT NOT NULL,
    language TEXT NOT NULL,
    kind TEXT NOT NULL CHECK (kind IN ('source', 'local')),
    listing_id TEXT REFERENCES source_listings(id),
    listing_title TEXT,
    listing_key TEXT,
    availability TEXT NOT NULL DEFAULT 'unknown'
        CHECK (availability IN ('available', 'unavailable', 'unknown')),
    created_at TEXT NOT NULL,
    CHECK ((kind = 'local') = (source_id = 'local'))
);

INSERT INTO source_tracks_new (id, work_id, source_id, language, kind, listing_id,
                               listing_title, listing_key, availability, created_at)
SELECT t.id, t.work_id, t.source_id, t.language, t.kind,
       CASE WHEN t.listing_id IS NOT NULL AND l.work_id IS t.work_id THEN t.listing_id ELSE NULL END,
       l.raw_title, l.source_listing_key,
       CASE WHEN t.kind = 'source' AND (t.listing_id IS NULL OR l.work_id IS NOT t.work_id)
            THEN 'unavailable'
            ELSE t.availability END,
       t.created_at
FROM source_tracks t LEFT JOIN source_listings l ON l.id = t.listing_id;

DROP TABLE source_tracks;
ALTER TABLE source_tracks_new RENAME TO source_tracks;
CREATE UNIQUE INDEX source_tracks_listing_language ON source_tracks (listing_id, language)
    WHERE kind = 'source' AND listing_id IS NOT NULL;
CREATE UNIQUE INDEX source_tracks_local_work_language ON source_tracks (work_id, language)
    WHERE kind = 'local';
