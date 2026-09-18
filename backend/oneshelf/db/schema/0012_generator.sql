-- Adapter Generator drafts (Master §12). Drafts are developer artefacts: generating one never installs
-- it, and a submission bundle is prepared locally and never published (ledger A1).
CREATE TABLE generator_drafts (
    id TEXT PRIMARY KEY,
    start_url TEXT NOT NULL,
    name TEXT NOT NULL,
    state TEXT NOT NULL CHECK (state IN ('discovered', 'generated', 'failed')),
    draft_json TEXT NOT NULL,
    package_path TEXT,
    bundle_path TEXT,
    error TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
