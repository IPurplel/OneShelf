-- Follow baselines and release events (Master §20). Detection compares catalogs, never numbers.
ALTER TABLE follows ADD COLUMN next_check_at TEXT;
ALTER TABLE follows ADD COLUMN last_error_category TEXT;

CREATE TABLE follow_baselines (
    id TEXT PRIMARY KEY,
    follow_id TEXT NOT NULL REFERENCES follows(id) ON DELETE CASCADE,
    kind TEXT NOT NULL CHECK (kind IN ('first_follow', 'source_change')),
    track_id TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE follow_baseline_units (
    baseline_id TEXT NOT NULL REFERENCES follow_baselines(id) ON DELETE CASCADE,
    unit_key TEXT NOT NULL,
    PRIMARY KEY (baseline_id, unit_key)
);

CREATE TABLE release_events (
    id TEXT PRIMARY KEY,
    follow_id TEXT NOT NULL REFERENCES follows(id) ON DELETE CASCADE,
    work_id TEXT NOT NULL,
    track_id TEXT NOT NULL,
    unit_key TEXT NOT NULL,
    reading_unit_id TEXT,
    kind TEXT NOT NULL CHECK (kind IN ('NEW_RELEASE', 'NEWLY_AVAILABLE')),
    detected_at TEXT NOT NULL,
    seen INTEGER NOT NULL DEFAULT 0 CHECK (seen IN (0, 1)),
    UNIQUE (follow_id, unit_key)
);
CREATE INDEX release_events_work ON release_events (work_id, detected_at);

-- Capability health states with hysteresis (Master §21); signals stay in source_health_signals.
CREATE TABLE source_health_state (
    source_id TEXT NOT NULL,
    capability TEXT NOT NULL,
    state TEXT NOT NULL CHECK (state IN ('healthy', 'degraded', 'unavailable', 'rate_limited', 'reconnect_required',
                                         'catalog_suspicious', 'unknown')),
    category TEXT,
    plugin_version TEXT,
    since TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (source_id, capability)
);
