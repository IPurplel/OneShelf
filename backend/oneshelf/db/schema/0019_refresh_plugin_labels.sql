-- Recalculate labels parsed under the older rule that let defaults override valid name labels.
-- PluginManager performs the hash-checked package backfill at startup.
UPDATE plugins SET metadata_ready = 0;
