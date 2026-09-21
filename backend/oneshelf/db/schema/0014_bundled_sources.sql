-- Official bundled source adapters (explicit user requirement, 2026-09-21).
--
-- The official adapters ship inside the image and are installed once, on a fresh library, through the
-- normal plugin pipeline. Two things are needed for that to be safe: a channel that says a plugin
-- arrived that way, and a durable record of what the bootstrap has already done — so that a restart,
-- a rebuild or an update can never bring back a source the person removed.
--
-- Widening a CHECK constraint means rebuilding the table. This runs inside the migration transaction
-- with foreign keys on, so the order matters: build both replacements, drop the child before the
-- parent so no row is ever orphaned, then rename — which also repoints the child's foreign key.

CREATE TABLE plugins_new (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    state TEXT NOT NULL CHECK (state IN ('active', 'disabled', 'pending_review', 'uninstalled')),
    active_version TEXT,
    trust_label TEXT NOT NULL CHECK (trust_label IN ('official', 'verified_community', 'community', 'local')),
    channel TEXT NOT NULL CHECK (channel IN ('registry', 'upload', 'bundled')),
    registry_url TEXT,
    installed_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    CHECK ((state = 'active') = (active_version IS NOT NULL) OR state = 'disabled')
);
INSERT INTO plugins_new (id, name, state, active_version, trust_label, channel, registry_url, installed_at, updated_at)
    SELECT id, name, state, active_version, trust_label, channel, registry_url, installed_at, updated_at FROM plugins;

CREATE TABLE plugin_versions_new (
    plugin_id TEXT NOT NULL REFERENCES plugins_new(id),
    version TEXT NOT NULL,
    sha256 TEXT NOT NULL CHECK (length(sha256) = 64),
    permissions_json TEXT NOT NULL,
    approved_permissions_json TEXT,
    status TEXT NOT NULL CHECK (status IN ('active', 'previous', 'pending_review', 'retired')),
    trust_label TEXT NOT NULL CHECK (trust_label IN ('official', 'verified_community', 'community', 'local')),
    test_report_json TEXT NOT NULL,
    store_relpath TEXT NOT NULL,
    installed_at TEXT NOT NULL,
    PRIMARY KEY (plugin_id, version)
);
INSERT INTO plugin_versions_new (plugin_id, version, sha256, permissions_json, approved_permissions_json, status,
                                 trust_label, test_report_json, store_relpath, installed_at)
    SELECT plugin_id, version, sha256, permissions_json, approved_permissions_json, status,
           trust_label, test_report_json, store_relpath, installed_at FROM plugin_versions;

DROP TABLE plugin_versions;
DROP TABLE plugins;
ALTER TABLE plugins_new RENAME TO plugins;
ALTER TABLE plugin_versions_new RENAME TO plugin_versions;
CREATE UNIQUE INDEX plugin_versions_one_active ON plugin_versions (plugin_id) WHERE status = 'active';

-- Small, internal, and not a setting: nothing in the API writes here.
CREATE TABLE app_meta (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

-- What the bootstrap did for each official adapter. A plugin row alone cannot say "we tried and it
-- failed", because a failed install leaves no plugin row; and "skipped" records that an existing library
-- already managed its sources, so nothing is ever inferred twice.
CREATE TABLE bundled_plugins (
    plugin_id TEXT PRIMARY KEY,
    status TEXT NOT NULL CHECK (status IN ('installed', 'failed', 'skipped')),
    bundled_version TEXT NOT NULL,
    bundled_sha256 TEXT,
    detail TEXT,
    updated_at TEXT NOT NULL
);
