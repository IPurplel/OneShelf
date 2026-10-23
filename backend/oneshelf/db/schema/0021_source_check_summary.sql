-- When each source last checked out successfully, and when it was last tried (Master §21; UI-004).
-- Health signals are pruned after seven days, so the last success of a quiet source would otherwise vanish and
-- read as "never checked". One row per source, updated with every recorded signal; a failure never clears
-- `last_successful_at`. Backfilled from the signals still held.
CREATE TABLE source_check_summary (
    source_id TEXT PRIMARY KEY,
    last_successful_at TEXT,
    last_attempted_at TEXT NOT NULL
);

INSERT INTO source_check_summary (source_id, last_successful_at, last_attempted_at)
    SELECT source_id, max(CASE WHEN outcome = 'success' THEN created_at END), max(created_at)
    FROM source_health_signals GROUP BY source_id;
