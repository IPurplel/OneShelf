-- A Source Listing's cover, as the source presents it (INV-28: presentation only). It never takes part in
-- identity, grouping or matching; Core serves it to the browser through /api/covers under the source's own
-- network policy, never as a remote URL.
ALTER TABLE source_listings ADD COLUMN cover_url TEXT;
