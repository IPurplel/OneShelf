-- Speed up work detail loading: assets are looked up by reading_unit_id on every page open.
CREATE INDEX IF NOT EXISTS idx_assets_reading_unit ON assets (reading_unit_id);
