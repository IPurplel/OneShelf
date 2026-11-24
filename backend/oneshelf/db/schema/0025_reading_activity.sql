-- Reading goals: the hours in which something was read (UTC, 'YYYY-MM-DDTHH'), so a daily streak can be
-- counted in the reader's own days. At most 24 rows a day, and nothing about what was read.
CREATE TABLE reading_activity (
    hour TEXT PRIMARY KEY
);

-- What is known already: the last hour each chapter in progress or finished was read.
INSERT OR IGNORE INTO reading_activity (hour)
SELECT DISTINCT substr(updated_at, 1, 13) FROM reading_state
WHERE read_state IN ('partial', 'read') AND updated_at IS NOT NULL;
