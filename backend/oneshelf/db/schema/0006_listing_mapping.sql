-- Who decided a listing's Work association (Master §6.6, INV-04): a user decision is never replaced by
-- automatic evidence on a later refresh.
ALTER TABLE source_listings ADD COLUMN mapping_decided_by TEXT
    CHECK (mapping_decided_by IS NULL OR mapping_decided_by IN ('user', 'evidence'));
