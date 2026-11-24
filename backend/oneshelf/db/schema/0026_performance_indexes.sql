-- Indexes for queries on hot paths (PERFORMANCE_STUDY.md §3.2, §3.4). No data changes.

-- Health signals are pruned by age after every recipe run; without this the prune scans the table.
CREATE INDEX IF NOT EXISTS source_health_signals_created ON source_health_signals (created_at);

-- A Work's chapter list asks which releases on the selected track are still unseen.
CREATE INDEX IF NOT EXISTS release_events_track_unseen ON release_events (track_id, seen);

-- A Work's chapter list and the Reader ask for each unit's latest download job.
CREATE INDEX IF NOT EXISTS download_jobs_unit_created ON download_jobs (reading_unit_id, created_at);
