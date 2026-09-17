-- Plugin management (Master §9.5, §10). Plugin rows are kept after uninstall to preserve provenance
-- and offer reinstall; package files live in the plugin store, never in the database.

CREATE TABLE plugins (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    state TEXT NOT NULL CHECK (state IN ('active', 'disabled', 'pending_review', 'uninstalled')),
    active_version TEXT,
    trust_label TEXT NOT NULL CHECK (trust_label IN ('official', 'verified_community', 'community', 'local')),
    channel TEXT NOT NULL CHECK (channel IN ('registry', 'upload')),
    registry_url TEXT,
    installed_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    CHECK ((state = 'active') = (active_version IS NOT NULL) OR state = 'disabled')
);

CREATE TABLE plugin_versions (
    plugin_id TEXT NOT NULL REFERENCES plugins(id),
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
CREATE UNIQUE INDEX plugin_versions_one_active ON plugin_versions (plugin_id) WHERE status = 'active';
