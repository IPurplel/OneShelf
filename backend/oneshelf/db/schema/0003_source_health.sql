-- Passive capability-level health signals (Master §21). Bounded; interpreted into states in C6.
CREATE TABLE source_health_signals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_id TEXT NOT NULL,
    capability TEXT NOT NULL,
    outcome TEXT NOT NULL CHECK (outcome IN ('success', 'failure', 'content_missing')),
    category TEXT,
    plugin_version TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE INDEX source_health_signals_lookup ON source_health_signals (source_id, capability, id);
